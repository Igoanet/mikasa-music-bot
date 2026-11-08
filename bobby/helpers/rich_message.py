import aiohttp
from pyrogram import types
from bobby import config


def _convert_markup(reply_markup):
    if reply_markup is None:
        return None
    if isinstance(reply_markup, types.InlineKeyboardMarkup):
        kb = []
        for row in reply_markup.inline_keyboard:
            r = []
            for b in row:
                item = {"text": b.text}
                if b.url:
                    item["url"] = b.url
                elif b.callback_data:
                    item["callback_data"] = b.callback_data
                elif b.copy_text:
                    item["copy_text"] = {"text": b.copy_text.text}

                # Preserve button style and custom emoji
                if getattr(b, "icon_custom_emoji_id", None):
                    item["icon_custom_emoji_id"] = str(b.icon_custom_emoji_id)
                if getattr(b, "style", None):
                    item["style"] = getattr(b.style, "value", str(b.style).lower())
                r.append(item)
            kb.append(r)
        return {"inline_keyboard": kb}
    if isinstance(reply_markup, dict):
        return reply_markup
    return None


async def send_rich_message(
    chat_id: int | str,
    blocks: list[dict],
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> dict:
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendRichMessage"
    payload = {
        "chat_id": chat_id,
        "rich_message": {"blocks": blocks},
    }
    markup = _convert_markup(reply_markup)
    if markup:
        payload["reply_markup"] = markup

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()


async def edit_rich_message(
    chat_id: int | str,
    message_id: int,
    blocks: list[dict],
    reply_markup: types.InlineKeyboardMarkup | None = None,
) -> dict:
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "rich_message": {"blocks": blocks},
    }
    markup = _convert_markup(reply_markup)
    if markup:
        payload["reply_markup"] = markup

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()


def get_start_chat_button_blocks(bot_user: str, support_channel: str, support_chat: str) -> list[dict]:
    if not support_channel.startswith("http"):
        support_channel = f"https://t.me/{support_channel.lstrip('@')}"
    if not support_chat.startswith("http"):
        support_chat = f"https://t.me/{support_chat.lstrip('@')}"

    return [
        {
            "type": "paragraph",
            "text": (
                "🎧 ˹ᴍɪᴋᴀꜱᴀ 𓆩⚔️𓆪 ᴍᴜꜱɪᴄ♪ 🕊️\n"
                f"✨ ˹ᴍɪᴋᴀꜱᴀ ✘ ᴍᴜꜱɪᴄ˼ ✨\n"
                "ᴀᴅᴠᴀɴᴄᴇᴅ ᴍᴜsɪᴄ ᴘʟᴀʏᴇʀ ʙᴏᴛ ғᴏʀ ᴛᴇʟᴇɢʀᴀᴍ ɢʀᴏᴜᴘ ᴠɪᴅᴇᴏᴄʜᴀᴛs.\n\n"
                "⚡️ ʟᴀɢ ғʀᴇᴇ • 🛡 ɴᴏ ᴘʀᴏᴍᴏ & ᴀᴅs • 🕞 24×7 ᴜᴘᴛɪᴍᴇ\n\n"
                "❤️ ᴠɪsɪᴛ sᴜᴘᴘᴏʀᴛ ᴄʜᴀɴɴᴇʟ & sᴜᴘᴘᴏʀᴛ ᴄʜᴀᴛ ғᴏʀ ᴍᴏʀᴇ..."
            ),
        },
        {
            "type": "buttons",
            "buttons": [
                {
                    "text": "📢 Support Channel",
                    "url": support_channel,
                },
                {
                    "text": "💬 Support Chat",
                    "url": support_chat,
                },
            ],
        },
    ]
