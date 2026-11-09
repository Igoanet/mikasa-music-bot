# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import re

from pyrogram import enums, errors, filters, types

from bobby import anon, app, config, db, lang, queue, tg, yt
from bobby.helpers import buttons, can_manage_vc, is_group_owner, is_live_group_admin


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


@app.on_callback_query(filters.regex(r"^cancel_dl$") & ~app.bl_users)
@lang.language()
async def cancel_dl(_, query: types.CallbackQuery):
    await _safe_answer(query)
    await tg.cancel(query)


@app.on_callback_query(filters.regex(r"^controls ") & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _controls(_, query: types.CallbackQuery):
    args = query.data.split()
    action, chat_id = args[1], int(args[2])
    qaction = len(args) == 4
    user = query.from_user.mention

    if query.message.chat.id != chat_id:
        return await _safe_answer(query, query.lang["user_no_perms"], show_alert=True)

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

    if action in {"force", "replay"} and await db.get_play_mode(chat_id):
        if not await is_live_group_admin(chat_id, query):
            return await _safe_answer(query, query.lang["play_admin"], show_alert=True)

    # Check factual state: is a call active or is there a track currently queued/playing?
    call_active = await db.get_call(chat_id) or bool(queue.get_current(chat_id))
    if not call_active:
        return await _safe_answer(query, query.lang["not_playing"], show_alert=True)

    if action == "mute":
        try:
            import bobby
            calls = getattr(bobby, "anon", None) or getattr(bobby, "calls", None)
            if calls is None:
                from bobby.core.calls import calls as _c
                calls = _c
            state = _MUTE_STATE.get(chat_id, False)
            if state:
                await calls.unmute(chat_id)
                _MUTE_STATE[chat_id] = False
                note = "🔊 Unmuted."
            else:
                await calls.mute(chat_id)
                _MUTE_STATE[chat_id] = True
                note = "🔇 Muted."
        except Exception as ex:
            return await _safe_answer(query, f"Couldn't change mute: {type(ex).__name__}", show_alert=True)
        try:
            timer_text = (
                query.message.reply_markup.inline_keyboard[0][0].text
                if query.message.reply_markup and query.message.reply_markup.inline_keyboard
                else None
            )
            await query.edit_message_reply_markup(
                reply_markup=buttons.controls(
                    chat_id,
                    timer=timer_text,
                    autoplay=await db.get_autoplay(chat_id),
                    muted=_MUTE_STATE.get(chat_id, False),
                    is_admin=True,
                    autoplay_all=await db.get_autoplay_all(chat_id),
                    _lang=query.lang,
                )
            )
        except Exception:
            pass
        return await _safe_answer(query, note, show_alert=True)

    if action == "status":
        return await _safe_answer(query)

    # Resolve pause / resume state dynamically so button tap always does what it displays
    if action in ("pause", "resume"):
        _is_playing = await db.playing(chat_id)
        if action == "pause" and not _is_playing:
            action = "resume"
        elif action == "resume" and _is_playing:
            action = "pause"

    reply = None
    if action == "pause":
        if not await db.playing(chat_id):
            return await _safe_answer(query, query.lang["play_already_paused"], show_alert=True)
        await anon.pause(chat_id)
        if qaction:
            await _safe_answer(query)
            return await query.edit_message_reply_markup(
                reply_markup=buttons.queue_markup(chat_id, query.lang["paused"], False)
            )
        reply = query.lang["play_paused"].format(user)

    elif action == "resume":
        if await db.playing(chat_id):
            return await _safe_answer(query, query.lang["play_not_paused"], show_alert=True)
        await anon.resume(chat_id)
        if qaction:
            await _safe_answer(query)
            return await query.edit_message_reply_markup(
                reply_markup=buttons.queue_markup(chat_id, query.lang["playing"], True)
            )
        reply = query.lang["play_resumed"].format(user)

    elif action == "skip":
        await _safe_answer(query, query.lang.get("skipped", "Skipped."))
        await anon.play_next(chat_id)
        reply = query.lang["play_skipped"].format(user)

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

        msg = await app.send_message(chat_id=chat_id, text=query.lang["play_next"])
        from bobby.helpers.playback_loader import PlaybackLoader
        loader = PlaybackLoader(msg).start()
        if not media.file_path:
            media.file_path = await yt.download(media.id, video=media.video)
        media.message_id = msg.id
        await _safe_answer(query)
        return await anon.play_media(chat_id, msg, media)

    elif action == "replay":
        media = queue.get_current(chat_id)
        if not media:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        media.user = user
        await anon.replay(chat_id)
        reply = query.lang["play_replayed"].format(user)

    elif action == "seekb":
        media = queue.get_current(chat_id)
        if not media:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        start_from = max(1, getattr(media, "time", 0) - 15)
        await anon.play_media(chat_id, query.message, media, start_from)
        media.time = start_from
        reply = query.lang["play_seeked"].format(
            query.lang.get("backward", "⏪"), start_from, user
        )

    elif action == "seekf":
        media = queue.get_current(chat_id)
        if not media:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        if not await db.playing(chat_id):
            return await _safe_answer(query, query.lang["play_already_paused"], show_alert=True)
        dur = getattr(media, "duration_sec", 0) or 0
        if not dur:
            return await _safe_answer(query, query.lang["play_seek_no_dur"], show_alert=True)
        start_from = getattr(media, "time", 0) + 15
        if start_from + 10 > dur:
            start_from = max(1, dur - 5)
        await anon.play_media(chat_id, query.message, media, start_from)
        media.time = start_from
        reply = query.lang["play_seeked"].format(
            query.lang.get("forward", "⏩"), start_from, user
        )

    elif action == "stop":
        await anon.stop(chat_id)
        reply = query.lang["play_stopped"].format(user)

    # Acknowledge button tap
    await _safe_answer(query)

    try:
        if action in ["skip", "replay", "stop"]:
            if reply:
                await query.message.reply_text(reply)
            try:
                await query.message.delete()
            except Exception:
                pass
        else:
            keyboard = buttons.controls(
                chat_id,
                status=_panel_row1(chat_id),
                paused=(action == "pause"),
                autoplay=await db.get_autoplay(chat_id),
                _lang=query.lang,
                is_admin=True,
                autoplay_all=await db.get_autoplay_all(chat_id),
            )
            try:
                await query.edit_message_reply_markup(reply_markup=keyboard)
            except Exception:
                pass
            if reply:
                await _safe_answer(query, reply)
    except Exception:
        pass


@app.on_callback_query(filters.regex(r"^start_menu$") & ~app.bl_users)
@lang.language()
async def _start_menu_cb(_, query: types.CallbackQuery):
    private = query.message.chat.type == enums.ChatType.PRIVATE
    bot_user = getattr(app, "username", None) or (app.me.username if getattr(app, "me", None) else "MikasaMusic_Bot")
    key = buttons.start_key(query.lang, private, owner=bool(query.from_user and query.from_user.id == config.OWNER_ID))

    if private:
        from bobby.helpers.rich_message import edit_rich_message, get_start_chat_button_blocks
        blocks = get_start_chat_button_blocks(bot_user, config.SUPPORT_CHANNEL, config.SUPPORT_CHAT)
        resp = await edit_rich_message(query.message.chat.id, query.message.id, blocks, reply_markup=key)
        if resp.get("ok"):
            return
    else:
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

    _text = query.lang["start_gp" if not private else "start_pm"].format(
        bot_user, config.SUPPORT_CHANNEL, config.SUPPORT_CHAT, config.OWNER_ID
    )
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=_text, reply_markup=key)
        else:
            await query.edit_message_text(text=_text, reply_markup=key)
    except Exception:
        await _safe_answer(query)


@app.on_callback_query(filters.regex(r"^help(?: |$)") & ~app.bl_users)
@lang.language()
async def _help(_, query: types.CallbackQuery):
    data = query.data.split()
    if len(data) == 1:
        return await _safe_answer(query, url=f"https://t.me/{app.username}?start=help")

    if data[1] == "back":
        return await query.edit_message_text(
            text=query.lang["help_menu"],
            reply_markup=buttons.help_markup(
                query.lang,
                staff=bool(query.from_user)
                and (
                    query.from_user.id == config.OWNER_ID
                    or query.from_user.id in app.sudoers
                ),
            ),
        )
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

    await query.edit_message_text(
        text=query.lang[f"help_{data[1]}"],
        reply_markup=buttons.help_markup(query.lang, True),
    )


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
