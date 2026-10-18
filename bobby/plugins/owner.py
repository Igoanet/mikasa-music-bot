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
            [b("✖️ Close", "own_close", D, buttons.prem["cross"])],
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


@app.on_message(filters.command("owner") & _OWNER)
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
    # reuse the /accounts panel; its acct_* buttons work on any message
    rows = acct_kb().inline_keyboard[:-1]  # drop its Close button
    rows.append([InlineKeyboardButton("« Back", callback_data="own_back",
                                      style=enums.ButtonStyle.PRIMARY)])
    await cq.message.edit_text(acct_text(), reply_markup=InlineKeyboardMarkup(rows))


@app.on_callback_query(filters.regex(r"^own_stats$") & filters.user(config.OWNER_ID))
async def cb_own_stats(_, cq: CallbackQuery):
    await cq.answer("Counting…")
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


async def _assistant_group_ids() -> list:
    """Every group id the assistant account is in.

    A bot cannot list its own dialogs (BOT_METHOD_INVALID), so the scan goes
    through the assistant user session stored in data/sessions.json.
    Falls back to the bot's own known chats if that session is unavailable.
    """
    try:
        raw = json.loads(pathlib.Path("data/sessions.json").read_text())
    except Exception:
        raw = {}
    sess = None
    for _uid, val in (raw or {}).items():
        if isinstance(val, str) and len(val) > 60:
            sess = val
            break
        if isinstance(val, dict):
            for key in ("session", "session_string", "string", "value"):
                if isinstance(val.get(key), str) and len(val[key]) > 60:
                    sess = val[key]
                    break
        if sess:
            break
    if not sess:
        return [int(c) for c in (await db.get_chats() or []) if int(c) < 0]
    try:
        from pyrogram import Client as _C
        ub = _C("own_groups_scan", api_id=config.API_ID, api_hash=config.API_HASH,
                session_string=sess, in_memory=True)
        await ub.start()
        ids = []
        try:
            async for d in ub.get_dialogs():
                ch = d.chat
                if ch.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
                    ids.append(ch.id)
        finally:
            try:
                await ub.stop()
            except Exception:
                pass
        if ids:
            return ids
    except Exception as exc:
        logger.info("owner: assistant dialog scan failed: %s", type(exc).__name__)
    return [int(c) for c in (await db.get_chats() or []) if int(c) < 0]


@app.on_callback_query(filters.regex(r"^own_groups$") & filters.user(config.OWNER_ID))
async def cb_own_groups(_, cq: CallbackQuery):
    await cq.answer("Scanning groups…")
    admin_lines, scanned, plain, capped = [], 0, 0, False

    # A bot account cannot list its dialogs (Telegram answers
    # BOT_METHOD_INVALID to messages.GetDialogs), so the groups the bot has
    # served are the only list it can walk.
    known = await _assistant_group_ids()
    for chat_id in known:
        scanned += 1
        if scanned > 400:  # keep the scan fast + flood-safe on huge accounts
            capped = True
            break
        try:
            member = await app.get_chat_member(chat_id, "me")
        except errors.FloodWait as fw:
            await asyncio.sleep(min(fw.value, 5))
            continue
        except Exception:
            continue  # kicked / deactivated / unreachable chat
        if member.status != enums.ChatMemberStatus.ADMINISTRATOR:
            plain += 1
            continue
        priv = member.privileges
        if priv is None:
            plain += 1
            continue
        try:
            title = (await app.get_chat(chat_id)).title or "?"
        except Exception:
            title = "?"
        got = [l for a, l in _GROUP_PERMS if getattr(priv, a, False)]
        missing = [l for a, l in _GROUP_PERMS if not getattr(priv, a, False)]
        line = (f"<b>{html.escape(title)}</b> "
                f"<code>{chat_id}</code>\n"
                f"└ <b>{len(got)}/{len(_GROUP_PERMS)}</b> perms")
        if missing:
            line += f" • missing: {', '.join(missing)}"
        if not getattr(priv, "can_manage_video_chats", False):
            line += " ⚠️ <b>no video-chat perm — music can't play!</b>"
        admin_lines.append(line)

    n_admin = len(admin_lines)
    text = (
        f"🛡 <b>Bot Admin Rights</b>\n\n"
        f"Groups checked: <b>{scanned}{'+' if capped else ''}</b> "
        f"(groups the assistant account is in)\n"
        f"Admin in: <b>{n_admin}</b> • Member only: <b>{plain}</b>\n"
    )
    if n_admin:
        # stay under Telegram's 4096-char message cap regardless of how long
        # group titles are — budget by characters, not entry count
        shown = []
        budget = 3900 - len(text)
        for i, line in enumerate(admin_lines, 1):
            entry = f"<b>{i}.</b> {line}"
            if len(entry) + 2 > budget - 60:  # reserve for the "…more" note
                break
            shown.append(entry)
            budget -= len(entry) + 2
        text += "\n" + "\n\n".join(shown)
        if n_admin > len(shown):
            text += f"\n\n…and {n_admin - len(shown)} more."
    elif scanned:
        text += "\nThe bot isn't admin in any of these groups yet."
    else:
        text += "\nNo group on record yet — play something in a group first."
    try:
        await cq.message.edit_text(text, reply_markup=_back_kb())
    except errors.MessageNotModified:
        pass
