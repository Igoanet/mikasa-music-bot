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
        # Main Table Header
        [
            {"text": [{"type": "bold", "text": "COMMAND"}], "is_header": True, "align": "left"},
            {"text": [{"type": "bold", "text": "COMMAND DETAILS"}], "is_header": True, "align": "left"},
        ],
        # 1. PLAY PART (Full row)
        [
            {"text": [{"type": "bold", "text": "🎵 PLAY COMMANDS"}], "is_header": True, "colspan": 2, "align": "center"},
        ],
        [
            {"text": [{"type": "code", "text": "/play"}], "align": "left"},
            {"text": "🎵 Stream Audio In VC", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/vplay"}], "align": "left"},
            {"text": "🎬 Stream Video In VC", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/pause"}], "align": "left"},
            {"text": "⏸ Pause Current Stream", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/resume"}], "align": "left"},
            {"text": "▶️ Resume Music Playback", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/skip"}], "align": "left"},
            {"text": "⏭ Skip To Next Song", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/stop"}], "align": "left"},
            {"text": "⏹ Stop & Clear Stream", "align": "left"},
        ],
        # 2. AUTOPLAY PART (Full row)
        [
            {"text": [{"type": "bold", "text": "🔄 AUTOPLAY ENGINE"}], "is_header": True, "colspan": 2, "align": "center"},
        ],
        [
            {"text": [{"type": "code", "text": "/autoplay"}], "align": "left"},
            {"text": "🔄 Toggle Smart Autoplay", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/playforce"}], "align": "left"},
            {"text": "⚡️ Force Immediate Play", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/cplay"}], "align": "left"},
            {"text": "📢 Channel Stream Play", "align": "left"},
        ],
        # 3. LOOP PART (Full row)
        [
            {"text": [{"type": "bold", "text": "🔁 LOOP & QUEUE"}], "is_header": True, "colspan": 2, "align": "center"},
        ],
        [
            {"text": [{"type": "code", "text": "/loop"}], "align": "left"},
            {"text": "🔁 Loop Track 1-10x", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/queue"}], "align": "left"},
            {"text": "📜 View Queued Playlist", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/shuffle"}], "align": "left"},
            {"text": "🔀 Randomize Queue Order", "align": "left"},
        ],
        # 4. SETTINGS & TOOLS (Full row)
        [
            {"text": [{"type": "bold", "text": "⚙️ SETTINGS & TOOLS"}], "is_header": True, "colspan": 2, "align": "center"},
        ],
        [
            {"text": [{"type": "code", "text": "/seek"}], "align": "left"},
            {"text": "⏩ Seek Duration Back/Fwd", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/speed"}], "align": "left"},
            {"text": "🎚 Play Speed (0.5x-2x)", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/auth"}], "align": "left"},
            {"text": "🛡 Authorize Controllers", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/lang"}], "align": "left"},
            {"text": "🌐 Switch Bot Language", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/ping"}], "align": "left"},
            {"text": "📶 Check Latency & Health", "align": "left"},
        ],
        [
            {"text": [{"type": "code", "text": "/stats"}], "align": "left"},
            {"text": "📊 Overall Bot Stats", "align": "left"},
        ],
    ]

    if staff:
        cells.extend([
            [
                {"text": [{"type": "bold", "text": "🛡 STAFF COMMANDS"}], "is_header": True, "colspan": 2, "align": "center"},
            ],
            [
                {"text": [{"type": "code", "text": "/activevc"}], "align": "left"},
                {"text": "🎙 Active Voice Chats", "align": "left"},
            ],
            [
                {"text": [{"type": "code", "text": "/broadcast"}], "align": "left"},
                {"text": "📢 Global Broadcast", "align": "left"},
            ],
            [
                {"text": [{"type": "code", "text": "/restart"}], "align": "left"},
                {"text": "🔄 Restart Bot Engine", "align": "left"},
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
            "is_bordered": True,
            "is_striped": True,
            "cells": cells,
        },
    ]

    return blocks
