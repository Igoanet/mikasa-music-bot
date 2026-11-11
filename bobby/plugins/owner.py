import pathlib
import json
# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Owner control panel (/owner) — one private-chat hub for the important
owner jobs: assistant session management, stats, sudoers, broadcast,
and the logger toggle. Owner-only (not even sudoers)."""

import asyncio
import html

from pyrogram import enums, errors, filters
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup, Message)

from bobby import app, config, db, userbot
from bobby.helpers import buttons
from bobby.plugins.account import _kb as acct_kb
from bobby.plugins.account import _text as acct_text

_OWNER = filters.private & filters.user(config.OWNER_ID)


def _panel_kb() -> InlineKeyboardMarkup:
    """Every owner function, one button each."""
    R = enums.ButtonStyle.PRIMARY
    D = enums.ButtonStyle.DANGER

    def b(text, data, style=R, icon=None):
        kw = {"callback_data": data, "style": style}
        if icon:
            kw["icon_custom_emoji_id"] = icon
        return InlineKeyboardButton(text, **kw)

    return InlineKeyboardMarkup(
        [
            [b("👥 Assistants", "own_acct"), b("📊 Stats", "own_stats")],
            [b("🛡 Admin Groups", "own_groups"), b("👑 Sudoers", "own_sudo")],
            [b("🛠 Group console", "own_groupconsole")],
            [b("📄 Log channel", "own_logbind"), b("🚫 Blacklist", "own_blacklist")],
            [b("📡 Streams", "own_vc"), b("🧹 Storage", "own_clean")],
            [b("🔒 Play mode", "own_playmode"), b("📢 Broadcast", "own_bcast")],
            [b("📜 Commands", "own_cmds"), b("🔄 Restart", "own_restart", D)],
            [b("Close", "own_close", D, buttons.prem["cross"])],
        ]
    )


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("« Back", callback_data="own_back",
                               style=enums.ButtonStyle.PRIMARY)]]
    )


def _panel_text() -> str:
    return (
        "<b>👑 Owner Panel</b>\n\n"
        f"Assistants running: <b>{len(userbot.clients)}</b> · "
        f"Groups: <b>{len(db.chats)}</b>\n\n"
        "<i>Every function below is one tap. Sections answer in place; "
        "use « Back to return.</i>"
    )


@app.on_message(filters.command("owner", prefixes=["/", "!", "?", "."]) & _OWNER)
async def owner_cmd(_, msg: Message):
    await msg.reply_text(_panel_text(), reply_markup=_panel_kb())


@app.on_callback_query(filters.regex(r"^own_panel$"))
async def cb_own_panel(_, cq: CallbackQuery):
    # /start "Owner Panel" button — owner only; send a fresh panel message
    # (the /start message is a photo, which can't be edited into text)
    if cq.from_user.id != config.OWNER_ID:
        await cq.answer("Owner only.", show_alert=True)
        return
    await cq.answer()
    await cq.message.reply_text(_panel_text(), reply_markup=_panel_kb())


@app.on_callback_query(filters.regex(r"^own_back$") & filters.user(config.OWNER_ID))
async def cb_own_back(_, cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(_panel_text(), reply_markup=_panel_kb())


@app.on_callback_query(filters.regex(r"^own_close$") & filters.user(config.OWNER_ID))
async def cb_own_close(_, cq: CallbackQuery):
    await cq.answer()
    try:
        await cq.message.delete()
    except Exception:
        pass


@app.on_callback_query(filters.regex(r"^own_acct$") & filters.user(config.OWNER_ID))
async def cb_own_acct(_, cq: CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text("<b>👥 Assistants</b>\n\n<i>Loading assistants...</i>", reply_markup=_back_kb())
    except Exception:
        pass
    # reuse the /accounts panel; its acct_* buttons work on any message
    rows = acct_kb().inline_keyboard[:-1]  # drop its Close button
    rows.append([InlineKeyboardButton("« Back", callback_data="own_back",
                                      style=enums.ButtonStyle.PRIMARY)])
    await cq.message.edit_text(acct_text(), reply_markup=InlineKeyboardMarkup(rows))


@app.on_callback_query(filters.regex(r"^own_stats$") & filters.user(config.OWNER_ID))
async def cb_own_stats(_, cq: CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text("<b>📊 Stats</b>\n\n<i>Loading stats...</i>", reply_markup=_back_kb())
    except Exception:
        pass
    text = (
        "<b>📊 Stats</b>\n\n"
        f"• Users: <b>{len(await db.get_users())}</b>\n"
        f"• Groups: <b>{len(await db.get_chats())}</b>\n"
        f"• Assistants: <b>{len(userbot.clients)}</b>\n"
        f"• Sudoers: <b>{len(app.sudoers)}</b>\n"
        f"• Blacklisted groups: <b>{len(db.blacklisted)}</b>\n"
        f"• Blacklisted users: <b>{len(app.bl_users)}</b>"
    )
    await cq.message.edit_text(text, reply_markup=_back_kb())


@app.on_callback_query(filters.regex(r"^own_sudo$") & filters.user(config.OWNER_ID))
async def cb_own_sudo(_, cq: CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text("<b>👑 Sudoers</b>\n\n<i>Loading sudoers...</i>", reply_markup=_back_kb())
    except Exception:
        pass
    lines = ["<b>👑 Sudoers</b>", ""]
    sudoers = await db.get_sudoers()
    if not sudoers:
        lines.append("None yet.")
    for uid in sudoers:
        try:
            user = await app.get_users(uid)
            lines.append(f"• {user.mention} (<code>{uid}</code>)")
        except Exception:
            lines.append(f"• <code>{uid}</code>")
    lines.append("\nManage with /addsudo and /delsudo (reply to a user or pass an ID).")
    await cq.message.edit_text("\n".join(lines), reply_markup=_back_kb())


@app.on_callback_query(filters.regex(r"^own_bcast$") & filters.user(config.OWNER_ID))
async def cb_own_bcast(_, cq: CallbackQuery):
    await cq.answer()
    await cq.message.edit_text(
        "<b>📢 Broadcast</b>\n\n"
        "Reply to any message with /broadcast to send it to all groups, "
        "or /broadcast -user for all users.",
        reply_markup=_back_kb(),
    )


@app.on_callback_query(filters.regex(r"^own_logger$") & filters.user(config.OWNER_ID))
async def cb_own_logger(_, cq: CallbackQuery):
    if not config.LOGGER_ID:
        await cq.answer(
            "No log group configured (LOGGER_ID is unset) — logging stays off.",
            show_alert=True,
        )
        return
    new = not await db.is_logger()
    await db.set_logger(new)
    await cq.answer(f"Logger {'ON' if new else 'OFF'}", show_alert=True)


# bot admin permissions reported by the Admin Groups scan, in display order
_GROUP_PERMS = [
    ("can_manage_video_chats", "Video chats"),
    ("can_delete_messages", "Delete msgs"),
    ("can_invite_users", "Invite users"),
    ("can_pin_messages", "Pin msgs"),
    ("can_change_info", "Change info"),
    ("can_restrict_members", "Ban users"),
    ("can_promote_members", "Promote"),
    ("can_manage_chat", "Manage chat"),
]


_assistant_group_cache: list = []
_assistant_group_cache_ts: float = 0.0

async def _assistant_group_ids() -> list:
    """Every group id known from the database (chats, assistant, auth, lang) and assistant dialogs."""
    global _assistant_group_cache, _assistant_group_cache_ts
    now = time.monotonic()
    if _assistant_group_cache and (now - _assistant_group_cache_ts < 30.0):
        return _assistant_group_cache

    ids = set()
    # 1. Pull all group IDs recorded across all JSON tables in db._data
    try:
        data = getattr(db, "_data", None) or {}
        for category in ("assistant", "chats", "auth", "lang"):
            for k in (data.get(category) or {}).keys():
                try:
                    cid = int(k)
                    if cid < 0:
                        ids.add(cid)
                except Exception:
                    pass
    except Exception:
        pass

    # 2. Assistant dialog groups
    try:
        if getattr(userbot, "clients", None):
            for ub in userbot.clients:
                try:
                    async for d in ub.get_dialogs(limit=100):
                        ch = getattr(d, "chat", None)
                        if ch and ch.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
                            ids.add(ch.id)
                except Exception:
                    pass
    except Exception:
        pass

    result = sorted(list(ids))
    _assistant_group_cache = result
    _assistant_group_cache_ts = now
    return result


@app.on_callback_query(filters.regex(r"^own_groups$") & filters.user(config.OWNER_ID))
async def cb_own_groups(_, cq: CallbackQuery):
    await cq.answer()
    try:
        await cq.message.edit_text(
            "<b>🛡 Bot Admin Rights</b>\n\n<i>Scanning groups and admin permissions, please wait...</i>",
            reply_markup=_back_kb(),
        )
    except Exception:
        pass

    known = await _assistant_group_ids()
    scanned = len(known)
    bot_id = app.me.id if getattr(app, "me", None) else (await app.get_me()).id
    sem = asyncio.Semaphore(10)

    async def _inspect_chat(chat_id: int):
        async with sem:
            try:
                member = await asyncio.wait_for(app.get_chat_member(chat_id, bot_id), timeout=3.5)
            except Exception:
                return None
            if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                return False
            priv = getattr(member, "privileges", None)
            if priv is None:
                return False
            try:
                chat = await asyncio.wait_for(app.get_chat(chat_id), timeout=2.5)
                title = chat.title or "?"
            except Exception:
                title = "?"
            got = [l for a, l in _GROUP_PERMS if getattr(priv, a, False)]
            missing = [l for a, l in _GROUP_PERMS if not getattr(priv, a, False)]
            line = (f"<b>{html.escape(title)}</b> <code>{chat_id}</code>\n"
                    f"└ <b>{len(got)}/{len(_GROUP_PERMS)}</b> perms")
            if missing:
                line += f" • missing: {', '.join(missing)}"
            if not getattr(priv, "can_manage_video_chats", False):
                line += " ⚠️ <b>no video-chat perm — music can't play!</b>"
            return line

    admin_lines = []
    plain = 0
    if known:
        results = await asyncio.gather(*[_inspect_chat(cid) for cid in known])
        for r in results:
            if isinstance(r, str):
                admin_lines.append(r)
            elif r is False:
                plain += 1

    n_admin = len(admin_lines)
    text = (
        f"🛡 <b>Bot Admin Rights</b>\n\n"
        f"Groups checked: <b>{scanned}</b>\n"
        f"Admin in: <b>{n_admin}</b> • Member only: <b>{plain}</b>\n\n"
    )
    if n_admin:
        shown = []
        budget = 3900 - len(text)
        for i, line in enumerate(admin_lines, 1):
            entry = f"<b>{i}.</b> {line}"
            if len(entry) + 2 > budget - 60:
                break
            shown.append(entry)
            budget -= len(entry) + 2
        text += "\n\n".join(shown)
        if n_admin > len(shown):
            text += f"\n\n…and {n_admin - len(shown)} more."
    else:
        text += "The bot is not an admin in any known group."

    try:
        await cq.message.edit_text(text, reply_markup=_back_kb())
    except errors.MessageNotModified:
        pass
