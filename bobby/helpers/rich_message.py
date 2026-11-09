# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import aiohttp
from pyrogram import types
from bobby import config

START_IMG_FILE_ID = "AgACAgQAAyEGAAMBBc0zVQACBSdq8UvK3kHxnjo5hnqxe7j2iNlHIAACEA5rG3aQiVOG1scuN2Og2AEAAwIAA3kAAz0E"


def _convert_markup(reply_markup):
    if not reply_markup:
        return None
    if hasattr(reply_markup, "inline_keyboard"):
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


def get_start_chat_button_blocks(
    bot_user: str,
    support_channel: str,
    support_chat: str,
    photo_file_id: str | None = None,
    is_group: bool = False,
) -> list[dict]:
    if not support_channel.startswith("http"):
        support_channel = f"https://t.me/{support_channel.lstrip('@')}"

    owner_url = config.OWNER_CHAT or "https://t.me/RohanDevta"
    if not owner_url.startswith("http"):
        owner_url = f"https://t.me/{owner_url.lstrip('@')}"
    owner_handle = owner_url.rstrip("/").split("/")[-1]
    if not owner_handle.startswith("@"):
        owner_handle = f"@{owner_handle}"

    photo_id = photo_file_id or START_IMG_FILE_ID

    blocks = [
        {
            "type": "photo",
            "photo": {
                "type": "photo",
                "media": photo_id,
            },
        },
        {
            "type": "paragraph",
            "text": [
                {"type": "custom_emoji", "custom_emoji_id": "6269555901628159084", "alternative_text": "🎧"},
                "  ",
                {
                    "type": "url",
                    "url": f"https://t.me/{bot_user}",
                    "text": "˹ᴍɪᴋᴀꜱᴀ 𓆩⚔️𓆪 ᴍᴜꜱɪᴄ♪",
                },
                "  ",
                {"type": "custom_emoji", "custom_emoji_id": "5316740183222140641", "alternative_text": "🕊️"},
                "\n\n",
                {"type": "custom_emoji", "custom_emoji_id": "5893321843149902412", "alternative_text": "✨"},
                "  ᴀᴅᴠᴀɴᴄᴇᴅ ᴍᴜsɪᴄ ᴘʟᴀʏᴇʀ ʙᴏᴛ ғᴏʀ ᴛᴇʟᴇɢʀᴀᴍ ɢʀᴏᴜᴘ ᴠɪᴅᴇᴏᴄʜᴀᴛs. ",
                {"type": "custom_emoji", "custom_emoji_id": "5893321843149902412", "alternative_text": "✨"},
            ],
        },
        {
            "type": "paragraph",
            "text": ["\u2800"],
        },
        {
            "type": "expandable_blockquote",
            "text": [
                {"type": "bold", "text": "ᴡʜʏ ᴄʜᴏᴏsᴇ ᴍɪᴋᴀsᴀ ᴍᴜsɪᴄ ?"},
                "\n\n",
                {"type": "custom_emoji", "custom_emoji_id": "5893048571560726748", "alternative_text": "⚡️"},
                "  ",
                {"type": "bold", "text": "ʟᴀɢ ғʀᴇᴇ — ᴜʟᴛʀᴀ-ғᴀsᴛ ʜǫ sᴛʀᴇᴀᴍɪɴɢ"},
                "\n\n",
                {"type": "custom_emoji", "custom_emoji_id": "5902016123972358349", "alternative_text": "🛡"},
                "  ",
                {"type": "bold", "text": "ɴᴏ ᴘʀᴏᴍᴏ & ᴀᴅs — 100% ᴄʟᴇᴀɴ & sᴘᴀᴍ ғʀᴇᴇ"},
                "\n\n",
                {"type": "custom_emoji", "custom_emoji_id": "5893102202817352158", "alternative_text": "🕞"},
                "  ",
                {"type": "bold", "text": "24×7 ᴜᴘᴛɪᴍᴇ — ɴᴏɴ-sᴛᴏᴘ sᴛᴀʙʟᴇ ᴘʟᴀʏʙᴀᴄᴋ"},
                "\n\n",
                {"type": "custom_emoji", "custom_emoji_id": "5895770017458294953", "alternative_text": "💫"},
                "  ",
                {"type": "bold", "text": "ᴜɴᴍᴀᴛᴄʜᴇᴅ sᴏᴜɴᴅ — ᴄʀʏsᴛᴀʟ ᴄʟᴇᴀʀ sᴏᴜɴᴅ ᴀᴜᴅɪᴏ"},
            ],
        },
        {
            "type": "paragraph",
            "text": ["\u2800"],
        },
        {
            "type": "paragraph",
            "text": [
                {"type": "custom_emoji", "custom_emoji_id": "5212982655343141065", "alternative_text": "🛡"},
                " ᴠɪsɪᴛ  ғᴏʀ ᴍᴏʀᴇ...",
            ],
        },
        {
            "type": "buttons",
            "buttons": [
                {
                    "style": "primary",
                    "url": owner_url,
                    "text": [
                        {
                            "type": "custom_emoji",
                            "custom_emoji_id": "5199612362021157840",
                            "alternative_text": "❄️",
                        },
                        "  Support Chat",
                    ],
                },
                {
                    "style": "primary",
                    "url": support_channel,
                    "text": [
                        {
                            "type": "custom_emoji",
                            "custom_emoji_id": "5398024200235529935",
                            "alternative_text": "❄️",
                        },
                        "  Support Channel",
                    ],
                },
            ],
        },
        {
            "type": "paragraph",
            "text": ["\u2800"],
        },
        {
            "type": "paragraph",
            "text": [
                {"type": "custom_emoji", "custom_emoji_id": "5893402730268987918", "alternative_text": "🍀"},
                "  ",
                {"type": "bold", "text": "ᴜɴʟᴇᴀsʜ ᴍɪᴋᴀsᴀ ᴍᴜsɪᴄ ɪɴ ʏᴏᴜʀ ɢʀᴏᴜᴘ — ᴛᴀᴘ ʙᴇʟᴏᴡ ᴛᴏ ᴀᴅᴅ ᴍᴇ !"},
            ],
        },
    ]

    return blocks


def get_help_menu_blocks(staff: bool = False, photo_file_id: str | None = None) -> list[dict]:
    cells = [
        [
            {"text": [{"type": "bold", "text": "⚫️ SECTION"}], "align": "left"},
            {"text": [{"type": "bold", "text": "⚪️ COMMAND"}], "align": "left"},
            {"text": [{"type": "bold", "text": "⚫️ DETAILS"}], "align": "left"},
        ],
        # PLAY PART (Black section)
        [
            {"text": [{"type": "bold", "text": "⚫️ PLAY"}], "align": "left"},
            {"text": [{"type": "code", "text": "/play"}], "align": "left"},
            {"text": "🎵 Stream music track", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚫️ PLAY"}], "align": "left"},
            {"text": [{"type": "code", "text": "/vplay"}], "align": "left"},
            {"text": "🎬 Stream video in VC", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚫️ PLAY"}], "align": "left"},
            {"text": [{"type": "code", "text": "/pause"}], "align": "left"},
            {"text": "⏸ Pause active stream", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚫️ PLAY"}], "align": "left"},
            {"text": [{"type": "code", "text": "/resume"}], "align": "left"},
            {"text": "▶️ Resume music stream", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚫️ PLAY"}], "align": "left"},
            {"text": [{"type": "code", "text": "/skip"}], "align": "left"},
            {"text": "⏭ Skip to next song", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚫️ PLAY"}], "align": "left"},
            {"text": [{"type": "code", "text": "/stop"}], "align": "left"},
            {"text": "⏹ Stop & clear stream", "align": "left"},
        ],
        # AUTOPLAY PART (White section)
        [
            {"text": [{"type": "bold", "text": "⚪️ AUTO"}], "align": "left"},
            {"text": [{"type": "code", "text": "/autoplay"}], "align": "left"},
            {"text": "🔄 Smart stream autoplay", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚪️ AUTO"}], "align": "left"},
            {"text": [{"type": "code", "text": "/playforce"}], "align": "left"},
            {"text": "⚡️ Force play track", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚪️ AUTO"}], "align": "left"},
            {"text": [{"type": "code", "text": "/cplay"}], "align": "left"},
            {"text": "📢 Channel music play", "align": "left"},
        ],
        # LOOP PART (Black section)
        [
            {"text": [{"type": "bold", "text": "⚫️ LOOP"}], "align": "left"},
            {"text": [{"type": "code", "text": "/loop"}], "align": "left"},
            {"text": "🔁 Loop track 1-10x", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚫️ LOOP"}], "align": "left"},
            {"text": [{"type": "code", "text": "/queue"}], "align": "left"},
            {"text": "📜 View track queue", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚫️ LOOP"}], "align": "left"},
            {"text": [{"type": "code", "text": "/shuffle"}], "align": "left"},
            {"text": "🔀 Randomize track order", "align": "left"},
        ],
        # SETTINGS PART (White section)
        [
            {"text": [{"type": "bold", "text": "⚪️ TOOLS"}], "align": "left"},
            {"text": [{"type": "code", "text": "/seek"}], "align": "left"},
            {"text": "⏩ Seek stream duration", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚪️ TOOLS"}], "align": "left"},
            {"text": [{"type": "code", "text": "/speed"}], "align": "left"},
            {"text": "🎚 Play speed (0.5-2x)", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚪️ TOOLS"}], "align": "left"},
            {"text": [{"type": "code", "text": "/auth"}], "align": "left"},
            {"text": "🛡 Authorize controllers", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚪️ TOOLS"}], "align": "left"},
            {"text": [{"type": "code", "text": "/lang"}], "align": "left"},
            {"text": "🌐 Switch bot language", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚪️ TOOLS"}], "align": "left"},
            {"text": [{"type": "code", "text": "/ping"}], "align": "left"},
            {"text": "📶 Check latency & health", "align": "left"},
        ],
        [
            {"text": [{"type": "bold", "text": "⚪️ TOOLS"}], "align": "left"},
            {"text": [{"type": "code", "text": "/stats"}], "align": "left"},
            {"text": "📊 Overall bot stats", "align": "left"},
        ],
    ]

    if staff:
        cells.extend([
            [
                {"text": [{"type": "bold", "text": "⚫️ STAFF"}], "align": "left"},
                {"text": [{"type": "code", "text": "/activevc"}], "align": "left"},
                {"text": "🎙 Active voice chats", "align": "left"},
            ],
            [
                {"text": [{"type": "bold", "text": "⚫️ STAFF"}], "align": "left"},
                {"text": [{"type": "code", "text": "/broadcast"}], "align": "left"},
                {"text": "📢 Global broadcast", "align": "left"},
            ],
            [
                {"text": [{"type": "bold", "text": "⚫️ STAFF"}], "align": "left"},
                {"text": [{"type": "code", "text": "/restart"}], "align": "left"},
                {"text": "🔄 Restart bot engine", "align": "left"},
            ],
        ])

    photo_id = photo_file_id or START_IMG_FILE_ID

    blocks = [
        {
            "type": "photo",
            "photo": {
                "type": "photo",
                "media": photo_id,
            },
        },
        {
            "type": "paragraph",
            "text": [
                {"type": "custom_emoji", "custom_emoji_id": "5893161718179173515", "alternative_text": "⚙️"},
                "  ",
                {"type": "bold", "text": "ʜᴇʟᴘ & ᴄᴏᴍᴍᴀɴᴅs"},
            ],
        },
        {
            "type": "paragraph",
            "text": ["\u2800"],
        },
        {
            "type": "expandable_blockquote",
            "text": [
                {"type": "custom_emoji", "custom_emoji_id": "5893321843149902412", "alternative_text": "✨"},
                "  ",
                {"type": "bold", "text": "ᴇxᴘʟᴏʀᴇ ᴀʟʟ ᴘʟᴀʏʙᴀᴄᴋ ᴄᴏɴᴛʀᴏʟs, sᴍᴀʀᴛ ǫᴜᴇᴜᴇs & ɢʀᴏᴜᴘ sᴇᴛᴛɪɴɢs ʙᴇʟᴏᴡ."},
                "\n\n",
                {"type": "custom_emoji", "custom_emoji_id": "5895770017458294953", "alternative_text": "💫"},
                "  ",
                {"type": "bold", "text": "ᴇᴠᴇʀʏᴛʜɪɴɢ ʏᴏᴜ ɴᴇᴇᴅ ᴛᴏ ᴘᴏᴡᴇʀ ʏᴏᴜʀ ɢʀᴏᴜᴘ's ʜǫ ᴍᴜsɪᴄ sᴛᴀᴛɪᴏɴ."},
            ],
        },
        {
            "type": "paragraph",
            "text": ["\u2800"],
        },
        {
            "type": "table",
            "cells": cells,
        },
    ]

    return blocks
