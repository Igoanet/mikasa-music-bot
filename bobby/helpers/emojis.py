# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Centralized Telegram Premium Animated Custom Emojis for Mikasa Bot.

Selected exclusively from paneer's curated packs with priority for animated icons:
- OutlineEmoji (100% animated)
- ProtectStatus (100% animated)
- vector_icons_by_fStikBot (100% animated)
- AdaptiveStatus (100% animated)
- Statausproxtara_by_fStikBot (animated audio/status)
- Rnxtcx_by_fStikBot (fallback icons)
"""

from typing import Union


def tg_emoji(emoji_id: Union[str, int], fallback: str) -> str:
    """Format an emoji tag with fallback for reliable Telegram message delivery."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


# Verified Telegram Premium animated custom emoji IDs from paneer's packs
EMOJI_IDS = {
    # Audio & Music (Animated)
    "headphone": "6246810588052199536",   # 🎧 Statausproxtara (Animated)
    "music": "5334665104677941170",       # 🎵 vector_icons (Animated)
    "disc": "5258234027046883085",        # 📀 vector_icons (Animated)
    "notes": "5892966078123872045",       # 🎶 ProtectStatus (Animated)
    "radio": "6246810588052199536",       # 🎧 Statausproxtara (Animated)
    "mic": "6246851227032753502",         # 🎙 Statausproxtara (Animated)
    "wave": "5895444149699612825",        # 📊 ProtectStatus (Animated)

    # User & Identity (Animated)
    "user": "5902335789798265487",        # 👤 ProtectStatus (Animated)
    "users": "5316705578670636235",       # 👥 AdaptiveStatus (Animated)
    "tag": "5902449142575141204",         # 🔗 ProtectStatus (Animated)
    "id": "5902449142575141204",          # 🔗 ProtectStatus (Animated)

    # Time & Duration (Animated)
    "clock": "5902050947567194830",       # ⏰ ProtectStatus (Animated)
    "duration": "5258113901106580375",    # ⌛ vector_icons (Animated)

    # Aesthetic, Status & Vibe (Animated)
    "sword": "5453991094435997597",       # ⚔️ vector_icons (Animated)
    "dove": "5316740183222140641",        # 🕊️ AdaptiveStatus (Animated Flying Bird)
    "crown": "5893376775781617954",       # 👑 ProtectStatus (Animated)
    "diamond": "5264892613630111886",     # 💎 vector_icons (Animated)
    "fire": "5893185207355315979",        # 🔥 ProtectStatus (Animated)
    "heart": "5442678635909621223",       # ❤️ OutlineEmoji (Animated)
    "star": "5893494861612455015",        # ⭐ ProtectStatus (Animated)
    "sparkles": "5893321843149902412",    # ✨ ProtectStatus (Animated)
    "lightning": "5893450623449305489",   # ⚡ ProtectStatus (Animated)
    "bot": "5355051922862653659",         # 🤖 OutlineEmoji (Animated)
    "alert": "5904692292324692386",       # ⚠️ ProtectStatus (Animated)
    "warning": "5893072412924187198",     # ❗️ ProtectStatus (Animated)
    "stats": "5895444149699612825",       # 📊 ProtectStatus (Animated)
    "ping": "5319164151094849427",        # 📶 AdaptiveStatus (Animated)
    "rocket": "5372917041193828849",      # 🚀 OutlineEmoji (Animated)
    "bell": "5431374840332302296",        # 🔔 vector_icons (Animated)
    "gear": "5893161718179173515",        # ⚙️ ProtectStatus (Animated)
    "pin": "5895440460322706085",         # 📌 ProtectStatus (Animated)

    # Controls & UI (Animated)
    "play": "5316567469702264826",        # ▶️ AdaptiveStatus (Animated)
    "pause": "5278619986238122736",       # 🔇 vector_icons (Animated)
    "stop": "5319109106793986870",        # ⏹ AdaptiveStatus (Animated)
    "next": "5316567469702264826",        # ▶️ AdaptiveStatus (Animated)
    "replay": "5292226786229236118",      # 🔄 vector_icons (Animated)
    "cross": "5893163582194978381",       # ❌ ProtectStatus (Animated)
    "check": "5895514131896733546",       # ✅ ProtectStatus (Animated)
    "trash": "5904542823167824187",       # 🗑 ProtectStatus (Animated)
    "shield": "5902016123972358349",      # 🛡 ProtectStatus (Animated)
    "search": "6255612376201039503",      # 🔍 Rnxtcx
    "lock": "6258239736545021832",        # 🔒 Rnxtcx
    "key": "6257963359694491109",         # 🔑 Rnxtcx
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
USERS = tg_emoji(EMOJI_IDS["users"], "👥")
TAG = tg_emoji(EMOJI_IDS["tag"], "🔖")
ID = tg_emoji(EMOJI_IDS["id"], "🆔")

CLOCK = tg_emoji(EMOJI_IDS["clock"], "⏱️")
DURATION = tg_emoji(EMOJI_IDS["duration"], "⏳")

SWORD = tg_emoji(EMOJI_IDS["sword"], "⚔️")
DOVE = tg_emoji(EMOJI_IDS["dove"], "🕊️")
CROWN = tg_emoji(EMOJI_IDS["crown"], "👑")
DIAMOND = tg_emoji(EMOJI_IDS["diamond"], "💎")
FIRE = tg_emoji(EMOJI_IDS["fire"], "🔥")
HEART = tg_emoji(EMOJI_IDS["heart"], "❤️")
STAR = tg_emoji(EMOJI_IDS["star"], "⭐")
SPARKLES = tg_emoji(EMOJI_IDS["sparkles"], "✨")
LIGHTNING = tg_emoji(EMOJI_IDS["lightning"], "⚡")
BOT = tg_emoji(EMOJI_IDS["bot"], "🤖")
ALERT = tg_emoji(EMOJI_IDS["alert"], "⚠️")
WARNING = tg_emoji(EMOJI_IDS["warning"], "❗️")
STATS = tg_emoji(EMOJI_IDS["stats"], "📊")
PING = tg_emoji(EMOJI_IDS["ping"], "📈")
ROCKET = tg_emoji(EMOJI_IDS["rocket"], "🚀")
BELL = tg_emoji(EMOJI_IDS["bell"], "🔔")
GEAR = tg_emoji(EMOJI_IDS["gear"], "⚙️")
PIN = tg_emoji(EMOJI_IDS["pin"], "📌")

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
