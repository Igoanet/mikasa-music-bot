"""Offline regressions for scoped bot-exit assistant cleanup."""

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "bobby_group_exit_test_module",
    ROOT / "bobby" / "core" / "group_exit.py",
)
GROUP_EXIT = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = GROUP_EXIT
SPEC.loader.exec_module(GROUP_EXIT)


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, *args, **kwargs):
        self.warnings.append((args, kwargs))


class FakeAssistant:
    def __init__(self, failures=0, entered=None):
        self.leave_calls = []
        self.failures = failures
        self.entered = entered

    async def leave_chat(self, chat_id):
        self.leave_calls.append(chat_id)
        if self.entered is not None:
            self.entered.set()
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary")


class FakeBinding:
    """One entry in TgCall.clients: a PyTgCalls binding, not the controller."""


class FakeCalls:
    def __init__(self, error=None, entered=None, release=None):
        self.error = error
        self.entered = entered
        self.release = release
        self.binding = FakeBinding()
        self.clients = [self.binding]
        self.stop_calls = []

    async def stop(
        self,
        chat_id,
        expected_generation=None,
        assistant_client=None,
    ):
        self.stop_calls.append(
            (chat_id, expected_generation, assistant_client)
        )
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error:
            raise self.error


def member(user_id, status):
    return types.SimpleNamespace(
        user=types.SimpleNamespace(id=user_id),
        status=status,
    )


def update(chat_id, user_id, old_status, new_status, *, omit_new=False):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(id=chat_id, type="supergroup"),
        old_chat_member=member(user_id, old_status),
        new_chat_member=None if omit_new else member(user_id, new_status),
    )


class GroupExitTests(unittest.IsolatedAsyncioTestCase):
    def make_manager(self, mapped=1, calls=None, failures=0, leave_entered=None):
        assistant = FakeAssistant(failures, leave_entered)
        bot = types.SimpleNamespace(id=99)
        db = types.SimpleNamespace(
            assistant={},
            _data={"assistant": {str(-100): mapped} if mapped is not None else {}},
        )
        userbot = types.SimpleNamespace(clients=[assistant])
        calls = calls or FakeCalls()
        calls._lifecycle = types.SimpleNamespace(
            _states={
                -100: types.SimpleNamespace(generation=7),
            }
        )
        manager = GROUP_EXIT.GroupExitCleanup(
            bot,
            db,
            userbot,
            calls,
            FakeLogger(),
            timeout=0.05,
            retry_delay=0,
        )
        return manager, assistant, db, calls

    async def test_removed_bot_cleans_only_mapped_assistant(self):
        calls = FakeCalls()
        manager, assistant, _, _ = self.make_manager(calls=calls)

        self.assertTrue(
            await manager.handle_chat_member_update(
                update(-100, 99, "member", "left")
            )
        )

        self.assertEqual(assistant.leave_calls, [-100])
        self.assertEqual(calls.stop_calls[0][0], -100)
        self.assertEqual(calls.stop_calls[0][1], 7)
        self.assertIs(calls.stop_calls[0][2], calls.binding)

    async def test_kicked_and_voluntary_paths_are_supported(self):
        for new_status in ("banned", "left"):
            manager, assistant, _, _ = self.make_manager(calls=FakeCalls())
            await manager.handle_chat_member_update(
                update(-100, 99, "administrator", new_status)
            )
            self.assertEqual(assistant.leave_calls, [-100])

        manager, assistant, _, _ = self.make_manager(calls=FakeCalls())
        await manager.on_bot_leave(-100)
        self.assertEqual(assistant.leave_calls, [-100])

    async def test_idle_chat_snapshots_generation_zero_not_any_future_play(self):
        calls = FakeCalls()
        manager, assistant, _, _ = self.make_manager(calls=calls)
        calls._lifecycle._states.clear()
        await manager.on_bot_leave(-100)
        self.assertEqual(calls.stop_calls[0][1], 0)
        self.assertEqual(assistant.leave_calls, [-100])

    async def test_removed_parser_shape_with_no_new_member_is_supported(self):
        manager, assistant, _, _ = self.make_manager(calls=FakeCalls())
        await manager.handle_chat_member_update(
            update(-100, 99, "member", None, omit_new=True)
        )
        self.assertEqual(assistant.leave_calls, [-100])

    async def test_self_left_service_message_is_a_fallback_only_for_this_bot(self):
        manager, assistant, _, _ = self.make_manager(calls=FakeCalls())
        message = types.SimpleNamespace(
            chat=types.SimpleNamespace(id=-100, type="group"),
            left_chat_member=types.SimpleNamespace(id=99),
        )
        self.assertTrue(await manager.handle_left_service_message(message))
        self.assertEqual(assistant.leave_calls, [-100])

        manager, assistant, _, _ = self.make_manager(calls=FakeCalls())
        message.left_chat_member.id = 1234
        self.assertFalse(await manager.handle_left_service_message(message))
        self.assertEqual(assistant.leave_calls, [])

    async def test_other_member_and_promotions_are_ignored(self):
        calls = FakeCalls()
        manager, assistant, _, _ = self.make_manager(calls=calls)

        self.assertFalse(
            await manager.handle_chat_member_update(
                update(-100, 1234, "member", "left")
            )
        )
        self.assertFalse(
            await manager.handle_chat_member_update(
                update(-100, 99, "member", "administrator")
            )
        )
        self.assertEqual(assistant.leave_calls, [])
        self.assertEqual(calls.stop_calls, [])

    async def test_duplicate_events_are_idempotent(self):
        manager, assistant, _, _ = self.make_manager(calls=FakeCalls())
        event = update(-100, 99, "member", "left")

        await asyncio.gather(
            manager.handle_chat_member_update(event),
            manager.handle_chat_member_update(event),
        )

        self.assertEqual(assistant.leave_calls, [-100])

    async def test_idle_chat_and_no_assignment_do_not_allocate(self):
        manager, assistant, db, _ = self.make_manager(mapped=None)
        await manager.handle_chat_member_update(
            update(-100, 99, "member", "left")
        )
        self.assertEqual(assistant.leave_calls, [])
        self.assertEqual(db.assistant, {})

    async def test_failed_voice_cleanup_still_leaves_group(self):
        calls = FakeCalls(error=RuntimeError("native teardown"))
        manager, assistant, _, _ = self.make_manager(calls=calls)

        await manager.handle_chat_member_update(
            update(-100, 99, "member", "banned")
        )

        self.assertEqual(assistant.leave_calls, [-100])

    async def test_retry_budget_is_bounded(self):
        manager, assistant, _, _ = self.make_manager(
            calls=FakeCalls(), failures=2
        )
        await manager.handle_chat_member_update(
            update(-100, 99, "member", "left")
        )
        self.assertEqual(assistant.leave_calls, [-100, -100])

    async def test_failed_leave_does_not_retry_after_rejoin(self):
        first_leave = asyncio.Event()
        manager, assistant, _, _ = self.make_manager(
            calls=FakeCalls(),
            failures=1,
            leave_entered=first_leave,
        )
        exiting = asyncio.create_task(
            manager.handle_chat_member_update(
                update(-100, 99, "member", "left")
            )
        )
        await first_leave.wait()
        await manager.mark_bot_joined(-100)
        await exiting
        self.assertEqual(assistant.leave_calls, [-100])

    async def test_rejoin_invalidates_stale_exit_cleanup(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = FakeCalls(entered=entered, release=release)
        manager, assistant, _, _ = self.make_manager(calls=calls)

        exiting = asyncio.create_task(
            manager.handle_chat_member_update(
                update(-100, 99, "member", "left")
            )
        )
        await entered.wait()
        await manager.mark_bot_joined(-100)
        release.set()
        await exiting

        self.assertEqual(assistant.leave_calls, [])

    async def test_fresh_membership_probe_blocks_stale_leave_without_update(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = FakeCalls(entered=entered, release=release)
        manager, assistant, _, _ = self.make_manager(calls=calls)
        manager.bot.get_chat_member = AsyncMock(
            return_value=member(99, "member")
        )

        await manager.handle_chat_member_update(
            update(-100, 99, "member", "left")
        )

        self.assertEqual(assistant.leave_calls, [])
        self.assertEqual(calls.stop_calls, [])

    async def test_reconciliation_requires_proof_of_nonmembership(self):
        manager, assistant, _, _ = self.make_manager(calls=FakeCalls())
        manager.bot.get_chat_member = AsyncMock(
            side_effect=PermissionError("not allowed")
        )
        self.assertFalse(await manager.reconcile_chat(-100))
        self.assertEqual(assistant.leave_calls, [])

        manager.bot.get_chat_member = AsyncMock(
            return_value=member(99, "member")
        )
        self.assertFalse(await manager.reconcile_chat(-100))
        self.assertEqual(assistant.leave_calls, [])

        manager.bot.get_chat_member = AsyncMock(
            return_value=member(99, "left")
        )
        self.assertTrue(await manager.reconcile_chat(-100))
        self.assertEqual(assistant.leave_calls, [-100])

    async def test_persisted_mapping_is_snapshotted_without_populating_cache(self):
        manager, assistant, db, _ = self.make_manager(calls=FakeCalls())
        await manager.handle_chat_member_update(
            update(-100, 99, "member", "left")
        )
        self.assertEqual(db.assistant, {})
        self.assertEqual(db._data["assistant"], {"-100": 1})
        self.assertEqual(assistant.leave_calls, [-100])


if __name__ == "__main__":
    unittest.main()