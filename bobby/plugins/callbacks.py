# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import asyncio
import logging
import re

from pyrogram import enums, errors, filters, types

from bobby import anon, app, config, db, lang, queue, tg, yt
from bobby.helpers import buttons, can_manage_vc, is_group_owner, is_live_group_admin

logger = logging.getLogger("bobby")


def _panel_row1(chat_id: int) -> str:
    """Row 1 of the panel: the live progress line."""
    try:
        from bobby.core.disco import progress_bar
        cur = queue.get_current(chat_id)
        return progress_bar(getattr(cur, 'time', 0) or 0,
                            getattr(cur, 'duration_sec', 0) or 0)
    except Exception:
        return ""


# chat_id -> assistant muted? (per process)
_MUTE_STATE: dict = {}


async def _safe_answer(query: types.CallbackQuery, *args, **kwargs):
    """Answer a callback safely without crashing on already-answered or expired queries."""
    try:
        return await query.answer(*args, **kwargs)
    except (errors.QueryIdInvalid, errors.BadRequest):
        return None
    except Exception:
        return None


async def _notify_chat(chat_id: int, text: str):
    """Send notification to chat without blocking."""
    try:
        sent = await app.send_message(chat_id, text, parse_mode=enums.ParseMode.HTML)
        try:
            from bobby.helpers.group_cleaner import track_group_message
            track_group_message(chat_id, sent.id)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Failed to send button notification in {chat_id}: {e}")


@app.on_callback_query(filters.regex(r"^cancel_dl$") & ~app.bl_users)
@lang.language()
async def cancel_dl(_, query: types.CallbackQuery):
    await _safe_answer(query)
    await tg.cancel(query)


@app.on_callback_query(filters.regex(r"^controls ") & ~app.bl_users)
@lang.language()
async def _controls(_, query: types.CallbackQuery):
    args = query.data.split()
    action, chat_id = args[1], int(args[2])
    qaction = len(args) == 4
    user = query.from_user.mention

    if query.message.chat.id != chat_id:
        return await _safe_answer(query, query.lang["user_no_perms"], show_alert=True)

    user_id = query.from_user.id
    if await db.get_play_mode(chat_id):
        is_adm = (
            user_id in app.sudoers
            or await db.is_auth(chat_id, user_id)
            or user_id in await db.get_admins(chat_id)
            or await is_live_group_admin(chat_id, query)
        )
        if not is_adm:
            return await _safe_answer(query, query.lang["play_admin"], show_alert=True)

    if action == "autoplay":
        enabled = not await db.get_autoplay(chat_id)
        await db.set_autoplay(chat_id, enabled)
        if not enabled:
            from bobby.helpers import _recs as recs
            recs.cancel(chat_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=buttons.controls(
                    chat_id,
                    autoplay=enabled,
                    _lang=query.lang,
                    is_admin=True,
                    autoplay_all=await db.get_autoplay_all(chat_id),
                )
            )
        except Exception:
            pass
        return await _safe_answer(
            query,
            query.lang["autoplay_toggle_on"] if enabled else query.lang["autoplay_toggle_off"],
            show_alert=True,
        )

    # Check factual state: is a call active or is there a track currently queued/playing?
    call_active = await db.get_call(chat_id) or bool(queue.get_current(chat_id))
    if not call_active:
        return await _safe_answer(query, query.lang["not_playing"], show_alert=True)

    if action == "status":
        return await _safe_answer(query)

    # 1. MUTE / UNMUTE (or PAUSE / RESUME)
    if action in ("mute", "pause", "resume"):
        await _safe_answer(query)
        _is_playing = await db.playing(chat_id)
        if action == "mute":
            should_pause = _is_playing
        elif action == "pause":
            should_pause = True
        else:
            should_pause = False

        if should_pause:
            await anon.pause(chat_id)
            _MUTE_STATE[chat_id] = True
            reply = f"🔇 <b>{user} has muted the music.</b>"
        else:
            await anon.resume(chat_id)
            _MUTE_STATE[chat_id] = False
            reply = f"🔊 <b>{user} has unmuted the music.</b>"

        asyncio.create_task(_notify_chat(chat_id, reply))

        if qaction:
            try:
                await query.edit_message_reply_markup(
                    reply_markup=buttons.queue_markup(chat_id, query.lang["paused"] if should_pause else query.lang["playing"], not should_pause)
                )
            except Exception:
                pass
            return

        try:
            keyboard = buttons.controls(
                chat_id,
                status=_panel_row1(chat_id),
                paused=should_pause,
                autoplay=await db.get_autoplay(chat_id),
                _lang=query.lang,
                is_admin=True,
                autoplay_all=await db.get_autoplay_all(chat_id),
            )
            await query.edit_message_reply_markup(reply_markup=keyboard)
        except Exception:
            pass
        return

    # 2. REPLAY
    elif action == "replay":
        media = queue.get_current(chat_id)
        if not media:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        await _safe_answer(query)
        media.user = user
        reply = f"🔁 <b>{user} has requested replay.</b>"
        asyncio.create_task(_notify_chat(chat_id, reply))
        try:
            await query.message.delete()
        except Exception:
            pass
        await anon.replay(chat_id)
        return

    # 3. SEEK BACK (-15s)
    elif action == "seekb":
        media = queue.get_current(chat_id)
        if not media:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        await _safe_answer(query, "-15s", show_alert=False)
        reply = f"⏪ <b>{user} has seeked 15s back.</b>"
        asyncio.create_task(_notify_chat(chat_id, reply))
        start_from = max(1, getattr(media, "time", 0) - 15)
        media.time = start_from
        await anon.play_media(chat_id, query.message, media, start_from)
        return

    # 4. SEEK FORWARD (+15s)
    elif action == "seekf":
        media = queue.get_current(chat_id)
        if not media:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        if not await db.playing(chat_id):
            return await _safe_answer(query, query.lang["play_already_paused"], show_alert=True)
        dur = getattr(media, "duration_sec", 0) or 0
        if not dur:
            return await _safe_answer(query, query.lang["play_seek_no_dur"], show_alert=True)
        await _safe_answer(query, "+15s", show_alert=False)
        reply = f"⏩ <b>{user} has seeked 15s forward.</b>"
        asyncio.create_task(_notify_chat(chat_id, reply))
        start_from = getattr(media, "time", 0) + 15
        if start_from + 10 > dur:
            start_from = max(1, dur - 5)
        media.time = start_from
        await anon.play_media(chat_id, query.message, media, start_from)
        return

    # 5. SKIP
    elif action == "skip":
        media = queue.get_current(chat_id)
        if not media:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        await _safe_answer(query, query.lang.get("skipped", "Skipped."))
        reply = f"⏭️ <b>{user} has skipped the song.</b>"
        asyncio.create_task(_notify_chat(chat_id, reply))
        try:
            await query.message.delete()
        except Exception:
            pass
        await anon.play_next(chat_id, force_skip=True)
        return

    # 6. STOP
    elif action == "stop":
        await _safe_answer(query)
        reply = f"⏹️ <b>{user} has stopped the playback.</b>"
        asyncio.create_task(_notify_chat(chat_id, reply))
        try:
            await query.message.delete()
        except Exception:
            pass
        await anon.stop(chat_id)
        return

    # 7. FORCE PLAY FROM QUEUE
    elif action == "force":
        pos, media = queue.check_item(chat_id, args[3])
        if not media or pos == -1:
            await _safe_answer(query)
            return await query.edit_message_text(query.lang["play_expired"])

        curr = queue.get_current(chat_id)
        m_id = curr.message_id if curr else 0
        queue.force_add(chat_id, media, remove=pos)
        try:
            if m_id or media.message_id:
                to_delete = [mid for mid in [m_id, media.message_id] if mid]
                await app.delete_messages(chat_id=chat_id, message_ids=to_delete, revoke=True)
            media.message_id = None
        except Exception:
            pass

        if not media.file_path:
            media.file_path = await yt.download(media.id, video=media.video)
        await _safe_answer(query)
        return await anon.play_media(chat_id, query.message, media)


@app.on_callback_query(filters.regex(r"^start_menu$") & ~app.bl_users)
@lang.language()
async def _start_menu_cb(_, query: types.CallbackQuery):
    private = query.message.chat.type == enums.ChatType.PRIVATE
    bot_user = getattr(app, "username", None) or (app.me.username if getattr(app, "me", None) else "MikasaMusic_Bot")
    key = buttons.start_key(query.lang, private, owner=bool(query.from_user and query.from_user.id == config.OWNER_ID))
    _text = query.lang["start_gp" if not private else "start_pm"].format(
        bot_user, config.SUPPORT_CHANNEL, config.SUPPORT_CHAT, config.OWNER_ID
    )

    from bobby.helpers.rich_message import edit_rich_message, send_rich_message, get_start_chat_button_blocks
    blocks = get_start_chat_button_blocks(bot_user, config.SUPPORT_CHANNEL, config.SUPPORT_CHAT, is_group=not private)
    res = await edit_rich_message(query.message.chat.id, query.message.id, blocks, reply_markup=key)
    if not res.get("ok"):
        try:
            await query.message.delete()
        except Exception:
            pass
        resp = await send_rich_message(query.message.chat.id, blocks, reply_markup=key)
        if not resp.get("ok"):
            import os
            photo_path = "assets/start-preview.jpg" if os.path.exists("assets/start-preview.jpg") else config.START_IMG
            try:
                await app.send_photo(query.message.chat.id, photo=photo_path, caption=_text, reply_markup=key)
            except Exception:
                await app.send_message(query.message.chat.id, text=_text, reply_markup=key)

    await _safe_answer(query)


@app.on_callback_query(filters.regex(r"^(start_info|start_details)$") & ~app.bl_users)
@lang.language()
async def _start_info_cb(_, query: types.CallbackQuery):
    await _safe_answer(
        query,
        "˹ᴍɪᴋᴀꜱᴀ 𓆩⚔️𓆪 ᴍᴜꜱɪᴄ♪ is active & ready!\n\n"
        "⚡️ Lag Free — Ultra-Fast HQ Streaming\n"
        "🛡 100% Clean & Spam-Free\n"
        "🕞 24x7 Non-Stop Stable Playback\n"
        "💫 Unmatched Crystal Clear Audio\n\n"
        "Type /play followed by a song name or link to start streaming!",
        show_alert=True,
    )


@app.on_callback_query(filters.regex(r"^help(?: |$)") & ~app.bl_users)
@lang.language()
async def _help(_, query: types.CallbackQuery):
    data = query.data.split()
    is_owner = bool(query.from_user and query.from_user.id == config.OWNER_ID)
    staff = is_owner or (bool(query.from_user) and query.from_user.id in app.sudoers)

    if len(data) == 1 or data[1] == "back":
        from bobby.helpers.rich_message import edit_rich_message, send_rich_message, get_help_menu_blocks, get_help_text
        blocks = get_help_menu_blocks(staff=staff, owner=is_owner)
        markup = buttons.help_markup(query.lang, back=False, staff=staff, owner=is_owner)
        res = await edit_rich_message(query.message.chat.id, query.message.id, blocks, reply_markup=markup)
        if not res.get("ok"):
            try:
                if query.message.photo:
                    await query.edit_message_caption(caption=get_help_text(staff=staff, owner=is_owner), reply_markup=markup)
                else:
                    await query.edit_message_text(text=get_help_text(staff=staff, owner=is_owner), reply_markup=markup)
            except Exception:
                await send_rich_message(query.message.chat.id, blocks, reply_markup=markup)
        return await _safe_answer(query)

    elif data[1] == "close":
        try:
            await query.message.delete()
            if query.message.reply_to_message:
                return await query.message.reply_to_message.delete()
        except Exception:
            return

    _uid = query.from_user.id if query.from_user else 0
    if data[1] in ("blist", "sudo", "owner") and (
        _uid != config.OWNER_ID and _uid not in app.sudoers
    ):
        return await _safe_answer(query)

    text = query.lang.get(f"help_{data[1]}", query.lang["help_menu"])
    markup = buttons.help_markup(query.lang, back=True, staff=staff)
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=markup)
        else:
            await query.edit_message_text(text=text, reply_markup=markup)
    except Exception:
        await query.message.reply_text(text=text, reply_markup=markup)
    await _safe_answer(query)


@app.on_callback_query(filters.regex(r"^settings(?: |$)") & ~app.bl_users)
@lang.language()
async def _settings_cb(_, query: types.CallbackQuery):
    cmd = query.data.split()
    if len(cmd) == 1:
        return await _safe_answer(query)

    chat_id = query.message.chat.id
    _admin = await db.get_play_mode(chat_id)

    if cmd[1] == "play":
        desired = cmd[2].lower() if len(cmd) > 2 else ""
        if not await is_group_owner(chat_id, query):
            return await _safe_answer(
                query,
                query.lang["play_mode_owner_only"],
                show_alert=True,
            )
        if desired not in {"admins", "everyone"}:
            return await _safe_answer(
                query,
                query.lang["play_mode_usage"],
                show_alert=True,
            )
        _admin = desired == "admins"
        await db.set_play_mode(chat_id, _admin)
        await _safe_answer(
            query,
            query.lang["play_mode_set"].format(
                query.lang["play_admins"] if _admin else query.lang["play_everyone"]
            ),
            show_alert=True,
        )
    else:
        user = getattr(query, "from_user", None)
        user_id = getattr(user, "id", None)
        if (
            query.message.chat.type != enums.ChatType.PRIVATE
            and (
                user_id is None
                or (
                    user_id not in app.sudoers
                    and user_id not in await db.get_admins(chat_id)
                )
            )
        ):
            return await _safe_answer(query, query.lang["user_no_perms"], show_alert=True)
        await _safe_answer(query)

    _force = await db.get_force_mode(chat_id)
    _delete = await db.get_cmd_delete(chat_id)
    _language = await db.get_lang(chat_id)
    _autoplay = await db.get_autoplay(chat_id)

    if cmd[1] == "delete":
        _delete = not _delete
        await db.set_cmd_delete(chat_id, _delete)
    elif cmd[1] == "force":
        _force = not _force
        await db.set_force_mode(chat_id, _force)
    elif cmd[1] == "autoplay":
        _autoplay = not _autoplay
        await db.set_autoplay(chat_id, _autoplay)

    await query.edit_message_reply_markup(
        reply_markup=buttons.settings_markup(
            query.lang,
            _admin,
            _delete,
            _language,
            chat_id,
            _force,
            _autoplay,
        )
    )


@app.on_callback_query(filters.regex(r"^retry_vc ") & ~app.bl_users)
@lang.language()
async def _retry_vc(_, query: types.CallbackQuery):
    try:
        chat_id = int(query.data.split()[1])
    except Exception:
        return await _safe_answer(query)

    if query.message.chat.id != chat_id:
        return await _safe_answer(query, query.lang.get("user_no_perms", "Not allowed"), show_alert=True)

    pending = getattr(anon, "_pending_vc_retry", {}).pop(chat_id, None)
    if not pending:
        return await _safe_answer(query, "No pending song to retry. Please send /play <song> again.", show_alert=True)

    media, seek_time = pending
    await _safe_answer(query, "🔄 Retrying voice chat connection...")
    try:
        await query.message.edit_text("🔄 <b>Connecting to voice chat...</b>")
    except Exception:
        pass

    await anon.play_media(chat_id, query.message, media, seek_time)
