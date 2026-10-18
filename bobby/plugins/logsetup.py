"""Logger channel for the music bot.

Adapted from two reference bots:
  * ExonRobot's /setlog — an admin forwards a message from a channel to bind it
  * ShrutiMusic's join watcher — announce when the bot is added to a group

core/bot.py and core/userbot.py already read config.LOGGER_ID; this plugin
makes that value settable at runtime (db-backed) so a channel can be bound
without editing .env, and posts bot + playback lifecycle events to it.
"""

import html

from pyrogram import enums, filters, types
from pyrogram.errors import FloodWait

from bobby import app, config, db, logger

_PRE = ["/", "!", "?"]
_LOG_KEY = "log_channel"


async def log_channel_id() -> int:
    """The bound log channel, falling back to LOGGER_ID from the env."""
    try:
        stored = await db.get(_LOG_KEY)
        if stored:
            return int(stored)
    except Exception:
        pass
    return int(getattr(config, "LOGGER_ID", 0) or 0)


async def to_log(text: str, markup=None) -> bool:
    """Post to the log channel.  Never raises — logging must not break music."""
    cid = await log_channel_id()
    if not cid:
        return False
    try:
        await app.send_message(cid, text, parse_mode=enums.ParseMode.HTML,
                               disable_web_page_preview=True, reply_markup=markup)
        return True
    except FloodWait as fw:
        logger.info("logsetup: log channel flood-limited %ss", fw.value)
        return False
    except Exception as exc:
        logger.info("logsetup: log post failed: %s", type(exc).__name__)
        return False


def _is_owner(m: types.Message) -> bool:
    return bool(m.from_user and m.from_user.id == config.OWNER_ID)


# ── /setlog — bind a channel ────────────────────────────────────────────────
@app.on_message(filters.command(["setlog", "setlogger"], prefixes=_PRE))
async def setlog(_, m: types.Message):
    if not _is_owner(m):
        return
    target = None
    # 1) reply to a message from the channel
    rt = getattr(m, "reply_to_message", None)
    if rt is not None:
        fwd = getattr(rt, "forward_from_chat", None) or getattr(rt, "sender_chat", None)
        if fwd is not None:
            target = fwd.id
    # 2) forwarded into the command itself
    if target is None:
        fwd = getattr(m, "forward_from_chat", None)
        if fwd is not None:
            target = fwd.id
    # 3) explicit numeric id (works with -100… channel ids)
    if target is None and len(m.command) > 1 and m.command[1].lstrip("-").isdigit():
        target = int(m.command[1])

    if target is None:
        return await m.reply_text(
            "<b>Bind a log channel</b>\n\n"
            "1. Add this bot to the channel as admin\n"
            "2. Forward any message from that channel here, then reply "
            "<code>/setlog</code>\n\n"
            "or send <code>/setlog -1001234567890</code>",
            parse_mode=enums.ParseMode.HTML)

    try:
        chat = await app.get_chat(target)
    except Exception as exc:
        return await m.reply_text(
            f"Error: cannot reach <code>{target}</code> "
            f"(<code>{type(exc).__name__}</code>). Add the bot to it first.",
            parse_mode=enums.ParseMode.HTML)

    await db.set(_LOG_KEY, int(target))
    config.LOGGER_ID = int(target)          # existing plumbing picks it up now
    ok = await to_log(
        f"✅ <b>Log channel bound</b>\n"
        f"Channel: <b>{html.escape(chat.title or str(target))}</b>\n"
        f"<code>{target}</code>\n"
        f"Bound by <code>{m.from_user.id}</code>")
    await m.reply_text(
        f"Success: log channel set to <b>{html.escape(chat.title or str(target))}</b> "
        f"(<code>{target}</code>).\n"
        f"Test message delivered: <b>{'yes' if ok else 'NO — check bot admin rights'}</b>",
        parse_mode=enums.ParseMode.HTML)


@app.on_message(filters.command(["unsetlog", "clearlog"], prefixes=_PRE))
async def unsetlog(_, m: types.Message):
    if not _is_owner(m):
        return
    await db.set(_LOG_KEY, 0)
    config.LOGGER_ID = 0
    await m.reply_text("Log channel unbound.")


@app.on_message(filters.command(["logstatus", "loginfo"], prefixes=_PRE))
async def logstatus(_, m: types.Message):
    if not _is_owner(m):
        return
    cid = await log_channel_id()
    if not cid:
        return await m.reply_text("No log channel bound. Use /setlog.")
    try:
        chat = await app.get_chat(cid)
        title = html.escape(chat.title or str(cid))
    except Exception:
        title = f"<code>{cid}</code> (unreachable)"
    await m.reply_text(f"Log channel: <b>{title}</b>\n<code>{cid}</code>",
                       parse_mode=enums.ParseMode.HTML)


# ── report when the bot lands in / leaves a group ───────────────────────────
@app.on_message(filters.new_chat_members, group=-10)
async def bot_added_watcher(_, m: types.Message):
    try:
        me = await app.get_me()
    except Exception:
        return
    for member in (m.new_chat_members or []):
        if member.id != me.id:
            continue
        try:
            count = await app.get_chat_members_count(m.chat.id)
        except Exception:
            count = "?"
        link = ""
        try:
            if not m.chat.username:
                link = await app.export_chat_invite_link(m.chat.id)
        except Exception:
            pass
        added_by = m.from_user.mention if m.from_user else "unknown"
        await to_log(
            f"➕ <b>Added to a new group</b>\n"
            f"Title: <b>{html.escape(m.chat.title or str(m.chat.id))}</b>\n"
            f"ID: <code>{m.chat.id}</code>\n"
            f"Members: <b>{count}</b>\n"
            f"Added by: {added_by}"
            + (f"\nInvite: {link}" if link else ""))


@app.on_message(filters.left_chat_member, group=-10)
async def bot_left_watcher(_, m: types.Message):
    try:
        me = await app.get_me()
    except Exception:
        return
    if m.left_chat_member and m.left_chat_member.id == me.id:
        await to_log(f"➖ <b>Removed from a group</b>\n"
                     f"Title: <b>{html.escape(m.chat.title or str(m.chat.id))}</b>\n"
                     f"ID: <code>{m.chat.id}</code>")


@app.on_message(filters.command("testlog", prefixes=_PRE))
async def testlog(_, m: types.Message):
    if not _is_owner(m):
        return
    ok = await to_log("🔔 Test message from the music bot.")
    await m.reply_text("Sent." if ok else "Failed — is the bot an admin in the channel?")
