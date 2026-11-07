import asyncio
import logging
from pyrogram import enums

logger = logging.getLogger("bobby")

LOADING_STAGES = [
    '<tg-emoji emoji-id="5355051922862653659">🤖</tg-emoji>  <b>Preparing playback…</b>',
    '<tg-emoji emoji-id="5305388752162539722">👻</tg-emoji>  <b>Preparing playback…</b>',
    '<tg-emoji emoji-id="5337037846475720165">👾</tg-emoji>  <b>Preparing playback…</b>',
]


class PlaybackLoader:
    """Cycles through animated loading stages (🤖 -> 👻 -> 👾) until playback starts."""

    def __init__(self, message):
        self.message = message
        self.stop_event = asyncio.Event()
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self._run())
        setattr(self.message, "_loader", self)
        return self

    async def _run(self):
        idx = 0
        try:
            # Keep initial '⏳ Preparing playback…' visible for ~1.0s
            await asyncio.sleep(1.0)
            while not self.stop_event.is_set():
                text = LOADING_STAGES[idx % len(LOADING_STAGES)]
                idx += 1
                try:
                    await self.message.edit_text(text, parse_mode=enums.ParseMode.HTML)
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=1.4)
                    break
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass

    def stop(self):
        self.stop_event.set()
        if self.task and not self.task.done():
            self.task.cancel()
