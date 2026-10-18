"""Mikasa-side VC participant observer.

This plugin never creates a client and never joins a voice chat.  It attaches
one raw-update handler to each assistant already present in ``userbot.clients``
and performs bounded official participant reads for groups that Maki has
advertised through the shared SQLite store.
"""

from __future__ import annotations

from bobby import logger, userbot
from bobby.core.vc_monitor import VoiceChatMonitor
from bobby.core.vc_monitor_store import get_store


monitor: VoiceChatMonitor | None = None


async def on_start(_app) -> None:
    global monitor
    if monitor is not None:
        return
    monitor = VoiceChatMonitor(
        store=get_store(),
        clients_provider=lambda: list(userbot.clients),
    )
    logger.info("VC monitor observer started using existing assistant clients")
    await monitor.run()
