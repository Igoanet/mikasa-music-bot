"""Mikasa-side VC participant observer and notification dispatcher.

Mikasa observes voice chat participant updates across assistant accounts and
directly delivers join notices to the group chat, automatically deleting them
after 5 seconds.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import time
from datetime import datetime, timezone

from pyrogram import enums, filters, types
from pyrogram.errors import FloodWait

from bobby import app, logger, userbot
from bobby.core.vc_monitor import PublicIdentity, VoiceChatMonitor
from bobby.core.vc_monitor_store import VCMonitorStore, get_store

store: VCMonitorStore = get_store()
monitor: VoiceChatMonitor | None = None
_consumer_task: asyncio.Task | None = None

_NOTICE_DELETE = max(0.0, float(os.getenv("VC_NOTICE_DELETE", "5")))


def _join_notice(identity: PublicIdentity) -> str:
    """Format voice-chat join notice, one detail per line with 5s autodelete."""
    name = html.escape(str(getattr(identity, "name", "") or "user")[:256], quote=True)
    username = getattr(identity, "username", None)
    try:
        peer = int(getattr(identity, "peer_id", 0))
    except (TypeError, ValueError):
        peer = 0
    kind = getattr(identity, "kind", "user")
    if kind == "channel":
        public_id, heading = str(-1000000000000 - abs(peer)), "🎧 <b>Channel in VC</b>"
    elif kind == "chat":
        public_id, heading = str(-abs(peer)), "🎧 <b>Chat in VC</b>"
    else:
        public_id, heading = str(peer), "🎧 <b>Joined VC</b>"
    now = datetime.now(timezone.utc).astimezone()
    lines = [heading, f"👤 {name}"]
    if username:
        lines.append(f"🔖 <code>@{html.escape(str(username)[:64], quote=True)}</code>")
    lines.append(f"🆔 <code>{public_id}</code>")
    lines.append(f"🕐 {now.strftime('%I:%M %p').lstrip('0')}")
    return "\n".join(lines)


class MikasaVCConsumer:
    def __init__(self, bot, storage: VCMonitorStore, delete_delay: float = _NOTICE_DELETE):
        self.bot = bot
        self.store = storage
        self.delete_delay = delete_delay
        self._running = False
        self._delete_tasks: set[asyncio.Task] = set()

    async def _delete_row(self, row: dict) -> None:
        try:
            await self.bot.delete_messages(int(row["chat_id"]), int(row["message_id"]))
            logger.info("VC notice %s deleted in %s", row["message_id"], row["chat_id"])
        except asyncio.CancelledError:
            self.store.release_pending_delete(int(row["id"]))
            raise
        except Exception as exc:
            self.store.finish_delete(
                int(row["id"]),
                success=False,
                error=type(exc).__name__,
                now=time.time(),
            )
        else:
            self.store.finish_delete(int(row["id"]), success=True, now=time.time())

    async def _delete_after_send(self, delete_id: int) -> None:
        try:
            await asyncio.sleep(self.delete_delay)
            row = self.store.claim_pending_delete(delete_id, now=time.time())
            if row is not None:
                await self._delete_row(row)
        except asyncio.CancelledError:
            raise

    def _track_delete(self, delete_id: int) -> None:
        task = asyncio.create_task(self._delete_after_send(delete_id))
        self._delete_tasks.add(task)
        task.add_done_callback(self._delete_tasks.discard)

    async def process_pending_deletes(self) -> None:
        rows = self.store.claim_pending_deletes(now=time.time(), limit=25)
        for row in rows:
            await self._delete_row(row)

    async def process_events(self) -> None:
        rows = self.store.claim_events(now=time.time(), limit=25)
        for row in rows:
            chat_id = int(row["chat_id"])
            if not self.store.is_enabled(chat_id):
                self.store.ack_event(int(row["id"]))
                continue

            identity = PublicIdentity(
                peer_id=int(row["user_id"]),
                name=str(row.get("name") or "Telegram user"),
                username=str(row.get("username") or ""),
                kind=str(row.get("kind") or "user"),
            )
            text = _join_notice(identity)
            try:
                sent = await self.bot.send_message(
                    chat_id,
                    text,
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except asyncio.CancelledError:
                raise
            except FloodWait as exc:
                wait = min(float(getattr(exc, "value", 0) or 0) + 1.0, 120.0)
                logger.info("VC monitor publish flood-limited %.0fs", wait)
                self.store.release_event(int(row["id"]))
                await asyncio.sleep(wait)
                continue
            except Exception as exc:
                logger.info("VC monitor publish failed: %s", type(exc).__name__)
                self.store.release_event(int(row["id"]))
                continue

            sent_id = getattr(sent, "id", None)
            if sent_id is None:
                self.store.ack_event(int(row["id"]))
                continue

            sent_at = time.time()
            delete_id = self.store.add_pending_delete(
                chat_id,
                int(sent_id),
                due_at=sent_at + self.delete_delay,
                now=sent_at,
            )
            self.store.ack_event(int(row["id"]))
            self._track_delete(delete_id)

    async def run(self) -> None:
        self._running = True
        try:
            await self.process_pending_deletes()
            while self._running:
                try:
                    self.store.prune(now=time.time())
                    await self.process_pending_deletes()
                    await self.process_events()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug("VC consumer tick error: %s", exc)
                await asyncio.sleep(0.5)
        finally:
            self._running = False
            for t in list(self._delete_tasks):
                t.cancel()


_consumer: MikasaVCConsumer | None = None


@app.on_message(filters.group & filters.command(["vcmonitor"]))
async def vcmonitor_command(_, message: types.Message) -> None:
    chat_id = int(message.chat.id)
    store.remember_chat(chat_id)

    # Verify admin privileges
    if message.from_user:
        try:
            member = await app.get_chat_member(chat_id, message.from_user.id)
            is_admin = member.status in {enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER}
            can_manage_vc = (
                member.status == enums.ChatMemberStatus.OWNER
                or getattr(member.privileges, "can_manage_video_chats", False)
            )
            if not is_admin or not can_manage_vc:
                await message.reply_text(
                    "⚠️ You need the <b>Manage Video Chats</b> admin permission to configure VC monitoring."
                )
                return
        except Exception:
            pass

    args = [part.lower() for part in (message.command or [])[1:]]
    command = args[0] if args else "status"

    if command in {"on", "off"}:
        enabled = command == "on"
        store.set_enabled(chat_id, enabled)
        await message.reply_text(
            f"🎧 <b>VC Monitor {'enabled' if enabled else 'disabled'}.</b>\n"
            + (
                "Join notices will be announced and automatically deleted after 5 seconds."
                if enabled
                else "VC join notices are now silenced for this group."
            ),
            parse_mode=enums.ParseMode.HTML,
        )
        return

    # Status check
    setting = store.get_setting(chat_id)
    health = store.get_health(chat_id)
    enabled_text = "ON" if setting.get("enabled", True) else "OFF"
    assistant_count = len(userbot.clients) if hasattr(userbot, "clients") else 0

    status = (health or {}).get("status", "ready")
    last_seen = (health or {}).get("last_seen")
    last_seen_str = (
        datetime.fromtimestamp(float(last_seen), timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        if last_seen
        else "none yet"
    )

    await message.reply_text(
        f"🎧 <b>VC Monitor Status</b>\n\n"
        f"• Status: <b>{enabled_text}</b>\n"
        f"• Assistants Online: <code>{assistant_count}</code>\n"
        f"• Health: <code>{status}</code>\n"
        f"• Last Activity: <code>{last_seen_str}</code>\n"
        f"• Auto-Delete: <code>5s</code>\n\n"
        f"Usage: <code>/vcmonitor on|off|status</code>",
        parse_mode=enums.ParseMode.HTML,
    )


async def on_start(_app) -> None:
    global monitor, _consumer, _consumer_task
    if monitor is None:
        monitor = VoiceChatMonitor(
            store=store,
            clients_provider=lambda: list(getattr(userbot, "clients", [])),
        )
        await monitor.run()

    if _consumer is None:
        _consumer = MikasaVCConsumer(bot=app, storage=store, delete_delay=_NOTICE_DELETE)
        _consumer_task = asyncio.create_task(_consumer.run())
        logger.info("Mikasa VC notification consumer started")
