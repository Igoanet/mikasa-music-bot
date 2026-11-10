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
    '<tg-emoji emoji-id="5355051922862653659">🤖</tg-emoji>'
    '<tg-emoji emoji-id="5337037846475720165">👾</tg-emoji>'
    '<tg-emoji emoji-id="5305388752162539722">👻</tg-emoji> '
    '<b>Preparing playback...</b>'
)

EMOJI_HEART_FIRE = '<tg-emoji emoji-id="5436351771125494452">❤️‍🔥</tg-emoji>'
EMOJI_MOON = '<tg-emoji emoji-id="5289930954410836372">🌕</tg-emoji>'
EMOJI_LEAF = '<tg-emoji emoji-id="5253944419870062295">🍃</tg-emoji>'

PLAYBACK_EMOJIS = [EMOJI_HEART_FIRE, EMOJI_MOON, EMOJI_LEAF]


class PlaybackLoader:
    """Handles playback preparation animation with randomized 3-emoji sequence.

    - The 3 emojis (❤️‍🔥, 🌕, 🍃) are randomized on every play request.
    - Animation transitions: initial text -> emoji[0] -> emoji[1] -> emoji[2].
    - Focuses strictly on speed: if music loads at any point, the loader stops
      immediately and releases the poster card without waiting to finish the cycle.
    """

    def __init__(self, message):
        self.message = message
        self.stop_event = asyncio.Event()
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self._run())
        setattr(self.message, "_loader", self)
        return self

    async def _run(self):
        try:
            seq = list(PLAYBACK_EMOJIS)
            random.shuffle(seq)

            # Step 0: Initial text shown for ~0.4s
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.4)
                return
            except asyncio.TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            # Step 1: First randomized emoji
            try:
                await self.message.edit_text(seq[0], parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.7)
                return
            except asyncio.TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            # Step 2: Second randomized emoji
            try:
                await self.message.edit_text(seq[1], parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.7)
                return
            except asyncio.TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            # Step 3: Third randomized emoji (sticks and carries forward until poster arrives)
            try:
                await self.message.edit_text(seq[2], parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

            await self.stop_event.wait()
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
