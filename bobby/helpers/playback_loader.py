import asyncio
import logging
from pyrogram import enums

logger = logging.getLogger("bobby")

# Premium Animated Emojis:
# 🔍 from VariousAnimations (5435907392334215552)
# ❤️‍🔥 from VariousAnimations (5436266163837351085)
# 🌕 from ReaperSkullEmoji (5289930954410836372)
TEXT_PREPARING = '<tg-emoji emoji-id="5435907392334215552">🔍</tg-emoji> <b>Preparing playback...</b>'
EMOJI_HEART_FIRE = '<tg-emoji emoji-id="5436266163837351085">❤️‍🔥</tg-emoji>'
EMOJI_MOON = '<tg-emoji emoji-id="5289930954410836372">🌕</tg-emoji>'


class PlaybackLoader:
    """Handles playback preparation animation.

    Step 1: '<tg-emoji ...>🔍</tg-emoji> <b>Preparing playback...</b>' shows up first (~0.5s).
    Step 2: Transitions to the premium animated ❤️‍🔥 (~0.8s).
    Step 3: Transitions to the premium animated 🌕 (from ReaperSkullEmoji).
    Step 4: 🌕 carries forward continuously (never goes back to ❤️‍🔥) until the
            track starts and the full music poster card with controls is sent.
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
            # Step 1: Ensure initial 'Preparing playback...' is shown for ~0.5s
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.5)
                return
            except asyncio.TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            # Step 2: Show premium animated ❤️‍🔥 (~0.8s)
            try:
                await self.message.edit_text(EMOJI_HEART_FIRE, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.8)
                return
            except asyncio.TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            # Step 3: Show premium animated 🌕 (from ReaperSkullEmoji)
            try:
                await self.message.edit_text(EMOJI_MOON, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

            # Step 4: 🌕 carries forward — stays here and never goes back to ❤️‍🔥
            await self.stop_event.wait()
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
