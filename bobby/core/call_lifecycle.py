"""Small, transport-agnostic guards for one chat's call lifecycle.

The py-tgcalls ``leave_call`` implementation stops ntgcalls before sending
LeaveGroupCall.  If the native call has already gone away, its early
NotInCallError therefore prevents the MTProto leave from being sent.  Keep
that workaround here, separate from queue/UI code, so it is easy to exercise
without a Telegram session.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Awaitable, Callable
import time

_ADVANCE_STALE = 10.0   # seconds before a claimed advance is dead


def _log_advance_stale(chat_id: int) -> None:
    import logging
    logging.getLogger("bobby").warning(
        "advance claim for %s was stale (>%ss): releasing it so /skip works",
        chat_id, int(_ADVANCE_STALE),
    )



Log = Callable[[str, int, int, str], None]
Cleanup = Callable[[], Awaitable[None]]


@dataclass
class _State:
    generation: int = 0
    active: bool = False
    terminal: bool = False
    advancing: int | None = None
    advancing_at: float = 0.0
    installing: bool = False


class _NoActiveCall(LookupError):
    """Fresh FullChat explicitly proved that this chat has no active call."""


class CallLifecycle:
    """Serialize terminal cleanup and reject obsolete playback transitions."""

    def __init__(self) -> None:
        self._states: dict[int, _State] = {}
        self._state_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._cleanup_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._native_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _state(self, chat_id: int) -> _State:
        return self._states.setdefault(chat_id, _State())

    async def start(self, chat_id: int, expected: int | None = None) -> int | None:
        """Start a stream generation, waiting for any terminal leave first."""
        async with self._cleanup_locks[chat_id]:
            async with self._state_locks[chat_id]:
                state = self._state(chat_id)
                if expected is not None and state.generation != expected:
                    return None
                state.generation += 1
                state.active = True
                state.terminal = False
                state.advancing = None
                state.advancing_at = 0.0
                # End events from the replaced stream must not consume the
                # new queue item while its source/join is still being prepared.
                # This covers direct seek/force as well as automatic advance.
                state.installing = True
                return state.generation

    async def install(self, chat_id: int, generation: int, play: Cleanup) -> bool:
        """Serialize native installs; an older await cannot overwrite a new play."""
        async with self._native_locks[chat_id]:
            if not await self.current(chat_id, generation):
                return False
            await play()
            # Drain end notifications queued by the replacement itself before
            # accepting events for the new stream. No duration-based grace.
            await asyncio.sleep(0)
            return await self.ready(chat_id, generation)

    async def ready(self, chat_id: int, generation: int) -> bool:
        async with self._state_locks[chat_id]:
            state = self._state(chat_id)
            if not state.active or state.generation != generation:
                return False
            state.installing = False
            return True

    async def recover(self, chat_id: int, generation: int, cleanup: Cleanup) -> bool:
        async with self._native_locks[chat_id]:
            if not await self.current(chat_id, generation):
                return False
            result = await cleanup()
            return result is not False and await self.current(chat_id, generation)

    async def installing(self, chat_id: int) -> bool:
        async with self._state_locks[chat_id]:
            return self._state(chat_id).installing

    async def current(self, chat_id: int, generation: int) -> bool:
        async with self._state_locks[chat_id]:
            state = self._state(chat_id)
            return state.active and state.generation == generation

    async def claim_advance(
        self,
        chat_id: int,
        expected: int | None = None,
        *,
        stream_ended: bool = False,
    ) -> int | None:
        """Claim one skip/end transition for the current stream generation."""
        async with self._state_locks[chat_id]:
            state = self._state(chat_id)
            if (
                not state.active
                or (expected is not None and state.generation != expected)
            ):
                return None
            if stream_ended and state.installing:
                return None
            if state.advancing == state.generation:
                # An advance is already in flight: a second one must NOT
                # double-skip (rapid taps, or a StreamEnded racing the skip).
                # But a claim that never reached start() used to stay set
                # forever, silently dropping EVERY later /skip.
                if time.monotonic() - getattr(state, "advancing_at", 0.0) < _ADVANCE_STALE:
                    return None
                _log_advance_stale(chat_id)
            state.advancing = state.generation
            state.advancing_at = time.monotonic()
            return state.generation

    async def release_advance(self, chat_id: int, generation: int | None = None) -> None:
        """Hand a claimed advance back so the next /skip is not dropped.

        `advancing` is otherwise cleared only by start()/terminal(), so any
        early return between claim_advance() and start() left it set to the
        live generation: /skip then answered "skipped" while doing nothing.
        """
        async with self._state_locks[chat_id]:
            state = self._state(chat_id)
            if generation is None or state.advancing == generation:
                state.advancing = None
                state.advancing_at = 0.0

    async def terminal(
        self,
        chat_id: int,
        cleanup: Cleanup,
        expected: int | None = None,
    ) -> bool:
        """Invalidate a generation and run exactly one cancellation-safe leave."""
        async with self._cleanup_locks[chat_id]:
            async with self._state_locks[chat_id]:
                state = self._state(chat_id)
                if (
                    (expected is not None and state.generation != expected)
                    or state.terminal
                ):
                    return False
                state.generation += 1
                state.active = False
                state.terminal = True
                state.advancing = None
                state.advancing_at = 0.0
                state.installing = False
            # Invalidate immediately, then wait for any old native install
            # before leaving. start() waits for this cleanup lock, so this
            # leave cannot remove a subsequently requested stream.
            async def after_install():
                async with self._native_locks[chat_id]:
                    await cleanup()
            await _finish_cleanup(after_install)
            return True

    async def cleanup_if_terminal(
        self,
        chat_id: int,
        stale_generation: int,
        cleanup: Cleanup,
    ) -> bool:
        """Leave a play request which completed after its stop, but not a new play."""
        async with self._cleanup_locks[chat_id]:
            async with self._state_locks[chat_id]:
                state = self._state(chat_id)
                if state.active or not state.terminal or state.generation == stale_generation:
                    return False
            await _finish_cleanup(cleanup)
            return True


async def _finish_cleanup(cleanup: Cleanup) -> None:
    """Do not abandon a leave request merely because its caller is cancelled."""
    task = asyncio.create_task(cleanup())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def _fresh_input_call(client, chat_id: int):
    """Resolve the current group-call handle through the assistant account.

    ``ClientCache.get_input_call`` is deliberately not used here.  The
    py-tgcalls cache can outlive a voice-chat replacement, and its public
    leave method is allowed to return after a cache miss without sending a
    Telegram request.  FullChat is a fresh MTProto read on the already-bound
    assistant account, so a handle from another chat/call cannot be reused.
    """
    from pyrogram.raw.functions.channels import GetFullChannel
    from pyrogram.raw.functions.messages import GetFullChat
    from pyrogram.raw.types import GroupCallDiscarded, InputChannel, InputGroupCall
    from pyrogram.raw.types import InputPeerChannel, InputPeerChat

    adapter = client._app._bind_client
    account = adapter._app
    # ClientCache turns lookup failures into None.  Bypass that cache using
    # the already-connected ASSISTANT, never another session or the bot.
    peer = await account.resolve_peer(chat_id)
    if isinstance(peer, InputPeerChannel):
        full = await account.invoke(GetFullChannel(channel=InputChannel(
            channel_id=peer.channel_id, access_hash=peer.access_hash)))
    elif isinstance(peer, InputPeerChat):
        full = await account.invoke(GetFullChat(chat_id=peer.chat_id))
    else:
        raise LookupError("not a group peer")
    full_chat = getattr(full, "full_chat", None)
    if full_chat is None or not hasattr(full_chat, "call"):
        raise LookupError("full chat response has no call state")
    call = full_chat.call
    if call is None or isinstance(call, GroupCallDiscarded):
        raise _NoActiveCall
    if not isinstance(call, InputGroupCall):
        raise LookupError("no verified input call")
    return adapter, account, call


def _invalidate_voice_caches(client, chat_id: int, adapter) -> None:
    """Drop both ntgcalls and py-tgcalls' MTProto call caches.

    ``LeaveCall`` clears its native binding state, but the adapter's
    ``ClientCache`` is separate and otherwise retains the old InputGroupCall
    handle for up to ``cache_duration`` seconds.
    """
    clear = getattr(client, "_clear_cache", None)
    if clear is not None:
        try:
            clear(chat_id)
        except Exception:
            pass
    cache = getattr(adapter, "_cache", None)
    drop = getattr(cache, "drop_cache", None)
    if drop is not None:
        try:
            drop(chat_id)
        except Exception:
            pass


def _invalidate_confirmed_call_cache(client, chat_id: int) -> None:
    """Keep a verified departure from poisoning the next same-chat join."""
    adapter = getattr(getattr(client, "_app", None), "_bind_client", None)
    if adapter is not None:
        _invalidate_voice_caches(client, chat_id, adapter)


async def _raw_leave(client, chat_id: int):
    """Send a real assistant RPC with a freshly validated call handle.

    Return the exact handle used for the request so the caller can verify the
    same voice chat.  The library adapter may silently do nothing on a cache
    miss, hence this direct request is required even after native teardown.
    """
    from pyrogram.raw.functions.phone import LeaveGroupCall

    adapter, _, call = await _fresh_input_call(client, chat_id)
    await adapter._invoke(LeaveGroupCall(call=call, source=0))
    _invalidate_voice_caches(client, chat_id, adapter)
    return call


def _peer_user_id(peer) -> int | None:
    """Return a user peer id, never a channel/chat id."""
    if peer is None:
        return None
    name = type(peer).__name__
    if name not in {"PeerUser", "InputPeerUser"}:
        return None
    value = getattr(peer, "user_id", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_self_participant(participant, account_id: int) -> bool:
    """Match the authenticated account, not merely a nonempty result.

    ``phone.getGroupParticipants`` may return another participant even when a
    self-targeted query was requested.  A raw participant's PeerUser is the
    strongest identity check; ``is_self`` is useful for adapters which omit
    the peer but is never allowed to turn a different user into self.
    """
    if getattr(participant, "left", False):
        return False
    peer_id = _peer_user_id(getattr(participant, "peer", None))
    if peer_id is not None:
        return peer_id == account_id
    # The installed py-tgcalls adapter's normalized participant carries
    # ``user_id`` instead of the raw PeerUser.  Keep this exact-id fallback
    # useful for an adapter implementation without accepting its other users.
    participant_id = getattr(participant, "user_id", None)
    if participant_id is not None:
        try:
            return int(participant_id) == account_id
        except (TypeError, ValueError):
            return False
    return bool(getattr(participant, "is_self", False))


async def _fresh_participants(adapter, call, ids=None):
    """Read all participants directly, bypassing py-tgcalls' participant cache."""
    from pyrogram.raw.functions.phone import GetGroupParticipants

    offset = ""
    seen_offsets: set[str] = set()
    while True:
        result = await adapter._invoke(GetGroupParticipants(
            call=call,
            ids=[] if ids is None else ids,
            sources=[],
            offset=offset,
            # Match py-tgcalls' real adapter.  Telegram uses zero here to
            # request its complete participant page and supplies next_offset.
            limit=0,
        ))
        participants = getattr(result, "participants", None)
        if participants is None:
            raise LookupError("participant response has no participant list")
        for participant in participants:
            yield participant
        next_offset = getattr(result, "next_offset", None) or ""
        if not next_offset:
            return
        if next_offset in seen_offsets:
            raise LookupError("participant response repeated its offset")
        seen_offsets.add(next_offset)
        offset = next_offset


async def _assistant_absent(client, chat_id: int, call=None) -> bool:
    """Confirm exact-self absence; raise for an explicit fresh no-call state."""
    from pyrogram.raw.types import InputPeerSelf

    adapter = getattr(getattr(client, "_app", None), "_bind_client", None)
    account = getattr(adapter, "_app", None)
    if adapter is None or account is None:
        raise LookupError("assistant adapter unavailable")

    # Always refresh FullChat here.  A call handle captured before a leave can
    # be stale, while an explicit no-call response is authoritative.
    _, _, current_call = await _fresh_input_call(client, chat_id)
    if call is None or current_call != call:
        call = current_call
    get_me = getattr(account, "get_me", None)
    if get_me is None:
        raise LookupError("assistant identity unavailable")
    me = await get_me()
    account_id = getattr(me, "id", None)
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        raise LookupError("assistant identity has no user id")

    # Telegram may omit muted listeners from an unfiltered page.  Ask for the
    # exact session identity first, then retain the full fresh walk as a
    # second check; the caller only treats absence as conclusive after a
    # successful LeaveGroupCall.
    async for participant in _fresh_participants(
        adapter, call, ids=[InputPeerSelf()],
    ):
        if _is_self_participant(participant, account_id):
            return False
    async for participant in _fresh_participants(adapter, call):
        if _is_self_participant(participant, account_id):
            return False
    return True


async def leave_assistant(
    client,
    chat_id: int,
    log: Log,
    *,
    attempts: int = 2,
    timeout: float = 4.0,
    settle_delay: float = 0.0,
) -> bool:
    """Leave *this assistant* without ever discarding the group's voice chat.

    ``client.leave_call`` is tried first to clear normal py-tgcalls state, but
    its return is never treated as departure proof: a direct MTProto
    LeaveGroupCall is always attempted with a fresh InputGroupCall handle.
    Fresh exact-self participant checks verify a successful RPC. Absence must
    remain true after a short settling interval because Telegram can briefly
    omit a listener immediately after the RPC and then show it again. A missing
    self in a visibility-limited list cannot prove departure when that RPC
    failed. Failures are bounded and type-only logged; transport exception text
    can contain details that do not belong in operational logs.
    """
    # Callers may provide a retry count, but cleanup must remain finite even
    # when an unexpected caller passes an unbounded value.
    attempts = max(1, min(int(attempts), 3))
    for attempt in range(1, attempts + 1):
        call = None
        rpc_succeeded = False
        try:
            await asyncio.wait_for(
                client.leave_call(chat_id, close=False),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            log("native leave failed", chat_id, attempt, type(ex).__name__)

        try:
            call = await asyncio.wait_for(
                _raw_leave(client, chat_id),
                timeout=timeout,
            )
            rpc_succeeded = True
        except _NoActiveCall:
            # A fresh, structurally valid FullChat with no active call is
            # already the desired state; do not turn it into a warning loop.
            _invalidate_confirmed_call_cache(client, chat_id)
            log("assistant leave verified", chat_id, attempt, "no active call")
            return True
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            log("MTProto leave failed", chat_id, attempt, type(ex).__name__)

        try:
            absent = await asyncio.wait_for(
                _assistant_absent(client, chat_id, call),
                timeout=timeout,
            )
            if absent:
                if rpc_succeeded:
                    stable_absent = True
                    if settle_delay > 0:
                        await asyncio.sleep(min(float(settle_delay), 2.0))
                        try:
                            stable_absent = await asyncio.wait_for(
                                _assistant_absent(client, chat_id, call),
                                timeout=timeout,
                            )
                        except _NoActiveCall:
                            stable_absent = True
                    if stable_absent:
                        _invalidate_confirmed_call_cache(client, chat_id)
                        log("assistant leave verified", chat_id, attempt,
                            "self stably absent after RPC")
                        return True
                    log("assistant leave verification found self", chat_id, attempt,
                        "self returned after settling")
                # A visibility-limited omission cannot prove departure after
                # the direct RPC itself failed.
                else:
                    log("assistant leave absence inconclusive", chat_id, attempt,
                        "LeaveGroupCall failed")
            else:
                log("assistant leave verification found self", chat_id, attempt,
                    "self participant still present")
        except _NoActiveCall:
            _invalidate_confirmed_call_cache(client, chat_id)
            log("assistant leave verified", chat_id, attempt, "no active call")
            return True
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            log("assistant leave verification failed", chat_id, attempt,
                type(ex).__name__)

        if attempt < attempts:
            await asyncio.sleep(0.2 * attempt)

    log("assistant leave exhausted", chat_id, attempts, "retry budget exhausted")
    return False