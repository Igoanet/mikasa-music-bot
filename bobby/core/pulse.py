# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Playback pulse — measures, per play, where the audio pipeline stalls.

The chain is  source -> ffmpeg -> stdout pipe -> ntgcalls -> WebRTC ->
Telegram -> listener.  Everything up to the pipe is observable from inside
this process without touching the audio path:

* the fill level of ffmpeg's stdout pipe (``FIONREAD`` on our read end —
  the very fd ntgcalls reads from);
* ffmpeg's CPU time (``/proc/<pid>/task/*/schedstat``; this kernel has no
  ``/proc/<pid>/io``) — it only burns CPU while it is decoding, i.e. while
  it has input AND room in the pipe;
* what ffmpeg is blocked on (``/proc/<pid>/wchan``): ``anon_pipe_write``
  means "pipe full, waiting for ntgcalls", anything socket-ish means
  "waiting for input".

ntgcalls reads 100 ms of PCM (19 200 B at 48 kHz stereo s16) per read and
ffmpeg refills the 64 KB pipe at once, so in a healthy play the pipe sits
near full (>= 46 KB) and ffmpeg spends ~1 ms of CPU per 100 ms.  Two
failure shapes are told apart:

* **source underrun** — the pipe holds less than one slice for 300 ms:
  ffmpeg cannot keep it full because its input (spool/CDN) or its decoder
  stalled.  The gap the listener hears was born HERE.
* **consumer stall** — the pipe is stocked but ffmpeg has done no work for
  300 ms (it is parked in ``anon_pipe_write``): ntgcalls is not reading.
  Either the play is paused or the media/WebRTC side is wedged; the source
  is innocent.  (ntgcalls pulls one slice every 100 ms, so three silent
  100 ms windows can only mean >= 200 ms without a pull.)

Past the pipe the audio is Opus over UDP (ntgcalls sends 60 ms packets,
~17/s, and Telegram's relay answers with RTCP feedback ~10/s).  The kernel
counts those datagrams (``/proc/net/snmp``), so the watcher also tells:

* **send gap** — no UDP datagram left this box for 300 ms while a song is
  playing: the stall is INSIDE the process past the pipe (WebRTC/ntgcalls
  send path) — the network never saw it.
* **receive gap** — nothing came back from Telegram for 1 s: the relay's
  feedback stopped, i.e. packets are being lost or held up on the path in
  one direction or the other (relay reports arrive only for what it got).
* socket-level drops / tx-queue of our own UDP sockets (``/proc/net/udp``):
  rx drops mean the WebRTC network thread fell behind reading.

Everything is logged with the chat id so a user report can be matched to
numbers instead of guesses.  Also here: a main-event-loop lag monitor —
nothing on the audio path runs on the bot loop any more (the spool has its
own thread), but a blocked loop still delays commands and is worth a line.
"""

import asyncio
import fcntl
import os
import struct
import termios
import threading
import time

from bobby import logger

_TICK = 0.1                  # sampling period
_SLICE = 19_200              # one ntgcalls read: 100 ms of 48 kHz stereo s16le
_SRC_TICKS = 3               # pipe under one slice for 300 ms = source underrun
_CON_TICKS = 3               # no decode work for 300 ms with a stocked pipe = consumer stall
_IDLE_CPU_NS = 100_000       # < 0.1 ms CPU per tick: ffmpeg did no real decoding
_WARMUP = 1.0                # ignore the first second (initial pipe fill)
_FIND_TIMEOUT = 20           # ffmpeg spawn wait (join + probe can take a while)
_SEND_GAP_TICKS = 3          # 300 ms without one UDP datagram leaving = send gap
_RECV_GAP_TICKS = 10         # 1 s without one UDP datagram arriving = receive gap
_SOCK_EVERY = 10             # our UDP sockets are inspected once a second
_UDP_FIELDS = ("InDatagrams", "OutDatagrams", "InErrors", "RcvbufErrors", "SndbufErrors")

_watchers: dict[int, threading.Event] = {}
_lock = threading.Lock()


# ------------------------------------------------------------------ loop lag
async def loop_lag_monitor(threshold: float = 0.25, interval: float = 0.5) -> None:
    """Log when the bot's main loop is blocked for more than `threshold` s."""
    loop = asyncio.get_running_loop()
    while True:
        started = loop.time()
        await asyncio.sleep(interval)
        lag = loop.time() - started - interval
        if lag > threshold:
            logger.warning("event loop blocked for %.2fs (main bot loop)", lag)


# ------------------------------------------------------------ ffmpeg watcher
def watch(chat_id: int, track_id: str, media_path: str, duration: int = 0) -> None:
    """Start (or replace) the pulse watcher for a chat's current play.
    `duration` (seconds, 0 = unknown) tells a normal end-of-song EOF tail
    apart from a source that died mid-song."""
    stop = threading.Event()
    with _lock:
        prev = _watchers.pop(chat_id, None)
        if prev is not None:
            prev.set()
        _watchers[chat_id] = stop
    threading.Thread(
        target=_run,
        args=(chat_id, str(track_id), str(media_path), int(duration or 0), stop),
        name=f"pulse-{chat_id}",
        daemon=True,
    ).start()


def _find_ffmpeg(media_path: bytes, stop: threading.Event) -> int | None:
    """pid of the AUDIO ffmpeg decoding `media_path` (not the `sh -c` parent,
    not ffprobe, not the video decoder of the same play)."""
    deadline = time.monotonic() + _FIND_TIMEOUT
    while not stop.is_set() and time.monotonic() < deadline:
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open(f"/proc/{d}/cmdline", "rb") as f:
                    cmd = f.read()
            except OSError:
                continue
            argv = cmd.split(b"\0")
            if not argv or not argv[0].endswith(b"ffmpeg"):
                continue
            if media_path in cmd and b"s16le" in cmd:
                return int(d)
        stop.wait(0.5)
    return None


def _pipe_fd(ffmpeg_pid: int) -> tuple[int | None, str]:
    """Our read end of ffmpeg's stdout pipe (the fd ntgcalls reads)."""
    try:
        target = os.readlink(f"/proc/{ffmpeg_pid}/fd/1")
    except OSError:
        return None, ""
    if not target.startswith("pipe:"):
        return None, target
    for name in os.listdir("/proc/self/fd"):
        try:
            if os.readlink(f"/proc/self/fd/{name}") == target:
                return int(name), target
        except OSError:
            continue
    return None, target


def _cpu_ns(ffmpeg_pid: int) -> int | None:
    """Total on-CPU nanoseconds of every ffmpeg thread; None once it exited."""
    try:
        total = 0
        for tid in os.listdir(f"/proc/{ffmpeg_pid}/task"):
            try:
                with open(f"/proc/{ffmpeg_pid}/task/{tid}/schedstat") as f:
                    total += int(f.read().split()[0])
            except (OSError, ValueError, IndexError):
                continue
        return total
    except OSError:
        return None


def _wchan(ffmpeg_pid: int) -> str:
    try:
        with open(f"/proc/{ffmpeg_pid}/wchan") as f:
            return f.read().strip() or "running"
    except OSError:
        return "?"


def _fill(fd: int | None, target: str) -> int | None:
    if fd is None:
        return None
    try:
        # the fd number could be recycled once ntgcalls closes the pipe;
        # make sure it is still OUR end of THIS pipe before asking
        if os.readlink(f"/proc/self/fd/{fd}") != target:
            return None
        buf = fcntl.ioctl(fd, termios.FIONREAD, b"\0\0\0\0")
        return struct.unpack("i", buf)[0]
    except OSError:
        return None


# ------------------------------------------------------------------- network
# Linux keeps no per-socket packet counters for UDP, so the send/receive view
# is the whole network namespace (this container): IPv4 ``/proc/net/snmp`` +
# IPv6 ``/proc/net/snmp6``.  With ONE play running the only steady UDP flow in
# the box is that call (the other bots use UDP for the odd DNS lookup), so a
# box-wide gap is that call's gap.  With several plays at once the numbers
# blur together — the watcher says so instead of pretending.
_active_plays = 0
_active_lock = threading.Lock()


def _udp_counters() -> dict[str, int] | None:
    """Namespace-wide UDP totals, IPv4 + IPv6 combined.
    OutDatagrams moving while a song plays is proof the audio left the box;
    InDatagrams moving is Telegram's relay talking back (RTCP)."""
    totals: dict[str, int] | None = None
    try:
        with open("/proc/net/snmp") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    for i, line in enumerate(lines):
        if line.startswith("Udp:") and i + 1 < len(lines):
            keys = line.split()[1:]
            try:
                vals = [int(v) for v in lines[i + 1].split()[1:]]
            except ValueError:
                return None
            row = dict(zip(keys, vals))
            totals = {k: row.get(k, 0) for k in _UDP_FIELDS}
            break
    if totals is None:
        return None
    try:  # IPv6 lives in a "Udp6InDatagrams <n>" one-per-line file
        with open("/proc/net/snmp6") as f:
            for line in f:
                p = line.split()
                if len(p) == 2 and p[0].startswith("Udp6"):
                    key = p[0][4:]
                    if key in totals:
                        try:
                            totals[key] += int(p[1])
                        except ValueError:
                            pass
    except OSError:
        pass  # no IPv6 stack: v4 totals are the whole story
    return totals


def _our_udp_sockets() -> dict[int, tuple[int, int, int]]:
    """{local port: (tx_queue B, rx_queue B, rx drops)} for every UDP socket
    this process owns — during a call that is the WebRTC media socket."""
    inodes = set()
    try:
        names = os.listdir("/proc/self/fd")
    except OSError:
        return {}
    for name in names:
        try:
            link = os.readlink(f"/proc/self/fd/{name}")
        except OSError:
            continue
        if link.startswith("socket:[") and link.endswith("]"):
            inodes.add(link[8:-1])
    found: dict[int, tuple[int, int, int]] = {}
    for path in ("/proc/net/udp", "/proc/net/udp6"):
        try:
            with open(path) as f:
                rows = f.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            p = row.split()
            # sl local rem st tx:rx tr:when retrnsmt uid timeout inode ref ptr drops
            if len(p) < 10 or p[9] not in inodes:
                continue
            try:
                port = int(p[1].rsplit(":", 1)[1], 16)
                txq, rxq = (int(x, 16) for x in p[4].split(":"))
                drops = int(p[12]) if len(p) > 12 else 0  # column absent on old kernels
            except (ValueError, IndexError):
                continue
            found[port] = (txq, rxq, drops)
    return found


class _NetPulse:
    """UDP-side view of one play: send/receive continuity + our socket health.

    Every method swallows its own errors: a surprise /proc format must never
    stop the pipe diagnostics that share the sampling loop."""

    def __init__(self, tag: str, started: float) -> None:
        self.tag = tag
        self.started = started
        self.base = self.last = _udp_counters()
        self.out_zero = self.in_zero = 0
        self.send_gap_since: float | None = None
        self.recv_gap_since: float | None = None
        self.n_send = self.n_recv = 0
        self.worst_send = self.worst_recv = 0.0
        self.ticks = 0
        self.txq_max = 0
        self.first_drops: dict[int, int] = {}
        self.last_drops: dict[int, int] = {}
        self.ports: set[int] = set()
        self.shared = False          # another play overlapped: box-wide numbers only
        self.broken = False
        global _active_plays
        with _active_lock:
            _active_plays += 1

    def close(self) -> None:
        global _active_plays
        with _active_lock:
            _active_plays = max(0, _active_plays - 1)

    @property
    def enabled(self) -> bool:
        return self.base is not None

    def tick(self, now: float, warm: bool) -> None:
        if self.last is None or self.broken:
            return
        try:
            self._tick(now, warm)
        except Exception as ex:
            self.broken = True
            logger.warning("%s: udp telemetry stopped (%s) — pipe monitoring continues", self.tag, ex)

    def _tick(self, now: float, warm: bool) -> None:
        cur = _udp_counters()
        if cur is None:
            return
        d_out = cur["OutDatagrams"] - self.last["OutDatagrams"]
        d_in = cur["InDatagrams"] - self.last["InDatagrams"]
        self.last = cur
        self.ticks += 1
        if self.ticks % _SOCK_EVERY == 0:
            self._sockets()
        if not warm:
            return
        at = now - self.started
        with _active_lock:
            overlap = _active_plays > 1
        if overlap:
            self.shared = True
        scope = (
            " (another play is active — box-wide count, not this call alone)" if overlap else ""
        )

        self.out_zero = self.out_zero + 1 if d_out == 0 else 0
        if self.send_gap_since is None:
            if self.out_zero == _SEND_GAP_TICKS:
                self.send_gap_since = now - _SEND_GAP_TICKS * _TICK
        elif d_out > 0:
            dur = now - self.send_gap_since   # first datagram fell somewhere in this tick: <= 100 ms high
            self.send_gap_since = None
            self.n_send += 1
            self.worst_send = max(self.worst_send, dur)
            logger.warning(
                "%s: udp send gap %.1fs at %.0fs — no UDP datagram left this box at all%s "
                "(the stall is inside the process past the pipe: WebRTC/ntgcalls send path)",
                self.tag, dur, at - dur, scope,
            )

        self.in_zero = self.in_zero + 1 if d_in == 0 else 0
        if self.recv_gap_since is None:
            if self.in_zero == _RECV_GAP_TICKS:
                self.recv_gap_since = now - _RECV_GAP_TICKS * _TICK
        elif d_in > 0:
            dur = now - self.recv_gap_since
            self.recv_gap_since = None
            self.n_recv += 1
            self.worst_recv = max(self.worst_recv, dur)
            logger.warning(
                "%s: udp receive gap %.1fs at %.0fs — no UDP datagram reached this box at all%s "
                "(Telegram's relay feedback stopped: packets lost or held up on the network path)",
                self.tag, dur, at - dur, scope,
            )

    def _sockets(self) -> None:
        for port, (txq, _rxq, drops) in _our_udp_sockets().items():
            self.ports.add(port)
            self.txq_max = max(self.txq_max, txq)
            self.first_drops.setdefault(port, drops)
            self.last_drops[port] = drops

    def summary(self, now: float) -> str:
        if self.base is None or self.last is None:
            return "udp counters unavailable"
        try:
            return self._summary(now)
        except Exception as ex:
            return f"udp summary unavailable ({ex})"

    def _summary(self, now: float) -> str:
        # (a gap still open at song end is the normal EOF tail — not counted;
        # a send path that dies mid-song shows up as a consumer stall anyway)
        secs = max(now - self.started, 0.001)
        out = self.last["OutDatagrams"] - self.base["OutDatagrams"]
        inc = self.last["InDatagrams"] - self.base["InDatagrams"]
        drops = sum(self.last_drops[p] - self.first_drops[p] for p in self.last_drops)
        errs = sum(self.last[k] - self.base[k] for k in ("InErrors", "RcvbufErrors", "SndbufErrors"))
        note = " [box-wide: plays overlapped]" if self.shared else ""
        if self.broken:
            note += " [telemetry stopped early]"
        return (
            f"udp out {out} pkts ({out / secs:.1f}/s) in {inc} ({inc / secs:.1f}/s), "
            f"send gaps {self.n_send} (worst {self.worst_send:.1f}s), "
            f"receive gaps {self.n_recv} (worst {self.worst_recv:.1f}s), "
            f"socket rx drops {drops}, tx queue max {self.txq_max} B, udp errors {errs}, "
            f"ports {sorted(self.ports) or '-'}{note}"
        )


def _run(chat_id: int, track_id: str, media_path: str, duration: int, stop: threading.Event) -> None:
    tag = f"pulse[{chat_id}] {track_id}"
    try:
        pid = _find_ffmpeg(media_path.encode(), stop)
        if pid is None:
            if not stop.is_set():
                logger.warning("%s: audio ffmpeg not found — not monitored", tag)
            return
        fd, target = _pipe_fd(pid)
        if fd is None:
            logger.warning("%s: ffmpeg pid %s found but its pipe is not visible — not monitored", tag, pid)
            return
        logger.info("%s: watching ffmpeg pid %s (pipe fd %s)", tag, pid, fd)
        _sample_loop(tag, pid, fd, target, duration, stop)
    except Exception as ex:  # a monitor must never take the bot down
        logger.warning("%s: watcher aborted: %s", tag, ex)
    finally:
        with _lock:
            if _watchers.get(chat_id) is stop:
                del _watchers[chat_id]


def _sample_loop(tag: str, pid: int, fd: int, target: str, duration: int, stop: threading.Event) -> None:
    started = time.monotonic()
    net = _NetPulse(tag, started)
    if not net.enabled:
        logger.warning("%s: /proc/net/snmp unreadable — udp side not monitored", tag)
    try:
        _sample(tag, pid, fd, target, duration, stop, started, net)
    finally:
        net.close()


def _sample(tag: str, pid: int, fd: int, target: str, duration: int, stop: threading.Event,
            started: float, net: "_NetPulse") -> None:
    last_cpu = _cpu_ns(pid)
    low_ticks = idle_ticks = 0
    stall_kind: str | None = None
    stall_since = 0.0
    n_src = n_con = 0
    worst_src = worst_con = total_src = 0.0
    fill_sum = fill_n = 0
    fill_min: int | None = None

    def _close_stall(now: float, at_exit: bool = False) -> None:
        nonlocal stall_kind, n_src, n_con, worst_src, worst_con, total_src
        dur = now - stall_since
        if at_exit:
            # ffmpeg left during the gap: the pipe drains and ffmpeg spends
            # ~1-2 s in its reconnect-at-EOF probe (416) at every song end —
            # that is the normal tail, not a stall. Earlier than the known
            # duration it means the source was cut off.
            played = now - started
            if duration and played < duration - 5:
                logger.warning(
                    "%s: %s gap ran into ffmpeg exit at %.0fs of %ds — source cut off mid-song",
                    tag, stall_kind, played, duration,
                )
            else:
                logger.info("%s: end-of-song tail %.1fs (ffmpeg EOF probe) — normal", tag, dur)
            stall_kind = None
            return
        if stall_kind == "source":
            n_src += 1
            worst_src = max(worst_src, dur)
            total_src += dur
        else:
            n_con += 1
            worst_con = max(worst_con, dur)
        logger.warning("%s: %s stall over after %.1fs", tag, stall_kind, dur)
        stall_kind = None

    while not stop.wait(_TICK):
        cpu = _cpu_ns(pid)
        if cpu is None:
            break  # ffmpeg gone: song over / skipped
        fill = _fill(fd, target)
        if fill is None:
            break  # our end of the pipe is gone: ntgcalls closed the stream
        now = time.monotonic()
        worked = cpu - (last_cpu or 0)
        last_cpu = cpu
        fill_sum += fill
        fill_n += 1
        fill_min = fill if fill_min is None else min(fill_min, fill)
        warm = now - started > _WARMUP
        net.tick(now, warm)

        low_ticks = low_ticks + 1 if fill < _SLICE else 0
        idle_ticks = idle_ticks + 1 if worked < _IDLE_CPU_NS else 0

        if stall_kind is None and warm:
            if low_ticks == _SRC_TICKS:
                stall_kind = "source"
                stall_since = now - _SRC_TICKS * _TICK
                if duration and now - started >= duration - 5:
                    logger.info("%s: pipe empty at %.0fs of %ds — song ending", tag, now - started, duration)
                else:
                    logger.warning(
                        "%s: source underrun — pipe down to %d B for 300 ms, "
                        "ffmpeg %s (input/decoder starved: the gap was born here)",
                        tag, fill, "decoding" if worked >= _IDLE_CPU_NS else "waiting in " + _wchan(pid),
                    )
            elif idle_ticks == _CON_TICKS and fill >= _SLICE:
                stall_kind = "consumer"
                stall_since = now - _CON_TICKS * _TICK
                logger.warning(
                    "%s: consumer stall — %d KB queued, ffmpeg idle in %s for "
                    "300 ms: ntgcalls stopped reading (paused, or media/WebRTC "
                    "side wedged; the source is not the problem)",
                    tag, fill // 1024, _wchan(pid),
                )
        elif stall_kind == "source" and fill >= _SLICE:
            _close_stall(now)
        elif stall_kind == "consumer" and (worked >= _IDLE_CPU_NS or fill < _SLICE):
            _close_stall(now)

    now = time.monotonic()
    if stall_kind is not None:
        _close_stall(now, at_exit=not stop.is_set())
    if fill_n:
        logger.info(
            "%s: %.0fs monitored — source underruns %d (worst %.1fs, total %.1fs), "
            "consumer stalls %d (worst %.1fs), pipe fill avg %d KB min %d B; %s",
            tag, now - started, n_src, worst_src, total_src, n_con, worst_con,
            fill_sum // fill_n // 1024, fill_min or 0, net.summary(now),
        )
