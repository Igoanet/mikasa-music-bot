# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import json
import re
from functools import wraps
from pathlib import Path

from pyrogram import errors

from bobby import db, logger

lang_codes = {
    "ar": "العربية",
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "hi": "हिन्दी",
    "ja": "日本語",
    "my": "မြန်မာဘာသာ",
    "pa": "ਪੰਜਾਬੀ",
    "pt": "Português",
    "ru": "Русский",
    "tr": "Türkçe",
    "zh": "中文"
}

# Mapping of raw unicode emojis to verified Telegram Premium animated custom emoji tags
# Curated exclusively from paneer's specified packs
PREMIUM_EMOJI_MAP = {
    "⚠️": "5904692292324692386",  # Animated Alert (ProtectStatus)
    "❗️": "5893072412924187198",  # Animated Important (ProtectStatus)
    "✅": "5895514131896733546",  # Animated Check (ProtectStatus)
    "❌": "5893163582194978381",  # Animated Cross (ProtectStatus)
    "⏳": "5258113901106580375",  # Animated Hourglass (vector_icons)
    "⌛": "5258113901106580375",  # Animated Hourglass (vector_icons)
    "⏱": "5902050947567194830",  # Animated Clock (ProtectStatus)
    "⏰": "5902050947567194830",  # Animated Clock (ProtectStatus)
    "💾": "5213002459437342368",  # AnimatedActions
    "🎵": "5334665104677941170",  # Animated Music (vector_icons)
    "🎶": "5892966078123872045",  # Animated Notes (ProtectStatus)
    "🎧": "6269555901628159084",  # Animated Headphone (emj_2c260_by_TgEmodziBot)
    "⏸": "5278619986238122736",  # Animated Pause (vector_icons)
    "⏭": "6255624844491100107",  # Animated Next (Rnxtcx Door/Next)
    "🔁": "5292226786229236118",  # Animated Replay (vector_icons)
    "🔄": "5292226786229236118",  # Animated Reload (vector_icons)
    "⏹": "5319109106793986870",  # Animated Stop (AdaptiveStatus)
    "▶️": "5892966078123872045",  # Animated Notes/Music (ProtectStatus)
    "📊": "5895444149699612825",  # Animated Stats (ProtectStatus)
    "📈": "5319164151094849427",  # Animated Ping/Signal (AdaptiveStatus)
    "🗑": "5904542823167824187",  # Animated Trash (ProtectStatus)
    "🛡": "5902016123972358349",  # Animated Shield (ProtectStatus)
    "🤖": "5355051922862653659",  # Animated Bot (OutlineEmoji)
    "⚡": "5893450623449305489",  # Animated Lightning (ProtectStatus)
    "✨": "5893321843149902412",  # Animated Sparkles (ProtectStatus)
    "🔥": "5893185207355315979",  # Animated Fire (ProtectStatus)
    "❤️": "5442678635909621223",  # Animated Heart (OutlineEmoji)
    "⭐": "5893494861612455015",  # Animated Star (ProtectStatus)
    "⭐️": "5893494861612455015",  # Animated Star (ProtectStatus)
    "👥": "5316705578670636235",  # Animated Users (AdaptiveStatus)
    "👤": "5902335789798265487",  # Animated User (ProtectStatus)
    "🔗": "5902449142575141204",  # Animated Link (ProtectStatus)
    "🕊": "5316740183222140641",  # Animated Flying Dove (AdaptiveStatus)
    "🕊️": "5316740183222140641", # Animated Flying Dove (AdaptiveStatus)
    "🔔": "5431374840332302296",  # Animated Bell (vector_icons)
    "🚀": "5372917041193828849",  # Animated Rocket (OutlineEmoji)
    "⚙️": "5893161718179173515",  # Animated Settings (ProtectStatus)
    "📌": "5895440460322706085",  # Animated Pin (ProtectStatus)
    "👑": "5893376775781617954",  # Animated Crown (ProtectStatus)
    "💎": "5264892613630111886",  # Animated Diamond (vector_icons)
}

_EMOJI_REGEX = re.compile("|".join(re.escape(k) for k in sorted(PREMIUM_EMOJI_MAP.keys(), key=len, reverse=True)))


def _format_premium_emojis(text: str) -> str:
    """Transform standard unicode emojis in locale strings to premium tags with clean padding."""
    if not isinstance(text, str):
        return text
    parts = re.split(r'(<tg-emoji[^>]*>.*?</tg-emoji>)', text)
    processed = []
    for part in parts:
        if part.startswith('<tg-emoji'):
            processed.append(part)
        else:
            def _repl(match):
                char = match.group(0)
                eid = PREMIUM_EMOJI_MAP.get(char)
                if not eid:
                    return char
                return f'<tg-emoji emoji-id="{eid}">{char}</tg-emoji>  '
            processed.append(_EMOJI_REGEX.sub(_repl, part))
    res = "".join(processed)
    res = re.sub(r'(</tg-emoji>)\s+', r'\1  ', res)
    return res


class Language:
    """
    Language class for managing multilingual support using JSON language files.
    """

    def __init__(self):
        self.lang_codes = lang_codes
        self.lang_dir = Path(__file__).resolve().parent.parent / "locales"
        self.languages = self.load_files()

    def load_files(self):
        languages = {}
        lang_files = {file.stem: file for file in self.lang_dir.glob("*.json")}
        for lang_code, lang_file in lang_files.items():
            with open(lang_file, "r", encoding="utf-8") as file:
                raw_data = json.load(file)
                processed = {}
                for k, v in raw_data.items():
                    if isinstance(v, str):
                        processed[k] = _format_premium_emojis(v)
                    else:
                        processed[k] = v
                languages[lang_code] = processed
        # English is the complete reference: a string missing from another
        # locale falls back to it instead of raising KeyError in a handler.
        base = languages.get("en", {})
        for lang_code, strings in languages.items():
            if lang_code != "en":
                languages[lang_code] = {**base, **strings}
        logger.info(f"Loaded languages: {', '.join(languages.keys())}")
        return languages

    async def get_lang(self, chat_id: int) -> dict:
        lang_code = await db.get_lang(chat_id)
        return self.languages[lang_code]

    def get_languages(self) -> dict:
        files = {f.stem for f in self.lang_dir.glob("*.json")}
        return {code: self.lang_codes[code] for code in sorted(files)}

    def language(self):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                fallen = next(
                    (
                        arg
                        for arg in args
                        if hasattr(arg, "chat") or hasattr(arg, "message")
                    ),
                    None,
                )

                if not fallen.from_user:
                    return

                if hasattr(fallen, "chat"):
                    chat = fallen.chat
                elif hasattr(fallen, "message"):
                    chat = fallen.message.chat

                if not chat: return

                if chat.id in db.blacklisted:
                    logger.info(f"Chat {chat.id} is blacklisted, leaving...")
                    return await chat.leave()

                lang_code = await db.get_lang(chat.id)
                fallen.lang = self.languages[lang_code]
                try:
                    return await func(*args, **kwargs)
                except (errors.FloodWait, errors.SlowmodeWait):
                    return
                except (
                    errors.ChannelInvalid, errors.ChannelPrivate,
                    errors.MessageIdInvalid, errors.MessageNotModified,
                ):
                    return
                except (
                    errors.Forbidden, errors.exceptions.Forbidden,
                    errors.ChatWriteForbidden, errors.exceptions.ChatWriteForbidden,
                ):
                    return

            return wrapper

        return decorator
