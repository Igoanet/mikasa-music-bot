# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


from functools import wraps

from pyrogram import StopPropagation, enums, types

from bobby import app, db


def _actor_user(update) -> object | None:
    """Return the human user behind an update, if there is one.

    Telegram can deliver messages on behalf of an anonymous administrator or a
    channel.  Those updates must never be treated as a user's proof of group
    ownership/administration: there is no user identity that can be checked
    live in that case.
    """
    # The production callers pass a Message/CallbackQuery so sender_chat can
    # be rejected.  Accepting a bare user object also keeps this primitive
    # useful to offline callers that already performed identity extraction.
    user = (
        update
        if isinstance(update, int)
        or hasattr(update, "id") and not hasattr(update, "from_user")
        else getattr(update, "from_user", None)
    )
    if isinstance(update, int):
        update = None
    sender_chat = getattr(update, "sender_chat", None)
    if sender_chat is None:
        message = getattr(update, "message", None)
        sender_chat = getattr(message, "sender_chat", None)
    if user is None or sender_chat is not None:
        return None
    if getattr(user, "is_bot", False):
        return None
    return user


async def _live_member_status(chat_id: int, user_id: int):
    """Fetch a member directly from Telegram.

    Permission-sensitive playback policy checks deliberately do not fall back
    to ``db.get_admins``.  A denied/failed RPC therefore means denial, rather
    than accidentally authorising a stale cached administrator.
    """
    if not user_id:
        return None
    try:
        member = await app.get_chat_member(chat_id, user_id)
    except Exception:
        return None
    return getattr(member, "status", None)


def _status_value(status) -> str:
    value = getattr(status, "value", status)
    return str(value).lower().rsplit(".", 1)[-1]


async def is_group_owner(chat_id: int, update) -> bool:
    """Return whether ``update``'s human user is the live group owner."""
    user = _actor_user(update)
    if user is None:
        return False
    user_id = user if isinstance(user, int) else user.id
    return _status_value(await _live_member_status(chat_id, user_id)) in {
        "owner",
        "creator",
    }


async def is_live_group_admin(chat_id: int, update) -> bool:
    """Return whether ``update``'s human user is a live group admin/owner."""
    user = _actor_user(update)
    if user is None:
        return False
    user_id = user if isinstance(user, int) else user.id
    return _status_value(await _live_member_status(chat_id, user_id)) in {
        "administrator",
        "owner",
        "creator",
    }


def admin_check(func):
    @wraps(func)
    async def wrapper(_, update: types.Message | types.CallbackQuery, *args, **kwargs):
        async def reply(text):
            if isinstance(update, types.Message):
                return await update.reply_text(text)
            else:
                return await update.answer(text, show_alert=True)

        chat = (
            update.chat
            if isinstance(update, types.Message)
            else update.message.chat
        )
        if chat.type == enums.ChatType.PRIVATE:
            return await func(_, update, *args, **kwargs)

        user_id = update.from_user.id
        admins = await db.get_admins(chat.id)

        if user_id in app.sudoers:
            return await func(_, update, *args, **kwargs)

        if user_id not in admins:
            return await reply(update.lang["user_no_perms"])

        return await func(_, update, *args, **kwargs)

    return wrapper


def can_manage_vc(func):
    @wraps(func)
    async def wrapper(_, update: types.Message | types.CallbackQuery, *args, **kwargs):
        chat_id = (
            update.chat.id
            if isinstance(update, types.Message)
            else update.message.chat.id
        )
        user_id = update.from_user.id

        command = (
            (update.command[0].lower() if getattr(update, "command", None) else "")
            if isinstance(update, types.Message)
            else ""
        )
        callback_action = (
            (update.data or "").split()[1]
            if isinstance(update, types.CallbackQuery)
            and len((update.data or "").split()) > 1
            else ""
        )
        # Force/replay callbacks and queue imports can start fresh playback.
        # In strict admins-only mode they must use Telegram's live membership,
        # rather than this decorator's historical auth/sudo/admin cache.
        if (
            await db.get_play_mode(chat_id)
            and (
                callback_action in {"force", "replay"}
                or command in {"import", "ip"}
            )
        ):
            if await is_live_group_admin(chat_id, update):
                return await func(_, update, *args, **kwargs)
            if isinstance(update, types.Message):
                return await update.reply_text(update.lang["play_admin"])
            return await update.answer(update.lang["play_admin"], show_alert=True)

        if user_id in app.sudoers:
            return await func(_, update, *args, **kwargs)

        if await db.is_auth(chat_id, user_id):
            return await func(_, update, *args, **kwargs)

        admins = await db.get_admins(chat_id)
        if user_id in admins:
            return await func(_, update, *args, **kwargs)

        if isinstance(update, types.Message):
            return await update.reply_text(update.lang["user_no_perms"])
        else:
            return await update.answer(update.lang["user_no_perms"], show_alert=True)

    return wrapper


async def is_admin(chat_id: int, user_id: int) -> bool:
    if user_id in await db.get_admins(chat_id):
        return True
    try:
        member = await app.get_chat_member(chat_id, user_id)
        return member.status in [
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        ]
    except Exception:
        raise StopPropagation


async def reload_admins(chat_id: int) -> list[int]:
    try:
        admins = [
            admin
            async for admin in app.get_chat_members(
                chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS
            )
            if not admin.user.is_bot
        ]
        return [admin.user.id for admin in admins]
    except Exception:
        return []
