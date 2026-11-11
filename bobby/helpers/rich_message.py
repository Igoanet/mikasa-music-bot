# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import json
import os
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
                item = {"text": b.text or "\u200b"}
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
    photo_path: str | None = None,
    message_effect_id: str | int | None = None,
) -> dict:
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendRichMessage"
    markup = _convert_markup(reply_markup)

    if photo_path and os.path.exists(str(photo_path)):
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        data.add_field(
            "photo_file",
            open(str(photo_path), "rb"),
            filename=os.path.basename(str(photo_path)),
            content_type="image/png" if str(photo_path).endswith(".png") else "image/jpeg",
        )
        data.add_field("rich_message", json.dumps({"blocks": blocks}))
        if markup:
            data.add_field("reply_markup", json.dumps(markup))
        if message_effect_id:
            data.add_field("message_effect_id", str(message_effect_id))
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                return await resp.json()

    payload = {
        "chat_id": chat_id,
        "rich_message": {"blocks": blocks},
    }
    if markup:
        payload["reply_markup"] = markup
    if message_effect_id:
        payload["message_effect_id"] = str(message_effect_id)

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
                    "text": "˹ᴍɪᴋᴀꜱᴀ ✘ ᴍᴜꜱɪᴄ˼",
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
                {"type": "bold", "text": "ᴡʜʏ ᴄʜᴏᴏsᴇ ᴍɪᴋᴀsᴀ ᴍᴜsɪᴄ ?\n\n"},
                {"type": "custom_emoji", "custom_emoji_id": "5893048571560726748", "alternative_text": "⚡️"},
                {"type": "bold", "text": "  ʟᴀɢ ғʀᴇᴇ — ᴜʟᴛʀᴀ-ғᴀsᴛ ʜǫ sᴛʀᴇᴀᴍɪɴɢ\n\n"},
                {"type": "custom_emoji", "custom_emoji_id": "5902016123972358349", "alternative_text": "🛡"},
                {"type": "bold", "text": "  ɴᴏ ᴘʀᴏᴍᴏ & ᴀᴅs — 100% ᴄʟᴇᴀɴ & sᴘᴀᴍ ғʀᴇᴇ\n\n"},
                {"type": "custom_emoji", "custom_emoji_id": "5893102202817352158", "alternative_text": "🕞"},
                {"type": "bold", "text": "  24×7 ᴜᴘᴛɪᴍᴇ — ɴᴏɴ-sᴛᴏᴘ sᴛᴀʙʟᴇ ᴘʟᴀʏʙᴀᴄᴋ\n\n"},
                {"type": "custom_emoji", "custom_emoji_id": "5895770017458294953", "alternative_text": "💫"},
                {"type": "bold", "text": "  ᴜɴᴍᴀᴛᴄʜᴇᴅ sᴏᴜɴᴅ — ᴄʀʏsᴛᴀʟ ᴄʟᴇᴀʀ sᴏᴜɴᴅ ᴀᴜᴅɪᴏ"},
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


def _cmd_item(emoji_id: str, fallback: str, desc: str) -> dict:
    return {
        "text": [
            {"type": "custom_emoji", "custom_emoji_id": emoji_id, "alternative_text": fallback},
            f" {desc}",
        ],
        "align": "left",
    }


def _cat_header(emoji_id: str, fallback: str, title: str) -> dict:
    return {
        "text": [
            {"type": "custom_emoji", "custom_emoji_id": emoji_id, "alternative_text": fallback},
            {"type": "bold", "text": f" {title}"},
        ],
        "is_header": True,
        "colspan": 2,
        "align": "left",
    }


def get_help_text(staff: bool = False) -> str:
    text = (
        '<tg-emoji emoji-id="6269555901628159084">🎧</tg-emoji><b> PLAY COMMANDS</b>  \n'
        '<code>/play</code>                   <tg-emoji emoji-id="6258277974638858828">🎵</tg-emoji>  Stream Audio In VC\n'
        '<code>/vplay</code>                  <tg-emoji emoji-id="6257814208365203474">🖼</tg-emoji>  Stream Video In VC\n'
        '<code>/pause</code>                  <tg-emoji emoji-id="5265214392579925557">▶️</tg-emoji>  Pause Current Stream\n'
        '<code>/resume</code>                <tg-emoji emoji-id="5264955367397270190">▶️</tg-emoji>  Resume Music Playback\n'
        '<code>/skip</code>                     <tg-emoji emoji-id="6255624844491100107">🚪</tg-emoji>  skip To Next Song\n'
        '<code>/playforce</code>      <tg-emoji emoji-id="6257850436414345286">📲</tg-emoji>  Force Immediate Play\n'
        '<code>/cplay</code>                  <tg-emoji emoji-id="6257876274937598023">🖼</tg-emoji>  Channel Stream Play\n'
        '<code>/seekback</code>         <tg-emoji emoji-id="6257833351034441574">⬅️</tg-emoji>  Seek Duration Back\n'
        '<code>/seekforth</code>        <tg-emoji emoji-id="6258229583242333883">➡️</tg-emoji>  Seek Duration forth\n\n\n'
        '<tg-emoji emoji-id="5319090522470495400">⭕️</tg-emoji><b>  AUTOPLAY ENGINE</b>  \n'
        '<code>/autoplay on</code>       <tg-emoji emoji-id="6255981326776667522">📍</tg-emoji>  Turn autoplay on\n'
        '<code>/autoplay off</code>      <tg-emoji emoji-id="6258005244215562150">📍</tg-emoji>  Turn autoplay off\n\n'
        '<tg-emoji emoji-id="5316883317302246413">💫</tg-emoji><b>  LOOP &amp; QUEUE</b>  \n'
        '<code>/loop</code>  <tg-emoji emoji-id="6257818730965766046">🔃</tg-emoji> Loop Track 1-10x\n'
        '<code>/queue</code> <tg-emoji emoji-id="6255560325492379134">🗒</tg-emoji> View Queued Playlist\n\n\n'
        '<tg-emoji emoji-id="5893161718179173515">⚙️</tg-emoji><b> SETTINGS &amp; TOOLS</b>  \n'
        '<code>/speed</code> <tg-emoji emoji-id="6258066331535412617">⏲</tg-emoji>  Play Speed (0.5x-2x)\n'
        '<code>/auth</code>  <tg-emoji emoji-id="6258110135906865510">👥</tg-emoji> Authorize Controllers\n'
        '<code>/lang</code>  <tg-emoji emoji-id="6257916192363646612">🤖</tg-emoji> Switch Bot Language\n'
        '<code>/ping</code>  <tg-emoji emoji-id="6255608862917791716">📶</tg-emoji> Check Latency &amp; Health\n'
        '<code>/stats</code>  <tg-emoji emoji-id="6258205153468353758">📊</tg-emoji> Overall Bot Stats'
    )
    if staff:
        text += (
            '\n\n\n'
            '<tg-emoji emoji-id="5902016123972358349">🛡</tg-emoji><b> STAFF COMMANDS</b>  \n'
            '<code>/activevc</code>     <tg-emoji emoji-id="6258243546181013251">🎙</tg-emoji>  Active Voice Chats\n'
            '<code>/broadcast</code>   <tg-emoji emoji-id="6257760143316881369">👥</tg-emoji> Global Broadcast\n'
            '<code>/restart</code>     <tg-emoji emoji-id="6258260768999870546">🔄</tg-emoji> Restart Bot Engine'
        )
    return text


def get_help_menu_blocks(staff: bool = False, photo_file_id: str | None = None) -> list[dict]:
    cells = [
        # 1. PLAY COMMANDS (Full row)
        [
            _cat_header("6269555901628159084", "🎧", "PLAY COMMANDS"),
        ],
        [
            {"text": [{"type": "code", "text": "/play"}], "align": "left"},
            _cmd_item("6258277974638858828", "🎵", "Stream Audio In VC"),
        ],
        [
            {"text": [{"type": "code", "text": "/vplay"}], "align": "left"},
            _cmd_item("6257814208365203474", "🎬", "Stream Video In VC"),
        ],
        [
            {"text": [{"type": "code", "text": "/pause"}], "align": "left"},
            _cmd_item("5265214392579925557", "⏸️", "Pause Current Stream"),
        ],
        [
            {"text": [{"type": "code", "text": "/resume"}], "align": "left"},
            _cmd_item("5264955367397270190", "▶️", "Resume Music Playback"),
        ],
        [
            {"text": [{"type": "code", "text": "/skip"}], "align": "left"},
            _cmd_item("6255624844491100107", "🚪", "Skip To Next Song"),
        ],
        [
            {"text": [{"type": "code", "text": "/playforce"}], "align": "left"},
            _cmd_item("6257850436414345286", "📲", "Force Immediate Play"),
        ],
        [
            {"text": [{"type": "code", "text": "/cplay"}], "align": "left"},
            _cmd_item("6257876274937598023", "🖼", "Channel Stream Play"),
        ],
        [
            {"text": [{"type": "code", "text": "/seekback"}], "align": "left"},
            _cmd_item("6257833351034441574", "⬅️", "Seek Duration Back"),
        ],
        [
            {"text": [{"type": "code", "text": "/seekforth"}], "align": "left"},
            _cmd_item("6258229583242333883", "➡️", "Seek Duration forth"),
        ],
        # 2. AUTOPLAY ENGINE (Full row)
        [
            _cat_header("5319090522470495400", "⭕️", "AUTOPLAY ENGINE"),
        ],
        [
            {"text": [{"type": "code", "text": "/autoplay on"}], "align": "left"},
            _cmd_item("6255981326776667522", "📍", "Turn autoplay on"),
        ],
        [
            {"text": [{"type": "code", "text": "/autoplay off"}], "align": "left"},
            _cmd_item("6258005244215562150", "📍", "Turn autoplay off"),
        ],
        # 3. LOOP & QUEUE (Full row)
        [
            _cat_header("5316883317302246413", "💫", "LOOP & QUEUE"),
        ],
        [
            {"text": [{"type": "code", "text": "/loop"}], "align": "left"},
            _cmd_item("6257818730965766046", "🔃", "Loop Track 1-10x"),
        ],
        [
            {"text": [{"type": "code", "text": "/queue"}], "align": "left"},
            _cmd_item("6255560325492379134", "🗒", "View Queued Playlist"),
        ],
        # 4. SETTINGS & TOOLS (Full row)
        [
            _cat_header("5893161718179173515", "⚙️", "SETTINGS & TOOLS"),
        ],
        [
            {"text": [{"type": "code", "text": "/speed"}], "align": "left"},
            _cmd_item("6258066331535412617", "⏲", "Play Speed (0.5x-2x)"),
        ],
        [
            {"text": [{"type": "code", "text": "/auth"}], "align": "left"},
            _cmd_item("6258110135906865510", "👥", "Authorize Controllers"),
        ],
        [
            {"text": [{"type": "code", "text": "/lang"}], "align": "left"},
            _cmd_item("6257916192363646612", "🤖", "Switch Bot Language"),
        ],
        [
            {"text": [{"type": "code", "text": "/ping"}], "align": "left"},
            _cmd_item("6255608862917791716", "📶", "Check Latency & Health"),
        ],
        [
            {"text": [{"type": "code", "text": "/stats"}], "align": "left"},
            _cmd_item("6258205153468353758", "📊", "Overall Bot Stats"),
        ],
    ]

    if staff:
        cells.extend([
            [
                _cat_header("5902016123972358349", "🛡", "STAFF COMMANDS"),
            ],
            [
                {"text": [{"type": "code", "text": "/activevc"}], "align": "left"},
                _cmd_item("6258243546181013251", "🎙", "Active Voice Chats"),
            ],
            [
                {"text": [{"type": "code", "text": "/broadcast"}], "align": "left"},
                _cmd_item("6257760143316881369", "👥", "Global Broadcast"),
            ],
            [
                {"text": [{"type": "code", "text": "/restart"}], "align": "left"},
                _cmd_item("6258260768999870546", "🔄", "Restart Bot Engine"),
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
                {"type": "custom_emoji", "custom_emoji_id": "5893494861612455015", "alternative_text": "⭐"},
                "  ",
                {"type": "bold", "text": "HELP & COMMANDS"},
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
                {"type": "bold", "text": "EXPLORE ALL PLAYBACK CONTROLS, SMART QUEUES & GROUP SETTINGS BELOW."},
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


def get_playback_blocks(
    clean_track: str,
    track_url: str,
    duration: str,
    user_name: str,
    support_chat: str,
    support_channel: str,
    has_photo: bool = False,
    photo_file_id: str | None = None,
) -> list[dict]:
    blocks = []
    if has_photo:
        blocks.append({
            "type": "photo",
            "photo": {
                "type": "photo",
                "media": photo_file_id or "attach://photo_file",
            },
        })
    elif photo_file_id:
        blocks.append({
            "type": "photo",
            "photo": {
                "type": "photo",
                "media": photo_file_id,
            },
        })

    blocks.extend([
        {
            "type": "paragraph",
            "text": [
                {"type": "custom_emoji", "custom_emoji_id": "6269555901628159084", "alternative_text": "🎧"},
                "  ",
                {"type": "bold", "text": "˹ ᴍɪᴋᴀꜱᴀ "},
                {"type": "custom_emoji", "custom_emoji_id": "5453991094435997597", "alternative_text": "⚔"},
                {"type": "bold", "text": " ᴍᴜꜱɪᴄ♪ "},
                {"type": "custom_emoji", "custom_emoji_id": "5316740183222140641", "alternative_text": "🕊"},
                {"type": "bold", "text": " ˼"},
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
                {"type": "bold", "text": "ᴛʀᴀᴄᴋ : "},
                {"type": "url", "url": track_url, "text": clean_track},
                "\n\u2800\n",
                {"type": "custom_emoji", "custom_emoji_id": "5316575093269214796", "alternative_text": "⏰"},
                "  ",
                {"type": "bold", "text": "ᴅᴜʀᴀᴛɪᴏɴ : "},
                duration,
                "\n\u2800\n",
                {"type": "custom_emoji", "custom_emoji_id": "5902335789798265487", "alternative_text": "👤"},
                "  ",
                {"type": "bold", "text": "ʀᴇǫᴜᴇsᴛᴇᴅ ʙʏ : "},
                user_name,
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
                "  ",
                {"type": "bold", "text": "ɪғ ʏᴏᴜ ғᴏᴜɴᴅ ᴀɴʏ ɪssᴜᴇ ʀᴇᴘᴏʀᴛ ɪᴍᴍᴇᴅɪᴀᴛᴇʟʏ :"},
            ],
        },
        {
            "type": "buttons",
            "buttons": [
                {
                    "style": "primary",
                    "url": support_chat,
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
                {"type": "bold", "text": "ᴜsᴇ ᴛʜᴇ ᴄᴏɴᴛʀᴏʟ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴍᴀɴᴀɢᴇ ᴘʟᴀʏ"},
            ],
        },
    ])
    return blocks

