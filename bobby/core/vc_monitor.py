"""Voice Chat participant observer and Telegram raw update handler."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

from pyrogram import Client, raw
from pyrogram.raw.types import (
    Channel,
    ChannelForbidden,
    Chat,
    ChatForbidden,
    GroupCall,
    GroupCallDiscarded,
    GroupCallParticipant,
    InputChannel,
    InputGroupCall,
    InputPeerChannel,
    InputPeerChat,
    PeerChannel,
    PeerChat,
    PeerUser,
    UpdateGroupCall,
    UpdateGroupCallParticipants,
)
from pyrogram.raw.functions.channels import GetFullChannel
from pyrogram.raw.functions.messages import GetFullChat
from pyrogram.raw.functions.phone import GetGroupParticipants, ToggleGroupCallStartSubscription

from bobby.core.vc_monitor_store import VCMonitorStore, get_store

logger = logging.getLogger(__name__)


@dataclass
class PublicIdentity:
    peer_id: int
    name: str
    username: str = ""
    kind: str = "user"


def escaped_notice(identity: PublicIdentity) -> tuple[str, str]:
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
        self._call_to_chat: dict[int, int] = {}
        self._chat_to_call: dict[int, InputGroupCall] = {}
        self._known_participants: dict[int, set[int]] = {}
        self._last_call_poll: dict[int, float] = {}
        self._last_call_resolve: dict[int, float] = {}
        self._poll_task: asyncio.Task | None = None

    def _extract_peer(self, peer: Any) -> tuple[int, str]:
        if isinstance(peer, PeerUser):
            return int(peer.user_id), "user"
        if isinstance(peer, PeerChannel):
            return int(peer.channel_id), "channel"
        if isinstance(peer, PeerChat):
            return int(peer.chat_id), "chat"
        if hasattr(peer, "user_id"):
            return int(peer.user_id), "user"
        if hasattr(peer, "channel_id"):
            return int(peer.channel_id), "channel"
        if hasattr(peer, "chat_id"):
            return int(peer.chat_id), "chat"
        return 0, "unknown"

    def _normalize_chat_id(self, peer_id: int, kind: str) -> int:
        pid = abs(int(peer_id))
        if kind == "channel":
            return -int(f"100{pid}") if pid < 1000000000000 else -pid
        elif kind == "chat":
            return -pid
        return int(peer_id)

    async def _resolve_call_for_chat(self, client: Client, chat_id: int) -> Optional[InputGroupCall]:
        try:
            peer = await client.resolve_peer(chat_id)
        except Exception:
            try:
                chat = await client.get_chat(chat_id)
                peer = await client.resolve_peer(chat.id)
            except Exception as ex:
                logger.debug("Failed to resolve chat %s: %s", chat_id, ex)
                return None

        try:
            call = None
            if isinstance(peer, (InputPeerChannel, InputChannel)):
                full = await client.invoke(
                    GetFullChannel(
                        channel=InputChannel(
                            channel_id=peer.channel_id,
                            access_hash=peer.access_hash,
                        )
                    )
                )
                call = getattr(getattr(full, "full_chat", None), "call", None)
            elif isinstance(peer, InputPeerChat):
                full = await client.invoke(GetFullChat(chat_id=peer.chat_id))
                call = getattr(getattr(full, "full_chat", None), "call", None)

            if call and isinstance(call, InputGroupCall):
                self._chat_to_call[chat_id] = call
                self._call_to_chat[call.id] = chat_id
                try:
                    await client.invoke(ToggleGroupCallStartSubscription(call=call, subscribed=True))
                except Exception:
                    pass
                return call
            else:
                self._chat_to_call.pop(chat_id, None)
                return None
        except Exception as ex:
            logger.debug("GetFull error for %s: %s", chat_id, ex)
            return None

    async def _handle_raw_update(self, client: Client, update: Any, users: dict, chats: dict) -> None:
        # 1. UpdateGroupCall
        if isinstance(update, UpdateGroupCall):
            call_obj = getattr(update, "call", None)
            call_id = getattr(call_obj, "id", None)
            peer = getattr(update, "peer", None)
            if call_id and peer:
                p_id, p_kind = self._extract_peer(peer)
                if p_id:
                    chat_id = self._normalize_chat_id(p_id, p_kind)
                    self._call_to_chat[call_id] = chat_id
                    if hasattr(call_obj, "access_hash"):
                        self._chat_to_call[chat_id] = InputGroupCall(id=call_id, access_hash=call_obj.access_hash)
            elif isinstance(call_obj, GroupCallDiscarded):
                if call_id and call_id in self._call_to_chat:
                    c_id = self._call_to_chat.pop(call_id)
                    self._chat_to_call.pop(c_id, None)
                    self._known_participants.pop(c_id, None)
            return

        # 2. UpdateGroupCallParticipants
        if not isinstance(update, UpdateGroupCallParticipants):
            return

        call = getattr(update, "call", None)
        call_id = getattr(call, "id", None)
        chat_id = self._call_to_chat.get(call_id) if call_id else None

        if not chat_id and chats:
            for c in chats.values():
                cid = getattr(c, "id", None)
                if cid:
                    c_name = type(c).__name__
                    kind = "channel" if c_name in ("Channel", "ChannelForbidden") else "chat"
                    chat_id = self._normalize_chat_id(cid, kind)
                    if call_id:
                        self._call_to_chat[call_id] = chat_id
                    break

        if not chat_id and call_id:
            for cid, c_call in self._chat_to_call.items():
                if getattr(c_call, "id", None) == call_id:
                    chat_id = cid
                    self._call_to_chat[call_id] = cid
                    break

        if not chat_id:
            return

        self.store.remember_chat(chat_id)
        assistant_id = getattr(client, "id", None) or getattr(getattr(client, "me", None), "id", None)

        for p in getattr(update, "participants", []):
            if not isinstance(p, GroupCallParticipant):
                continue

            peer_id, kind = self._extract_peer(getattr(p, "peer", None))
            if not peer_id or peer_id == assistant_id:
                continue

            if getattr(p, "left", False):
                if chat_id in self._known_participants:
                    self._known_participants[chat_id].discard(peer_id)
                continue

            known = self._known_participants.setdefault(chat_id, set())
            if peer_id in known:
                continue

            known.add(peer_id)

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

            if self.store.is_enabled(chat_id):
                self.store.record_event(
                    chat_id=chat_id,
                    user_id=peer_id,
                    name=name,
                    username=username,
                    kind=kind,
                    joined_at=time.time(),
                )
                logger.info("VC Monitor (realtime): recorded join for %s (%d) in chat %s", name, peer_id, chat_id)
                self.store.record_health(
                    chat_id=chat_id,
                    status="active",
                    assistant_id=assistant_id,
                    last_seen=time.time(),
                    detail=f"{name} joined voice chat",
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

    async def _poll_active_calls(self) -> None:
        await asyncio.sleep(4.0)
        while self._running:
            try:
                clients = self.clients_provider()
                if not clients:
                    await asyncio.sleep(2.5)
                    continue

                for c in clients:
                    self.attach_client(c)

                client = clients[0]
                assistant_id = getattr(client, "id", None) or getattr(getattr(client, "me", None), "id", None)

                chat_candidates = []
                try:
                    from bobby import db
                    if hasattr(db, "active_calls") and isinstance(db.active_calls, dict):
                        chat_candidates.extend(list(db.active_calls.keys()))
                except Exception:
                    pass

                for cid in self.store.known_chats(limit=30):
                    if cid not in chat_candidates:
                        chat_candidates.append(cid)

                now = time.time()
                for chat_id in chat_candidates:
                    if not self._running:
                        break
                    if not self.store.is_enabled(chat_id):
                        continue

                    call = self._chat_to_call.get(chat_id)
                    if not call:
                        if now - self._last_call_resolve.get(chat_id, 0.0) < 6.0:
                            continue
                        self._last_call_resolve[chat_id] = now
                        call = await self._resolve_call_for_chat(client, chat_id)

                    if not call:
                        if chat_id in self._known_participants:
                            self._known_participants.pop(chat_id, None)
                        continue

                    if now - self._last_call_poll.get(chat_id, 0.0) < 2.0:
                        continue
                    self._last_call_poll[chat_id] = now

                    try:
                        res = await client.invoke(
                            GetGroupParticipants(
                                call=call,
                                ids=[],
                                sources=[],
                                offset="",
                                limit=100,
                            )
                        )
                        users_map = {u.id: u for u in getattr(res, "users", [])}
                        current_pids: set[int] = set()

                        for p in getattr(res, "participants", []):
                            if getattr(p, "left", False):
                                continue
                            pid, kind = self._extract_peer(getattr(p, "peer", None))
                            if not pid or pid == assistant_id:
                                continue
                            current_pids.add(pid)

                        if chat_id not in self._known_participants:
                            self._known_participants[chat_id] = current_pids
                            self.store.record_health(
                                chat_id=chat_id,
                                status="active",
                                assistant_id=assistant_id,
                                last_seen=time.time(),
                                detail=f"Observing {len(current_pids)} active participant(s)",
                            )
                        else:
                            previous_pids = self._known_participants[chat_id]
                            new_joiners = current_pids - previous_pids

                            for pid in new_joiners:
                                name = "Telegram User"
                                username = ""
                                if pid in users_map:
                                    u = users_map[pid]
                                    first = getattr(u, "first_name", "") or ""
                                    last = getattr(u, "last_name", "") or ""
                                    name = f"{first} {last}".strip() or "Telegram User"
                                    username = getattr(u, "username", "") or ""
                                else:
                                    try:
                                        entity = await client.get_users(pid)
                                        first = getattr(entity, "first_name", "") or ""
                                        last = getattr(entity, "last_name", "") or ""
                                        name = f"{first} {last}".strip() or "Telegram User"
                                        username = getattr(entity, "username", "") or ""
                                    except Exception:
                                        pass

                                self.store.record_event(
                                    chat_id=chat_id,
                                    user_id=pid,
                                    name=name,
                                    username=username,
                                    kind="user",
                                    joined_at=time.time(),
                                )
                                logger.info(
                                    "VC Monitor (polling): detected %s (%d) joined VC in %s",
                                    name, pid, chat_id,
                                )
                                self.store.record_health(
                                    chat_id=chat_id,
                                    status="active",
                                    assistant_id=assistant_id,
                                    last_seen=time.time(),
                                    detail=f"{name} joined VC",
                                )

                            self._known_participants[chat_id] = current_pids

                    except Exception as poll_ex:
                        err_str = str(poll_ex)
                        if any(k in err_str for k in ("GROUPCALL_INVALID", "CALL_NOT_FOUND", "GROUPCALL_JOIN_MISSING", "400")):
                            self._chat_to_call.pop(chat_id, None)
                            self._known_participants.pop(chat_id, None)
                        logger.debug("VC monitor poll error for chat %s: %s", chat_id, poll_ex)

            except asyncio.CancelledError:
                break
            except Exception as loop_ex:
                logger.debug("VC monitor loop error: %s", loop_ex)

            await asyncio.sleep(1.5)

    async def run(self) -> None:
        self._running = True
        clients = self.clients_provider()
        for client in clients:
            self.attach_client(client)
            try:
                async for dialog in client.get_dialogs(limit=100):
                    if dialog.chat and str(dialog.chat.type) in ("ChatType.SUPERGROUP", "ChatType.GROUP"):
                        self.store.remember_chat(dialog.chat.id)
            except Exception as ex:
                logger.debug("pre-seed dialogs error: %s", ex)
        logger.info("VoiceChatMonitor attached to %d assistant client(s)", len(clients))
        self._poll_task = asyncio.create_task(self._poll_active_calls())

    def stop(self) -> None:
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
