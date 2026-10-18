# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


from pyrogram import filters, types

from bobby import anon, app, db, lang
from bobby.helpers._selfdel import clean_reply
from bobby.helpers import can_manage_vc
from bobby.helpers import _recs as recs


@app.on_message(filters.command(["end", "stop"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _stop(_, m: types.Message):
    if len(m.command) > 1:
        return

    # a stop is final: a suggestion card or autoplay pick that is still being
    # looked up must not start the music again behind the user's back
    recs.cancel(m.chat.id)
    call = await db.get_call(m.chat.id)
    await anon.stop(m.chat.id)
    if not call:
        return await clean_reply(m, m.lang["not_playing"])

    await clean_reply(m, m.lang["play_stopped"].format(m.from_user.mention))
