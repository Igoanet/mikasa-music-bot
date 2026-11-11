# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Broadcast — forward/copy a message to all groups (and optionally users),
with an optional silent pin in every group where the bot has pin permission.

Usage:
  Reply to any message → /broadcast
  Bot asks: 📌 With Pin   |   📢 No Pin
  Tap your choice — it runs immediately.

Extra flags (append to /broadcast):
  -copy      copy instead of forward (hides origin)
  -nochat    skip groups, send to users only (use with -user)
  -user      also send to individual users
"""

import asyncio
import os
import time

from pyrogram import errors, filters, types
from pyrogram.enums import ParseMode

from bobby import app, db, lang

# ── state ────────────────────────────────────────────────────────────────────
broadcasting = asyncio.Lock()

# pending[msg_id] = (source_message, flags_dict)
_pending: dict[int, tuple] = {}


# ── helpers ──────────────────────────────────────────────────────────────────
def _parse_flags(cmd: list[str]) -> dict:
    return {
        "copy":    "-copy"   in cmd,
        "nochat":  "-nochat" in cmd,
        "user":    "-user"   in cmd,
    }


def _mode_kb(msg_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton("📌 With Pin",   callback_data=f"bcast:pin:{msg_id}"),
            types.InlineKeyboardButton("📢 No Pin",     callback_data=f"bcast:nopin:{msg_id}"),
        ],
        [
            types.InlineKeyboardButton("✖ Cancel",      callback_data=f"bcast:cancel:{msg_id}"),
        ],
    ])


async def _run_broadcast(trigger_msg: types.Message,
                         source_msg:  types.Message,
                         flags:       dict,
                         pin:         bool):
    """Core broadcast loop — called after mode is chosen."""

    if broadcasting.locked():
        return await trigger_msg.reply_text("⏳ A broadcast is already running. Wait for it to finish.")

    copy   = flags["copy"]
    groups: set = set()
    users:  set = set()

    if not flags["nochat"]:
        groups = set(await db.get_chats())
    if flags["user"]:
        users = set(await db.get_users())

    chats = list(groups | users)
    total = len(chats)

    if not total:
        return await trigger_msg.reply_text("No chats to broadcast to.")

    pin_label = "📌 with pin" if pin else "📢 no pin"
    status = await trigger_msg.reply_text(
        f"<b>Broadcast started</b> — {total} target(s) · {pin_label}\n"
        f"<i>Progress updates every 25 deliveries.</i>",
        parse_mode=ParseMode.HTML,
    )

    count_g = count_u = pinned = pin_fail = 0
    t0 = time.time()
    failed_file = None

    async with broadcasting:
        for i, chat in enumerate(chats, 1):
            sent_msg = None
            try:
                sent_msg = (
                    await source_msg.copy(chat, reply_markup=source_msg.reply_markup)
                    if copy
                    else await source_msg.forward(chat)
                )
                if chat in groups:
                    count_g += 1
                else:
                    count_u += 1

                # pin only in groups, only when requested
                if pin and chat in groups and sent_msg:
                    try:
                        await app.pin_chat_message(
                            chat, sent_msg.id,
                            disable_notification=True,
                            both_sides=False,
                        )
                        pinned += 1
                    except Exception:
                        pin_fail += 1

                await asyncio.sleep(0.2)

            except errors.FloodWait as fw:
                await asyncio.sleep(fw.value + 10)
            except Exception as ex:
                if not failed_file:
                    failed_file = open("errors.txt", "w")
                failed_file.write(f"{chat} — {ex}\n")
                continue

            # progress update every 25
            if i % 25 == 0:
                elapsed = time.time() - t0
                try:
                    pin_line = f" · 📌 pinned <b>{pinned}</b> (failed {pin_fail})" if pin else ""
                    await status.edit_text(
                        f"<b>Broadcasting…</b>  {i}/{total}\n"
                        f"Groups: <b>{count_g}</b> · Users: <b>{count_u}</b>"
                        f"{pin_line}\n"
                        f"<i>{elapsed:.0f}s elapsed</i>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass

    elapsed = time.time() - t0
    pin_line = f"\n📌 Pinned: <b>{pinned}</b> groups" + (f" (no-perm skip: {pin_fail})" if pin_fail else "") if pin else ""
    summary = (
        f"<b>✅ Broadcast done</b> in <b>{elapsed:.0f}s</b>\n"
        f"Groups: <b>{count_g}</b> · Users: <b>{count_u}</b>"
        f"{pin_line}"
    )

    if failed_file:
        failed_file.close()
        await trigger_msg.reply_document(document="errors.txt", caption=summary,
                                         parse_mode=ParseMode.HTML)
        try:
            os.remove("errors.txt")
        except Exception:
            pass
    else:
        await status.edit_text(summary, parse_mode=ParseMode.HTML)


# ── /broadcast command ───────────────────────────────────────────────────────
@app.on_message(filters.command(["broadcast"]) & app.sudoers)
@lang.language()
async def _broadcast(_, message: types.Message):
    if not message.reply_to_message:
        return await message.reply_text(
            "<b>📢 Broadcast</b>\n\n"
            "Reply to any message with <code>/broadcast</code> to begin.\n\n"
            "<b>Flags:</b>\n"
            "  <code>-copy</code>   — copy (hides source)\n"
            "  <code>-nochat</code> — skip groups\n"
            "  <code>-user</code>   — also send to users\n\n"
            "<i>You'll be asked whether to pin or not.</i>",
            parse_mode=ParseMode.HTML,
        )

    flags = _parse_flags(message.command)
    src   = message.reply_to_message
    _pending[message.id] = (src, flags)

    await message.reply_text(
        "<b>📢 Broadcast ready</b>\n\n"
        "Choose the delivery mode:",
        reply_markup=_mode_kb(message.id),
        parse_mode=ParseMode.HTML,
    )


# ── callback: pin / nopin / cancel ───────────────────────────────────────────
@app.on_callback_query(filters.regex(r"^bcast:(pin|nopin|cancel):(\d+)$") & app.sudoers)
async def _bcast_cb(_, cq: types.CallbackQuery):
    await cq.answer()
    parts   = cq.data.split(":")
    mode    = parts[1]          # pin | nopin | cancel
    msg_id  = int(parts[2])

    entry = _pending.pop(msg_id, None)
    if not entry:
        try:
            await cq.message.edit_text("⚠️ Broadcast session expired — send /broadcast again.")
        except Exception:
            pass
        return

    src_msg, flags = entry

    if mode == "cancel":
        try:
            await cq.message.edit_text("❌ Broadcast cancelled.")
        except Exception:
            pass
        return

    pin = (mode == "pin")
    try:
        await cq.message.delete()
    except Exception:
        pass

    await _run_broadcast(cq.message, src_msg, flags, pin)
