"""Offline VC-end lifecycle regressions; no Telegram client is started."""

import asyncio
import collections
import importlib
import inspect
import sys
import types as pytypes
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pyrogram.raw.functions.phone import GetGroupParticipants, LeaveGroupCall
from pyrogram.raw.types import (
    InputGroupCall, InputPeerChannel, InputPeerSelf, PeerUser,
)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _exception(name):
    return type(name, (Exception,), {})


def load_calls_module():
    """Import the real calls module with only its process globals faked."""
    for name in list(sys.modules):
        if name == "bobby" or name.startswith("bobby."):
            del sys.modules[name]

    bobby = pytypes.ModuleType("bobby")
    bobby.__path__ = [str(ROOT / "bobby")]
    bobby.config = pytypes.SimpleNamespace(THUMB_GEN=False, DEFAULT_THUMB=None)
    bobby.logger = pytypes.SimpleNamespace(
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
        exception=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    bobby.app = pytypes.SimpleNamespace()
    bobby.db = pytypes.SimpleNamespace()
    bobby.lang = pytypes.SimpleNamespace()
    bobby.queue = pytypes.SimpleNamespace()
    bobby.thumb = pytypes.SimpleNamespace()
    bobby.userbot = pytypes.SimpleNamespace()
    bobby.yt = pytypes.SimpleNamespace()
    sys.modules["bobby"] = bobby

    helpers = pytypes.ModuleType("bobby.helpers")
    helpers.__path__ = [str(ROOT / "bobby" / "helpers")]
    helpers.Media = type("Media", (), {})
    helpers.Track = type("Track", (), {})
    helpers.buttons = pytypes.SimpleNamespace()
    sys.modules["bobby.helpers"] = helpers

    # calls.py only needs these names to define TgCall; methods which would
    # need actual pyrogram/ntgcalls are never entered by this test suite.
    ntgcalls = pytypes.ModuleType("ntgcalls")
    for name in (
        "ConnectionNotFound", "TelegramServerError", "RTMPStreamingUnsupported",
        "ConnectionError", "TransportParseException",
    ):
        setattr(ntgcalls, name, _exception(name))
    sys.modules["ntgcalls"] = ntgcalls

    # Use real Pyrogram raw types so fallback tests cover an actual
    # LeaveGroupCall request, not a mock adapter's successful no-op.

    pytgcalls = pytypes.ModuleType("pytgcalls")
    pytgcalls.PyTgCalls = type("PyTgCalls", (), {})
    pytgcalls.exceptions = pytypes.SimpleNamespace(
        NotInCallError=_exception("NotInCallError"),
        NoActiveGroupCall=_exception("NoActiveGroupCall"),
        NoAudioSourceFound=_exception("NoAudioSourceFound"),
    )
    class MediaStream:
        class Flags:
            REQUIRED = object()
            AUTO_DETECT = object()
            IGNORE = object()

        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    pytgcalls.types = pytypes.SimpleNamespace(
        MediaStream=MediaStream,
        AudioQuality=pytypes.SimpleNamespace(HIGH=object()),
        VideoQuality=pytypes.SimpleNamespace(HD_720p=object()),
        GroupCallConfig=lambda **kwargs: pytypes.SimpleNamespace(**kwargs),
    )
    sys.modules["pytgcalls"] = pytgcalls
    session = pytypes.ModuleType("pytgcalls.pytgcalls_session")
    session.PyTgCallsSession = type("PyTgCallsSession", (), {})
    sys.modules["pytgcalls.pytgcalls_session"] = session
    return importlib.import_module("bobby.core.calls")


CALLS = load_calls_module()
LIFECYCLE = importlib.import_module("bobby.core.call_lifecycle")


class FakeQueue:
    def __init__(self, items=()):
        self.queues = collections.defaultdict(collections.deque)
        self.queues[1].extend(items)
        self.purged = []

    def get_queue(self, chat_id):
        return list(self.queues[chat_id])

    def clear(self, chat_id):
        self.queues[chat_id].clear()

    def purge_item(self, item):
        self.purged.append(item)

    def get_current(self, chat_id):
        return self.queues[chat_id][0] if self.queues[chat_id] else None

    def get_next(self, chat_id):
        if self.queues[chat_id]:
            self.queues[chat_id].popleft()
        return self.get_current(chat_id)


class FakeDb:
    def __init__(self, client, loop=0):
        self.client = client
        self.loop = loop
        self.removed = 0
        self.added = 0

    async def get_assistant(self, chat_id):
        return self.client

    async def remove_call(self, chat_id):
        self.removed += 1

    async def add_call(self, chat_id):
        self.added += 1

    async def set_loop(self, chat_id, loop):
        self.loop = loop

    async def get_loop(self, chat_id):
        return self.loop

    async def get_call(self, chat_id):
        return True

    async def get_autoplay(self, chat_id):
        return False


class FakeClient:
    def __init__(self, native=None, mtproto=None):
        self.native = native or AsyncMock()
        self.mtproto = mtproto or AsyncMock()
        self.call = InputGroupCall(id=123, access_hash=456)
        self.participants = []
        self.participant_reads = None
        self.raw_requests = []
        self.full = pytypes.SimpleNamespace(
            full_chat=pytypes.SimpleNamespace(call=self.call),
        )
        account = pytypes.SimpleNamespace(
            get_me=AsyncMock(return_value=pytypes.SimpleNamespace(id=99)),
            resolve_peer=AsyncMock(return_value=InputPeerChannel(
                channel_id=1, access_hash=2)),
            invoke=AsyncMock(return_value=self.full),
        )
        self.adapter = pytypes.SimpleNamespace(
            get_input_call=AsyncMock(return_value=self.call),
            _invoke=self._invoke,
            _app=account,
            _cache=pytypes.SimpleNamespace(drop_cache=lambda chat_id: None),
        )
        self._app = pytypes.SimpleNamespace(
            _bind_client=self.adapter, leave_group_call=AsyncMock())
        self.play = AsyncMock()

    async def _invoke(self, request):
        self.raw_requests.append(request)
        if isinstance(request, GetGroupParticipants):
            participants = self.participants
            if self.participant_reads is not None:
                participants = self.participant_reads.pop(0)
            return pytypes.SimpleNamespace(
                participants=participants,
                next_offset="",
            )
        return await self.mtproto(request)

    async def leave_call(self, chat_id, close=False):
        return await self.native(chat_id, close=close)


class Item:
    def __init__(self, name, seed=None):
        self.name = name
        self.seed = seed
        self.message_id = 0
        self.file_path = "ready"
        self.video = False
        self.id = name
        self.duration_sec = 0
        self.duration = "0:01"
        self.url = "https://example.invalid/" + name
        self.title = name
        self.user = "user"


class CallLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_missing_still_sends_mtproto_leave_without_close(self):
        native = AsyncMock(side_effect=_exception("NotInCallError")())
        mtproto = AsyncMock()
        client = FakeClient(native, mtproto)
        log = []

        left = await LIFECYCLE.leave_assistant(
            client, 1, lambda *entry: log.append(entry), timeout=0.05,
            settle_delay=0,
        )

        self.assertTrue(left)
        self.assertEqual(native.await_args.kwargs["close"], False)
        mtproto.assert_awaited_once()
        self.assertIsInstance(mtproto.await_args.args[0], LeaveGroupCall)
        self.assertIs(mtproto.await_args.args[0].call, client.call)
        client._app.leave_group_call.assert_not_awaited()
        self.assertEqual(log[0][-1], "NotInCallError")

    async def test_native_success_is_not_leave_confirmation(self):
        client = FakeClient()
        # A successful native teardown must still inspect the real participant
        # list.  When self is still there, issue the direct request and verify
        # again rather than treating the native return as proof.
        still_present = pytypes.SimpleNamespace(
            peer=PeerUser(user_id=99),
            left=False,
            is_self=True,
        )
        client.participant_reads = [[still_present], [], []]
        client.participants = [
            pytypes.SimpleNamespace(
                peer=PeerUser(user_id=1234),
                left=False,
                is_self=False,
            ),
        ]
        raw = []

        left = await LIFECYCLE.leave_assistant(
            client, 1, lambda *entry: raw.append(entry), timeout=0.05,
            settle_delay=0,
        )

        self.assertTrue(left)
        self.assertGreaterEqual(client.mtproto.await_count, 1)
        self.assertGreaterEqual(
            sum(isinstance(item, GetGroupParticipants)
                for item in client.raw_requests),
            2,
        )
        self.assertIn("assistant leave verified", [entry[0] for entry in raw])

    async def test_omitted_self_still_sends_direct_leave_rpc(self):
        client = FakeClient()
        client.participants = [
            pytypes.SimpleNamespace(
                peer=PeerUser(user_id=1234),
                left=False,
                is_self=False,
            ),
        ]
        client.participant_reads = [[], []]

        self.assertTrue(await LIFECYCLE.leave_assistant(
            client, 1, lambda *entry: None, timeout=0.05, settle_delay=0,
        ))
        client.mtproto.assert_awaited_once()
        participant_requests = [
            item for item in client.raw_requests
            if isinstance(item, GetGroupParticipants)
        ]
        self.assertTrue(participant_requests)
        self.assertIsInstance(
            participant_requests[0].ids[0], InputPeerSelf,
        )

    async def test_failed_leave_with_empty_listing_is_not_success(self):
        client = FakeClient(
            AsyncMock(side_effect=_exception("NotInCallError")()),
            AsyncMock(side_effect=RuntimeError("leave failed")),
        )
        client.participant_reads = [[], []]

        self.assertFalse(await LIFECYCLE.leave_assistant(
            client, 1, lambda *entry: None, attempts=1, timeout=0.05,
            settle_delay=0,
        ))
        client.mtproto.assert_awaited_once()

    async def test_self_participant_keeps_leave_unconfirmed_after_bounded_retries(self):
        client = FakeClient()
        client.participants = [
            pytypes.SimpleNamespace(
                peer=PeerUser(user_id=99),
                left=False,
                is_self=True,
            ),
        ]
        logs = []

        left = await LIFECYCLE.leave_assistant(
            client, 1, lambda *entry: logs.append(entry),
            attempts=2, timeout=0.05, settle_delay=0,
        )

        self.assertFalse(left)
        self.assertEqual(client.mtproto.await_count, 2)
        self.assertEqual(
            sum(isinstance(item, GetGroupParticipants)
                for item in client.raw_requests),
            2,
        )
        self.assertEqual(logs[-1][0], "assistant leave exhausted")

    async def test_transient_absence_is_retried_when_self_returns(self):
        client = FakeClient()
        self_participant = pytypes.SimpleNamespace(
            peer=PeerUser(user_id=99),
            left=False,
            is_self=True,
        )
        # First post-RPC read is empty, but the settling read sees the
        # assistant again.  The second leave remains absent and succeeds.
        client.participant_reads = [
            [], [], [self_participant],
            [], [], [], [],
        ]
        logs = []

        left = await LIFECYCLE.leave_assistant(
            client, 1, lambda *entry: logs.append(entry),
            attempts=2, timeout=0.05, settle_delay=0.001,
        )

        self.assertTrue(left)
        self.assertEqual(client.mtproto.await_count, 2)
        self.assertTrue(any(
            entry[0] == "assistant leave verification found self"
            and entry[-1] == "self returned after settling"
            for entry in logs
        ))

    async def test_departed_self_record_is_not_treated_as_present(self):
        client = FakeClient()
        client.participants = [
            pytypes.SimpleNamespace(
                peer=PeerUser(user_id=99),
                left=True,
                is_self=True,
            ),
            pytypes.SimpleNamespace(
                peer=PeerUser(user_id=4567),
                left=False,
                is_self=False,
            ),
        ]

        self.assertTrue(await LIFECYCLE.leave_assistant(
            client, 1, lambda *entry: None, timeout=0.05,
        ))

    async def test_raw_leave_uses_fresh_handle_not_stale_adapter_cache(self):
        client = FakeClient()
        stale = InputGroupCall(id=111, access_hash=222)
        fresh = InputGroupCall(id=333, access_hash=444)
        client.adapter.get_input_call.return_value = stale
        client.full.full_chat.call = fresh
        still_present = pytypes.SimpleNamespace(
            peer=PeerUser(user_id=99),
            left=False,
            is_self=True,
        )
        client.participant_reads = [[still_present], [], []]

        self.assertTrue(await LIFECYCLE.leave_assistant(
            client, 1, lambda *entry: None, timeout=0.05,
        ))
        request = next(
            item for item in client.raw_requests
            if isinstance(item, LeaveGroupCall)
        )
        self.assertEqual(request.call.id, fresh.id)
        self.assertEqual(request.call.access_hash, fresh.access_hash)
        client.adapter.get_input_call.assert_not_awaited()

    async def test_transient_mtproto_failure_retries_with_finite_budget(self):
        native = AsyncMock(side_effect=_exception("NotInCallError")())
        mtproto = AsyncMock(side_effect=[RuntimeError("temporary"), None])
        client = FakeClient(native, mtproto)
        still_present = pytypes.SimpleNamespace(
            peer=PeerUser(user_id=99),
            left=False,
            is_self=True,
        )
        client.participant_reads = [[still_present], [], []]

        self.assertTrue(await LIFECYCLE.leave_assistant(
            client, 1, lambda *args: None, attempts=2, timeout=0.05,
        ))
        self.assertEqual(native.await_count, 2)
        self.assertEqual(mtproto.await_count, 2)

    async def test_timeout_uses_mtproto_fallback(self):
        async def never(*args, **kwargs):
            await asyncio.sleep(10)

        mtproto = AsyncMock()
        client = FakeClient(AsyncMock(side_effect=never), mtproto)
        self.assertTrue(await LIFECYCLE.leave_assistant(
            client, 1, lambda *args: None, attempts=1, timeout=0.01,
        ))
        mtproto.assert_awaited_once()
        self.assertIsInstance(mtproto.await_args.args[0], LeaveGroupCall)

    def test_playback_never_contains_group_wide_discard(self):
        # A bot-side DiscardGroupCall ends the shared voice chat for every
        # participant. Playback recovery may only leave this assistant.
        self.assertNotIn("DiscardGroupCall", inspect.getsource(CALLS.TgCall))
        self.assertFalse(hasattr(CALLS.TgCall, "_sweep_zombie_call"))

    async def test_cache_miss_refreshes_assistant_and_sends_raw_rpc(self):
        client = FakeClient(AsyncMock(side_effect=RuntimeError("native gone")))
        client.adapter.get_input_call.return_value = None
        self.assertTrue(await LIFECYCLE.leave_assistant(
            client, 1, lambda *args: None, timeout=0.05))
        self.assertGreaterEqual(client.adapter._app.invoke.await_count, 2)
        self.assertIsInstance(client.mtproto.await_args.args[0], LeaveGroupCall)

    async def test_invalid_call_lookup_never_succeeds_as_noop(self):
        client = FakeClient(AsyncMock(side_effect=RuntimeError("native gone")))
        client.adapter.get_input_call.return_value = None
        client.adapter._app.invoke.return_value = pytypes.SimpleNamespace()
        self.assertFalse(await LIFECYCLE.leave_assistant(
            client, 1, lambda *args: None, timeout=0.05))
        self.assertEqual(client.native.await_count, 2)
        client.mtproto.assert_not_awaited()
        client._app.leave_group_call.assert_not_awaited()

    async def test_authoritative_no_call_is_already_absent(self):
        client = FakeClient(AsyncMock(side_effect=RuntimeError("native gone")))
        client.adapter.get_input_call.return_value = None
        client.adapter._app.invoke.return_value.full_chat.call = None

        self.assertTrue(await LIFECYCLE.leave_assistant(
            client, 1, lambda *args: None, timeout=0.05,
        ))
        client.mtproto.assert_not_awaited()

    async def test_cancelled_terminal_waits_for_cleanup(self):
        lifecycle = LIFECYCLE.CallLifecycle()
        await lifecycle.start(1)
        entered = asyncio.Event()
        release = asyncio.Event()
        finished = asyncio.Event()

        async def cleanup():
            entered.set()
            await release.wait()
            finished.set()

        task = asyncio.create_task(lifecycle.terminal(1, cleanup))
        await entered.wait()
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(finished.is_set())

    async def test_duplicate_stream_end_claim_is_ignored(self):
        lifecycle = LIFECYCLE.CallLifecycle()
        generation = await lifecycle.start(1)
        await lifecycle.ready(1, generation)
        self.assertEqual(
            await lifecycle.claim_advance(1, generation, stream_ended=True),
            generation,
        )
        self.assertIsNone(
            await lifecycle.claim_advance(1, generation, stream_ended=True)
        )

    async def test_stop_then_new_play_cannot_be_cleaned_by_old_generation(self):
        lifecycle = LIFECYCLE.CallLifecycle()
        old = await lifecycle.start(1)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def cleanup():
            entered.set()
            await release.wait()

        stopping = asyncio.create_task(lifecycle.terminal(1, cleanup, old))
        await entered.wait()
        starting = asyncio.create_task(lifecycle.start(1))
        await asyncio.sleep(0)
        self.assertFalse(starting.done())
        release.set()
        self.assertTrue(await stopping)
        new = await starting
        self.assertNotEqual(new, old)
        self.assertFalse(await lifecycle.cleanup_if_terminal(1, old, cleanup))

    async def test_delayed_end_is_ignored_during_direct_replacement(self):
        lifecycle = LIFECYCLE.CallLifecycle()
        old = await lifecycle.start(1)
        await lifecycle.ready(1, old)
        new = await lifecycle.start(1)
        await asyncio.sleep(0.8)  # exceeds the old arbitrary 0.75s grace
        self.assertIsNone(await lifecycle.claim_advance(1, stream_ended=True))
        await lifecycle.ready(1, new)
        self.assertEqual(
            await lifecycle.claim_advance(1, stream_ended=True), new)

    async def test_concurrent_native_installs_finish_in_request_order(self):
        lifecycle = LIFECYCLE.CallLifecycle()
        entered, release = asyncio.Event(), asyncio.Event()
        order = []

        async def old_play():
            entered.set()
            await release.wait()
            order.append("old")

        async def new_play():
            order.append("new")

        old = await lifecycle.start(1)
        first = asyncio.create_task(lifecycle.install(1, old, old_play))
        await entered.wait()
        new = await lifecycle.start(1)
        second = asyncio.create_task(lifecycle.install(1, new, new_play))
        await asyncio.sleep(0)
        self.assertFalse(second.done())
        release.set()
        self.assertFalse(await first)
        self.assertTrue(await second)
        self.assertEqual(order, ["old", "new"])

    async def test_stop_waits_for_old_install_before_new_install(self):
        lifecycle = LIFECYCLE.CallLifecycle()
        entered, release = asyncio.Event(), asyncio.Event()
        order = []

        async def old_play():
            entered.set()
            await release.wait()
            order.append("old")

        async def leave():
            order.append("leave")

        old = await lifecycle.start(1)
        installing = asyncio.create_task(lifecycle.install(1, old, old_play))
        await entered.wait()
        stopping = asyncio.create_task(lifecycle.terminal(1, leave))
        await asyncio.sleep(0)
        starting = asyncio.create_task(lifecycle.start(1))
        await asyncio.sleep(0)
        self.assertFalse(starting.done())
        release.set()
        self.assertFalse(await installing)
        self.assertTrue(await stopping)
        new = await starting

        async def new_play():
            order.append("new")

        self.assertTrue(await lifecycle.install(1, new, new_play))
        self.assertEqual(order, ["old", "leave", "new"])


class TgCallEndTests(unittest.IsolatedAsyncioTestCase):
    def make_call(self, items, loop=0):
        self.client = FakeClient()
        self.queue = FakeQueue(items)
        self.db = FakeDb(self.client, loop)
        CALLS.db = self.db
        CALLS.queue = self.queue
        CALLS.lang = pytypes.SimpleNamespace(
            get_lang=AsyncMock(return_value={
                "play_next": "next",
                "play_again": "again",
                "play_media": "{} {} {} {}",
                "play_skip_failed": "skip",
                "error_no_file": "no file {}",
            })
        )
        CALLS.app = pytypes.SimpleNamespace(
            send_message=AsyncMock(return_value=pytypes.SimpleNamespace(
                id=50, edit_text=AsyncMock())),
            delete_messages=AsyncMock(),
        )
        CALLS.buttons = pytypes.SimpleNamespace(
            controls=lambda chat_id, **kwargs: None
        )
        return CALLS.TgCall()

    @staticmethod
    def live_item(path="expired-feed"):
        item = Item("live")
        item.duration = "LIVE"
        item.view_count = "LIVE"
        item.url = "https://www.youtube.com/watch?v=2qsYNs7GpPo"
        item.file_path = path
        return item

    async def test_live_install_refreshes_stale_feed_without_fallback(self):
        call = self.make_call([])
        media = self.live_item()
        fresh = AsyncMock(side_effect=["fresh-feed-1", "fresh-feed-2"])
        fallback = AsyncMock(return_value="wrong-track-download")
        CALLS.yt = pytypes.SimpleNamespace(
            resolve_play_source=fresh,
            get_live=AsyncMock(),
            play_source=AsyncMock(return_value="wrong-play-source"),
            download_with_fallback=fallback,
        )
        self.client.play.side_effect = [
            CALLS.exceptions.NoAudioSourceFound(),
            None,
        ]
        generation = await call._lifecycle.start(1)
        message = pytypes.SimpleNamespace(edit_text=AsyncMock())

        result = await call._play_media(1, message, media, 0, generation)

        self.assertTrue(result)
        self.assertEqual(fresh.await_count, 2)
        self.assertEqual(media.file_path, "fresh-feed-2")
        fallback.assert_not_awaited()
        CALLS.yt.play_source.assert_not_awaited()
        CALLS.yt.get_live.assert_not_awaited()
        self.assertEqual(self.client.play.await_count, 2)

    async def test_queued_live_ignores_prefetched_feed_at_install(self):
        finished = Item("finished")
        media = self.live_item()
        call = self.make_call([finished, media])
        resolve = AsyncMock(return_value="fresh-queued-feed")
        CALLS.yt = pytypes.SimpleNamespace(resolve_play_source=resolve)
        await call._lifecycle.start(1)

        await call.play_next(1)

        resolve.assert_awaited_once()
        self.assertEqual(media.file_path, "fresh-queued-feed")
        self.client.play.assert_awaited_once()

    async def test_live_refresh_cannot_switch_track_identity(self):
        call = self.make_call([])
        media = self.live_item()
        original_id = media.id

        async def switch_upload(track, **kwargs):
            track.id = "different-broadcast"
            return "wrong-broadcast-feed"

        fallback = AsyncMock(return_value="alternate-download")
        CALLS.yt = pytypes.SimpleNamespace(
            resolve_play_source=AsyncMock(side_effect=switch_upload),
            download_with_fallback=fallback,
        )
        generation = await call._lifecycle.start(1)
        message = pytypes.SimpleNamespace(edit_text=AsyncMock())

        result = await call._play_media(1, message, media, 0, generation)

        self.assertFalse(result)
        self.assertEqual(media.id, original_id)
        self.assertIsNone(media.file_path)
        self.client.play.assert_not_awaited()
        fallback.assert_not_awaited()

    async def test_normal_end_with_no_queue_stops_and_leaves_immediately(self):
        call = self.make_call([Item("last")])
        await call._lifecycle.start(1)

        await call.play_next(1)

        self.assertEqual(self.db.removed, 1)
        self.assertEqual(self.queue.get_queue(1), [])
        self.client.native.assert_awaited_once()
        self.client.mtproto.assert_awaited_once()

    async def test_queue_loop_rotates_and_starts_next_without_leaving(self):
        first, second = Item("one"), Item("two")
        call = self.make_call([first, second], loop=-1)
        await call._lifecycle.start(1)
        call._play_media = AsyncMock()

        await call.play_next(1)

        self.assertEqual(self.queue.get_current(1), second)
        call._play_media.assert_awaited_once()
        self.client.native.assert_not_awaited()

    async def test_duplicate_stream_end_and_duplicate_stop_are_idempotent(self):
        first, second = Item("one"), Item("two")
        call = self.make_call([first, second])
        generation = await call._lifecycle.start(1)
        await call._lifecycle.ready(1, generation)
        call._play_media = AsyncMock()

        await asyncio.gather(
            call.play_next(1, stream_ended=True),
            call.play_next(1, stream_ended=True),
        )
        call._play_media.assert_awaited_once()

        await asyncio.gather(call.stop(1), call.stop(1))
        self.assertEqual(self.db.removed, 1)
        self.client.native.assert_awaited_once()

    async def test_long_failed_source_queue_is_iterative(self):
        items = [Item(str(i)) for i in range(1100)]
        for item in items:
            item.file_path = None
        call = self.make_call(items)
        CALLS.yt = pytypes.SimpleNamespace(play_source=AsyncMock(return_value=None))
        await call._lifecycle.start(1)
        await call.play_next(1)
        self.assertEqual(self.queue.get_queue(1), [])
        self.assertEqual(CALLS.yt.play_source.await_count, 1099)
        self.client.native.assert_awaited_once()

    async def test_thousand_resolvable_native_failures_are_iterative(self):
        # One current item has just ended; every following source resolves,
        # but native installation rejects it.  This used to recurse through
        # _recover_track_failure -> play_next until Python hit its stack cap.
        items = [Item("finished")] + [Item(f"failed-{i}") for i in range(1000)]
        call = self.make_call(items)
        self.client.play.side_effect = CALLS.ConnectionError("native failed")
        await call._lifecycle.start(1)

        await call.play_next(1)

        self.assertEqual(self.client.play.await_count, 1000)
        self.assertEqual(self.queue.get_queue(1), [])
        self.assertEqual(self.db.removed, 1)

    async def test_initial_native_failure_hands_off_to_iterative_driver(self):
        first, second = Item("first"), Item("second")
        call = self.make_call([first, second])
        self.client.play.side_effect = CALLS.ConnectionError("native failed")
        message = pytypes.SimpleNamespace(edit_text=AsyncMock())

        await call.play_media(1, message, first)

        # The first direct request fails, then the shared queue driver handles
        # the next item. Neither failure recursively invokes play_next.
        self.assertEqual(self.client.play.await_count, 2)
        self.assertEqual(self.queue.get_queue(1), [])
        self.assertEqual(self.db.removed, 1)

    async def test_source_resolver_exception_skips_and_finishes_queue(self):
        first, second = Item("finished"), Item("resolver-raises")
        second.file_path = None
        call = self.make_call([first, second])
        CALLS.yt = pytypes.SimpleNamespace(
            play_source=AsyncMock(side_effect=RuntimeError("resolver broken"))
        )
        await call._lifecycle.start(1)

        await call.play_next(1)

        CALLS.yt.play_source.assert_awaited_once()
        self.assertEqual(self.queue.get_queue(1), [])
        self.assertEqual(self.db.removed, 1)
        self.assertFalse(await call._lifecycle.installing(1))

    async def test_source_resolver_cancellation_is_not_swallowed(self):
        first, second = Item("finished"), Item("resolver-cancelled")
        second.file_path = None
        call = self.make_call([first, second])
        CALLS.yt = pytypes.SimpleNamespace(
            play_source=AsyncMock(side_effect=asyncio.CancelledError())
        )
        generation = await call._lifecycle.start(1)

        with self.assertRaises(asyncio.CancelledError):
            await call.play_next(1)

        # Advancing claimed the old generation and installed a replacement
        # generation before resolution began; cancellation must not be
        # mistaken for a failed source or terminal cleanup.
        state = call._lifecycle._states[1]
        self.assertNotEqual(state.generation, generation)
        self.assertTrue(state.active)
        self.assertTrue(state.installing)

    async def test_all_failed_queue_loop_stops_after_one_round(self):
        items = [Item("one"), Item("two")]
        for item in items:
            item.file_path = None
        call = self.make_call(items, loop=-1)
        CALLS.yt = pytypes.SimpleNamespace(play_source=AsyncMock(return_value=None))
        await call._lifecycle.start(1)
        await call.play_next(1)
        self.assertEqual(CALLS.yt.play_source.await_count, 2)
        self.client.native.assert_awaited_once()

    async def test_process_failure_recovery_advances_without_terminal_cleanup(self):
        first, second = Item("one"), Item("two")
        call = self.make_call([first, second])
        generation = await call._lifecycle.start(1)
        message = pytypes.SimpleNamespace(edit_text=AsyncMock())
        call.play_next = AsyncMock()

        failed = await call._recover_track_failure(1, message, generation)

        self.assertEqual(self.queue.get_queue(1), [first, second])
        self.assertEqual(self.db.removed, 0)
        self.client.native.assert_not_awaited()
        self.assertFalse(failed)
        call.play_next.assert_not_awaited()

if __name__ == "__main__":
    unittest.main()