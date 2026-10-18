# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Local stream spool — the jitter wall between the internet and ffmpeg.

WHY THIS EXISTS (root cause of the mid-song micro-stalls, found 2026-09-06):
ntgcalls pulls PCM from ffmpeg's stdout in fixed 10 ms frames with only
~200 ms of read-ahead, and NEVER inserts silence — a frame that arrives late
is an audible gap followed by a burst catch-up. ffmpeg, in turn, keeps no
network buffer worth the name for an HTTP input: the AVIO buffer is 32 KB,
"-rtbufsize" only applies to libavdevice capture devices, and "-re" makes
it read strictly just-in-time. So every hiccup of a remote CDN / relay
(hundreds of ms are normal on a free relay) travelled straight into the
voice chat.

THE FIX: ffmpeg never talks to the internet any more. Every remote audio
URL is fetched here — in-process, at full link speed, into RAM — and ffmpeg
reads it from http://127.0.0.1 where reads complete in microseconds. The
download runs 20-100x faster than playback, so after the first second the
whole song is already local; a remote stall can no longer reach the
encoder. No disk is touched, nothing waits for a "download": bytes are
served the moment they arrive, exactly like a live stream.

A spool entry also knows its RECIPE (upstream URL + headers, or the command
that produces the bytes), so a local URL stays valid for the life of the
process — a re-play/seek after eviction just refetches transparently.

THREADING: the spool server and its producers run on their OWN thread with
their own event loop. The bot's main loop is busy with updates, handlers
and the occasional sync library call; if it were also the thing answering
ffmpeg's reads, any hiccup there (a blocked handler, a burst of updates)
would stall the voice chat even though the bytes are already in RAM. On a
dedicated loop the only work between ffmpeg and its data is a memory copy.
The public coroutines (wrap / from_command / prime) can be awaited from any
loop; they hop onto the spool loop and hop back with the result.
"""

import asyncio
import secrets
import threading
import time
from typing import Callable

import aiohttp
from aiohttp import web

from bobby import logger

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
_CHUNK = 512 * 1024
_MAX_ENTRY = 128 * 1024 * 1024        # per stream; audio never gets near it
_MAX_TOTAL = 256 * 1024 * 1024        # LRU-evict idle entries beyond this
# a finished song is released by the queue the moment it can never play again
# (Queue.purge_file -> forget); the TTL only catches entries that path missed
_IDLE_TTL = 30 * 60
_GC_EVERY = 60                        # the spool sweeps itself; it used to wait for the next play
# upstream must answer within this; a slow source fails over fast
# instead of holding the play request (measured 2026-09-30)
_FIRST_BYTE_TIMEOUT = 15              # upstream must start within this
_STALL_TIMEOUT = 20                   # no new bytes for this long = give up
_RETRIES = 3
_RANGE_SETTLE = 3                     # ranged request vs unknown length: wait this long for it


async def _stop_process(proc) -> None:
    """Reap a producer without turning its natural-exit race into a play error."""
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            # The child can exit after returncode was sampled but before kill.
            # It still has to be reaped, but this is not a spool failure.
            pass
        await proc.wait()


class _Entry:
    __slots__ = (
        "token", "recipe", "buf", "total", "done", "error", "ctype",
        "cond", "task", "clients", "last_used", "doomed",
    )

    def __init__(self, token: str, recipe: tuple):
        self.token = token
        self.recipe = recipe
        self.buf = bytearray()
        self.total: int | None = None
        self.done = False
        self.error: str | None = None
        self.ctype = "application/octet-stream"
        self.cond = asyncio.Condition()
        self.task: asyncio.Task | None = None
        self.clients = 0
        self.last_used = time.monotonic()
        self.doomed = False  # forget() arrived while a reader was attached: drop when it leaves

    async def _notify(self) -> None:
        async with self.cond:
            self.cond.notify_all()

    async def _finish(self, error: str | None = None) -> None:
        if error:
            self.error = error
        else:
            self.done = True
            self.total = len(self.buf)
        await self._notify()


class StreamSpool:
    def __init__(self):
        self._entries: dict[str, _Entry] = {}
        self._recipes: dict[str, tuple] = {}
        self._runner: web.AppRunner | None = None
        self._base: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread_lock = threading.Lock()
        self._start_lock: asyncio.Lock | None = None  # created on the spool loop
        # set_pinned(): () -> the URLs some queue still needs.  The sweeps never
        # evict those, however idle — /speed plays a tempo file for a while and
        # then needs the untempoed original back, e.g. "/speed 1".  The provider
        # reads bot-loop state, so it is always called ON the bot loop and the
        # snapshot is handed to the spool thread (never a cross-thread read)
        self._pinned: Callable[[], set[str]] | None = None
        self._pin_loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------ lifecycle
    def _spool_loop(self) -> asyncio.AbstractEventLoop:
        """The dedicated spool thread + loop (started on first use)."""
        if self._loop is None:
            with self._thread_lock:
                if self._loop is None:
                    loop = asyncio.new_event_loop()
                    threading.Thread(
                        target=self._run_loop, args=(loop,),
                        name="spool", daemon=True,
                    ).start()
                    self._loop = loop
        return self._loop

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    async def _on_spool(self, coro):
        """Run `coro` on the spool loop; await its result from any loop."""
        fut = asyncio.run_coroutine_threadsafe(coro, self._spool_loop())
        return await asyncio.wrap_future(fut)

    async def _start_server(self) -> None:  # runs on the spool loop
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        async with self._start_lock:
            if self._runner:
                return
            app = web.Application()
            app.router.add_get("/s/{token}", self._serve)
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001
            self._runner = runner
            self._base = f"http://127.0.0.1:{port}/s/"
            asyncio.ensure_future(self._gc_timer())
            logger.info(
                "stream spool listening on 127.0.0.1:%s (thread %s)",
                port, threading.current_thread().name,
            )

    async def _gc_timer(self) -> None:  # runs on the spool loop
        while True:
            await asyncio.sleep(_GC_EVERY)
            try:
                self._gc(await self._pinned_snapshot())
            except Exception as e:  # noqa: BLE001
                logger.warning("spool gc: %r", e)

    def set_pinned(self, provider: Callable[[], set[str]]) -> None:
        """Call from the bot loop: `provider()` returns the URLs still referenced by a
        queue.  It will only ever be invoked on this same loop."""
        self._pinned = provider
        self._pin_loop = asyncio.get_running_loop()

    def _pinned_now(self) -> set[str]:
        """Bot loop only."""
        return set(self._pinned()) if self._pinned else set()

    async def _pinned_snapshot(self) -> set[str] | None:  # spool loop
        """Ask the bot loop which URLs are still needed; None = could not tell."""
        if self._pinned is None:
            return set()
        loop = self._pin_loop
        if loop is None or loop.is_closed():
            return None
        try:
            fut = asyncio.wrap_future(asyncio.run_coroutine_threadsafe(self._pinned_async(), loop))
            return await asyncio.wait_for(fut, 5)
        except Exception:  # noqa: BLE001 — bot loop busy/stopping: evict nothing this round
            return None

    async def _pinned_async(self) -> set[str]:  # bot loop
        return self._pinned_now()

    def is_local(self, url: str | None) -> bool:
        return bool(url and self._base and url.startswith(self._base))

    # --------------------------------------------------------------- public
    async def wrap(self, url: str, headers: dict | None = None) -> str:
        """Local URL that mirrors `url`. Idempotent for spool URLs."""
        if self.is_local(url):
            return url
        return await self._on_spool(self._wrap(url, dict(headers or {})))

    async def from_command(self, argv: list[str], ctype: str | None = None) -> str:
        """Local URL fed by a subprocess's stdout (e.g. yt-dlp -o -)."""
        return await self._on_spool(self._from_command(list(argv), ctype))

    def forget(self, url: str) -> None:
        """Release a spool URL: its buffer is dropped (right away, or as soon as the
        last reader detaches) and the recipe is gone, so it cannot be rebuilt.
        Safe from any thread; a no-op for foreign URLs."""
        if not self.is_local(url) or self._loop is None:
            return
        token = url[len(self._base):]
        self._loop.call_soon_threadsafe(self._forget, token)

    async def stats(self) -> dict:
        """{"entries", "bytes", "idle_bytes"} — what the spool holds in RAM right now."""
        if self._loop is None:
            return {"entries": 0, "bytes": 0, "idle_bytes": 0}
        return await self._on_spool(self._stats())

    async def clear_idle(self) -> int:
        """Drop every idle entry no queue still needs (manual clean); returns bytes
        freed.  Call from the bot loop."""
        if self._loop is None:
            return 0
        return await self._on_spool(self._clear_idle(self._pinned_now()))

    async def prime(self, url: str, timeout: float = 25) -> bool:
        """Wait until a spool URL has its first bytes (or failed). Lets a
        caller verify a source really produces data before handing it to
        ffmpeg — a dead upstream then costs one tier, not the whole play."""
        if not self.is_local(url):
            return False
        return await self._on_spool(self._prime(url[len(self._base):], timeout))

    # ------------------------------------------ internal (spool loop only)
    async def _wrap(self, url: str, headers: dict) -> str:
        await self._start_server()
        return self._register(("http", url, headers), await self._pinned_snapshot())

    async def _from_command(self, argv: list[str], ctype: str | None) -> str:
        await self._start_server()
        return self._register(("proc", argv, ctype), await self._pinned_snapshot())

    async def _prime(self, token: str, timeout: float) -> bool:
        entry = self._ensure(token)
        if not entry:
            return False
        try:
            async with entry.cond:
                await asyncio.wait_for(
                    entry.cond.wait_for(
                        lambda: entry.buf or entry.done or entry.error
                    ),
                    timeout,
                )
        except asyncio.TimeoutError:
            return False
        return not entry.error and bool(entry.buf)

    def _register(self, recipe: tuple, pinned: set[str] | None) -> str:
        self._gc(pinned)
        token = secrets.token_urlsafe(12)
        self._recipes[token] = recipe
        self._ensure(token)
        return self._base + token

    def _ensure(self, token: str) -> _Entry | None:
        entry = self._entries.get(token)
        if entry and entry.error and entry.clients == 0:
            entry = None  # failed earlier: rebuild from the recipe
        if entry is None:
            recipe = self._recipes.get(token)
            if recipe is None:
                return None
            entry = _Entry(token, recipe)
            self._entries[token] = entry
            entry.task = asyncio.create_task(self._fetch(entry))
        entry.last_used = time.monotonic()
        return entry

    def _forget(self, token: str) -> None:  # spool loop only
        self._recipes.pop(token, None)
        entry = self._entries.get(token)
        if entry is None:
            return
        if entry.clients:
            entry.doomed = True  # _serve drops it when the reader detaches
            return
        self._drop(entry)

    def _drop(self, entry: _Entry) -> None:  # spool loop only
        self._entries.pop(entry.token, None)
        if entry.task and not entry.task.done():
            entry.task.cancel()
        entry.buf = bytearray()  # give the RAM back now, not when the last reference dies

    def _idle(self) -> list:
        return [
            e for e in self._entries.values()
            if e.clients == 0 and (e.done or e.error)
        ]

    async def _stats(self) -> dict:  # spool loop only
        entries = list(self._entries.values())
        return {
            "entries": len(entries),
            "bytes": sum(len(e.buf) for e in entries),
            "idle_bytes": sum(len(e.buf) for e in self._idle()),
        }

    async def _clear_idle(self, pinned: set[str]) -> int:  # spool loop only
        freed = 0
        for e in self._idle():
            if self._base + e.token in pinned:
                continue
            freed += len(e.buf)
            self._drop(e)
        return freed

    def _gc(self, pinned: set[str] | None) -> None:
        """Expire idle entries (skipping `pinned`; None = unknown, so no TTL eviction
        at all) and, whatever their pins, keep the total under the hard cap — an
        evicted entry keeps its recipe and is refetched if it is ever asked for again."""
        now = time.monotonic()
        if pinned is not None:
            for e in self._idle():
                if self._base + e.token in pinned:
                    continue
                if now - e.last_used > _IDLE_TTL:
                    self._drop(e)
        total = sum(len(e.buf) for e in self._entries.values())
        if total <= _MAX_TOTAL:
            return
        keep = pinned or set()
        # oldest first, but anything a queue still needs goes last
        idle = sorted(self._idle(), key=lambda e: (self._base + e.token in keep, e.last_used))
        for e in idle:
            if e.token not in self._entries:
                continue
            total -= len(e.buf)
            self._drop(e)
            if total <= _MAX_TOTAL:
                break

    async def _fetch(self, entry: _Entry) -> None:
        kind = entry.recipe[0]
        try:
            if kind == "http":
                await self._fetch_http(entry, entry.recipe[1], entry.recipe[2])
            else:
                await self._fetch_proc(entry, entry.recipe[1], entry.recipe[2])
        except asyncio.CancelledError:
            await entry._finish("cancelled")
            raise
        except Exception as ex:
            # never log the message: upstream URLs can carry API keys
            logger.warning("spool fetch failed: %s", type(ex).__name__)
            await entry._finish(type(ex).__name__)

    async def _fetch_http(self, entry: _Entry, url: str, headers: dict) -> None:
        hdrs = {"User-Agent": _UA, **headers}
        timeout = aiohttp.ClientTimeout(
            total=None, sock_connect=15, sock_read=_STALL_TIMEOUT
        )
        ranges_ok = True
        attempt = 0
        high_water = 0  # retries only earn more retries by reaching NEW bytes
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                attempt += 1
                offset = len(entry.buf)
                req = dict(hdrs)
                if offset and ranges_ok:
                    req["Range"] = f"bytes={offset}-"
                try:
                    async with session.get(url, headers=req) as resp:
                        if offset and resp.status == 206:
                            pass
                        elif offset:
                            # server ignored our Range: restart from zero
                            ranges_ok = False
                            del entry.buf[:]
                            offset = 0
                        if resp.status not in (200, 206):
                            if 400 <= resp.status < 500 and resp.status != 429:
                                raise RuntimeError(f"upstream HTTP {resp.status}")
                            raise aiohttp.ClientResponseError(
                                resp.request_info, resp.history,
                                status=resp.status,
                            )
                        if entry.total is None:
                            cr = resp.headers.get("Content-Range", "")
                            cl = resp.headers.get("Content-Length")
                            if "/" in cr and cr.rsplit("/", 1)[1].isdigit():
                                entry.total = int(cr.rsplit("/", 1)[1])
                            elif cl and cl.isdigit() and resp.status == 200:
                                entry.total = int(cl)
                            if resp.headers.get("Content-Type"):
                                entry.ctype = resp.headers["Content-Type"]
                        async for chunk in resp.content.iter_chunked(_CHUNK):
                            entry.buf += chunk
                            if len(entry.buf) > _MAX_ENTRY:
                                raise OverflowError("spool entry too large")
                            await entry._notify()
                    if entry.total is not None and len(entry.buf) < entry.total:
                        raise EOFError("short read")  # retry with Range
                    await entry._finish()
                    return
                except (aiohttp.ClientError, asyncio.TimeoutError, EOFError) as ex:
                    made_progress = len(entry.buf) > high_water
                    high_water = max(high_water, len(entry.buf))
                    if attempt > _RETRIES and not made_progress:
                        raise
                    if attempt > _RETRIES * 3:
                        raise
                    logger.warning(
                        "spool upstream hiccup (%s), retry %s at byte %s",
                        type(ex).__name__, attempt, len(entry.buf),
                    )
                    await asyncio.sleep(0.5)

    async def _fetch_proc(self, entry: _Entry, argv: list[str], ctype) -> None:
        if ctype:
            entry.ctype = ctype
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        err_tail = bytearray()

        async def _drain_err():
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                err_tail.extend(line[-300:])
                del err_tail[:-1200]

        err_task = asyncio.create_task(_drain_err())
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        proc.stdout.read(_CHUNK),
                        _FIRST_BYTE_TIMEOUT if not entry.buf else _STALL_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError("producer stalled")
                if not chunk:
                    break
                entry.buf += chunk
                if len(entry.buf) > _MAX_ENTRY:
                    raise OverflowError("spool entry too large")
                await entry._notify()
            rc = await proc.wait()
            await err_task
            if rc != 0:
                # a non-zero exit after partial output is a TRUNCATED stream,
                # never a finished one: flag it so the reader gets a broken
                # connection (-> ffmpeg reconnect / next tier), not a clean EOF
                tail = bytes(err_tail).decode(errors="replace").strip()
                logger.warning(
                    "spool producer exited %s after %s bytes: %s",
                    rc, len(entry.buf), tail.splitlines()[-1:],
                )
                raise RuntimeError("producer failed")
            await entry._finish()
        finally:
            await _stop_process(proc)
            err_task.cancel()

    # ---------------------------------------------------------------- serve
    async def _serve(self, request: web.Request) -> web.StreamResponse:
        entry = self._ensure(request.match_info["token"])
        if entry is None:
            raise web.HTTPNotFound()
        entry.clients += 1
        try:
            return await self._stream(request, entry)
        finally:
            entry.clients -= 1
            entry.last_used = time.monotonic()
            if entry.doomed and entry.clients == 0:
                self._drop(entry)

    async def _stream(self, request: web.Request, entry: _Entry) -> web.StreamResponse:
        # wait for the first bytes so we can answer with real headers
        try:
            async with entry.cond:
                await asyncio.wait_for(
                    entry.cond.wait_for(
                        lambda: entry.buf or entry.done or entry.error
                    ),
                    _FIRST_BYTE_TIMEOUT,
                )
        except asyncio.TimeoutError:
            raise web.HTTPGatewayTimeout()
        if entry.error and not entry.buf:
            raise web.HTTPBadGateway()

        start, end = 0, None
        rng = request.headers.get("Range", "")
        if rng.startswith("bytes="):
            lo, _, hi = rng[6:].partition("-")
            if lo.isdigit():
                start = int(lo)
                if hi.isdigit():
                    end = int(hi)
            elif hi.isdigit() and entry.total is not None:
                start = max(0, entry.total - int(hi))
        if rng and entry.total is None and (start or end is not None):
            # A ranged request while the length is still unknown (producer
            # still running): a 206 MUST carry a finite Content-Range, so
            # give the producer a moment to finish — in practice the whole
            # song lands within seconds — before falling back to serving
            # the bytes available right now as a bounded range.
            try:
                async with entry.cond:
                    await asyncio.wait_for(
                        entry.cond.wait_for(
                            lambda: entry.total is not None or entry.error
                        ),
                        _RANGE_SETTLE,
                    )
            except asyncio.TimeoutError:
                pass
        if (rng and (start or end is not None) and entry.total is None
                and start >= len(entry.buf) and not entry.error):
            # A live producer can be BETWEEN chunks, not dead. Returning 502
            # here makes ffmpeg reconnect/back off mid-song and then catch up.
            # Wait for this offset on the spool loop; do not discard good
            # buffered audio or confuse a temporary stall with a clean EOF.
            try:
                async with entry.cond:
                    await asyncio.wait_for(
                        entry.cond.wait_for(
                            lambda: len(entry.buf) > start
                            or entry.total is not None or entry.error
                        ),
                        _STALL_TIMEOUT,
                    )
            except asyncio.TimeoutError:
                raise web.HTTPGatewayTimeout()
        if entry.total is not None and start >= entry.total:
            # ffmpeg's -reconnect_at_eof probe lands here: a clean 416 ends
            # the stream at once instead of a retry loop
            return web.Response(
                status=416, headers={"Content-Range": f"bytes */{entry.total}"}
            )

        headers = {"Accept-Ranges": "bytes", "Content-Type": entry.ctype}
        status = 200
        if entry.total is not None:
            last = entry.total - 1 if end is None else min(end, entry.total - 1)
            headers["Content-Length"] = str(last - start + 1)
            if rng:
                status = 206
                headers["Content-Range"] = f"bytes {start}-{last}/{entry.total}"
            stop = last + 1
        elif rng and (start or end is not None):
            # length still unknown: serve what exists as a valid bounded
            # 206 (bytes start-last/*). ffmpeg reads it and, at its end,
            # reconnects with a new Range — by then the length is known.
            avail = len(entry.buf)
            if start >= avail:
                raise web.HTTPBadGateway()  # producer died before this offset
            last = avail - 1 if end is None else min(end, avail - 1)
            status = 206
            headers["Content-Length"] = str(last - start + 1)
            headers["Content-Range"] = f"bytes {start}-{last}/*"
            stop = last + 1
        else:
            # plain GET, size unknown yet: chunked; ffmpeg treats it as a
            # live-ish stream, which is fine for playback
            stop = None
        resp = web.StreamResponse(status=status, headers=headers)
        await resp.prepare(request)
        try:
            await self._pump(request, resp, entry, start, stop)
        except (ConnectionResetError, ConnectionError, asyncio.CancelledError):
            pass  # reader went away (song skipped / ffmpeg closed) — routine
        return resp

    @staticmethod
    async def _pump(request, resp, entry: _Entry, start: int, stop: int | None) -> None:
        pos = start
        while stop is None or pos < stop:
            avail = len(entry.buf)
            if pos < avail:
                hi = avail if stop is None else min(avail, stop)
                await resp.write(bytes(entry.buf[pos:min(hi, pos + 2 * _CHUNK)]))
                pos = min(hi, pos + 2 * _CHUNK)
                continue
            if entry.done or entry.error:
                break
            try:
                async with entry.cond:
                    await asyncio.wait_for(
                        entry.cond.wait_for(
                            lambda: len(entry.buf) > pos or entry.done or entry.error
                        ),
                        _STALL_TIMEOUT,
                    )
            except asyncio.TimeoutError:
                break
        complete = (
            (stop is not None and pos >= stop)
            or (stop is None and entry.done and pos >= len(entry.buf))
        )
        if complete:
            await resp.write_eof()
        elif request.transport is not None:
            # upstream died / stalled mid-way: drop the connection so ffmpeg
            # sees an error (and reconnects) instead of a silent truncation
            request.transport.close()


spool = StreamSpool()
