# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Centralized Telegram Premium Custom Emojis for Mikasa Bot.

Selected exclusively from paneer's curated packs:
- OutlineEmoji
- ProtectStatus
- vector_icons_by_fStikBot
- AdaptiveStatus
- Statausproxtara_by_fStikBot
- Rnxtcx_by_fStikBot
"""

from typing import Union


def tg_emoji(emoji_id: Union[str, int], fallback: str) -> str:
    """Format an emoji tag with fallback for reliable Telegram message delivery."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


# Verified Telegram Premium custom emoji IDs from paneer's packs
EMOJI_IDS = {
    # Audio / Music
    "headphone": "6246810588052199536",   # 🎧 Statausproxtara
    "music": "6258277974638858828",       # 🎵 Rnxtcx
    "disc": "5258234027046883085",        # 💿 / 📀 vector_icons
    "notes": "5892966078123872045",       # 🎶 ProtectStatus
    "radio": "6255588285729476492",       # 📻 / 🔊 Rnxtcx
    "mic": "6257757136839774012",         # 🎙 Rnxtcx
    "wave": "6258258557091713178",        # 🎚 / 📊 Rnxtcx

    # User & Identity
    "user": "6257770403993750789",        # 👤 Rnxtcx
    "tag": "6257831293745106488",         # 🔖 / 🔗 Rnxtcx
    "id": "6258209182147678286",          # 🆔 Rnxtcx

    # Time & Duration
    "clock": "6258066331535412617",       # ⏱ / ⏲ Rnxtcx
    "duration": "5258113901106580375",    # ⏳ / ⌛ vector_icons

    # Branding, Status & Vibe
    "crown": "5893376775781617954",       # 👑 / 🏆 ProtectStatus
    "diamond": "5264892613630111886",     # 💎 vector_icons
    "fire": "5893185207355315979",        # 🔥 ProtectStatus
    "heart": "6257924700693860385",       # ❤️ Rnxtcx
    "star": "6257871224056057188",        # ⭐ Rnxtcx
    "sparkles": "5893321843149902412",    # ✨ ProtectStatus
    "lightning": "5893450623449305489",   # ⚡ ProtectStatus
    "bot": "6257916192363646612",         # 🤖 Rnxtcx
    "alert": "6255911043931835951",       # ⚠️ / ❗️ Rnxtcx
    "stats": "6258258557091713178",       # 📊 Rnxtcx
    "ping": "6257986788741090772",        # 📈 Rnxtcx

    # Controls & UI
    "play": "5316567469702264826",        # ▶️ AdaptiveStatus
    "pause": "6258105965493620367",       # ⏸ / 🔇 Rnxtcx
    "stop": "5319109106793986870",        # ⏹ AdaptiveStatus
    "next": "6258014727503351047",        # ⏭ / ⏩ Rnxtcx
    "replay": "6258260768999870546",      # 🔄 Rnxtcx
    "cross": "5893163582194978381",       # ❌ ProtectStatus
    "check": "5895514131896733546",       # ✅ ProtectStatus
    "search": "6255612376201039503",      # 🔍 Rnxtcx
    "trash": "6257915195931234169",       # 🗑 Rnxtcx
    "lock": "6258239736545021832",        # 🔒 Rnxtcx
    "key": "6257963359694491109",         # 🔑 Rnxtcx
    "shield": "6258029450651242413",      # 🛡 Rnxtcx
}

# Pre-formatted HTML tags
HEADPHONE = tg_emoji(EMOJI_IDS["headphone"], "🎧")
MUSIC = tg_emoji(EMOJI_IDS["music"], "🎵")
DISC = tg_emoji(EMOJI_IDS["disc"], "💿")
NOTES = tg_emoji(EMOJI_IDS["notes"], "🎶")
RADIO = tg_emoji(EMOJI_IDS["radio"], "📻")
MIC = tg_emoji(EMOJI_IDS["mic"], "🎙️")
WAVE = tg_emoji(EMOJI_IDS["wave"], "🎚️")

USER = tg_emoji(EMOJI_IDS["user"], "👤")
TAG = tg_emoji(EMOJI_IDS["tag"], "🔖")
ID = tg_emoji(EMOJI_IDS["id"], "🆔")

CLOCK = tg_emoji(EMOJI_IDS["clock"], "⏱️")
DURATION = tg_emoji(EMOJI_IDS["duration"], "⏳")

CROWN = tg_emoji(EMOJI_IDS["crown"], "👑")
DIAMOND = tg_emoji(EMOJI_IDS["diamond"], "💎")
FIRE = tg_emoji(EMOJI_IDS["fire"], "🔥")
HEART = tg_emoji(EMOJI_IDS["heart"], "❤️")
STAR = tg_emoji(EMOJI_IDS["star"], "⭐")
SPARKLES = tg_emoji(EMOJI_IDS["sparkles"], "✨")
LIGHTNING = tg_emoji(EMOJI_IDS["lightning"], "⚡")
BOT = tg_emoji(EMOJI_IDS["bot"], "🤖")
ALERT = tg_emoji(EMOJI_IDS["alert"], "⚠️")
STATS = tg_emoji(EMOJI_IDS["stats"], "📊")
PING = tg_emoji(EMOJI_IDS["ping"], "📈")

PLAY = tg_emoji(EMOJI_IDS["play"], "▶️")
PAUSE = tg_emoji(EMOJI_IDS["pause"], "⏸️")
STOP = tg_emoji(EMOJI_IDS["stop"], "⏹")
NEXT = tg_emoji(EMOJI_IDS["next"], "⏭️")
REPLAY = tg_emoji(EMOJI_IDS["replay"], "🔄")
CROSS = tg_emoji(EMOJI_IDS["cross"], "❌")
CHECK = tg_emoji(EMOJI_IDS["check"], "✅")
SEARCH = tg_emoji(EMOJI_IDS["search"], "🔍")
TRASH = tg_emoji(EMOJI_IDS["trash"], "🗑️")
LOCK = tg_emoji(EMOJI_IDS["lock"], "🔒")
KEY = tg_emoji(EMOJI_IDS["key"], "🔑")
SHIELD = tg_emoji(EMOJI_IDS["shield"], "🛡️")
