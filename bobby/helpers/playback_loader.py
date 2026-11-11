import asyncio
import logging
import random
from pyrogram import enums

logger = logging.getLogger("bobby")

# Premium Animated Emojis:
# 🔍 from VariousAnimations (5435907392334215552)
# ❤️‍🔥 from VariousAnimations (5436351771125494452)
# 🌕 from ReaperSkullEmoji (5289930954410836372)
# 🍃 from HalloweenTeamEmoji (5253944419870062295)
# 🤖👾👻 from OutlineEmoji (5355051922862653659, 5337037846475720165, 5305388752162539722)

TEXT_PREPARING = '<tg-emoji emoji-id="5435907392334215552">🔍</tg-emoji> <b>Preparing playback...</b>'

TEXT_PLAYBACK_PREPARING = (
    '<tg-emoji emoji-id="5355051922862653659">🤖</tg-emoji> '
    '<b>Preparing playback...</b>'
)

EMOJI_HEART_FIRE = '<tg-emoji emoji-id="5436351771125494452">❤️‍🔥</tg-emoji>'
EMOJI_MOON = '<tg-emoji emoji-id="5289930954410836372">🌕</tg-emoji>'
EMOJI_LEAF = '<tg-emoji emoji-id="5253944419870062295">🍃</tg-emoji>'

PLAYBACK_EMOJIS = [EMOJI_HEART_FIRE, EMOJI_MOON, EMOJI_LEAF]

EMOJI_ROBOT = '<tg-emoji emoji-id="5355051922862653659">🤖</tg-emoji>'
EMOJI_INVADER = '<tg-emoji emoji-id="5337037846475720165">👾</tg-emoji>'
EMOJI_GHOST = '<tg-emoji emoji-id="5305388752162539722">👻</tg-emoji>'

PLAYBACK_OUTLINE_EMOJIS = [EMOJI_ROBOT, EMOJI_INVADER, EMOJI_GHOST]


class PlaybackLoader:
    """Handles continuous randomized premium emoji rotation during playback preparation.

    - Continuously rotates through premium emojis without repeating the same emoji twice consecutively.
    - Standard playback rotates: ❤️‍🔥, 🌕, 🍃.
    - Replay/button playback rotates: 🤖, 👾, 👻 (OutlineEmoji).
    - Speed priority: the instant music connects, the loader halts immediately and releases the poster.
    """

    def __init__(self, message, is_playback: bool = False):
        self.message = message
        self.stop_event = asyncio.Event()
        self.task = None
        self.is_playback = is_playback

    def start(self):
        self.task = asyncio.create_task(self._run())
        setattr(self.message, "_loader", self)
        return self

    async def _run(self):
        try:
            pool = PLAYBACK_OUTLINE_EMOJIS if self.is_playback else PLAYBACK_EMOJIS

            # Initial preparing message shown for ~0.6s
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.6)
                return
            except asyncio.TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            last_emoji = None
            # Keep rotating continuously until music is loaded; never repeat the same emoji consecutively
            while not self.stop_event.is_set():
                candidates = [e for e in pool if e != last_emoji]
                next_emoji = random.choice(candidates)
                last_emoji = next_emoji

                try:
                    await self.message.edit_text(next_emoji, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass

                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=0.7)
                    return
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
