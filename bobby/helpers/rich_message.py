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


def get_start_blocks(bot_user: str, support_url: str, owner_url: str) -> list[dict]:
    sh = support_url.rstrip("/").split("/")[-1]
    oh = owner_url.rstrip("/").split("/")[-1]
    if not sh.startswith("@"):
        sh = f"@{sh}"
    if not oh.startswith("@"):
        oh = f"@{oh}"

    return [
        {
            "type": "paragraph",
            "text": (
                "🎧 ˹ᴍɪᴋᴀꜱᴀ 𓆩⚔️𓆪 ᴍᴜꜱɪᴄ♪ 🕊️\n"
                f"✨ ˹ᴍɪᴋᴀꜱᴀ ✘ ᴍᴜꜱɪᴄ˼ ✨\n"
                "ᴀᴅᴠᴀɴᴄᴇᴅ ᴍᴜsɪᴄ ᴘʟᴀʏᴇʀ ʙᴏᴛ ғᴏʀ ᴛᴇʟᴇɢʀᴀᴍ ɢʀᴏᴜᴘ ᴠɪᴅᴇᴏᴄʜᴀᴛs.\n\n"
                "⚡️ ʟᴀɢ ғʀᴇᴇ • 🛡 ɴᴏ ᴘʀᴏᴍᴏ & ᴀᴅs • 🕞 24×7 ᴜᴘᴛɪᴍᴇ"
            ),
        },
        {
            "type": "table",
            "is_compact": True,
            "is_bordered": True,
            "cells": [
                [
                    {"text": "COMMAND"},
                    {"text": "COMMAND DETAILS"},
                ],
                [
                    {"text": "/play"},
                    {"text": "🎵 PLAY AUDIO / VIDEO"},
                ],
                [
                    {"text": "/pause"},
                    {"text": "⏸️ PAUSE STREAM"},
                ],
                [
                    {"text": "/skip"},
                    {"text": "⏭️ SKIP CURRENT SONG"},
                ],
                [
                    {"text": "/queue"},
                    {"text": "📜 VIEW & MANAGE QUEUE"},
                ],
            ],
        },
        {
            "type": "buttons",
            "buttons": [
                {
                    "text": f"💬 Support — {sh} 👥",
                    "url": support_url,
                },
                {
                    "text": f"👑 Owner — {oh}",
                    "url": owner_url,
                },
            ],
        },
    ]


def get_help_blocks(category: str, support_url: str, owner_url: str) -> list[dict]:
    sh = support_url.rstrip("/").split("/")[-1]
    oh = owner_url.rstrip("/").split("/")[-1]
    if not sh.startswith("@"):
        sh = f"@{sh}"
    if not oh.startswith("@"):
        oh = f"@{oh}"

    # Default category table entries
    tables = {
        "menu": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/play"}, {"text": "🎵 PLAY AUDIO / VIDEO"}],
            [{"text": "/pause"}, {"text": "⏸️ PAUSE STREAM"}],
            [{"text": "/skip"}, {"text": "⏭️ SKIP CURRENT SONG"}],
            [{"text": "/queue"}, {"text": "📜 VIEW & MANAGE QUEUE"}],
            [{"text": "/settings"}, {"text": "⚙️ CONFIGURE PLAY MODE"}],
        ],
        "play": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/play"}, {"text": "🎵 PLAY AUDIO / SONG"}],
            [{"text": "/vplay"}, {"text": "🎥 PLAY VIDEO STREAM"}],
            [{"text": "/playforce"}, {"text": "⚡ FORCE PLAY AUDIO"}],
            [{"text": "/vplayforce"}, {"text": "⚡ FORCE PLAY VIDEO"}],
            [{"text": "/cplay"}, {"text": "📡 CHANNEL AUDIO PLAY"}],
            [{"text": "/cvplay"}, {"text": "📡 CHANNEL VIDEO PLAY"}],
        ],
        "admins": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/pause"}, {"text": "⏸️ PAUSE STREAM"}],
            [{"text": "/resume"}, {"text": "▶️ RESUME STREAM"}],
            [{"text": "/skip"}, {"text": "⏭️ SKIP CURRENT SONG"}],
            [{"text": "/stop"}, {"text": "⏹️ STOP & CLEAR QUEUE"}],
            [{"text": "/mute"}, {"text": "🔇 MUTE ASSISTANT"}],
            [{"text": "/unmute"}, {"text": "🔊 UNMUTE ASSISTANT"}],
        ],
        "queue": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/queue"}, {"text": "📜 SHOW TRACK QUEUE"}],
            [{"text": "/shuffle"}, {"text": "🔀 SHUFFLE QUEUE"}],
            [{"text": "/export"}, {"text": "📤 EXPORT QUEUE"}],
            [{"text": "/import"}, {"text": "📥 IMPORT QUEUE"}],
        ],
        "seek": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/seek"}, {"text": "⏩ SEEK FORWARD (SEC)"}],
            [{"text": "/seekback"}, {"text": "⏪ SEEK BACKWARD (SEC)"}],
        ],
        "loop": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/loop 1-20"}, {"text": "🔂 REPEAT CURRENT SONG"}],
            [{"text": "/loop off"}, {"text": "⏹️ DISABLE LOOP"}],
        ],
        "autoplay": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/autoplay on"}, {"text": "✅ ENABLE AUTOPLAY"}],
            [{"text": "/autoplay off"}, {"text": "❌ DISABLE AUTOPLAY"}],
        ],
        "speed": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/speed"}, {"text": "⚡ SET TEMPO (0.5x - 2.0x)"}],
        ],
        "auth": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/auth"}, {"text": "➕ AUTHORIZE USER"}],
            [{"text": "/unauth"}, {"text": "➖ UNAUTHORIZE USER"}],
            [{"text": "/authusers"}, {"text": "👥 LIST AUTH USERS"}],
        ],
        "ping": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/ping"}, {"text": "📡 CHECK BOT LATENCY"}],
            [{"text": "/help"}, {"text": "📖 OPEN HELP MENU"}],
        ],
        "stats": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/stats"}, {"text": "📊 SHOW SYSTEM STATS"}],
        ],
        "blist": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/blacklist"}, {"text": "🚫 BLACKLIST CHAT/USER"}],
            [{"text": "/unblacklist"}, {"text": "🔓 UNBLACKLIST CHAT/USER"}],
            [{"text": "/blacklisted"}, {"text": "📋 LIST BLACKLISTED"}],
        ],
        "sudo": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/activevc"}, {"text": "🎙️ LIST ACTIVE VCS"}],
            [{"text": "/ac"}, {"text": "📈 ACTIVE VC COUNT"}],
            [{"text": "/broadcast"}, {"text": "📢 GLOBAL BROADCAST"}],
        ],
        "owner": [
            [{"text": "COMMAND"}, {"text": "COMMAND DETAILS"}],
            [{"text": "/owner"}, {"text": "⚙️ OWNER PANEL"}],
            [{"text": "/accounts"}, {"text": "🤖 MANAGE ASSISTANTS"}],
            [{"text": "/restart"}, {"text": "🔄 RESTART BOT"}],
            [{"text": "/clean"}, {"text": "🧹 CLEAN CACHE FILES"}],
        ],
    }

    cells = tables.get(category, tables["menu"])

    return [
        {
            "type": "paragraph",
            "text": f"🎧 ˹ᴍɪᴋᴀꜱᴀ ᴍᴜꜱɪᴄ˼ — {category.upper()} COMMANDS",
        },
        {
            "type": "table",
            "is_compact": True,
            "is_bordered": True,
            "cells": cells,
        },
        {
            "type": "buttons",
            "buttons": [
                {
                    "text": f"💬 Support — {sh} 👥",
                    "url": support_url,
                },
                {
                    "text": f"👑 Owner — {oh}",
                    "url": owner_url,
                },
            ],
        },
    ]
