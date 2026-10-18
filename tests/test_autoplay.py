"""Autoplay safety: a background pick may never fight a real request, and
it may never replay the song that just finished."""

import asyncio
import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutoplayTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "bobby",
                "bobby.core",
                "bobby.core.ytmusic",
                "bobby.helpers",
                "bobby.plugins",
                "bobby.plugins.play",
            )
        }

        cls.state = types.SimpleNamespace(
            sent=[],
            deleted=[],
            played=[],
            entered=[],
            dropped=[],
            tracks=[],
            cancel_before_queue=None,
            cancel_after_queue=None,
            related=[],
            searched=[],
            resolve={},
            autoplay_on=True,
            in_call=False,
            queued=[],
        )
        state = cls.state

        async def _send_message(chat_id, text, **kwargs):
            state.sent.append((chat_id, text))
            return types.SimpleNamespace(
                id=100 + len(state.sent),
                chat=types.SimpleNamespace(id=chat_id),
                date=None,
            )

        async def _delete_messages(chat_id, message_id, **kwargs):
            state.deleted.append((chat_id, message_id))

        async def _get_me():
            return types.SimpleNamespace(id=42, mention="bot")

        async def _get_autoplay(chat_id):
            return state.autoplay_on

        async def _get_call(chat_id):
            return state.in_call

        async def _search(query, message_id, **kwargs):
            state.searched.append(query)
            resolved = state.resolve.get(query)
            return types.SimpleNamespace(id=resolved) if resolved else None

        async def _related(seed, limit=0, max_sec=0):
            return list(state.related)

        async def _play_hndlr(client, message):
            # mirrors the real handler: awaits, claim, queue insertion,
            # source resolution, a final claim, then playback
            state.entered.append(message.text)
            if state.cancel_before_queue is not None:
                state.cancel_before_queue()
                state.cancel_before_queue = None
            await asyncio.sleep(0)
            claim = getattr(message, "autoplay_claim", None)
            if claim is not None and not await claim():
                state.dropped.append(message.text)
                return
            state.queued.append(message.text)           # queue.add
            if state.cancel_after_queue is not None:
                state.cancel_after_queue()
                state.cancel_after_queue = None
            await asyncio.sleep(0)                      # source resolution
            if claim is not None and not await claim(final=True):
                state.queued.remove(message.text)       # queue.drop_item
                state.dropped.append(message.text)
                return
            state.played.append(message.text)
            state.tracks.append(getattr(message, "autoplay_track", None))

        bobby = types.ModuleType("bobby")
        bobby.app = types.SimpleNamespace(
            send_message=_send_message,
            delete_messages=_delete_messages,
            get_me=_get_me,
            me=None,
        )
        bobby.config = types.SimpleNamespace(DURATION_LIMIT=3600)
        bobby.logger = logging.getLogger("autoplay-test")
        bobby.db = types.SimpleNamespace(
            get_autoplay=_get_autoplay, get_call=_get_call
        )
        bobby.queue = types.SimpleNamespace(get_queue=lambda chat_id: state.queued)
        bobby.yt = types.SimpleNamespace(search=_search)

        core = types.ModuleType("bobby.core")
        core.__path__ = []
        ytmusic = types.ModuleType("bobby.core.ytmusic")
        ytmusic.related = _related

        helpers = types.ModuleType("bobby.helpers")
        helpers.__path__ = []
        helpers.buttons = types.SimpleNamespace(
            recs_markup=lambda *args, **kwargs: None
        )

        plugins = types.ModuleType("bobby.plugins")
        plugins.__path__ = []
        play = types.ModuleType("bobby.plugins.play")
        play.play_hndlr = _play_hndlr

        sys.modules.update(
            {
                "bobby": bobby,
                "bobby.core": core,
                "bobby.core.ytmusic": ytmusic,
                "bobby.helpers": helpers,
                "bobby.plugins": plugins,
                "bobby.plugins.play": play,
            }
        )

        spec = importlib.util.spec_from_file_location(
            "bobby_test_recs", ROOT / "bobby" / "helpers" / "_recs.py"
        )
        cls.recs = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.recs
        spec.loader.exec_module(cls.recs)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("bobby_test_recs", None)

    def setUp(self):
        state = self.state
        state.sent.clear()
        state.deleted.clear()
        state.played.clear()
        state.entered.clear()
        state.dropped.clear()
        state.tracks.clear()
        state.cancel_before_queue = None
        state.cancel_after_queue = None
        state.searched.clear()
        state.resolve.clear()
        state.related = []
        state.autoplay_on = True
        state.in_call = False
        state.queued.clear()
        self.recs._cache.clear()
        self.recs._gen.clear()
        self.recs._played.clear()
        self.recs._cards.clear()

    async def _run_autoplay(self, chat_id=-100123):
        self.recs.autoplay(chat_id, "SEEDSEED001", {})
        await asyncio.gather(*list(self.recs._tasks))

    async def test_plays_the_first_fresh_related_song(self):
        self.state.related = [
            {"id": "RELATED0001", "title": "Next Song", "artists": "Someone"}
        ]
        self.state.resolve["Next Song Someone"] = "RESOLVED001"

        await self._run_autoplay()

        self.assertEqual(self.state.played, ["/play Next Song Someone"])
        self.assertEqual(len(self.state.sent), 1)
        # the validated track itself is handed to /play — no second search
        self.assertEqual([t.id for t in self.state.tracks], ["RESOLVED001"])
        self.assertEqual(self.state.searched, ["Next Song Someone"])

    async def test_a_recommendation_resolving_to_the_seed_is_skipped(self):
        self.state.related = [
            {"id": "RELATED0001", "title": "Same Song Reupload", "artists": ""},
            {"id": "RELATED0002", "title": "Truly Next", "artists": ""},
        ]
        self.state.resolve["Same Song Reupload"] = "SEEDSEED001"
        self.state.resolve["Truly Next"] = "RESOLVED002"

        await self._run_autoplay()

        self.assertEqual(self.state.played, ["/play Truly Next"])

    async def test_a_song_already_auto_played_is_not_repeated(self):
        chat_id = -100123
        self.state.related = [
            {"id": "RELATED0001", "title": "First", "artists": ""},
            {"id": "RELATED0002", "title": "Second", "artists": ""},
        ]
        self.state.resolve["First"] = "RESOLVED001"
        self.state.resolve["Second"] = "RESOLVED002"

        await self._run_autoplay(chat_id)
        self.state.queued.clear()   # the first autoplay song finished
        await self._run_autoplay(chat_id)

        self.assertEqual(
            self.state.played, ["/play First", "/play Second"]
        )

    async def test_cancel_stops_a_pending_pick(self):
        chat_id = -100123
        self.state.related = [
            {"id": "RELATED0001", "title": "Next Song", "artists": ""}
        ]
        self.state.resolve["Next Song"] = "RESOLVED001"

        self.recs.autoplay(chat_id, "SEEDSEED001", {})
        self.recs.cancel(chat_id)   # /stop, /play or autoplay off
        await asyncio.gather(*list(self.recs._tasks))

        self.assertEqual(self.state.played, [])
        self.assertEqual(self.state.sent, [])

    async def test_a_running_voice_chat_blocks_autoplay(self):
        self.state.related = [
            {"id": "RELATED0001", "title": "Next Song", "artists": ""}
        ]
        self.state.resolve["Next Song"] = "RESOLVED001"
        self.state.in_call = True   # a real /play already started something

        await self._run_autoplay()

        self.assertEqual(self.state.played, [])

    async def test_autoplay_turned_off_mid_lookup_does_not_play(self):
        chat_id = -100123
        self.state.related = [
            {"id": "RELATED0001", "title": "Next Song", "artists": ""}
        ]
        self.state.resolve["Next Song"] = "RESOLVED001"
        self.state.autoplay_on = False

        await self._run_autoplay(chat_id)

        self.assertEqual(self.state.played, [])

    async def test_cancellation_after_the_handler_started_drops_the_track(self):
        chat_id = -100123
        self.state.related = [
            {"id": "RELATED0001", "title": "Next Song", "artists": ""}
        ]
        self.state.resolve["Next Song"] = "RESOLVED001"
        # a real /play lands after the autoplay handler already started
        self.state.cancel_before_queue = lambda: self.recs.cancel(chat_id)

        await self._run_autoplay(chat_id)

        self.assertEqual(self.state.entered, ["/play Next Song"])
        self.assertEqual(self.state.dropped, ["/play Next Song"])
        self.assertEqual(self.state.played, [])
        # the autoplay notice is cleaned up after losing the race
        self.assertTrue(self.state.deleted)

    async def test_cancel_after_queue_insertion_removes_the_track(self):
        chat_id = -100123
        self.state.related = [
            {"id": "RELATED0001", "title": "Next Song", "artists": ""}
        ]
        self.state.resolve["Next Song"] = "RESOLVED001"
        # /stop lands while the source is still being resolved
        self.state.cancel_after_queue = lambda: self.recs.cancel(chat_id)

        await self._run_autoplay(chat_id)

        self.assertEqual(self.state.dropped, ["/play Next Song"])
        self.assertEqual(self.state.played, [])
        self.assertEqual(self.state.queued, [])     # taken back out
        self.assertTrue(self.state.deleted)


    async def test_nothing_fresh_falls_back_to_the_suggestion_card(self):
        self.state.related = [
            {"id": "RELATED0001", "title": "Dead End", "artists": ""}
        ]
        # search resolves nothing for it → no playable candidate left

        await self._run_autoplay()

        self.assertEqual(self.state.played, [])
        self.assertEqual(len(self.state.sent), 1)   # the card, not a play


if __name__ == "__main__":
    unittest.main(verbosity=2)
