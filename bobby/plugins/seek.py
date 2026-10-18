# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


from pyrogram import filters, types

from bobby import anon, app, db, lang, queue
from bobby.helpers._selfdel import clean_reply
from bobby.helpers import can_manage_vc


@app.on_message(
    filters.command(["seek", "seekforward", "seekf", "seekback", "seekb"])
    & filters.group & ~app.bl_users
)
@lang.language()
@can_manage_vc
async def _seek(_, m: types.Message):
    # Direction, and a sensible default: a bare /seekback now steps 15s
    # (same as the panel buttons).  Before, it demanded an argument and
    # answered with a usage line instead (owner 2026-10-18).
    name = m.command[0].lower()
    backward = name in ("seekback", "seekb")
    if len(m.command) < 2:
        to_seek = 15
    else:
        try:
            to_seek = int(m.command[1])
        except ValueError:
            return await clean_reply(m, m.lang["play_seek_usage"].format(name))
    if to_seek < 1:
        return await clean_reply(m, m.lang["play_seek_min"])
    if to_seek > 600:
        to_seek = 600

    if not await db.get_call(m.chat.id):
        return await clean_reply(m, m.lang["not_playing"])

    if not await db.playing(m.chat.id):
        return await clean_reply(m, m.lang["play_already_paused"])

    media = queue.get_current(m.chat.id)
    if not media.duration_sec:
        return await clean_reply(m, m.lang["play_seek_no_dur"])

    sent = await clean_reply(m, m.lang["play_seeking"])
    if backward:
        stype = m.lang["backward"]
        start_from = media.time - to_seek
        if start_from < 1:
            start_from = 1
    else:
        stype = m.lang["forward"]
        start_from = media.time + to_seek
        if start_from + 10 > media.duration_sec:
            start_from = media.duration_sec - 5

    await anon.play_media(m.chat.id, sent, media, start_from)
    media.time = start_from
    await sent.edit_text(
        m.lang["play_seeked"].format(stype, start_from, m.from_user.mention)
    )
