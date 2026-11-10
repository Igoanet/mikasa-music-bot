import asyncio
import logging
from pyrogram import enums

logger = logging.getLogger("bobby")

# Step 2 emojis from VariousAnimations pack:
# First ❤️‍🔥 (5436266163837351085), then stick on second ❤️‍🔥 (5436351771125494452)
STAGE_2_EMOJI_FIRST = '<tg-emoji emoji-id="5436266163837351085">❤️‍🔥</tg-emoji>'
STAGE_2_EMOJI_STICK = '<tg-emoji emoji-id="5436351771125494452">❤️‍🔥</tg-emoji>'


class PlaybackLoader:
    """Handles playback preparation animation.

    Step 1: Displays initial message (🔍 Preparing playback...) once (~0.8s).
    Step 2: Disappears initial text and displays the first ❤️‍🔥 from VariousAnimations (~0.8s).
    Step 3: Switches to and sticks on the second ❤️‍🔥 from VariousAnimations until the track begins.
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
            # Step 1: Keep initial text visible for ~0.8s
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.8)
                return
            except asyncio.TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            # Step 2: First VariousAnimations ❤️‍🔥
            try:
                await self.message.edit_text(STAGE_2_EMOJI_FIRST, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=0.8)
                return
            except asyncio.TimeoutError:
                pass

            if self.stop_event.is_set():
                return

            # Step 3: Second VariousAnimations ❤️‍🔥 (sticks here)
            try:
                await self.message.edit_text(STAGE_2_EMOJI_STICK, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

            await self.stop_event.wait()
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
