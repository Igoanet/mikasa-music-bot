"""Central safety guard: per-user command rate limiting + handler timeouts.

Installed once right after the Client is created; wraps app.on_message and
app.on_callback_query so every plugin handler is covered without touching
plugin code.

- Commands ("/", "!" or "?" prefix) are rate-limited per user and globally;
  floods are dropped silently (no reply = no amplification).
- Staff (owner + sudo) are exempt from rate limits.
- A global in-flight semaphore caps concurrent command/callback handlers.
  It is sized from app.workers at install time (pyrogram defaults to
  min(32, cpu+4), which can be tiny on a shared VPS) and always reserves
  workers for plain-message listeners like anti-spam. Excess updates are
  rejected immediately instead of queuing up and starving the bot.
- Every command handler must finish within CMD_TIMEOUT seconds, except the
  long-running owner/sudo tools listed in no_timeout. Callbacks get
  CB_TIMEOUT and a bot-wide callback limit — except callbacks whose module
  is in cb_exempt_modules (they launch deliberately long jobs such as
  mass-ban or voice generation).
- The same Telegram message is counted once even when several handlers
  match it (different dispatcher groups).
- Per-user state maps are evicted once they grow past MAX_BUCKETS, so a
  distributed flood cannot grow memory forever.
"""

import asyncio
import functools
import logging
import time
from collections import defaultdict, deque

MAX_CMDS = 6          # commands per user per CMD_WINDOW
CMD_WINDOW = 15       # seconds
MAX_CB = 12           # button taps per user per CB_WINDOW
CB_WINDOW = 10        # seconds
GLOBAL_MAX = 300      # commands bot-wide per GLOBAL_WINDOW
GLOBAL_CB_MAX = 120   # callbacks bot-wide per GLOBAL_WINDOW
GLOBAL_WINDOW = 60    # seconds
CMD_TIMEOUT = 300     # seconds per command handler
CB_TIMEOUT = 60       # seconds per callback handler
MAX_BUCKETS = 5000    # hard cap on per-user state maps

_CMD_PREFIXES = ("/", "!", "?")

_hits = defaultdict(deque)          # uid -> deque[timestamps]
_cb_hits = defaultdict(deque)       # uid -> deque[timestamps]
_global = deque()                   # timestamps, all commands
_global_cb = deque()                # timestamps, all callbacks
_counted = {}                       # (chat_id, msg_id) -> ts (dedup)
_inflight = None                    # asyncio.Semaphore, created in install()


def _prune(dq, window, now):
    while dq and now - dq[0] > window:
        dq.popleft()


def _evict(d, window, now):
    """Drop stale/empty per-user buckets once the map grows too big."""
    if len(d) > MAX_BUCKETS:
        stale = [k for k, v in d.items() if not v or now - v[-1] > window]
        for k in stale:
            del d[k]


def _is_command(m) -> bool:
    text = m.text or m.caption or ""
    return text.startswith(_CMD_PREFIXES)


def _cmd_name(m) -> str:
    first = (m.text or m.caption or "").split(maxsplit=1)[0]
    return first.lstrip("/!?").split("@")[0].lower()


def install_guard(app, is_staff, no_timeout=frozenset(),
            cb_exempt_modules=frozenset(), log=None):
    """Wrap the client's handler decorators with rate limit + timeout.

    is_staff: async callable(uid) -> bool, exempt from rate limits.
    no_timeout: set of command names allowed to run past CMD_TIMEOUT.
    cb_exempt_modules: callback handlers from these modules are allowed to
        run past CB_TIMEOUT (they launch deliberately long jobs).
    """
    global _inflight
    log = log or logging.getLogger("rateguard")

    # size the concurrency cap from the real worker count, always keeping
    # some workers free for plain-message listeners
    workers = getattr(app, "workers", None) or 32
    reserve = max(2, workers // 4)
    slots = max(2, workers - reserve)
    _inflight = asyncio.Semaphore(slots)
    log.info("rateguard: %s workers -> %s handler slots", workers, slots)

    _orig_on_message = app.on_message
    _orig_on_cb = app.on_callback_query

    async def _allowed(uid: int, key) -> bool:
        now = time.monotonic()
        # same message already counted by an earlier handler group
        ts = _counted.get(key)
        if ts is not None and now - ts < CMD_WINDOW:
            return True
        if len(_counted) > MAX_BUCKETS:
            for k, v in list(_counted.items()):
                if now - v > CMD_WINDOW:
                    del _counted[k]
        if await is_staff(uid):
            return True
        _evict(_hits, CMD_WINDOW, now)
        dq = _hits[uid]
        _prune(dq, CMD_WINDOW, now)
        _prune(_global, GLOBAL_WINDOW, now)
        if len(dq) >= MAX_CMDS or len(_global) >= GLOBAL_MAX:
            return False
        dq.append(now)
        _global.append(now)
        _counted[key] = now
        return True

    def on_message(flt=None, group=0):
        def deco(handler):
            @functools.wraps(handler)
            async def wrapped(client, message, *args):
                if not _is_command(message):
                    return await handler(client, message, *args)
                uid = message.from_user.id if message.from_user else 0
                key = (message.chat.id, message.id)
                if not await _allowed(uid, key):
                    return None  # flood — drop silently
                if _inflight.locked():
                    return None  # all handler slots busy — reject, never queue
                await _inflight.acquire()
                try:
                    if _cmd_name(message) in no_timeout:
                        return await handler(client, message, *args)
                    try:
                        return await asyncio.wait_for(
                            handler(client, message, *args), CMD_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        log.warning(
                            "timeout %ss: /%s in %s",
                            CMD_TIMEOUT, _cmd_name(message),
                            handler.__module__,
                        )
                        return None
                finally:
                    _inflight.release()

            return _orig_on_message(flt, group)(wrapped)

        return deco

    def on_callback_query(flt=None, group=0):
        def deco(handler):
            @functools.wraps(handler)
            async def wrapped(client, cq, *args):
                uid = cq.from_user.id if cq.from_user else 0
                now = time.monotonic()
                _evict(_cb_hits, CB_WINDOW, now)
                dq = _cb_hits[uid]
                _prune(dq, CB_WINDOW, now)
                _prune(_global_cb, GLOBAL_WINDOW, now)
                if (
                    len(dq) >= MAX_CB or len(_global_cb) >= GLOBAL_CB_MAX
                ) and not await is_staff(uid):
                    try:
                        await cq.answer()
                    except Exception:
                        pass
                    return None
                dq.append(now)
                _global_cb.append(now)
                if _inflight.locked():
                    try:
                        await cq.answer()
                    except Exception:
                        pass
                    return None
                await _inflight.acquire()
                try:
                    if handler.__module__ in cb_exempt_modules:
                        # launches a deliberately long job (mass-ban, voice
                        # generation) — never cancelled by CB_TIMEOUT
                        return await handler(client, cq, *args)
                    try:
                        return await asyncio.wait_for(
                            handler(client, cq, *args), CB_TIMEOUT
                        )
                    except asyncio.TimeoutError:
                        log.warning(
                            "callback timeout %ss in %s",
                            CB_TIMEOUT, handler.__module__,
                        )
                        try:
                            await cq.answer()
                        except Exception:
                            pass
                        return None
                finally:
                    _inflight.release()

            return _orig_on_cb(flt, group)(wrapped)

        return deco

    app.on_message = on_message
    app.on_callback_query = on_callback_query
