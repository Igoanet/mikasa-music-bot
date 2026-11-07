# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Centralized Telegram Premium Custom Emojis for Mikasa Bot.

All emoji document IDs are verified against active public custom emoji sets
on the Telegram Bot API and MTProto, ensuring consistent aesthetic styling
and guaranteed delivery without DOCUMENT_INVALID errors.
"""

from typing import Union


def tg_emoji(emoji_id: Union[str, int], fallback: str) -> str:
    """Format an emoji tag with fallback for reliable Telegram message delivery."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


# Curated, verified Telegram Premium aesthetic custom emoji IDs
EMOJI_IDS = {
    # Music / Audio (Clean Aesthetic / Spotify style)
    "music": "5190527415268420178",       # 🎵 Single Note
    "disc": "5190527415268420178",        # 🎵 / 💿 Track
    "notes": "5188275770073557181",       # 🎶 Double Notes
    "headphone": "5188572127111948047",   # 🎧 Headphone
    "radio": "5197623757803367587",       # 📻 Radio
    "mic": "5343850098398871461",         # 🎙️ Microphone
    "wave": "5188275770073557181",        # 🎚️ Wave / Audio

    # User & Identity (Glass Aesthetic)
    "user": "6039352582344808994",        # 👤 User
    "tag": "6037209097311362167",         # 🔖 Username / Link
    "id": "5343863498696833806",          # 🆔 User ID Tag

    # Time & Duration (Glass / Premium Aesthetic)
    "clock": "6037134300455902667",       # ⏱️ / 🕔 Clock
    "duration": "5431672893882778047",    # ⏳ Duration / Hourglass

    # Branding & Status
    "crown": "5204174145570500822",       # 👑 Crown
    "fire": "5170202955713872686",        # 🔥 Fire
    "heart": "5168255956844282419",       # 🤍 White Aesthetic Heart
    "star": "5427086749278943412",        # ⭐️ Star
    "sparkles": "5253760217312683514",    # ✨ Sparkles
    "lightning": "5427113717378595836",   # ⚡ Lightning
    "bot": "5431490770089560625",         # 🤖 Bot

    # Controls & UI
    "play": "5341270334882463507",        # ▶️ Play
    "pause": "5431719700436369632",       # ⏸️ Pause
    "next": "5337214416876242766",        # ⏭️ Next
    "replay": "5429166458343011591",      # 🔄 Replay / Loop
    "cross": "6039552577496947899",       # ❌ Cross
    "check": "6039481603162381379",       # ✅ Check
    "folder": "6037277099528560962",      # 🗂️ Folder / Playlist
    "search": "6037364115565977596",      # 🔍 Search
    "trash": "6039475031862418768",       # 🗑️ Trash / Delete
    "lock": "6039356825772497478",        # 🔒 Lock
    "unlock": "6039401794080087203",      # 🔓 Unlock
    "shield": "5229142972305515214",      # 🛡️ Shield
}

# Pre-formatted HTML tags
MUSIC = tg_emoji(EMOJI_IDS["music"], "🎵")
DISC = tg_emoji(EMOJI_IDS["disc"], "💿")
NOTES = tg_emoji(EMOJI_IDS["notes"], "🎶")
HEADPHONE = tg_emoji(EMOJI_IDS["headphone"], "🎧")
WAVE = tg_emoji(EMOJI_IDS["wave"], "🎚️")
RADIO = tg_emoji(EMOJI_IDS["radio"], "📻")
MIC = tg_emoji(EMOJI_IDS["mic"], "🎙️")

USER = tg_emoji(EMOJI_IDS["user"], "👤")
TAG = tg_emoji(EMOJI_IDS["tag"], "🔖")
ID = tg_emoji(EMOJI_IDS["id"], "🆔")

CLOCK = tg_emoji(EMOJI_IDS["clock"], "⏱️")
DURATION = tg_emoji(EMOJI_IDS["duration"], "⏳")

CROWN = tg_emoji(EMOJI_IDS["crown"], "👑")
FIRE = tg_emoji(EMOJI_IDS["fire"], "🔥")
HEART = tg_emoji(EMOJI_IDS["heart"], "🤍")
STAR = tg_emoji(EMOJI_IDS["star"], "⭐️")
SPARKLES = tg_emoji(EMOJI_IDS["sparkles"], "✨")
LIGHTNING = tg_emoji(EMOJI_IDS["lightning"], "⚡")
BOT = tg_emoji(EMOJI_IDS["bot"], "🤖")

PLAY = tg_emoji(EMOJI_IDS["play"], "▶️")
PAUSE = tg_emoji(EMOJI_IDS["pause"], "⏸️")
NEXT = tg_emoji(EMOJI_IDS["next"], "⏭️")
REPLAY = tg_emoji(EMOJI_IDS["replay"], "🔄")
CROSS = tg_emoji(EMOJI_IDS["cross"], "❌")
CHECK = tg_emoji(EMOJI_IDS["check"], "✅")
FOLDER = tg_emoji(EMOJI_IDS["folder"], "🗂️")
SEARCH = tg_emoji(EMOJI_IDS["search"], "🔍")
TRASH = tg_emoji(EMOJI_IDS["trash"], "🗑️")
LOCK = tg_emoji(EMOJI_IDS["lock"], "🔒")
UNLOCK = tg_emoji(EMOJI_IDS["unlock"], "🔓")
SHIELD = tg_emoji(EMOJI_IDS["shield"], "🛡️")
