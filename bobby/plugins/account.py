# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Owner/sudoer-only assistant management from inside the bot (/accounts).

Add flow: phone number → OTP code → 2FA password (if set) → the session is
created in-memory, validated, registered with PyTgCalls, and persisted via
session_store. Credential messages (phone / OTP / password) are deleted
immediately. Pasting a ready-made Pyrogram session string also still works.
"""

import base64
import re

from pyrogram import Client, enums, errors, filters
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup, Message)

from bobby import app, config, logger, userbot
from bobby.core import session_store
from bobby.helpers import buttons

# uid -> {"stage": "phone"|"code"|"password", "client": Client, "phone": str,
#         "hash": str} — login attempts in flight
_pending: dict[int, dict] = {}

_PHONE_RE = re.compile(r"^\+?\d{7,15}$")

_CANCEL_KB = InlineKeyboardMarkup(
    [[InlineKeyboardButton("❌ Cancel", callback_data="acct_cancel",
                           style=enums.ButtonStyle.DANGER,
                           icon_custom_emoji_id=buttons.prem["cross"])]]
)


async def refresh_identities() -> int:
    """Pull each running assistant's current name/username from Telegram.

    Updates both the live client objects and the persisted store, so panels,
    logs and the button labels all agree with Telegram (2026-09-29).
    """
    return await userbot.refresh_identities()


def _kb() -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton("➕ Add Account", callback_data="acct_add",
                             style=enums.ButtonStyle.SUCCESS),
        InlineKeyboardButton("🔄 Refresh names", callback_data="acct_refresh",
                             style=enums.ButtonStyle.PRIMARY),
    ]]
    for uid, entry in session_store.load().items():
        label = entry.get("name") or uid
        if entry.get("username"):
            label += f" (@{entry['username']})"
        rows.append([InlineKeyboardButton(f"🗑 {label}"[:60], callback_data=f"acct_del|{uid}",
                                          style=enums.ButtonStyle.DANGER)])
    rows.append([InlineKeyboardButton("✖️ Close", callback_data="acct_close",
                                      style=enums.ButtonStyle.DANGER,
                                      icon_custom_emoji_id=buttons.prem["cross"])])
    return InlineKeyboardMarkup(rows)


def _text() -> str:
    env_count = sum(1 for s in (config.SESSION1, config.SESSION2, config.SESSION3) if s)
    lines = ["<b>📱 Assistant Accounts</b>", ""]
    lines.append(f"Running assistants: <b>{len(userbot.clients)}</b>")
    if env_count:
        lines.append(f"• {env_count} from environment config")
    for uid, entry in session_store.load().items():
        status = "🟢" if uid in userbot.saved else "🔴 (will retry on next restart)"
        name = entry.get("name") or uid
        uname = f" (@{entry['username']})" if entry.get("username") else ""
        lines.append(f"• {status} {name}{uname}")
    if not env_count and not session_store.load():
        lines.append("\nNo assistants yet — add one so the bot can join voice chats.")
    return "\n".join(lines)


async def _cancel_pending(uid: int) -> None:
    state = _pending.pop(uid, None)
    client = (state or {}).get("client")
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass


async def _finish_login(msg: Message, state: dict) -> None:
    """Login succeeded — export the session and register it as an assistant."""
    client: Client = state["client"]
    me = await client.get_me()
    session_string = await client.export_session_string()
    await client.disconnect()
    try:
        real_client = await userbot.add_saved(session_string)
    except Exception as ex:
        logger.warning(f"assistant register failed: {ex}")
        await msg.reply_text(
            "✅ Login worked, but starting the assistant failed: "
            f"<code>{type(ex).__name__}</code>. Try again."
        )
        return
    session_store.add(me.id, session_string, me.first_name, me.username)
    await msg.reply_text(
        f"✅ Assistant added: <b>{me.first_name}</b>"
        + (f" (@{me.username})" if me.username else "")
        + "\nIt can now join voice chats — try /play in a group."
    )
    _ = real_client  # kept running by userbot


async def _try_session_string(msg: Message, raw: str) -> bool:
    """Fallback: the text is a ready-made Pyrogram session string."""
    try:
        base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception:
        return False
    status = await msg.reply_text("⏳ Checking the session…")
    try:
        client = await userbot.add_saved(raw)
    except Exception as ex:
        logger.warning(f"session add failed: {ex}")
        await status.edit_text(
            "❌ Session rejected — it's invalid or revoked. "
            f"(<code>{type(ex).__name__}</code>)"
        )
        return True
    session_store.add(client.me.id, raw, client.me.first_name, client.me.username)
    await status.edit_text(
        f"✅ Assistant added: <b>{client.me.first_name}</b>"
        + (f" (@{client.me.username})" if client.me.username else "")
        + "\nIt can now join voice chats — try /play in a group."
    )
    return True


@app.on_message(filters.command("accounts") & filters.private & app.sudoers)
async def accounts_cmd(_, msg: Message):
    await msg.reply_text(_text(), reply_markup=_kb())


@app.on_callback_query(filters.regex(r"^acct_add$") & app.sudoers)
async def cb_acct_add(_, cq: CallbackQuery):
    await cq.answer()
    await _cancel_pending(cq.from_user.id)
    _pending[cq.from_user.id] = {"stage": "phone"}
    await cq.message.reply_text(
        "📱 <b>Add Assistant Account</b>\n\n"
        "Send the account's <b>phone number</b> with country code "
        "(e.g. <code>+919876543210</code>).\n\n"
        "I'll send the login OTP to that account, then ask for the code "
        "(and the 2FA password if one is set).\n\n"
        "⚠️ Private chat only — your messages are deleted immediately.",
        reply_markup=_CANCEL_KB,
    )


@app.on_callback_query(filters.regex(r"^acct_cancel$") & app.sudoers)
async def cb_acct_cancel(_, cq: CallbackQuery):
    await _cancel_pending(cq.from_user.id)
    await cq.answer()
    try:
        await cq.message.edit_text("Cancelled.")
    except Exception:
        pass


@app.on_callback_query(filters.regex(r"^acct_close$") & app.sudoers)
async def cb_acct_close(_, cq: CallbackQuery):
    await cq.answer()
    try:
        await cq.message.delete()
    except Exception:
        pass


@app.on_callback_query(filters.regex(r"^acct_del\|") & app.sudoers)
async def cb_acct_del(_, cq: CallbackQuery):
    uid = cq.data.split("|", 1)[1]
    await userbot.remove_saved(uid)
    entry = session_store.remove(int(uid))
    await cq.answer("Assistant removed." if entry else "Already gone.")
    try:
        await cq.message.edit_text(_text(), reply_markup=_kb())
    except Exception:
        pass


@app.on_message(filters.text & filters.private & app.sudoers, group=-2)
async def on_session_text(_, msg: Message):
    uid = msg.from_user.id if msg.from_user else 0
    state = _pending.get(uid)
    if not state:
        return

    raw = (msg.text or "").strip().replace(" ", "")

    # typing "cancel" (or /cancel) aborts the login at any stage
    if raw.lower() in ("cancel", "/cancel"):
        await _cancel_pending(uid)
        try:
            await msg.delete()
        except Exception:
            pass
        await msg.reply_text("❌ Login cancelled.")
        return

    try:
        await msg.delete()  # never leave credentials sitting in chat
    except Exception:
        pass

    # ── stage 1: phone number (or a pasted session string as fallback) ──
    if state["stage"] == "phone":
        if not _PHONE_RE.match(raw):
            if len(raw) > 100 and await _try_session_string(msg, raw):
                _pending.pop(uid, None)
                return
            await msg.reply_text(
                "❌ That doesn't look like a phone number. "
                "Send it with country code, e.g. <code>+919876543210</code>."
            )
            return

        phone = raw if raw.startswith("+") else f"+{raw}"
        client = Client(
            name=f"login_{uid}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            in_memory=True,
        )
        status = await msg.reply_text("⏳ Sending OTP…")
        try:
            await client.connect()
            sent = await client.send_code(phone)
        except errors.PhoneNumberInvalid:
            await client.disconnect()
            await status.edit_text("❌ Telegram says that phone number is invalid.")
            return
        except errors.FloodWait as ex:
            await client.disconnect()
            await status.edit_text(f"❌ Rate-limited — try again in {ex.value} seconds.")
            return
        except Exception as ex:
            await client.disconnect()
            logger.warning(f"send_code failed: {ex}")
            await status.edit_text(f"❌ Couldn't send the OTP (<code>{type(ex).__name__}</code>).")
            return

        state.update(stage="code", client=client, phone=phone, hash=sent.phone_code_hash)
        await status.edit_text(
            "📨 <b>OTP sent</b> to that account's Telegram.\n\n"
            "Send the code here — type it with dashes between digits "
            "(e.g. <code>1-2-3-4-5</code>) so Telegram doesn't eat the message.\n\n"
            "⚠️ If Telegram instantly voids codes, it's their anti-abuse "
            "protection on server IPs — wait a while and retry.",
            reply_markup=_CANCEL_KB,
        )
        return

    # ── stage 2: OTP code ──
    if state["stage"] == "code":
        code = raw.replace("-", "")
        client: Client = state["client"]
        status = await msg.reply_text("⏳ Verifying…")
        try:
            await client.sign_in(
                phone_number=state["phone"],
                phone_code_hash=state["hash"],
                phone_code=code,
            )
        except errors.SessionPasswordNeeded:
            state["stage"] = "password"
            await status.edit_text(
                "🔐 This account has <b>2FA</b> enabled — send its password.",
                reply_markup=_CANCEL_KB,
            )
            return
        except (errors.PhoneCodeInvalid,):
            await status.edit_text("❌ Wrong code — check it and send again.")
            return
        except errors.PhoneCodeExpired:
            await _cancel_pending(uid)
            await status.edit_text(
                "❌ The code expired (Telegram sometimes voids codes sent to "
                "datacenter IPs instantly). Tap ➕ Add Account to start over."
            )
            return
        except Exception as ex:
            await _cancel_pending(uid)
            logger.warning(f"sign_in failed: {ex}")
            await status.edit_text(f"❌ Login failed (<code>{type(ex).__name__}</code>). Start over.")
            return

        _pending.pop(uid, None)
        await status.edit_text("✅ Logged in — setting up the assistant…")
        await _finish_login(msg, state)
        return

    # ── stage 3: 2FA password ──
    if state["stage"] == "password":
        client: Client = state["client"]
        status = await msg.reply_text("⏳ Checking password…")
        try:
            await client.check_password(raw)
        except errors.PasswordHashInvalid:
            await status.edit_text("❌ Wrong password — send it again.")
            return
        except Exception as ex:
            await _cancel_pending(uid)
            logger.warning(f"check_password failed: {ex}")
            await status.edit_text(f"❌ Login failed (<code>{type(ex).__name__}</code>). Start over.")
            return

        _pending.pop(uid, None)
        await status.edit_text("✅ Logged in — setting up the assistant…")
        await _finish_login(msg, state)
        return


@app.on_callback_query(filters.regex(r"^acct_refresh$") & app.sudoers)
async def cb_acct_refresh(_, cq: CallbackQuery):
    n = await refresh_identities()
    try:
        await cq.message.edit_text(_text(), reply_markup=_kb())
    except Exception:
        pass
    await cq.answer(f"Refreshed {n} assistant(s) from Telegram")


@app.on_message(filters.command(["refreshassistant", "syncassistants"]) & app.sudoers)
async def refresh_assistant_cmd(_, msg: Message):
    note = await msg.reply_text("🔄 Refreshing assistant details from Telegram…")
    n = await refresh_identities()
    lines = ["<b>🔄 Assistants refreshed</b>", ""]
    for uid, entry in session_store.load().items():
        status = "🟢" if uid in userbot.saved else "🔴"
        uname = f" (@{entry['username']})" if entry.get("username") else ""
        lines.append(f"{status} {entry.get('name') or uid}{uname}")
    lines.append(f"\n<i>{n} changed.</i>")
    try:
        await note.edit_text("\n".join(lines))
    except Exception:
        pass
