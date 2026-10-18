# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

from pyrogram import filters, types

from bobby import anon, app, db, lang
from bobby.helpers._selfdel import clean_reply
from bobby.helpers import buttons, can_manage_vc

@app.on_message(filters.command(["pause"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _pause(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await clean_reply(m, m.lang["not_playing"])

    if not await db.playing(m.chat.id):
        return await clean_reply(m, m.lang["play_already_paused"])

    await anon.pause(m.chat.id)
    await clean_reply(m, 
        text=m.lang["play_paused"].format(m.from_user.mention),
        reply_markup=buttons.controls(
            m.chat.id,
            autoplay=await db.get_autoplay(m.chat.id),
            _lang=m.lang, is_admin=True,autoplay_all=await db.get_autoplay_all(m.chat.id),),
    )
