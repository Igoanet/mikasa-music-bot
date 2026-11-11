# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import asyncio
import logging
import random
from pyrogram import enums

logger = logging.getLogger("bobby")

# 1. Premium Animated Emojis for standard /play loading (randomized rotation, zero text):
# ❤️‍🔥 from VariousAnimations (5436351771125494452)
# 🌕 from ReaperSkullEmoji (5289930954410836372)
# 🍃 from HalloweenTeamEmoji (5253944419870062295)
EMOJI_HEART_FIRE = '<tg-emoji emoji-id="5436351771125494452">❤️‍🔥</tg-emoji>'
EMOJI_MOON = '<tg-emoji emoji-id="5289930954410836372">🌕</tg-emoji>'
EMOJI_LEAF = '<tg-emoji emoji-id="5253944419870062295">🍃</tg-emoji>'

PLAYBACK_EMOJIS = [EMOJI_HEART_FIRE, EMOJI_MOON, EMOJI_LEAF]

# 2. OutlineEmoji set for Replay, Loop, Autoplay (with "Preparing playback..."):
# https://t.me/addemoji/OutlineEmoji
EMOJI_ROBOT = '<tg-emoji emoji-id="5355051922862653659">🤖</tg-emoji>'
EMOJI_INVADER = '<tg-emoji emoji-id="5337037846475720165">👾</tg-emoji>'
EMOJI_GHOST = '<tg-emoji emoji-id="5305388752162539722">👻</tg-emoji>'

OUTLINE_EMOJIS = [EMOJI_ROBOT, EMOJI_INVADER, EMOJI_GHOST]


def get_random_playback_emoji() -> str:
    """Return one of the 3 randomized premium emojis for /play (no text)."""
    return random.choice(PLAYBACK_EMOJIS)


def get_random_outline_emoji() -> str:
    """Return one of the outline emojis."""
    return random.choice(OUTLINE_EMOJIS)


def get_preparing_playback_text() -> str:
    """Preparing playback text strictly for loop, autoplay, or replay."""
    return f"{get_random_outline_emoji()} <b>Preparing playback...</b>"


TEXT_PLAYBACK_PREPARING = get_preparing_playback_text()
TEXT_PREPARING = TEXT_PLAYBACK_PREPARING


class PlaybackLoader:
    """Handles continuous randomized premium emoji rotation during playback preparation.

    - If is_playback is False (standard /play):
      Uses the 3 randomized premium emojis (❤️‍🔥, 🌕, 🍃).
      Strictly NO text. Rotates continuously without repeating consecutively.
    - If is_playback is True (replay / loop / autoplay):
      Uses OutlineEmoji (🤖, 👾, 👻) with 'Preparing playback...' text.
    - Halts immediately when stopped.
    """

    def __init__(self, message, is_playback: bool = False, with_text: bool | None = None):
        self.message = message
        self.stop_event = asyncio.Event()
        self.task = None
        self.is_playback = is_playback
        self.with_text = is_playback if with_text is None else with_text

    def start(self):
        self.task = asyncio.create_task(self._run())
        return self

    async def _run(self):
        try:
            pool = OUTLINE_EMOJIS if self.is_playback else PLAYBACK_EMOJIS
            last_emoji = None

            while not self.stop_event.is_set():
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=0.6)
                    return
                except asyncio.TimeoutError:
                    pass

                if self.stop_event.is_set():
                    return

                candidates = [e for e in pool if e != last_emoji]
                next_emoji = random.choice(candidates)
                last_emoji = next_emoji

                content = (
                    f"{next_emoji} <b>Preparing playback...</b>"
                    if self.with_text
                    else next_emoji
                )
                try:
                    await self.message.edit_text(content, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
        if self.task and not self.task.done():
            self.task.cancel()


class _DummyLoader:
    def stop(self):
        pass
