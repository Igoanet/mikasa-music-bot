import asyncio
import logging
from pyrogram import enums

logger = logging.getLogger("bobby")

# Step 2 emojis: ⚡️ | 🤖 | 👻 | 👾 (shown one at a time in loop)
STAGE_2_EMOJIS = [
    '<tg-emoji emoji-id="5893450623449305489">⚡️</tg-emoji>',
    '<tg-emoji emoji-id="5355051922862653659">🤖</tg-emoji>',
    '<tg-emoji emoji-id="5305388752162539722">👻</tg-emoji>',
    '<tg-emoji emoji-id="5337037846475720165">👾</tg-emoji>',
]


class PlaybackLoader:
    """Handles playback preparation animation.

    Step 1: Displays initial message (0: 🍀 Next up or 1: 🔍 Preparing playback) once (~1.0s).
    Step 2: Disappears initial text and displays the stage 2 emojis one at a time:
            ⚡️ -> 🤖 -> 👻 -> 👾. If preparation takes time, loops strictly within
            Step 2 emojis and never returns to the initial message.
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
            # Keep initial text visible for ~1.0s
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=1.0)
                return
            except asyncio.TimeoutError:
                pass

            idx = 0
            # Step 2: Loop exclusively through the stage 2 emojis one at a time
            while not self.stop_event.is_set():
                text = STAGE_2_EMOJIS[idx % len(STAGE_2_EMOJIS)]
                idx += 1
                try:
                    await self.message.edit_text(text, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=1.0)
                    break
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
