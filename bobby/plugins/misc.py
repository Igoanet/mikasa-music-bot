# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import time
import asyncio

from pyrogram import enums, errors, filters, types

from bobby import anon, app, config, db, lang, logger, queue, tasks, userbot, yt
from bobby.core.group_exit import install as install_group_exit
from bobby.helpers import buttons
import os as _os
# Assistant group-sweep: OFF by default (2026-10-13).  Removing the
# assistant from groups the bot was merely idle in silently broke any
# other bot using that account (Maki VC monitor -> ChannelInvalid).
ASSISTANT_GROUP_SWEEP = (
    (_os.getenv("ASSISTANT_GROUP_SWEEP", "false") or "false")
    .strip().lower() in ("1", "true", "yes", "on")
)

group_exit = install_group_exit(app, db, userbot, anon, logger)

def _prefetchable(track) -> bool:
    """Only prefetch ordinary finite media; LIVE feeds are signed/short-lived."""
    return bool(
        track
        and not track.file_path
        and not getattr(track, "_prefetch_tried", False)
        and getattr(track, "duration", None) != "🔴 LIVE"
        and getattr(track, "view_count", None) != "LIVE"
    )

@app.on_message(filters.video_chat_started, group=19)
@app.on_message(filters.video_chat_ended, group=20)
async def _watcher_vc(_, m: types.Message):
    await anon.stop(m.chat.id)

async def auto_leave():
    while True:
        await asyncio.sleep(3600)
        for ub in userbot.clients:
            try:
                chats = [dialog.chat.id async for dialog in ub.get_dialogs()
                            if dialog.chat.type in [
                                enums.ChatType.GROUP, enums.ChatType.SUPERGROUP,
                            ]][-20:]
                for chat in chats:
                    if chat in [app.logger, -1001686672798, -1001549206010]:
                        continue
                    if chat in db.active_calls:
                        continue
                    if ASSISTANT_GROUP_SWEEP:
                        await ub.leave_chat(chat)
                        await asyncio.sleep(12)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

async def track_time():
    try:
        while True:
            await asyncio.sleep(1)
            for chat_id in list(db.active_calls):
                if not await db.playing(chat_id):
                    continue

                media = queue.get_current(chat_id)
                if not media:
                    continue
                media.time += 1
    except asyncio.CancelledError:
        raise

async def update_timer(length=10, sleep=12):
    while True:
        await asyncio.sleep(sleep)
        for chat_id in list(db.active_calls):
            if not await db.playing(chat_id):
                continue
            try:
                media = queue.get_current(chat_id)
                if not media:
                    continue
                duration, message_id = media.duration_sec, media.message_id
                if not duration or not message_id or not media.time:
                    continue
                played = media.time
                remaining = max(duration - played, 0)
                pos = min(int((played / duration) * length), length - 1)
                timer = "—" * pos + "◉" + "—" * (length - pos - 1)

                if played >= 10:
                    # prefetch the next track as soon as the current one is
                    # safely playing (was: only in the last 75s, and never
                    # for unknown-duration tracks) — downloads run niced +
                    # capped so they can't hurt playback, and an EARLY fetch
                    # is what makes the next song start the instant this one
                    # ends. One attempt per track: play_next's own resolve
                    # is the backstop — no 12s retry-hammering of a failing
                    # track against rate-limited APIs.
                    next = queue.get_next(chat_id, check=True)
                    if _prefetchable(next):
                        next._prefetch_tried = True
                        # playback may concurrently fall back to an alternate
                        # upload and switch this track's identity — only keep
                        # our result if the track is still the one we
                        # fetched and it still needs a source
                        expected_id = next.id
                        path = await yt.play_source(next, video=next.video)
                        if next.id == expected_id and not next.file_path:
                            next.file_path = path

                if remaining < 10:
                    remove = True
                else:
                    if config.THUMB_GEN:
                        timer = f"{time.strftime('%M:%S', time.gmtime(played))} | {timer} | -{time.strftime('%M:%S', time.gmtime(remaining))}"
                    else:
                        timer = None
                    remove = False

                if not timer and not remove:
                    continue

                await app.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=buttons.controls(
                        chat_id=chat_id,
                        timer=timer,
                        remove=remove,
                        # the timer refresh rewrites the whole panel — keep
                        # the autoplay switch on it instead of dropping it
                        autoplay=None if remove else await db.get_autoplay(chat_id),
                        _lang=await lang.get_lang(chat_id), is_admin=True,autoplay_all=await db.get_autoplay_all(chat_id),),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

async def vc_watcher(sleep=15):
    while True:
        await asyncio.sleep(sleep)
        for chat_id in list(db.active_calls):
            client = await db.get_assistant(chat_id)
            media = queue.get_current(chat_id)
            if not media:
                continue
            participants = await client.get_participants(chat_id)
            if len(participants) < 2 and media.time > 30:
                _lang = await lang.get_lang(chat_id)
                try:
                    sent = await app.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=media.message_id,
                        reply_markup=buttons.controls(
                            chat_id=chat_id, status=_lang["stopped"], remove=True
                        ),
                    )
                    await anon.stop(chat_id)
                    await sent.reply_text(_lang["auto_left"])
                except errors.MessageIdInvalid:
                    pass

if config.AUTO_END:
    tasks.append(asyncio.create_task(vc_watcher()))
if config.AUTO_LEAVE:
    tasks.append(asyncio.create_task(auto_leave()))
tasks.append(asyncio.create_task(track_time()))
tasks.append(asyncio.create_task(update_timer()))
