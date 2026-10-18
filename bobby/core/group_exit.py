"""Clean up one assistant when the bot leaves a group.

Telegram does not guarantee that a bot's ``my_chat_member`` update reaches a
process which was offline.  This module deliberately keeps the cleanup
scoped: it reacts only to an authenticated update about *this* bot (or to the
bot's own ``leave_chat`` call), snapshots the assistant assignment without
allocating one, and then asks only that assistant to leave the same group.

The voice-call teardown is best effort.  A broken/stale pytgcalls binding must
not prevent the assistant's ordinary ``leave_chat`` request, and this module
never uses ``close=True`` or discards a group call.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pyrogram import enums, filters, types


_ACTIVE_STATUSES = frozenset(
    {
        status.value
        for status in (
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.MEMBER,
            enums.ChatMemberStatus.RESTRICTED,
        )
    }
)
_EXIT_STATUSES = frozenset(
    status.value
    for status in (enums.ChatMemberStatus.LEFT, enums.ChatMemberStatus.BANNED)
)
_GROUP_TYPES = frozenset(
    {enums.ChatType.GROUP, enums.ChatType.SUPERGROUP}
)


def _status(member: Any) -> Any:
    raw = getattr(member, "status", None) if member is not None else None
    raw = getattr(raw, "value", raw)
    return raw.rsplit(".", 1)[-1].lower() if isinstance(raw, str) else raw


def _is_group(chat: Any) -> bool:
    chat_type = getattr(chat, "type", None)
    return chat_type in _GROUP_TYPES or str(chat_type).lower() in {
        "group",
        "supergroup",
        "chattype.group",
        "chattype.supergroup",
    }


def _chat_id(value: Any) -> int | None:
    chat = getattr(value, "chat", value)
    raw = getattr(chat, "id", chat)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@dataclass
class _State:
    """Membership state used to invalidate an in-flight stale cleanup."""

    member: bool | None = None
    epoch: int = 0


@dataclass(frozen=True)
class _Assignment:
    """Immutable assistant/binding/lifecycle snapshot for one exit event."""

    assistant: Any
    call: Any
    generation: int | None


class GroupExitCleanup:
    """Serialize and deduplicate bot-exit cleanup per chat.

    ``db.get_assistant`` is intentionally not used here.  That method is
    allowed to allocate an assistant for a cache miss, which is correct for
    playback but unsafe while handling an exit event.
    """

    def __init__(
        self,
        bot: Any,
        db: Any,
        userbot: Any,
        calls: Any,
        logger: Any,
        *,
        timeout: float = 4.0,
        attempts: int = 2,
        retry_delay: float = 0.2,
    ) -> None:
        self.bot = bot
        self.db = db
        self.userbot = userbot
        self.calls = calls
        self.logger = logger
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self.retry_delay = max(0.0, retry_delay)

        self._states: dict[int, _State] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._pending: dict[int, asyncio.Task] = {}

    def _lock(self, chat_id: int) -> asyncio.Lock:
        return self._locks.setdefault(chat_id, asyncio.Lock())

    def _state(self, chat_id: int) -> _State:
        return self._states.setdefault(chat_id, _State())

    def _bot_id(self) -> int | None:
        raw = getattr(self.bot, "id", None)
        if raw is None:
            raw = getattr(getattr(self.bot, "me", None), "id", None)
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _assignment(self, chat_id: int) -> _Assignment | None:
        """Return the currently mapped assistant without changing the map."""
        number = None
        cache = getattr(self.db, "assistant", None)
        if isinstance(cache, dict):
            number = cache.get(chat_id)

        if number is None:
            data = getattr(self.db, "_data", {})
            mapped = data.get("assistant", {}) if isinstance(data, dict) else {}
            number = mapped.get(str(chat_id))

        try:
            number = int(number)
        except (TypeError, ValueError):
            return None
        if number < 1:
            return None

        assistants = getattr(self.userbot, "clients", None) or []
        try:
            assistant = assistants[number - 1]
        except (IndexError, TypeError):
            return None

        calls = getattr(self.calls, "clients", None) or []
        try:
            call = calls[number - 1]
        except (IndexError, TypeError):
            call = None
        lifecycle = getattr(self.calls, "_lifecycle", None)
        states = getattr(lifecycle, "_states", None)
        state = states.get(chat_id) if isinstance(states, dict) else None
        # A missing lifecycle entry is generation zero, not permission to stop
        # any later generation created after the bot is re-added.
        generation = getattr(state, "generation", 0) if isinstance(states, dict) else None
        return _Assignment(
            assistant=assistant,
            call=call,
            generation=generation,
        )

    async def _is_current_absence(self, chat_id: int, epoch: int) -> bool:
        async with self._lock(chat_id):
            state = self._state(chat_id)
            return not state.member and state.epoch == epoch

    async def _bot_is_member_now(self, chat_id: int) -> bool:
        """Return true only when a fresh membership read proves a rejoin.

        ``None`` (no method, permission failure, or transport failure) is
        deliberately treated as unknown.  An exit update is authoritative
        enough to continue in that case; only a positive active status can
        invalidate the snapshot.
        """
        get_member = getattr(self.bot, "get_chat_member", None)
        bot_id = self._bot_id()
        if get_member is None or bot_id is None:
            return False
        try:
            member = await self._bounded(lambda: get_member(chat_id, bot_id))
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        return _status(member) in _ACTIVE_STATUSES

    async def _confirmed_absence(self, chat_id: int, epoch: int) -> bool:
        """Check membership, then re-check the epoch before any side effect."""
        if not await self._is_current_absence(chat_id, epoch):
            return False
        if await self._bot_is_member_now(chat_id):
            return False
        # _bot_is_member_now awaited Telegram.  A rejoin update may have been
        # dispatched while that request was in flight, so never use the first
        # epoch check as authorization for a physical leave.
        return await self._is_current_absence(chat_id, epoch)

    async def mark_bot_joined(self, chat_id: int) -> None:
        """Invalidate cleanup which was racing a bot rejoin."""
        async with self._lock(chat_id):
            state = self._state(chat_id)
            state.member = True
            state.epoch += 1

    async def _bounded(
        self,
        operation: Callable[[], Awaitable[Any] | Any],
    ) -> Any:
        result = operation()
        if inspect.isawaitable(result):
            return await asyncio.wait_for(result, timeout=self.timeout)
        return result

    async def _stop_voice(self, assignment: _Assignment, chat_id: int) -> None:
        """Clear this chat's queue/voice state, but never its group call."""
        if assignment.call is None:
            return
        # ``self.calls`` is the TgCall controller.  Its ``clients`` list holds
        # PyTgCalls bindings; the binding itself is not the controller.
        stop = getattr(self.calls, "stop", None)
        if stop is None:
            return
        try:
            # TgCall.stop expects its PyTgCalls binding for leave_call/raw
            # fallback, not the raw Pyrogram assistant client.
            kwargs = {"assistant_client": assignment.call}
            if assignment.generation is not None:
                kwargs["expected_generation"] = assignment.generation
            await self._bounded(lambda: stop(chat_id, **kwargs))
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            self.logger.warning(
                "group-exit voice cleanup failed in %s: %s",
                chat_id,
                type(ex).__name__,
            )

    async def _leave_assistant(self, assistant: Any, chat_id: int, epoch: int) -> bool:
        leave = getattr(assistant, "leave_chat", None)
        if leave is None:
            return False

        for attempt in range(1, self.attempts + 1):
            try:
                if not await self._confirmed_absence(chat_id, epoch):
                    return False
                await self._bounded(lambda: leave(chat_id))
                return True
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                self.logger.warning(
                    "group-exit assistant leave failed in %s (attempt %s): %s",
                    chat_id,
                    attempt,
                    type(ex).__name__,
                )
                if attempt < self.attempts:
                    await asyncio.sleep(self.retry_delay * attempt)
                    if not await self._confirmed_absence(chat_id, epoch):
                        return False
        return False

    async def _cleanup(self, chat_id: int, epoch: int, assignment: _Assignment) -> None:
        # A rejoin update can arrive before VC teardown.  Do not stop fresh
        # playback belonging to the rejoined bot.
        if not await self._confirmed_absence(chat_id, epoch):
            return
        try:
            await self._stop_voice(assignment, chat_id)
        finally:
            await self._leave_assistant(assignment.assistant, chat_id, epoch)

    async def mark_bot_left(self, chat_id: int) -> bool:
        """Handle one confirmed bot exit; duplicate events are idempotent."""
        async with self._lock(chat_id):
            state = self._state(chat_id)
            pending = self._pending.get(chat_id)
            if state.member is False:
                if pending is not None:
                    awaitable = pending
                else:
                    return False
            else:
                state.member = False
                state.epoch += 1
                epoch = state.epoch
                assignment = self._assignment(chat_id)
                if assignment is None:
                    return True
                pending = asyncio.create_task(
                    self._cleanup(chat_id, epoch, assignment)
                )
                self._pending[chat_id] = pending
                awaitable = pending

        try:
            await asyncio.shield(awaitable)
        finally:
            async with self._lock(chat_id):
                if self._pending.get(chat_id) is awaitable and awaitable.done():
                    self._pending.pop(chat_id, None)
        return True

    async def on_bot_leave(self, chat_id: int, **_: Any) -> bool:
        """Callback used by the Bot.leave_chat override."""
        return await self.mark_bot_left(chat_id)

    async def handle_chat_member_update(self, update: Any) -> bool:
        """Process only a status transition concerning this authenticated bot."""
        chat_id = _chat_id(update)
        if chat_id is None or not _is_group(getattr(update, "chat", None)):
            return False

        old = getattr(update, "old_chat_member", None)
        new = getattr(update, "new_chat_member", None)
        user = getattr(new, "user", None) or getattr(old, "user", None)
        bot_id = self._bot_id()
        if bot_id is None or getattr(user, "id", None) != bot_id:
            return False

        old_status = _status(old)
        new_status = _status(new)
        # Kurigram's parser leaves new_chat_member unset when the participant
        # disappears from UpdateChannelParticipant (ordinary self-leave).
        if old_status in _ACTIVE_STATUSES and (
            new is None or new_status in _EXIT_STATUSES
        ):
            return await self.mark_bot_left(chat_id)
        if new_status in _ACTIVE_STATUSES:
            await self.mark_bot_joined(chat_id)
        return False

    async def handle_left_service_message(self, message: Any) -> bool:
        """Fallback for clients which expose the self-left service message."""
        chat_id = _chat_id(message)
        if chat_id is None or not _is_group(getattr(message, "chat", None)):
            return False
        member = getattr(message, "left_chat_member", None)
        bot_id = self._bot_id()
        if bot_id is None or getattr(member, "id", None) != bot_id:
            return False
        return await self.mark_bot_left(chat_id)

    async def reconcile_chat(self, chat_id: int) -> bool:
        """Reconcile one explicitly requested chat after downtime.

        No scanner calls this method.  It only cleans up when Telegram
        explicitly proves the bot is ``LEFT``/``BANNED``; permission,
        transport, and malformed responses are all non-authoritative.
        """
        get_member = getattr(self.bot, "get_chat_member", None)
        bot_id = self._bot_id()
        if get_member is None or bot_id is None:
            return False
        try:
            member = await self._bounded(lambda: get_member(chat_id, bot_id))
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            self.logger.warning(
                "group-exit membership check unavailable in %s: %s",
                chat_id,
                type(ex).__name__,
            )
            return False

        status = _status(member)
        if status in _EXIT_STATUSES:
            return await self.mark_bot_left(chat_id)
        if status in _ACTIVE_STATUSES:
            await self.mark_bot_joined(chat_id)
        return False


def install(
    app: Any,
    db: Any,
    userbot: Any,
    calls: Any,
    logger: Any,
) -> GroupExitCleanup:
    """Install the two Kurigram/Pyrogram update hooks and return the manager."""
    manager = GroupExitCleanup(app, db, userbot, calls, logger)
    app._group_exit_manager = manager
    app._group_exit_hook = manager.on_bot_leave

    @app.on_chat_member_updated(group=18)
    async def _group_exit_member_update(_, update: types.ChatMemberUpdated):
        await manager.handle_chat_member_update(update)

    # Kurigram exposes a self-left service message on some update paths even
    # when the chat-member update is not delivered to the bot.
    @app.on_message(filters.left_chat_member, group=18)
    async def _group_exit_service_message(_, message: types.Message):
        await manager.handle_left_service_message(message)

    logger.info("group-exit: assistant cleanup handlers installed")
    return manager
