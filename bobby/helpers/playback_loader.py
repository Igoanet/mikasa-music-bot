import asyncio
import logging
from pyrogram import enums

logger = logging.getLogger("bobby")

# Step 2 emojis from OutlineEmoji (shown one at a time)
STAGE_2_EMOJIS = [
    '<tg-emoji emoji-id="5355051922862653659">🤖</tg-emoji>',
    '<tg-emoji emoji-id="5305388752162539722">👻</tg-emoji>',
    '<tg-emoji emoji-id="5337037846475720165">👾</tg-emoji>',
]


class PlaybackLoader:
    """Handles playback preparation animation.

    Step 1: Displays initial '🔍 Preparing playback…' once.
    Step 2: Disappears Step 1 text and displays the 3 Outline emojis one at a time:
            🤖 -> 👻 -> 👾. If preparation takes time, loops strictly within
            Step 2 emojis and never returns to Step 1.
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
            # Step 1 was sent by /play — keep it visible for ~1.0s
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=1.0)
                return
            except asyncio.TimeoutError:
                pass

            idx = 0
            # Step 2: Loop exclusively through the three emojis one at a time
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
