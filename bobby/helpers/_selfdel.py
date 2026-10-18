"""Auto-delete the bot's own plain command replies after a short delay."""

import asyncio

from pyrogram import enums

DELETE_AFTER = 60  # seconds

_GROUPS = (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP)


async def _del_later(chat_id: int, msg_id: int) -> None:
    await asyncio.sleep(DELETE_AFTER)
    try:
        from bobby import app

        await app.delete_messages(chat_id, msg_id)
    except Exception:
        pass


def arm_delete(msg) -> None:
    """Schedule deletion for an already-sent message (best-effort)."""
    try:
        if msg is not None:
            asyncio.get_running_loop().create_task(
                _del_later(msg.chat.id, msg.id)
            )
    except Exception:
        pass


async def clean_reply(m, *args, **kwargs):
    """reply_text wrapper: self-destructs in groups when there are no buttons.

    Messages with inline keyboards (player card, menus), private or channel
    replies, and calls with preserve=True (status messages that are later
    edited into cards) are left untouched.
    """
    preserve = kwargs.pop("preserve", False)
    sent = await m.reply_text(*args, **kwargs)
    try:
        chat_type = getattr(getattr(m, "chat", None), "type", None)
        if (
            sent is not None
            and not preserve
            and kwargs.get("reply_markup") is None
            and chat_type in _GROUPS
        ):
            asyncio.get_running_loop().create_task(
                _del_later(sent.chat.id, sent.id)
            )
    except Exception:
        pass
    return sent
