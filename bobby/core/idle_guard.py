"""Voice-chat guard: bound how long a pause may last, and how long a call may
sit with no playback.

Rules:
- A pause is honoured for VC_PAUSE_LIMIT seconds (default 300 = 5 min).  When
  it expires the bot either RESUMES (default) or STOPS, per VC_PAUSE_ACTION.
  Inside the window the user can resume or stop as usual.
- A call that has had no playback for VC_IDLE_TIMEOUT is stopped and left.
"""

import asyncio
import os
import time

from bobby import logger

PAUSE_LIMIT = int(os.getenv("VC_PAUSE_LIMIT", "300"))
PAUSE_ACTION = os.getenv("VC_PAUSE_ACTION", "resume").strip().lower()
IDLE_AFTER = int(os.getenv("VC_IDLE_TIMEOUT", "1800"))
CHECK_EVERY = 60

_last: dict[int, float] = {}


async def _say(chat_id: int, text: str) -> None:
    try:
        from bobby import app
        await app.send_message(chat_id, text)
    except Exception:
        pass


async def _sweep(now: float | None = None) -> None:
    """One pass — separated from the loop so it can be exercised in tests."""
    from bobby import anon, db, queue

    now = now or time.time()
    chats = set(getattr(queue, "queues", {}) or {}) | set(_last)
    for chat_id in list(chats):
        try:
            if not await db.get_call(chat_id):
                _last.pop(chat_id, None)
                continue
            if await db.playing(chat_id):
                _last[chat_id] = now          # playing: keep the call
                continue
            started = _last.setdefault(chat_id, now)
            idle = now - started
            # pause window expired?
            if PAUSE_LIMIT and idle >= PAUSE_LIMIT and PAUSE_ACTION == "resume":
                ok = await anon.resume(chat_id)
                _last[chat_id] = now
                logger.info("pause limit: resumed %s after %ds", chat_id, int(idle))
                if ok:
                    await _say(chat_id, "\u25b6\ufe0f Paused too long \u2014 resumed.")
                else:
                    await anon.stop(chat_id)
                    _last.pop(chat_id, None)
                continue
            limit = PAUSE_LIMIT if (PAUSE_LIMIT and PAUSE_ACTION == "stop") else IDLE_AFTER
            if idle >= limit:
                _last.pop(chat_id, None)
                logger.info("vc guard: leaving %s after %ds idle", chat_id, int(idle))
                await anon.stop(chat_id)
                if PAUSE_ACTION == "stop":
                    await _say(chat_id, "\u23f8 Paused too long \u2014 leaving.")
        except Exception as ex:  # noqa: BLE001
            logger.warning("vc guard %s: %s", chat_id, type(ex).__name__)


async def watchdog() -> None:
    logger.info(
        "vc guard: pause limit %ds (action=%s), idle stop %ds",
        PAUSE_LIMIT, PAUSE_ACTION, IDLE_AFTER,
    )
    while True:
        await asyncio.sleep(CHECK_EVERY)
        try:
            await _sweep()
        except Exception as ex:  # noqa: BLE001
            logger.warning("vc guard sweep: %s", type(ex).__name__)
