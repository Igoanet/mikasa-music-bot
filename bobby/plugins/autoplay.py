# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""/autoplay — keep the voice chat playing after the queue runs dry.

Off by default.  Only group admins (plus bot sudo users and members the
admins granted /auth) may switch it on or off, exactly like the other
playback settings; the same toggle sits in the /settings panel."""

from pyrogram import filters, types

from bobby import app, db, lang
from bobby.helpers import buttons, can_manage_vc
from bobby.helpers import _recs as recs


@app.on_message(filters.command(["autoplay"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _autoplay(_, m: types.Message):
    chat_id = m.chat.id
    status = await db.get_autoplay(chat_id)

    if len(m.command) > 1:
        arg = m.command[1].lower()
        if arg in {"on", "enable", "yes"}:
            status = True
        elif arg in {"off", "disable", "no"}:
            status = False
        else:
            return await m.reply_text(m.lang["autoplay_usage"])
        await db.set_autoplay(chat_id, status)
        if not status:
            # an autoplay pick already being looked up must not still land
            recs.cancel(chat_id)
        return await m.reply_text(
            m.lang["autoplay_set_on"] if status else m.lang["autoplay_set_off"]
        )

    admin_only = await db.get_play_mode(chat_id)
    force_all = await db.get_force_mode(chat_id)
    cmd_delete = await db.get_cmd_delete(chat_id)
    _language = await db.get_lang(chat_id)
    await m.reply_text(
        text=(m.lang["autoplay_set_on"] if status else m.lang["autoplay_set_off"]),
        reply_markup=buttons.settings_markup(
            m.lang, admin_only, cmd_delete, _language, chat_id, force_all, status
        ),
    )
