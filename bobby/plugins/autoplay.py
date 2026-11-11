# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""/autoplay — keep the voice chat playing after the queue runs dry.

Off by default.  Only group admins (plus bot sudo users and members the
admins granted /auth) may switch it on or off, exactly like the other
playback settings; the same toggle sits in the /settings panel."""

from pyrogram import filters, types

from bobby import app, db, lang
from bobby.helpers import can_manage_vc
from bobby.helpers import _recs as recs


@app.on_message(filters.command(["autoplay"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _autoplay(_, m: types.Message):
    chat_id = m.chat.id
    status = await db.get_autoplay(chat_id)

    if len(m.command) > 1:
        arg = m.command[1].lower()
        if arg in {"on", "enable", "yes", "true", "1"}:
            status = True
        elif arg in {"off", "disable", "no", "false", "0"}:
            status = False
        else:
            return await m.reply_text(
                "<b>‘ 𝐌𝐢𝐤𝐚𝐬𝐚 𝐗 𝐌𝐮𝐬𝐢𝐜. ♪ 🩸 🫀</b>\n\n"
                "> <b>Usage :</b> <code>/autoplay on</code> | <code>/autoplay off</code>"
            )
        await db.set_autoplay(chat_id, status)
        if not status:
            recs.cancel(chat_id)
        from bobby.helpers import emojis
        msg_text = (
            f"<b>‘ {emojis.HEADPHONE} ˹ᴍɪᴋᴀꜱᴀ 𓆩⚔️𓆪 ᴍᴜꜱɪᴄ♪ {emojis.DOVE}</b>\n\n"
            f"> <b>Autoplay :</b> {'<b>Enabled ' + emojis.CHECK + '</b>' if status else '<b>Disabled ' + emojis.CROSS + '</b>'}"
        )
        return await m.reply_text(msg_text)

    from bobby.helpers import emojis
    status_text = '<b>Enabled ' + emojis.CHECK + '</b>' if status else '<b>Disabled ' + emojis.CROSS + '</b>'
    btn = [
        [
            types.InlineKeyboardButton(
                text="Turn Off ❌" if status else "Turn On ✅",
                callback_data=f"panel_autoplay_toggle {chat_id}"
            ),
            types.InlineKeyboardButton(text="Close 🗑️", callback_data="help close")
        ]
    ]
    msg_text = (
        f"<b>‘ {emojis.HEADPHONE} ˹ᴍɪᴋᴀꜱᴀ 𓆩⚔️𓆪 ᴍᴜꜱɪᴄ♪ {emojis.DOVE}</b>\n\n"
        f"> <b>Autoplay :</b> {status_text}\n"
        f"> <b>Usage :</b> <code>/autoplay on</code> | <code>/autoplay off</code>"
    )
    return await m.reply_text(msg_text, reply_markup=types.InlineKeyboardMarkup(btn))


@app.on_callback_query(filters.regex(r"^panel_autoplay_toggle") & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _autoplay_toggle_cb(_, query: types.CallbackQuery):
    chat_id = query.message.chat.id
    status = not await db.get_autoplay(chat_id)
    await db.set_autoplay(chat_id, status)
    if not status:
        recs.cancel(chat_id)
    from bobby.helpers import emojis
    status_text = '<b>Enabled ' + emojis.CHECK + '</b>' if status else '<b>Disabled ' + emojis.CROSS + '</b>'
    btn = [
        [
            types.InlineKeyboardButton(
                text="Turn Off ❌" if status else "Turn On ✅",
                callback_data=f"panel_autoplay_toggle {chat_id}"
            ),
            types.InlineKeyboardButton(text="Close 🗑️", callback_data="help close")
        ]
    ]
    msg_text = (
        f"<b>‘ {emojis.HEADPHONE} ˹ᴍɪᴋᴀꜱᴀ 𓆩⚔️𓆪 ᴍᴜꜱɪᴄ♪ {emojis.DOVE}</b>\n\n"
        f"> <b>Autoplay :</b> {status_text}\n"
        f"> <b>Usage :</b> <code>/autoplay on</code> | <code>/autoplay off</code>"
    )
    try:
        await query.message.edit_text(msg_text, reply_markup=types.InlineKeyboardMarkup(btn))
    except Exception:
        pass
    await query.answer(f"Autoplay {'Enabled' if status else 'Disabled'}")
