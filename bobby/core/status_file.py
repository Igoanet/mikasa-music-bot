"""
Live status snapshot for the Webview page.

Every STATUS_EVERY seconds the bot writes data/status.json (atomic replace,
~1 KB): who it is, since when it runs, and every active voice chat with the
current track and position. The API server (artifacts/api-server, route
/api/music) renders the file; an updated_at older than STALE_AFTER seconds
means the bot is down, and a clean shutdown marks the file offline at once.

Since the bot moved to the VPS (2026-09-10) the API server cannot read the file
directly: STATUS_MIRROR (absolute path, optional) names a second copy — a
directory nginx serves — which the API server fetches over HTTP instead. A
mirror failure is logged (rate-limited) and never disturbs the primary write.
"""

import asyncio
import html
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from bobby import app, db, logger, queue

STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STATUS_FILE = STORE_DIR / "status.json"
_mirror_env = os.environ.get("STATUS_MIRROR", "").strip()
STATUS_MIRROR = Path(_mirror_env).expanduser() if _mirror_env else None
MIRROR_WARN_EVERY = 600    # seconds between repeated mirror-failure warnings
STATUS_EVERY = 10          # seconds between snapshots
STALE_AFTER = 3 * STATUS_EVERY
TITLE_RETRY = 300          # seconds before a failed chat-title lookup is retried
TITLE_TIMEOUT = 5          # seconds — a slow get_chat must not stall the snapshot loop
UNKNOWN_TITLE = "Unknown group"   # never expose raw chat ids on the page

_started = time.time()
_titles: dict[int, tuple[str, float]] = {}   # chat_id -> (title, retry_after or 0)
_write_lock = threading.Lock()   # the loop writes from a worker thread; mark_offline must not overtake it
_mirror_warned = 0.0
_offline_marked = False   # set under _write_lock by mark_offline(); later online snapshots are dropped
_TAG = re.compile(r"<[^>]+>")


async def _chat_title(chat_id: int) -> str:
    cached = _titles.get(chat_id)
    if cached and (not cached[1] or cached[1] > time.time()):
        return cached[0]
    try:
        chat = await asyncio.wait_for(app.get_chat(chat_id), timeout=TITLE_TIMEOUT)
        title = chat.title or chat.first_name or UNKNOWN_TITLE
        _titles[chat_id] = (title, 0)
    except Exception as e:
        logger.debug(f"status: title lookup failed for {chat_id}: {type(e).__name__}: {e}")
        title = UNKNOWN_TITLE
        _titles[chat_id] = (title, time.time() + TITLE_RETRY)
    return title


def _plain_name(user) -> str | None:
    """media.user is a Pyrogram mention (<a href="tg://user?id=…">Name</a>) — keep the name only."""
    if not user:
        return None
    return html.unescape(_TAG.sub("", str(user))).strip() or None


def _public_url(url) -> str | None:
    """Only web links go to the page; anything else (tg://, javascript:, local paths) is dropped."""
    if isinstance(url, str) and url.lower().startswith(("https://", "http://")):
        return url
    return None


async def snapshot() -> dict:
    calls = []
    for chat_id in list(db.active_calls):
        media = queue.get_current(chat_id)
        calls.append({
            "title": await _chat_title(chat_id),
            "playing": await db.playing(chat_id),
            "track": media.title if media else None,
            "url": _public_url(media.url) if media else None,
            "requested_by": _plain_name(media.user) if media else None,
            "duration_sec": media.duration_sec if media else 0,
            "position_sec": media.time if media else 0,
            "video": bool(media.video) if media else False,
            "queued": max(len(queue.get_queue(chat_id)) - 1, 0),
        })
    return {
        "online": True,
        "bot": getattr(app, "username", None),
        "name": getattr(app, "name", None),
        "started_at": _started,
        "updated_at": time.time(),
        "interval_sec": STATUS_EVERY,
        "stale_after_sec": STALE_AFTER,
        "served_chats": len(db.chats),
        "served_users": len(db.users),
        "active_calls": calls,
    }


def _atomic_write(target: Path, data: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix="status_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o644)  # the API server / nginx read it; nothing secret inside
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write(data: dict) -> None:
    global _mirror_warned
    with _write_lock:
        # mark_offline() may win the lock while a loop snapshot is still queued on the
        # worker thread; that older "online" snapshot must not overwrite the offline mark
        if _offline_marked and data.get("online"):
            return
        _atomic_write(STATUS_FILE, data)
        if STATUS_MIRROR is None:
            return
        try:
            _atomic_write(STATUS_MIRROR, data)
        except OSError as e:
            now = time.time()
            if now - _mirror_warned >= MIRROR_WARN_EVERY:
                _mirror_warned = now
                logger.warning(f"status: mirror write to {STATUS_MIRROR} failed: {type(e).__name__}: {e}")


def mark_offline() -> None:
    """Called from stop(): flag the file so the page flips at once, not after STALE_AFTER."""
    global _offline_marked
    with _write_lock:
        _offline_marked = True
    try:
        _write({
            "online": False,
            "bot": getattr(app, "username", None),
            "name": getattr(app, "name", None),
            "started_at": _started,
            "updated_at": time.time(),
            "interval_sec": STATUS_EVERY,
            "stale_after_sec": STALE_AFTER,
            "active_calls": [],
        })
    except Exception as e:
        logger.warning(f"status: offline mark failed: {type(e).__name__}: {e}")


async def loop() -> None:
    while True:
        try:
            data = await snapshot()
            await asyncio.to_thread(_write, data)  # disk I/O off the audio loop
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"status: snapshot failed: {type(e).__name__}: {e}")
        await asyncio.sleep(STATUS_EVERY)
