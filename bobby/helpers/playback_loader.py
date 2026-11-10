import asyncio
import logging
from pyrogram import enums

logger = logging.getLogger("bobby")

# Premium Animated Emojis from VariousAnimations pack:
# First: ⚡ (5436357131244680475)
# Then: 🌙 (5436296696759859723) (carries forward, never goes back to ⚡)
STAGE_2_EMOJI_FIRST = '<tg-emoji emoji-id="5436357131244680475">⚡️</tg-emoji>'
STAGE_2_EMOJI_STICK = '<tg-emoji emoji-id="5436296696759859723">🌙</tg-emoji>'


class PlaybackLoader:
    """Handles playback preparation animation.

    Step 1: First the ⚡ (premium emoji) shows up.
    Step 2: Transitions to 🌙 (premium emoji).
    Step 3: 🌙 carries forward and stays active until playback starts and
            the player poster + controls are sent simultaneously. It never loops back to ⚡.
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
            # Step 1: Ensure ⚡ is visible first
            if getattr(self.message, "text", "") != STAGE_2_EMOJI_FIRST:
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

            # Step 2: Show 🌙 (premium emoji)
            try:
                await self.message.edit_text(STAGE_2_EMOJI_STICK, parse_mode=enums.ParseMode.HTML)
            except Exception:
                pass

            # Step 3: 🌙 carries forward — it stays on 🌙 and never goes back to ⚡
            await self.stop_event.wait()
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
