# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


from pyrogram import filters, types

from bobby import anon, app, db, lang
from bobby.helpers._selfdel import clean_reply
from bobby.helpers import can_manage_vc


@app.on_message(filters.command(["skip", "next"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _skip(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await clean_reply(m, m.lang["not_playing"])

    await anon.play_next(m.chat.id)
    await clean_reply(m, m.lang["play_skipped"].format(m.from_user.mention))
