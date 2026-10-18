# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Song suggestions when the music stops ("You May Like To Listen These Tracks").

When a YouTube track ends (played out or skipped) and nothing is queued
behind it, one card offers three songs YouTube Music would have queued
next; tapping a song plays it in the same voice chat, "More Songs ?" /
"◀ Back" page through the rest of the list. The card is posted from a
background task, so a slow or failing lookup can never delay the teardown.
One live card per chat: a new card replaces the previous one instead of
piling lists into the group.
"""

import asyncio
import time

from bobby import app, config, db, logger, queue
from bobby.core import ytmusic
from bobby.helpers import buttons

PAGE = 3            # songs per card page
_PAGES = 5          # how many pages "More Songs ?" can reach
_TTL = 6 * 3600     # seconds a fetched list stays valid for paging
_MAX_SEEDS = 300    # cache bound — lists are tiny, this is just a leak guard

DEFAULT_TEXT = (
    "<b>You May Like To Listen These Tracks</b>\n\n"
    "Choose a song Below & I'll play it In This Voice Chat."
)
DEFAULT_MORE = "More Songs ?"
DEFAULT_BACK = "◀ Back"
DEFAULT_PICKED = "🎵 Adding it to the voice chat…"
DEFAULT_EXPIRED = "This list has expired — /play a song to get a fresh one."
DEFAULT_AUTOPLAY = "▶️ <b>Autoplay</b> — playing <b>{0}</b> next."

_AUTOPLAY_MEMORY = 12   # ids remembered per chat so autoplay doesn't loop
_AUTOPLAY_TRIES = 4     # candidates resolved before giving up on a seed

_cache: dict[str, tuple[float, list[dict]]] = {}  # seed video id → (at, items)
_cards: dict[int, int] = {}                        # chat id → live card message id
_gen: dict[int, int] = {}                          # chat id → newest request token
_played: dict[int, list[str]] = {}                 # chat id → recent autoplay ids
_tasks: set[asyncio.Task] = set()
_pre_start: dict[int, int] = {}   # chat -> token allowed with a LIVE call


async def items_for(seed: str) -> list[dict]:
    """Related songs for a seed video id (cached so paging is instant and
    a restart-survivor card can still page by refetching)."""
    hit = _cache.get(seed)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    items = await ytmusic.related(
        seed, limit=PAGE * _PAGES, max_sec=config.DURATION_LIMIT
    )
    if items:
        if len(_cache) >= _MAX_SEEDS:
            _cache.pop(next(iter(_cache)))
        _cache[seed] = (time.monotonic(), items)
    return items


def page_of(items: list[dict], page: int) -> tuple[list[dict], int, int]:
    """Slice for `page` → (items, page, pages). The buttons never ask for a
    page outside the list; an out-of-range number (stale card, shorter
    refetched list) is clamped rather than wrapped."""
    pages = max(1, -(-len(items) // PAGE))
    page = min(max(page, 0), pages - 1)
    return items[page * PAGE:(page + 1) * PAGE], page, pages


def markup(items: list[dict], seed: str, page: int, _lang: dict):
    chunk, page, pages = page_of(items, page)
    return buttons.recs_markup(
        chunk, seed, page, pages,
        _lang.get("recs_more", DEFAULT_MORE),
        _lang.get("recs_back", DEFAULT_BACK),
    )


def suggest(chat_id: int, seed: str, _lang: dict) -> None:
    """Fire-and-forget: post the suggestion card for `seed` in `chat_id`.
    Only the newest request per chat may touch the chat's card — two quick
    song ends (skip, skip) must not let the older (slower) lookup overwrite
    the newer card."""
    token = _gen.get(chat_id, 0) + 1
    _gen[chat_id] = token
    task = asyncio.create_task(_post(chat_id, seed, _lang, token))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def autoplay(chat_id: int, seed: str, _lang: dict) -> None:
    """Fire-and-forget: keep the music going after the queue ran dry.

    Same seeding and same newest-request-wins rule as ``suggest``; when
    nothing fresh is left to play the chat still gets the suggestion card
    instead of silence."""
    token = _gen.get(chat_id, 0) + 1
    _gen[chat_id] = token
    task = asyncio.create_task(_autoplay(chat_id, seed, _lang, token))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def cancel(chat_id: int) -> None:
    """Invalidate whatever this chat's pending card/autoplay task is about
    to do.  A real /play, a /stop, or switching autoplay off must always
    win over a lookup that started before it."""
    _gen[chat_id] = _gen.get(chat_id, 0) + 1


async def _may_autoplay(chat_id: int, token: int) -> bool:
    """Whether this autoplay task may still touch the chat.

    Autoplay exists to fill silence, so it only ever acts while the chat is
    still idle: nobody cancelled it, the setting is still on, no voice chat
    is running and the queue is still empty.  Checked again immediately
    before the queue is touched, so a /play that lands mid-lookup wins."""
    if _gen.get(chat_id) != token:
        return False
    try:
        if not await db.get_autoplay(chat_id):
            return False
        # A queue-dry hand-off keeps the call UP on purpose, so an active
        # voice chat is allowed for that one token (owner 2026-10-18).  The
        # old rule refused whenever a call existed, which is exactly why
        # autoplay could not start a second song before the leave.
        if _pre_start.get(chat_id) == token:
            return True
        if await db.get_call(chat_id) or queue.get_queue(chat_id):
            return False
    except Exception as ex:
        logger.warning("autoplay: state check failed in %s: %s", chat_id, ex)
        return False
    return True


async def _pick(chat_id: int, seed: str, items: list[dict], recent: list[str]):
    """First related song that really is a new song here.

    The recommendation id is not what ends up playing: autoplay hands a
    text query to /play, and YouTube search can resolve it to a different
    upload — including the track that just finished.  Resolve first, then
    judge the resolved track, so a "different" recommendation can never
    replay the seed or a recently auto-played song."""
    from bobby import yt  # lazy: avoids a helpers ↔ core import cycle

    attempts = 0
    for item in items:
        vid = item.get("id")
        if not vid or vid == seed or vid in recent:
            continue
        if attempts >= _AUTOPLAY_TRIES:
            break
        attempts += 1
        query_text = f"{item.get('title') or ''} {item.get('artists') or ''}".strip()
        if not query_text:
            continue
        try:
            track = await yt.search(query_text, 0)
        except Exception as ex:
            logger.warning("autoplay: search failed for %r: %s", query_text, ex)
            track = None
        resolved = getattr(track, "id", None) if track else None
        if not resolved or resolved == seed or resolved in recent:
            # dead end or the same song again — never try this one again
            recent.append(vid)
            continue
        return item, query_text, track
    return None


async def _autoplay(chat_id: int, seed: str, _lang: dict, token: int) -> None:
    try:
        items = await items_for(seed)
        if not await _may_autoplay(chat_id, token):
            return
        recent = _played.setdefault(chat_id, [])
        chosen = await _pick(chat_id, seed, items, recent)
        del recent[:-_AUTOPLAY_MEMORY]
        if not chosen:
            # nothing new related to this seed — fall back to the card
            logger.info("autoplay: nothing fresh after %s in %s", seed, chat_id)
            if _gen.get(chat_id) != token:
                return
            return await _post(chat_id, seed, _lang, token)
        item, query_text, track = chosen
        recent.extend([item["id"], track.id])
        del recent[:-_AUTOPLAY_MEMORY]
        await _play(chat_id, item, query_text, track, _lang, token)
    except Exception as ex:
        logger.warning("autoplay failed in %s: %s: %s", chat_id, type(ex).__name__, ex)


async def _play(
    chat_id: int, item: dict, query_text: str, track, _lang: dict, token: int
) -> None:
    """Play one suggested song as if an admin had typed /play <title>.

    The synthetic command carries the bot itself as its author, so every
    /play step (queue limit, assistant join, duration cap, status messages)
    stays exactly the normal one.  The playback-policy gate is skipped on
    purpose: autoplay only runs because an admin switched it on for this
    group."""
    from pyrogram import types as ptypes  # local: keeps this helper import-light

    from bobby.plugins.play import play_hndlr

    title = str(item.get("title") or "").replace("<", "&lt;").replace(">", "&gt;")
    if not await _may_autoplay(chat_id, token):
        return
    notice = await app.send_message(
        chat_id, _lang.get("autoplay_next", DEFAULT_AUTOPLAY).format(title)
    )
    # last check before the queue is touched: a /play or /stop that landed
    # while we were announcing wins, and its own status message stands
    if not await _may_autoplay(chat_id, token):
        await _delete(chat_id, notice.id)
        return
    me = getattr(app, "me", None) or await app.get_me()
    fake = ptypes.Message(
        client=app,
        id=notice.id,
        chat=notice.chat,
        from_user=me,
        date=notice.date,
        text=f"/play {query_text}",
        command=["play", query_text],
    )
    lost = False

    async def _claim(final: bool = False) -> bool:
        """Asked by /play twice: right before the queue is touched, and
        again right before playback starts (``final``).  By then this pick
        is itself the queued item, so the idle test would always fail —
        what still has to hold is that nobody took the chat over in the
        meantime and that autoplay is still switched on."""
        nonlocal lost
        if final:
            allowed = (
                _gen.get(chat_id) == token and await db.get_autoplay(chat_id)
            )
        else:
            allowed = await _may_autoplay(chat_id, token)
        lost = not allowed
        return allowed

    fake.delete = _keep
    fake.skip_live_probe = True   # a song off the related list is never live
    fake.autoplay = True          # authorised by the group's autoplay setting
    fake.autoplay_track = track   # the exact track that was validated above
    fake.autoplay_claim = _claim
    logger.info("autoplay: playing %s in %s", getattr(track, "id", "?"), chat_id)
    await play_hndlr(app, fake)
    if lost:
        await _delete(chat_id, notice.id)
    return not lost


async def _keep(*_args, **_kwargs) -> bool:
    """Stands in for Message.delete on the synthetic /play: the autoplay
    notice is the status header, the "delete commands" setting must not
    wipe it."""
    return True


async def _delete(chat_id: int, message_id: int) -> None:
    try:
        await app.delete_messages(chat_id, message_id)
    except Exception:
        pass  # already gone or no delete right — a stale card is harmless


async def autoplay_now(chat_id: int, seed: str, _lang: dict) -> bool:
    """Start the next related song while the voice chat is STILL up.

    Called the moment the queue runs dry with autoplay on.  Returns True only
    when playback was really handed to /play, so the caller can skip the
    teardown and leave the assistant in the chat (owner 2026-10-18).
    """
    token = _gen.get(chat_id, 0) + 1
    _gen[chat_id] = token
    _pre_start[chat_id] = token
    try:
        items = await items_for(seed)
        if not items:
            return False
        if _gen.get(chat_id) != token or not await db.get_autoplay(chat_id):
            return False
        recent = _played.setdefault(chat_id, [])
        chosen = await _pick(chat_id, seed, items, recent)
        if not chosen:
            logger.info("autoplay: nothing fresh after %s in %s", seed, chat_id)
            return False
        item, query_text, track = chosen
        recent.extend([item["id"], track.id])
        del recent[:-_AUTOPLAY_MEMORY]
        return bool(await _play(chat_id, item, query_text, track, _lang, token))
    except Exception as ex:
        logger.warning("autoplay hand-off failed in %s: %s: %s",
                       chat_id, type(ex).__name__, ex)
        return False
    finally:
        _pre_start.pop(chat_id, None)


async def _post(chat_id: int, seed: str, _lang: dict, token: int) -> None:
    try:
        items = await items_for(seed)
        if _gen.get(chat_id) != token:
            return  # a newer song end took over this chat's card
        if not items:
            logger.info("recs: nothing related to %s for chat %s", seed, chat_id)
            return
        old = _cards.pop(chat_id, None)
        if old:
            await _delete(chat_id, old)
        sent = await app.send_message(
            chat_id,
            _lang.get("recs_text", DEFAULT_TEXT),
            reply_markup=markup(items, seed, 0, _lang),
        )
        if _gen.get(chat_id) != token:
            # superseded while sending: the newer card is already the live
            # one, so this message must go instead of shadowing it
            await _delete(chat_id, sent.id)
            return
        _cards[chat_id] = sent.id
        logger.info("recs: card posted in %s for %s (%d songs)", chat_id, seed, len(items))
    except Exception as ex:
        # decoration only — never let it surface as a play error
        logger.warning("recs card failed in %s: %s: %s", chat_id, type(ex).__name__, ex)
