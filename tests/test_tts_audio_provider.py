import asyncio
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent.parent / "research" / "tools"))
from tts_module_harness import load_tts  # noqa: E402


tts = load_tts()


class _User:
    def __init__(self, uid):
        self.id = uid


class _Message:
    async def reply_text(self, *args, **kwargs):
        raise AssertionError("missing-provider preflight should not send a message")


class _Callback:
    def __init__(self):
        self.data = "tts|s:sad|audio-test"
        self.from_user = _User(7)
        self.message = _Message()
        self.answers = []

    async def answer(self, text="", **kwargs):
        self.answers.append((text, kwargs.get("show_alert", False)))


class _ShortMessage:
    def __init__(self, command, text, *, fail_delete=False):
        self.command = command
        self.text = text
        self.caption = None
        self.reply_to_message = None
        self.lang = {}
        self.voice = self.audio = self.video_note = self.video = None
        self.from_user = _User(7)
        self.chat = types.SimpleNamespace(id=700)
        self.id = 42
        self.fail_delete = fail_delete
        self.deleted = False
        self.replies = []
        self.events = []

    async def delete(self):
        self.events.append("delete")
        if self.fail_delete:
            raise RuntimeError("bot is not allowed to delete messages")
        self.deleted = True

    async def reply_text(self, text, **kwargs):
        self.events.append("picker" if kwargs.get("reply_markup") else "reply")
        self.replies.append((text, kwargs))


class TtsAudioProviderTests(unittest.TestCase):
    def setUp(self):
        self.mv = sys.modules["bobby.plugins.myvoice"]
        self.mv._BUSY.clear()
        self.mv._PUBLIC_SHOTS.clear()
        self.mv._LAST_SHOT.clear()
        tts.app.sent.clear()
        tts._PENDING.clear()
        tts._NO_MUSIC.clear()
        tts._MEME_LAST.clear()

    def test_shorthand_default_uses_current_neerja_edge_id(self):
        self.assertEqual(tts.DEFAULT_VOICEOVER, "e:neerja")
        self.assertEqual(tts.VOICES["neerja"][1], "en-IN-NeerjaExpressiveNeural")
        self.assertTrue(tts.preset_reference_path("e:neerja").endswith("e_neerja_expressive.wav"))

    def test_direct_key_defaults_to_openai_endpoint(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "direct-key"}, clear=True):
            self.assertEqual(tts._audio_provider(), ("https://api.openai.com/v1", "direct-key"))

    def test_direct_endpoint_wins_and_proxy_remains_fallback(self):
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "direct-key",
            "OPENAI_BASE_URL": "https://gateway.example/v1/",
            "AI_INTEGRATIONS_OPENAI_BASE_URL": "https://proxy.example/v1",
            "AI_INTEGRATIONS_OPENAI_API_KEY": "proxy-key",
        }, clear=True):
            self.assertEqual(tts._audio_provider(), ("https://gateway.example/v1", "direct-key"))
        with patch.dict(os.environ, {
            "AI_INTEGRATIONS_OPENAI_BASE_URL": "https://proxy.example/v1/",
            "AI_INTEGRATIONS_OPENAI_API_KEY": "proxy-key",
        }, clear=True):
            self.assertEqual(tts._audio_provider(), ("https://proxy.example/v1", "proxy-key"))

    def test_song_missing_config_alert_does_not_consume_cooldown(self):
        async def exercise():
            tts._PENDING.clear()
            tts._MEME_LAST.clear()
            tts._PENDING["audio-test"] = ("a sad line", 7, time.monotonic())
            callback = _Callback()
            with patch.dict(os.environ, {}, clear=True):
                await tts._tts_cb(None, callback)
            return callback

        callback = asyncio.run(exercise())
        self.assertEqual(callback.answers, [(tts.AUDIO_UNAVAILABLE_TEXT, True)])
        self.assertNotIn(7, tts._MEME_LAST)

    def test_stale_saved_voice_alert_keeps_record_and_gc_keep_list(self):
        async def exercise():
            store = tts.voice_store
            old_dir, old_file = store.STORE_DIR, store.STORE_FILE
            tmp = tempfile.TemporaryDirectory()
            try:
                store.STORE_DIR = Path(tmp.name) / "data"
                store.STORE_FILE = store.STORE_DIR / "voice_clones.json"
                store.STORE_DIR.mkdir(parents=True)
                old_root = "/home/runner/workspace/bots/bobby_music/data/voices"
                primary = f"{old_root}/primary.wav"
                extra = f"{old_root}/extra.wav"
                store.STORE_FILE.write_text(json.dumps({
                    "7": {
                        "engine": "local",
                        "label": "Restored later",
                        "created": 1,
                        "sample": primary,
                        "extra": [extra],
                    }
                }))
                tts._PENDING.clear()
                tts._PENDING["stale-test"] = ("hello", 7, time.monotonic())
                callback = _Callback()
                callback.data = "tts|u:7|stale-test"
                await tts._tts_cb(None, callback)
                refs = store.samples_of(store.get(7))
                return callback, store.get(7), refs, store.samples()
            finally:
                store.STORE_DIR, store.STORE_FILE = old_dir, old_file
                tmp.cleanup()

        callback, record, refs, keep = asyncio.run(exercise())
        self.assertTrue(callback.answers[-1][1])
        self.assertIn("missing", callback.answers[-1][0])
        self.assertIsNotNone(record)
        self.assertEqual(refs, [
            str(Path(record["sample"])),
            str(Path(record["extra"][0])),
        ])
        self.assertEqual(keep, set(refs))

    def test_vot_shows_saved_and_preset_choices_before_deleting_command(self):
        message = _ShortMessage(["vot", "hello"], "/vot hello <3 & welcome")
        saved = [("7", "Saved voice 1"), ("7/2", "Saved voice 2")]

        async def exercise():
            with patch.object(tts, "shorthand_text", new=AsyncMock()) as direct, \
                 patch.object(tts, "_saved_voices", return_value=saved):
                await tts._tts(None, message)
                return direct

        direct = asyncio.run(exercise())
        direct.assert_not_awaited()
        self.assertEqual(message.events, ["picker", "delete"])
        self.assertTrue(message.deleted)
        text, options = message.replies[0]
        self.assertIn("hello &lt;3 &amp; welcome", text)
        self.assertIs(options["quote"], False)
        self.assertEqual(options["parse_mode"], tts.enums.ParseMode.HTML)
        buttons = [b for row in options["reply_markup"].inline_keyboard for b in row]
        self.assertTrue(any(b.callback_data.startswith("tts|e:") for b in buttons))
        self.assertTrue(any(b.text == "Saved voice 1" for b in buttons))
        self.assertTrue(any(b.text == "Saved voice 2" for b in buttons))
        self.assertEqual(len(tts._PENDING), 1)
        key = next(iter(tts._PENDING))
        self.assertIn(f"tts|u:7/2|{key}", [b.callback_data for b in buttons])
        self.assertEqual(tts._PENDING[key][:2], ("hello <3 & welcome", 7))
        self.assertFalse(tts.app.sent)

    def test_vot_reply_preserves_source_message_and_its_text(self):
        source = _ShortMessage([], "the original words")
        source.from_user = _User(99)
        message = _ShortMessage(["vot"], "/vot")
        message.reply_to_message = source
        with patch.object(tts, "_saved_voices", return_value=[]):
            asyncio.run(tts._tts(None, message))
        self.assertTrue(message.deleted)
        self.assertFalse(source.deleted)
        self.assertEqual(next(iter(tts._PENDING.values()))[:2], ("the original words", 7))

    def test_vot_delete_permission_failure_keeps_usable_picker(self):
        message = _ShortMessage(["vot", "hello"], "/vot hello", fail_delete=True)
        with patch.object(tts, "_saved_voices", return_value=[]):
            asyncio.run(tts._tts(None, message))
        self.assertFalse(message.deleted)
        self.assertEqual(len(message.replies), 1)
        self.assertIsNotNone(message.replies[0][1]["reply_markup"])
        self.assertEqual(len(tts._PENDING), 1)

    def test_vot_picker_send_failure_keeps_command_and_clears_pending(self):
        message = _ShortMessage(["vot", "hello"], "/vot hello")
        with patch.object(message, "reply_text", new=AsyncMock(side_effect=RuntimeError("send failed"))), \
             patch.object(tts, "_saved_voices", return_value=[]):
            with self.assertRaises(RuntimeError):
                asyncio.run(tts._tts(None, message))
        self.assertFalse(message.deleted)
        self.assertFalse(tts._PENDING)

    def test_vot_cancelled_picker_send_keeps_command_and_clears_pending(self):
        message = _ShortMessage(["vot", "hello"], "/vot hello")
        with patch.object(message, "reply_text", new=AsyncMock(side_effect=asyncio.CancelledError())), \
             patch.object(tts, "_saved_voices", return_value=[]):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(tts._tts(None, message))
        self.assertFalse(message.deleted)
        self.assertFalse(tts._PENDING)

    def test_bare_vot_keeps_command_and_shows_usage(self):
        message = _ShortMessage(["vot"], "/vot")
        asyncio.run(tts._tts(None, message))
        self.assertFalse(message.deleted)
        self.assertEqual(message.replies[0][0], tts.USAGE_TEXT)
        self.assertFalse(tts._PENDING)

    def test_vot_selected_saved_voice_remains_bound_to_requester(self):
        message = _ShortMessage(["vot", "hello"], "/vot hello")

        async def exercise():
            with patch.object(tts, "_saved_voices", return_value=[("7/2", "Saved voice 2")]):
                await tts._tts(None, message)
            key = next(iter(tts._PENDING))
            callback = _Callback()
            callback.data = f"tts|u:7/2|{key}"
            with patch.object(tts, "_saved_voice", new=AsyncMock()) as chosen:
                callback.from_user = _User(99)
                await tts._tts_cb(None, callback)
                chosen.assert_not_awaited()
                callback.from_user = _User(7)
                await tts._tts_cb(None, callback)
                chosen.assert_awaited_once_with(callback, "u:7/2", key, "hello")
        asyncio.run(exercise())

    def test_long_text_command_keeps_its_existing_command_and_picker(self):
        message = _ShortMessage(["voiceovertext", "hello"], "/voiceovertext hello")
        with patch.object(tts, "_saved_voices", return_value=[]):
            asyncio.run(tts._tts(None, message))
        self.assertFalse(message.deleted)
        self.assertIsNotNone(message.replies[0][1]["reply_markup"])
        self.assertNotIn("quote", message.replies[0][1])

    def test_shorthand_text_deletes_own_command_and_sends_audio_only(self):
        class _Communicate:
            def __init__(self, *_args, **_kwargs):
                pass

            async def save(self, path):
                Path(path).write_bytes(b"generated")

        message = _ShortMessage(["voa", "private words"], "/voa private words")
        fake_edge = types.SimpleNamespace(Communicate=_Communicate)
        app = tts.app
        app.sent.clear()

        async def exercise():
            with patch.object(tts, "shorthand_text_available", return_value=True), \
                 patch.object(tts.mastering, "master", new=AsyncMock()), \
                 patch.dict(sys.modules, {"edge_tts": fake_edge}):
                return await tts.shorthand_text(message, "private words")

        self.assertTrue(asyncio.run(exercise()))
        self.assertTrue(message.deleted)
        self.assertEqual([kind for kind, _, _ in app.sent], ["audio"])
        payload = app.sent[0][2]
        self.assertTrue(payload["path"].endswith(".mp3"))
        self.assertNotIn("caption", payload)
        self.assertNotIn("title", payload)
        self.assertNotIn("performer", payload)
        self.assertNotIn(7, self.mv._BUSY)
        self.assertNotIn(7, self.mv._PUBLIC_SHOTS)
        self.assertIn(7, self.mv._LAST_SHOT)

    def test_shorthand_text_keeps_private_command_when_delete_is_forbidden(self):
        message = _ShortMessage(["voa", "private words"], "/voa private words", fail_delete=True)
        app = tts.app
        app.sent.clear()

        async def exercise():
            with patch.object(tts, "shorthand_text_available", return_value=True):
                return await tts.shorthand_text(message, "private words")

        self.assertFalse(asyncio.run(exercise()))
        self.assertFalse(message.deleted)
        self.assertEqual(len(message.replies), 1)
        self.assertIn("remove that command", message.replies[0][0])
        self.assertFalse(app.sent)
        self.assertNotIn(7, self.mv._BUSY)
        self.assertNotIn(7, self.mv._PUBLIC_SHOTS)
        self.assertNotIn(7, self.mv._LAST_SHOT)

    def test_shorthand_text_provider_failure_does_not_delete_or_claim_audio(self):
        message = _ShortMessage(["voa", "private words"], "/voa private words")
        app = tts.app
        app.sent.clear()

        async def exercise():
            with patch.object(tts, "shorthand_text_available", return_value=False):
                return await tts.shorthand_text(message, "private words")

        self.assertFalse(asyncio.run(exercise()))
        self.assertFalse(message.deleted)
        self.assertIn("unavailable", message.replies[0][0])
        self.assertFalse(app.sent)

    def test_shorthand_claim_is_shared_and_atomic_for_concurrent_requests(self):
        class _Communicate:
            started = None
            release = None

            def __init__(self, *_args, **_kwargs):
                pass

            async def save(self, path):
                self.started.set()
                await self.release.wait()
                Path(path).write_bytes(b"generated")

        first = _ShortMessage(["voa", "first"], "/voa first")
        second = _ShortMessage(["voa", "second"], "/voa second")
        Communicate = _Communicate
        Communicate.started = asyncio.Event()
        Communicate.release = asyncio.Event()

        async def exercise():
            fake_edge = types.SimpleNamespace(Communicate=Communicate)
            with patch.object(tts, "shorthand_text_available", return_value=True), \
                 patch.object(tts.mastering, "master", new=AsyncMock()), \
                 patch.dict(sys.modules, {"edge_tts": fake_edge}):
                running = asyncio.create_task(tts.shorthand_text(first, "first"))
                await Communicate.started.wait()
                blocked = await tts.shorthand_text(second, "second")
                Communicate.release.set()
                return blocked, await running

        blocked, made = asyncio.run(exercise())
        self.assertFalse(blocked)
        self.assertTrue(made)
        self.assertTrue(first.deleted)
        self.assertFalse(second.deleted)
        self.assertIn("previous clip", second.replies[0][0])
        self.assertFalse(self.mv._BUSY)
        self.assertFalse(self.mv._PUBLIC_SHOTS)

    def test_shorthand_cancellation_releases_public_claim_and_cooldown(self):
        class _Communicate:
            started = None

            def __init__(self, *_args, **_kwargs):
                pass

            async def save(self, _path):
                self.started.set()
                await asyncio.Event().wait()

        Communicate = _Communicate
        Communicate.started = asyncio.Event()
        message = _ShortMessage(["voa", "cancel"], "/voa cancel")

        async def exercise():
            fake_edge = types.SimpleNamespace(Communicate=Communicate)
            with patch.object(tts, "shorthand_text_available", return_value=True), \
                 patch.dict(sys.modules, {"edge_tts": fake_edge}):
                running = asyncio.create_task(tts.shorthand_text(message, "cancel"))
                await Communicate.started.wait()
                running.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await running

        asyncio.run(exercise())
        self.assertTrue(message.deleted)
        self.assertFalse(self.mv._BUSY)
        self.assertFalse(self.mv._PUBLIC_SHOTS)
        self.assertNotIn(7, self.mv._LAST_SHOT)


if __name__ == "__main__":
    unittest.main()