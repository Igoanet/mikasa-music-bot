# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import asyncio
from pyrogram import enums, filters, types

from bobby import app, config, db, lang
from bobby.helpers import buttons, is_group_owner, utils



@app.on_message(filters.command(["help"]) & filters.private & ~app.bl_users)
@lang.language()
async def _help(_, m: types.Message):
    staff = bool(m.from_user) and (
        m.from_user.id == config.OWNER_ID or m.from_user.id in app.sudoers
    )
    markup = buttons.help_markup(
        m.lang,
        staff=staff,
        owner=bool(m.from_user and m.from_user.id == config.OWNER_ID),
    )
    from bobby.helpers.rich_message import send_rich_message, get_help_menu_blocks, get_help_text
    blocks = get_help_menu_blocks(staff=staff)
    res = await send_rich_message(m.chat.id, blocks, reply_markup=markup)
    if not res.get("ok"):
        await m.reply_text(
            text=get_help_text(staff=staff),
            reply_markup=markup,
        )


@app.on_message(filters.command(["start"]))
@lang.language()
async def start(_, message: types.Message):
    if message.from_user.id in app.bl_users and message.from_user.id not in db.notified:
        return await message.reply_text(message.lang["bl_user_notify"])

    if len(message.command) > 1 and message.command[1] == "help":
        return await _help(_, message)

    private = message.chat.type == enums.ChatType.PRIVATE
    payload = message.command[1] if len(message.command) > 1 else ""
    # [voice stack removed] voice deep-link hand-off dropped
    bot_user = getattr(app, "username", None) or (app.me.username if getattr(app, "me", None) else "MikasaMusic_Bot")
    _text = message.lang["start_pm"].format(
        bot_user, config.SUPPORT_CHANNEL, config.SUPPORT_CHAT, config.OWNER_ID
    )

    key = buttons.start_key(
        message.lang, private, owner=message.from_user.id == config.OWNER_ID
    )

    from bobby.helpers.rich_message import send_rich_message, get_start_chat_button_blocks
    blocks = get_start_chat_button_blocks(
        bot_user, config.SUPPORT_CHANNEL, config.SUPPORT_CHAT, is_group=not private
    )
    resp = await send_rich_message(message.chat.id, blocks, reply_markup=key)
    if not resp.get("ok"):
        import os
        photo_path = "assets/start-preview.jpg" if os.path.exists("assets/start-preview.jpg") else config.START_IMG
        try:
            await message.reply_photo(
                photo=photo_path,
                caption=_text,
                reply_markup=key,
            )
        except Exception:
            await message.reply_text(text=_text, reply_markup=key)

    if private:
        if await db.is_user(message.from_user.id):
            return
        await utils.send_log(message)
        await db.add_user(message.from_user.id)
    else:
        if await db.is_chat(message.chat.id):
            return
        await utils.send_log(message, True)
        await db.add_chat(message.chat.id)


@app.on_message(filters.command(["playmode", "settings"]) & filters.group & ~app.bl_users)
@lang.language()
async def settings(_, message: types.Message):
    command = (message.command[0].lower() if message.command else "")
    if len(message.command or []) > 1:
        desired = message.command[1].lower()
        if command != "playmode" or desired not in {"admins", "everyone"}:
            return await message.reply_text(message.lang["play_mode_usage"])
        # The policy is scoped to this command's destination group.  Do not
        # infer a target from forwarded/source metadata or trust bot staff.
        if not await is_group_owner(message.chat.id, message):
            return await message.reply_text(message.lang["play_mode_owner_only"])
        await db.set_play_mode(message.chat.id, desired == "admins")
        admin_only = desired == "admins"
        force_all = await db.get_force_mode(message.chat.id)
        cmd_delete = await db.get_cmd_delete(message.chat.id)
        _language = await db.get_lang(message.chat.id)
        autoplay = await db.get_autoplay(message.chat.id)
        return await message.reply_text(
            message.lang["play_mode_set"].format(
                message.lang["play_admins"] if admin_only
                else message.lang["play_everyone"]
            ),
            reply_markup=buttons.settings_markup(
                message.lang,
                admin_only,
                cmd_delete,
                _language,
                message.chat.id,
                force_all,
                autoplay,
            ),
        )

    admin_only = await db.get_play_mode(message.chat.id)
    force_all = await db.get_force_mode(message.chat.id)
    cmd_delete = await db.get_cmd_delete(message.chat.id)
    _language = await db.get_lang(message.chat.id)
    autoplay = await db.get_autoplay(message.chat.id)
    await message.reply_text(
        text=message.lang["start_settings"].format(message.chat.title),
        reply_markup=buttons.settings_markup(
            message.lang, admin_only, cmd_delete, _language, message.chat.id,
            force_all, autoplay,
        ),
    )


@app.on_message(filters.new_chat_members, group=7)
@lang.language()
async def _new_member(_, message: types.Message):
    if message.chat.type not in [enums.ChatType.SUPERGROUP, enums.ChatType.GROUP]:
        return await message.chat.leave()

    for member in message.new_chat_members:
        if member.id == app.id:
            if not await db.is_chat(message.chat.id):
                await utils.send_log(message, True)
                await db.add_chat(message.chat.id)

            bot_user = getattr(app, "username", None) or (app.me.username if getattr(app, "me", None) else "MikasaMusic_Bot")
            _text = message.lang["start_gp"].format(
                bot_user, config.SUPPORT_CHANNEL, config.SUPPORT_CHAT, config.OWNER_ID
            )
            key = buttons.start_key(message.lang, private=False)

            from bobby.helpers.rich_message import send_rich_message, get_start_chat_button_blocks
            blocks = get_start_chat_button_blocks(bot_user, config.SUPPORT_CHANNEL, config.SUPPORT_CHAT, is_group=True)
            resp = await send_rich_message(message.chat.id, blocks, reply_markup=key)
            if not resp.get("ok"):
                import os
                photo_path = "assets/start-preview.jpg" if os.path.exists("assets/start-preview.jpg") else config.START_IMG
                try:
                    await message.reply_photo(
                        photo=photo_path,
                        caption=_text,
                        reply_markup=key,
                    )
                except Exception:
                    await message.reply_text(text=_text, reply_markup=key)
