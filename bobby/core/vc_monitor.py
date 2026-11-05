"""Voice Chat participant observer and Telegram raw update handler."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from pyrogram import Client
from pyrogram.raw.types import (
    GroupCallParticipant,
    PeerChannel,
    PeerChat,
    PeerUser,
    UpdateGroupCallParticipants,
)

from bobby.core.vc_monitor_store import VCMonitorStore, get_store

logger = logging.getLogger(__name__)


@dataclass
class PublicIdentity:
    peer_id: int
    name: str
    username: str = ""
    kind: str = "user"


def escaped_notice(identity: PublicIdentity) -> str:
    name = html.escape(identity.name[:256], quote=True)
    username = html.escape(identity.username[:64], quote=True) if identity.username else ""
    return name, username


class VoiceChatMonitor:
    def __init__(
        self,
        store: VCMonitorStore | None = None,
        clients_provider: Callable[[], List[Client]] | None = None,
    ) -> None:
        self.store = store or get_store()
        self.clients_provider = clients_provider or (lambda: [])
        self._running = False
        self._attached_clients: set[int] = set()

    def _extract_peer(self, peer: Any) -> tuple[int, str]:
        if isinstance(peer, PeerUser):
            return int(peer.user_id), "user"
        if isinstance(peer, PeerChannel):
            return int(peer.channel_id), "channel"
        if isinstance(peer, PeerChat):
            return int(peer.chat_id), "chat"
        return 0, "unknown"

    async def _handle_raw_update(self, client: Client, update: Any, users: dict, chats: dict) -> None:
        if not isinstance(update, UpdateGroupCallParticipants):
            return

        call = getattr(update, "call", None)
        chat_id = None
        if call is not None:
            # call may reference an id
            pass

        for p in getattr(update, "participants", []):
            if not isinstance(p, GroupCallParticipant):
                continue

            # check if participant just joined
            just_joined = getattr(p, "just_joined", False)
            left = getattr(p, "left", False)
            if left or not just_joined:
                continue

            peer_id, kind = self._extract_peer(getattr(p, "peer", None))
            if not peer_id:
                continue

            name = "Telegram User"
            username = ""

            if kind == "user" and peer_id in users:
                u = users[peer_id]
                first = getattr(u, "first_name", "") or ""
                last = getattr(u, "last_name", "") or ""
                name = f"{first} {last}".strip() or "Telegram User"
                username = getattr(u, "username", "") or ""
            elif kind in {"channel", "chat"} and peer_id in chats:
                c = chats[peer_id]
                name = getattr(c, "title", "") or "Chat"
                username = getattr(c, "username", "") or ""
            else:
                try:
                    entity = await client.get_users(peer_id)
                    first = getattr(entity, "first_name", "") or ""
                    last = getattr(entity, "last_name", "") or ""
                    name = f"{first} {last}".strip() or "Telegram User"
                    username = getattr(entity, "username", "") or ""
                except Exception:
                    pass

            chat_ids = set()
            for c in (chats or {}).values():
                cid = getattr(c, "id", None)
                if cid:
                    c_name = type(c).__name__
                    if c_name in ("Channel", "ChannelForbidden"):
                        full_id = -int(f"100{abs(int(cid))}") if abs(int(cid)) < 1000000000000 else -abs(int(cid))
                    else:
                        full_id = -abs(int(cid))
                    chat_ids.add(full_id)
                    self.store.remember_chat(full_id)

            target_chats = list(chat_ids) if chat_ids else self.store.known_chats(limit=100)
            for c_id in target_chats:
                if self.store.is_enabled(c_id):
                    self.store.record_event(
                        chat_id=c_id,
                        user_id=peer_id,
                        name=name,
                        username=username,
                        kind=kind,
                        joined_at=time.time(),
                    )
                    self.store.record_health(
                        chat_id=c_id,
                        status="active",
                        assistant_id=getattr(client, "id", None),
                        last_seen=time.time(),
                        detail="Participant joined voice chat",
                    )

    def attach_client(self, client: Client) -> None:
        c_id = id(client)
        if c_id in self._attached_clients:
            return
        self._attached_clients.add(c_id)

        @client.on_raw_update()
        async def _raw_update_handler(c: Client, update: Any, users: dict, chats: dict):
            try:
                await self._handle_raw_update(c, update, users, chats)
            except Exception as ex:
                logger.debug("VC monitor raw update error: %s", ex)

    async def run(self) -> None:
        self._running = True
        for client in self.clients_provider():
            try:
                async for dialog in client.get_dialogs(limit=100):
                    if dialog.chat and str(dialog.chat.type) in ("ChatType.SUPERGROUP", "ChatType.GROUP"):
                        self.store.remember_chat(dialog.chat.id)
            except Exception as ex:
                logger.debug("pre-seed dialogs error: %s", ex)
        clients = self.clients_provider()
        for client in clients:
            self.attach_client(client)
        logger.info("VoiceChatMonitor attached to %d assistant client(s)", len(clients))
