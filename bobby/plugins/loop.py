# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


from pyrogram import filters, types

from bobby import app, db, lang
from bobby.helpers import can_manage_vc


@app.on_message(filters.command(["loop"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _loop(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    chat_id = m.chat.id
    if len(m.command) < 2:
        count = await db.get_loop(chat_id)
        if count == -1:
            return await m.reply_text(
                m.lang.get("loop_queue_on", "🔁 The whole queue is looping.")
            )
        if count:
            return await m.reply_text(m.lang["loop_count"].format(count))
        return await m.reply_text(m.lang["loop_usage"])

    arg = m.command[1].lower()
    if arg in ["queue", "all", "playlist"]:
        await db.set_loop(chat_id, -1)
        return await m.reply_text(
            m.lang.get("loop_queue", "🔁 Looping the whole queue — tracks repeat until /loop off.")
        )

    disable = arg in ["off", "disable"]
    if not arg.isdigit() and not disable:
        return await m.reply_text(m.lang["loop_usage"])

    loop = int(arg) if not disable else 0
    if loop < 1: loop = 0
    elif loop > 20: loop = 20

    await db.set_loop(m.chat.id, loop)
    if loop == 0:
        return await m.reply_text(m.lang["loop_off"])
    await m.reply_text(m.lang["loop_set"].format(loop))
