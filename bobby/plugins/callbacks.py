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

# every filter is anchored to its own "<prefix> " protocol: an unanchored
# regex like "help" would also fire on foreign payloads that merely contain
# the word — e.g. a "recs play <video id>" whose random id spells it

async def _safe_answer(query, *args, **kwargs):
    """Answer a callback, tolerating an already-answered one.

    A callback can only be answered once; answering early (so the tap feels
    instant) and again at the end must not raise QueryIdInvalid
    (2026-09-30).
    """
    try:
        return await _safe_answer(query, *args, **kwargs)
    except errors.QueryIdInvalid:
        return None
    except Exception:
        return None


@app.on_callback_query(filters.regex(r"^cancel_dl$") & ~app.bl_users)
@lang.language()
async def cancel_dl(_, query: types.CallbackQuery):
    await _safe_answer(query, )
    await tg.cancel(query)


@app.on_callback_query(filters.regex(r"^controls ") & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _controls(_, query: types.CallbackQuery):
    args = query.data.split()
    action, chat_id = args[1], int(args[2])
    qaction = len(args) == 4
    user = query.from_user.mention

    # Callback data is user-controlled.  The message carrying the button is
    # the destination authority; never let a source-group user rewrite the
    # chat id and operate a different group's playback.
    if query.message.chat.id != chat_id:
        return await _safe_answer(query, query.lang["user_no_perms"], show_alert=True)

    if action == "autoplay":
        # the switch on the playing panel — the same setting /autoplay and
        # /settings change, so it works even if playback already ended
        enabled = not await db.get_autoplay(chat_id)
        await db.set_autoplay(chat_id, enabled)
        if not enabled:
            # a pick that is already being looked up must not still land
            from bobby.helpers import _recs as recs

            recs.cancel(chat_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=buttons.controls(
                    chat_id, autoplay=enabled, _lang=query.lang, is_admin=True,autoplay_all=await db.get_autoplay_all(chat_id),)
            )
        except Exception:
            pass
        return await _safe_answer(query, 
            query.lang["autoplay_toggle_on"]
            if enabled
            else query.lang["autoplay_toggle_off"],
            show_alert=True,
        )

    # Keep a second live check at the action boundary: a callback may have
    # been authorised by the decorator just before Telegram membership was
    # revoked, and force/replay both start fresh playback.
    if action in {"force", "replay"} and await db.get_play_mode(chat_id):
        if not await is_live_group_admin(chat_id, query):
            return await _safe_answer(query, query.lang["play_admin"], show_alert=True)

    if not await db.get_call(chat_id):
        try:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        except errors.QueryIdInvalid:
            try:
                await query.message.delete()
            except Exception:
                pass
            return

    if action == "mute":
        # toggle the assistant's microphone in this voice chat
        try:
            import bobby

            calls = None
            for name in ("calls", "call", "tgcall"):
                obj = getattr(bobby, name, None)
                if obj is not None and hasattr(obj, "mute"):
                    calls = obj
                    break
            if calls is None:
                from bobby.core.calls import calls as _c  # last resort
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
            return await _safe_answer(query, f"Couldn't change mute: {type(ex).__name__}",
                                      show_alert=True)
        try:
            await query.edit_message_reply_markup(
                reply_markup=buttons.controls(
                    chat_id,
                    timer=query.message.reply_markup.inline_keyboard[0][0].text,
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
        return await _safe_answer(query, )

    # +10s button guards run BEFORE the "processing" answer below — a
    # callback query can only be answered once, so rejections must be the
    # first (and only) answer or they raise QueryIdInvalid
    if action == "seekf":
        media = queue.get_current(chat_id)
        if not await db.playing(chat_id):
            return await _safe_answer(query, 
                query.lang["play_already_paused"], show_alert=True
            )
        if not media or not media.duration_sec:
            return await _safe_answer(query, 
                query.lang["play_seek_no_dur"], show_alert=True
            )

    try:
        await _safe_answer(query, query.lang["processing"], show_alert=True)
    except errors.QueryIdInvalid:
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # Pause/Resume is a single toggle (owner 2026-10-18).  The panel
    # labelled itself from a status line that is now a progress bar, so
    # it always read "Pause": tapping it while paused re-sent "pause",
    # the handler answered "already paused", and nothing played.  Make
    # the requested action match reality before dispatch, so a tap
    # always does what it looks like.
    if action in ("pause", "resume"):
        _playing = await db.playing(chat_id)
        if action == "pause" and not _playing:
            action = "resume"
        elif action == "resume" and _playing:
            action = "pause"

    if action == "pause":
        if not await db.playing(chat_id):
            return await _safe_answer(query, 
                query.lang["play_already_paused"], show_alert=True
            )
        await anon.pause(chat_id)
        if qaction:
            return await query.edit_message_reply_markup(
                reply_markup=buttons.queue_markup(chat_id, query.lang["paused"], False)
            )
        status = query.lang["paused"]
        reply = query.lang["play_paused"].format(user)

    elif action == "resume":
        if await db.playing(chat_id):
            return await _safe_answer(query, query.lang["play_not_paused"], show_alert=True)
        await anon.resume(chat_id)
        if qaction:
            return await query.edit_message_reply_markup(
                reply_markup=buttons.queue_markup(chat_id, query.lang["playing"], True)
            )
        reply = query.lang["play_resumed"].format(user)

    elif action == "skip":
        # Answer before the work: switching tracks takes seconds, and the tap
        # must feel instant (2026-09-30).
        await _safe_answer(query, query.lang["skipped"])
        await anon.play_next(chat_id)
        status = query.lang["skipped"]
        reply = query.lang["play_skipped"].format(user)

    elif action == "force":
        pos, media = queue.check_item(chat_id, args[3])
        if not media or pos == -1:
            return await query.edit_message_text(query.lang["play_expired"])

        m_id = queue.get_current(chat_id).message_id
        queue.force_add(chat_id, media, remove=pos)
        try:
            await app.delete_messages(
                chat_id=chat_id, message_ids=[m_id, media.message_id], revoke=True
            )
            media.message_id = None
        except Exception:
            pass

        msg = await app.send_message(chat_id=chat_id, text=query.lang["play_next"])
        if not media.file_path:
            media.file_path = await yt.download(media.id, video=media.video)
        media.message_id = msg.id
        return await anon.play_media(chat_id, msg, media)

    elif action == "replay":
        media = queue.get_current(chat_id)
        media.user = user
        await anon.replay(chat_id)
        status = query.lang["replayed"]
        reply = query.lang["play_replayed"].format(user)

    elif action == "seekb":
        # the -15s button: the same mechanism /seek uses (play_media at an
        # offset), stepped back 15s and clamped at the start (2026-09-30)
        media = queue.get_current(chat_id)
        start_from = max(0, media.time - 15)
        await anon.play_media(chat_id, query.message, media, start_from)
        media.time = start_from
        status = None
        reply = query.lang["play_seeked"].format(
            query.lang.get("backward", "\u23ea"), start_from, user
        )

    elif action == "seekf":
        # the +15s button — the same forward seek /seek does, fixed 10s
        # step; guards already ran above (single-answer rule)
        media = queue.get_current(chat_id)
        start_from = media.time + 15
        if start_from + 15 > media.duration_sec:
            start_from = media.duration_sec - 5
        await anon.play_media(chat_id, query.message, media, start_from)
        media.time = start_from
        status = None
        reply = query.lang["play_seeked"].format(
            query.lang["forward"], start_from, user
        )

    elif action == "stop":
        await anon.stop(chat_id)
        status = query.lang["stopped"]
        reply = query.lang["play_stopped"].format(user)

    try:
        if action in ["skip", "replay", "stop"]:
            await query.message.reply_text(reply)
            await query.message.delete()
        else:
            mtext = re.sub(
                r"\n\n<blockquote>.*?</blockquote>",
                "",
                query.message.caption.html or query.message.text.html,
                flags=re.DOTALL,
            )
            keyboard = buttons.controls(
                chat_id,
                status=_panel_row1(chat_id),
                paused=(action == "pause"),
                autoplay=await db.get_autoplay(chat_id),
                _lang=query.lang, is_admin=True,autoplay_all=await db.get_autoplay_all(chat_id),)
        await query.edit_message_text(
            f"{mtext}\n\n<blockquote>{reply}</blockquote>", reply_markup=keyboard
        )
    except Exception:
        pass

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
            return await query.message.reply_to_message.delete()
        except Exception:
            return

    # staff-only sections — anyone else tapping a stale/crafted button gets
    # silence, not a "no permission" page (they shouldn't know it exists)
    _uid = query.from_user.id if query.from_user else 0
    if data[1] in ("clone", "blist", "sudo", "owner") and (
        _uid != config.OWNER_ID and _uid not in app.sudoers
    ):
        return await _safe_answer(query, )

    await query.edit_message_text(
        text=query.lang[f"help_{data[1]}"],
        reply_markup=buttons.help_markup(query.lang, True),
    )

@app.on_callback_query(filters.regex(r"^settings(?: |$)") & ~app.bl_users)
@lang.language()
async def _settings_cb(_, query: types.CallbackQuery):
    cmd = query.data.split()
    if len(cmd) == 1:
        return await _safe_answer(query, )

    chat_id = query.message.chat.id
    _admin = await db.get_play_mode(chat_id)

    if cmd[1] == "play":
        # Policy changes are deliberately not covered by admin_check:
        # Telegram's live OWNER status is the only authority.  In particular,
        # a bot owner/sudo user, auth user, or stale cached group admin cannot
        # change another group's playback policy.
        desired = cmd[2].lower() if len(cmd) > 2 else ""
        if not await is_group_owner(chat_id, query):
            return await _safe_answer(query, 
                query.lang["play_mode_owner_only"], show_alert=True
            )
        if desired not in {"admins", "everyone"}:
            return await _safe_answer(query, 
                query.lang["play_mode_usage"], show_alert=True
            )
        _admin = desired == "admins"
        await db.set_play_mode(chat_id, _admin)
        await _safe_answer(query, 
            query.lang["play_mode_set"].format(
                query.lang["play_admins"] if _admin else query.lang["play_everyone"]
            ),
            show_alert=True,
        )
    else:
        # The remaining settings retain their historical cached-admin/sudo
        # gate.  Only playback-policy changes require live OWNER status.
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
        await _safe_answer(query, query.lang["processing"], show_alert=True)

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

# every filter is anchored to its own "<prefix> " protocol: an unanchored
# regex like "help" would also fire on foreign payloads that merely contain
# the word — e.g. a "recs play <video id>" whose random id spells it

@app.on_callback_query(filters.regex(r"^cancel_dl$") & ~app.bl_users)
@lang.language()
async def cancel_dl(_, query: types.CallbackQuery):
    await _safe_answer(query, )
    await tg.cancel(query)

@app.on_callback_query(filters.regex(r"^controls ") & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _controls(_, query: types.CallbackQuery):
    args = query.data.split()
    action, chat_id = args[1], int(args[2])
    qaction = len(args) == 4
    user = query.from_user.mention

    # Callback data is user-controlled.  The message carrying the button is
    # the destination authority; never let a source-group user rewrite the
    # chat id and operate a different group's playback.
    if query.message.chat.id != chat_id:
        return await _safe_answer(query, query.lang["user_no_perms"], show_alert=True)

    if action == "autoplay":
        # the switch on the playing panel — the same setting /autoplay and
        # /settings change, so it works even if playback already ended
        enabled = not await db.get_autoplay(chat_id)
        await db.set_autoplay(chat_id, enabled)
        if not enabled:
            # a pick that is already being looked up must not still land
            from bobby.helpers import _recs as recs

            recs.cancel(chat_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=buttons.controls(
                    chat_id, autoplay=enabled, _lang=query.lang, is_admin=True,autoplay_all=await db.get_autoplay_all(chat_id),)
            )
        except Exception:
            pass
        return await _safe_answer(query, 
            query.lang["autoplay_toggle_on"]
            if enabled
            else query.lang["autoplay_toggle_off"],
            show_alert=True,
        )

    # Keep a second live check at the action boundary: a callback may have
    # been authorised by the decorator just before Telegram membership was
    # revoked, and force/replay both start fresh playback.
    if action in {"force", "replay"} and await db.get_play_mode(chat_id):
        if not await is_live_group_admin(chat_id, query):
            return await _safe_answer(query, query.lang["play_admin"], show_alert=True)

    if not await db.get_call(chat_id):
        try:
            return await _safe_answer(query, query.lang["not_playing"], show_alert=True)
        except errors.QueryIdInvalid:
            try:
                await query.message.delete()
            except Exception:
                pass
            return

    if action == "mute":
        # toggle the assistant's microphone in this voice chat
        try:
            import bobby

            calls = None
            for name in ("calls", "call", "tgcall"):
                obj = getattr(bobby, name, None)
                if obj is not None and hasattr(obj, "mute"):
                    calls = obj
                    break
            if calls is None:
                from bobby.core.calls import calls as _c  # last resort
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
            return await _safe_answer(query, f"Couldn't change mute: {type(ex).__name__}",
                                      show_alert=True)
        try:
            await query.edit_message_reply_markup(
                reply_markup=buttons.controls(
                    chat_id,
                    timer=query.message.reply_markup.inline_keyboard[0][0].text,
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
        return await _safe_answer(query, )

    # +10s button guards run BEFORE the "processing" answer below — a
    # callback query can only be answered once, so rejections must be the
    # first (and only) answer or they raise QueryIdInvalid
    if action == "seekf":
        media = queue.get_current(chat_id)
        if not await db.playing(chat_id):
            return await _safe_answer(query, 
                query.lang["play_already_paused"], show_alert=True
            )
        if not media or not media.duration_sec:
            return await _safe_answer(query, 
                query.lang["play_seek_no_dur"], show_alert=True
            )

    try:
        await _safe_answer(query, query.lang["processing"], show_alert=True)
    except errors.QueryIdInvalid:
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # Pause/Resume is a single toggle (owner 2026-10-18).  The panel
    # labelled itself from a status line that is now a progress bar, so
    # it always read "Pause": tapping it while paused re-sent "pause",
    # the handler answered "already paused", and nothing played.  Make
    # the requested action match reality before dispatch, so a tap
    # always does what it looks like.
    if action in ("pause", "resume"):
        _playing = await db.playing(chat_id)
        if action == "pause" and not _playing:
            action = "resume"
        elif action == "resume" and _playing:
            action = "pause"

    if action == "pause":
        if not await db.playing(chat_id):
            return await _safe_answer(query, 
                query.lang["play_already_paused"], show_alert=True
            )
        await anon.pause(chat_id)
        if qaction:
            return await query.edit_message_reply_markup(
                reply_markup=buttons.queue_markup(chat_id, query.lang["paused"], False)
            )
        status = query.lang["paused"]
        reply = query.lang["play_paused"].format(user)

    elif action == "resume":
        if await db.playing(chat_id):
            return await _safe_answer(query, query.lang["play_not_paused"], show_alert=True)
        await anon.resume(chat_id)
        if qaction:
            return await query.edit_message_reply_markup(
                reply_markup=buttons.queue_markup(chat_id, query.lang["playing"], True)
            )
        reply = query.lang["play_resumed"].format(user)

    elif action == "skip":
        # Answer before the work: switching tracks takes seconds, and the tap
        # must feel instant (2026-09-30).
        await _safe_answer(query, query.lang["skipped"])
        await anon.play_next(chat_id)
        status = query.lang["skipped"]
        reply = query.lang["play_skipped"].format(user)

    elif action == "force":
        pos, media = queue.check_item(chat_id, args[3])
        if not media or pos == -1:
            return await query.edit_message_text(query.lang["play_expired"])

        m_id = queue.get_current(chat_id).message_id
        queue.force_add(chat_id, media, remove=pos)
        try:
            await app.delete_messages(
                chat_id=chat_id, message_ids=[m_id, media.message_id], revoke=True
            )
            media.message_id = None
        except Exception:
            pass

        msg = await app.send_message(chat_id=chat_id, text=query.lang["play_next"])
        if not media.file_path:
            media.file_path = await yt.download(media.id, video=media.video)
        media.message_id = msg.id
        return await anon.play_media(chat_id, msg, media)

    elif action == "replay":
        media = queue.get_current(chat_id)
        media.user = user
        await anon.replay(chat_id)
        status = query.lang["replayed"]
        reply = query.lang["play_replayed"].format(user)

    elif action == "seekf":
        # the +10s button — the same forward seek /seek does, fixed 10s
        # step; guards already ran above (single-answer rule)
        media = queue.get_current(chat_id)
        start_from = media.time + 10
        if start_from + 10 > media.duration_sec:
            start_from = media.duration_sec - 5
        await anon.play_media(chat_id, query.message, media, start_from)
        media.time = start_from
        status = None
        reply = query.lang["play_seeked"].format(
            query.lang["forward"], start_from, user
        )

    elif action == "stop":
        await anon.stop(chat_id)
        status = query.lang["stopped"]
        reply = query.lang["play_stopped"].format(user)

    try:
        if action in ["skip", "replay", "stop"]:
            await query.message.reply_text(reply)
            await query.message.delete()
        else:
            mtext = re.sub(
                r"\n\n<blockquote>.*?</blockquote>",
                "",
                query.message.caption.html or query.message.text.html,
                flags=re.DOTALL,
            )
            keyboard = buttons.controls(
                chat_id,
                status=_panel_row1(chat_id),
                paused=(action == "pause"),
                autoplay=await db.get_autoplay(chat_id),
                _lang=query.lang, is_admin=True,autoplay_all=await db.get_autoplay_all(chat_id),)
        await query.edit_message_text(
            f"{mtext}\n\n<blockquote>{reply}</blockquote>", reply_markup=keyboard
        )
    except Exception:
        pass

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
            return await query.message.reply_to_message.delete()
        except Exception:
            return

    # staff-only sections — anyone else tapping a stale/crafted button gets
    # silence, not a "no permission" page (they shouldn't know it exists)
    _uid = query.from_user.id if query.from_user else 0
    if data[1] in ("clone", "blist", "sudo", "owner") and (
        _uid != config.OWNER_ID and _uid not in app.sudoers
    ):
        return await _safe_answer(query, )

    await query.edit_message_text(
        text=query.lang[f"help_{data[1]}"],
        reply_markup=buttons.help_markup(query.lang, True),
    )

@app.on_callback_query(filters.regex(r"^settings(?: |$)") & ~app.bl_users)
@lang.language()
async def _settings_cb(_, query: types.CallbackQuery):
    cmd = query.data.split()
    if len(cmd) == 1:
        return await _safe_answer(query, )

    chat_id = query.message.chat.id
    _admin = await db.get_play_mode(chat_id)

    if cmd[1] == "play":
        # Policy changes are deliberately not covered by admin_check:
        # Telegram's live OWNER status is the only authority.  In particular,
        # a bot owner/sudo user, auth user, or stale cached group admin cannot
        # change another group's playback policy.
        desired = cmd[2].lower() if len(cmd) > 2 else ""
        if not await is_group_owner(chat_id, query):
            return await _safe_answer(query, 
                query.lang["play_mode_owner_only"], show_alert=True
            )
        if desired not in {"admins", "everyone"}:
            return await _safe_answer(query, 
                query.lang["play_mode_usage"], show_alert=True
            )
        _admin = desired == "admins"
        await db.set_play_mode(chat_id, _admin)
        await _safe_answer(query, 
            query.lang["play_mode_set"].format(
                query.lang["play_admins"] if _admin else query.lang["play_everyone"]
            ),
            show_alert=True,
        )
    else:
        # The remaining settings retain their historical cached-admin/sudo
        # gate.  Only playback-policy changes require live OWNER status.
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
        await _safe_answer(query, query.lang["processing"], show_alert=True)

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