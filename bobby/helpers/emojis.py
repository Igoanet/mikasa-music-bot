# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Centralized Telegram Premium Custom Emojis for Mikasa Bot."""

def tg_emoji(emoji_id: str | int, fallback: str) -> str:
    """Format an HTML custom premium emoji tag with fallback."""
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'

# Curated, verified Telegram Premium animated/custom emoji IDs
EMOJI_IDS = {
    "music": "5456140656643778548",     # 🎵
    "disc": "5271965913665510227",      # 💿
    "headphone": "5467770857777636735", # 🎧
    "wave": "5438647074697693754",      # 🎚️
    "radio": "5294117873442037255",     # 📡
    "user": "5451703669652296766",      # 👤
    "tag": "5471952986970267163",       # 🔖
    "id": "5467439506649727506",        # 🆔
    "clock": "5451996504289025178",     # ⏱️
    "play": "5472164871950836470",      # ▶️
    "pause": "5472097746192182068",     # ⏸️
    "next": "5472164871950836471",      # ⏭️
    "replay": "5447183459486379525",    # 🔄
    "cross": "5447183459486379525",     # ❌
    "star": "5471952986970267163",      # ⭐
    "rocket": "5312536423174695369",    # 🚀
    "phone": "5294177943033741467",     # 📱
    "channel": "5294117873442037255",   # 📢
    "heart": "5350725211463361390",     # ❤️
    "fire": "5336904367482085285",      # 🔥
}

# Pre-formatted HTML tags
MUSIC = tg_emoji(EMOJI_IDS["music"], "🎵")
DISC = tg_emoji(EMOJI_IDS["disc"], "💿")
HEADPHONE = tg_emoji(EMOJI_IDS["headphone"], "🎧")
WAVE = tg_emoji(EMOJI_IDS["wave"], "🎚️")
RADIO = tg_emoji(EMOJI_IDS["radio"], "📡")
USER = tg_emoji(EMOJI_IDS["user"], "👤")
TAG = tg_emoji(EMOJI_IDS["tag"], "🔖")
ID = tg_emoji(EMOJI_IDS["id"], "🆔")
CLOCK = tg_emoji(EMOJI_IDS["clock"], "⏱️")
PLAY = tg_emoji(EMOJI_IDS["play"], "▶️")
PAUSE = tg_emoji(EMOJI_IDS["pause"], "⏸️")
NEXT = tg_emoji(EMOJI_IDS["next"], "⏭️")
REPLAY = tg_emoji(EMOJI_IDS["replay"], "🔄")
CROSS = tg_emoji(EMOJI_IDS["cross"], "❌")
STAR = tg_emoji(EMOJI_IDS["star"], "⭐")
ROCKET = tg_emoji(EMOJI_IDS["rocket"], "🚀")
PHONE = tg_emoji(EMOJI_IDS["phone"], "📱")
CHANNEL = tg_emoji(EMOJI_IDS["channel"], "📢")
HEART = tg_emoji(EMOJI_IDS["heart"], "❤️")
FIRE = tg_emoji(EMOJI_IDS["fire"], "🔥")
