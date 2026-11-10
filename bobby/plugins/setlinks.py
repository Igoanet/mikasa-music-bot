# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Runtime link management for Support Chat, Support Channel, and Owner Contact.

Allows the owner and sudoers to dynamically change support and channel URLs
at runtime via Telegram commands. Changes are persisted to data/bot_settings.json
and reflect globally across all playback cards, start messages, and menus.
"""

from pyrogram import filters, types
from bobby import app, config
from bobby.core import bot_settings_store


def _clean_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("@"):
        return f"https://t.me/{raw.lstrip('@')}"
    if not raw.startswith("http://") and not raw.startswith("https://"):
        return f"https://t.me/{raw}"
    return raw


@app.on_message(filters.command(["setsupport", "setchat"]) & (filters.user(app.owner) | app.sudoers))
async def _set_support_chat(_, m: types.Message):
    if len(m.command) < 2:
        return await m.reply_text(
            f"<b>Usage:</b> <code>/setchat &lt;username or telegram link&gt;</code>\n\n"
            f"<b>Current Support Chat:</b> <code>{config.SUPPORT_CHAT}</code>"
        )
    url = _clean_url(m.command[1])
    bot_settings_store.set("SUPPORT_CHAT", url)
    await m.reply_text(
        f"✅ <b>Support Chat updated successfully!</b>\n\n"
        f"🔗 <b>New URL:</b> <a href=\"{url}\">{url}</a>\n"
        f"<i>This is now applied globally to all playback cards and start menus.</i>"
    )


@app.on_message(filters.command(["setchannel", "setsupportchannel"]) & (filters.user(app.owner) | app.sudoers))
async def _set_support_channel(_, m: types.Message):
    if len(m.command) < 2:
        return await m.reply_text(
            f"<b>Usage:</b> <code>/setchannel &lt;username or telegram link&gt;</code>\n\n"
            f"<b>Current Support Channel:</b> <code>{config.SUPPORT_CHANNEL}</code>"
        )
    url = _clean_url(m.command[1])
    bot_settings_store.set("SUPPORT_CHANNEL", url)
    await m.reply_text(
        f"✅ <b>Support Channel updated successfully!</b>\n\n"
        f"🔗 <b>New URL:</b> <a href=\"{url}\">{url}</a>\n"
        f"<i>This is now applied globally to all playback cards and start menus.</i>"
    )


@app.on_message(filters.command(["setowner", "setownerlink"]) & (filters.user(app.owner) | app.sudoers))
async def _set_owner_link(_, m: types.Message):
    if len(m.command) < 2:
        return await m.reply_text(
            f"<b>Usage:</b> <code>/setowner &lt;username or telegram link&gt;</code>\n\n"
            f"<b>Current Owner Contact:</b> <code>{config.OWNER_CHAT}</code>"
        )
    url = _clean_url(m.command[1])
    bot_settings_store.set("OWNER_CHAT", url)
    await m.reply_text(
        f"✅ <b>Owner Contact updated successfully!</b>\n\n"
        f"🔗 <b>New URL:</b> <a href=\"{url}\">{url}</a>"
    )


@app.on_message(filters.command(["getlinks", "links", "supportlinks"]) & (filters.user(app.owner) | app.sudoers))
async def _get_links(_, m: types.Message):
    await m.reply_text(
        f"<b>🛠 Global Bot Links Configuration:</b>\n\n"
        f"• <b>Support Chat:</b> <a href=\"{config.SUPPORT_CHAT}\">{config.SUPPORT_CHAT}</a>\n"
        f"• <b>Support Channel:</b> <a href=\"{config.SUPPORT_CHANNEL}\">{config.SUPPORT_CHANNEL}</a>\n"
        f"• <b>Owner Contact:</b> <a href=\"{config.OWNER_CHAT}\">{config.OWNER_CHAT}</a>\n\n"
        f"<i>To modify any of these:</i>\n"
        f"• <code>/setchat &lt;url or @username&gt;</code>\n"
        f"• <code>/setchannel &lt;url or @username&gt;</code>\n"
        f"• <code>/setowner &lt;url or @username&gt;</code>"
    )
