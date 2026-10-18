"""Offline singing regressions: never contact providers or Telegram."""
import asyncio
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


class SingingProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        tts._PENDING.clear()
        tts._MEME_LAST.clear()
        tts._NO_MUSIC.clear()

    async def test_every_song_uses_singing_tags_without_changing_lyrics(self):
        self.assertEqual(set(tts.SONG_VOICES), set(tts.eleven._SONG_PERFORMANCES))
        text = "नीला आसमान, प्यारी सुबह!"
        with patch.object(tts.eleven, "speak_voice", new=AsyncMock(return_value=b"song")) as synth:
            for style in tts.SONG_VOICES:
                with self.subTest(style=style):
                    synth.reset_mock()
                    self.assertEqual(await tts.eleven.sing(style, text), b"song")
                    args = synth.await_args
                    self.assertEqual(args.args[1], text)
                    self.assertIn("[singing]", args.args[2])
                    self.assertIn(args.args[0], tts.eleven.FREE_VOICES.values())

    async def test_unknown_style_cannot_synthesize(self):
        with patch.object(tts.eleven, "speak_voice", new=AsyncMock()) as synth:
            with self.assertRaises(ValueError):
                await tts.eleven.sing("unknown", "lyrics")
            synth.assert_not_awaited()

    async def test_eleven_only_vps_can_generate_song(self):
        with patch.object(tts.eleven, "configured", return_value=True), \
             patch.object(tts.eleven, "sing", new=AsyncMock(return_value=b"song")) as sing, \
             patch.object(tts, "_act", new=AsyncMock()) as act:
            self.assertEqual(await tts._song_audio("sad", "lyrics"), b"song")
            sing.assert_awaited_once_with("sad", "lyrics")
            act.assert_not_awaited()

    async def test_openai_stays_preferred_when_configured(self):
        with patch.object(tts, "_audio_provider", return_value=("https://example.invalid", "test")), \
             patch.object(tts, "_act", new=AsyncMock(return_value=b"openai")) as act, \
             patch.object(tts.eleven, "sing", new=AsyncMock()) as sing:
            self.assertEqual(await tts._song_audio("sad", "lyrics"), b"openai")
            act.assert_awaited_once_with("lyrics", *tts.SONG_VOICES["sad"][1:3])
            sing.assert_not_awaited()

    async def test_failed_openai_uses_singing_not_spoken_fallback(self):
        with patch.object(tts, "_audio_provider", return_value=("https://example.invalid", "test")), \
             patch.object(tts, "_act", new=AsyncMock(side_effect=RuntimeError("HTTP 503"))), \
             patch.object(tts.eleven, "configured", return_value=True), \
             patch.object(tts.eleven, "sing", new=AsyncMock(return_value=b"song")) as sing, \
             patch.object(tts, "_real_voice", new=AsyncMock()) as spoken:
            self.assertEqual(await tts._song_audio("sufi", "lyrics"), b"song")
            sing.assert_awaited_once_with("sufi", "lyrics")
            spoken.assert_not_awaited()

    async def test_cancel_does_not_start_another_provider(self):
        with patch.object(tts, "_audio_provider", return_value=("https://example.invalid", "test")), \
             patch.object(tts, "_act", new=AsyncMock(side_effect=asyncio.CancelledError())), \
             patch.object(tts.eleven, "sing", new=AsyncMock()) as sing:
            with self.assertRaises(asyncio.CancelledError):
                await tts._song_audio("sad", "lyrics")
            sing.assert_not_awaited()

    async def test_missing_providers_fail_explicitly(self):
        with self.assertRaises(tts.AudioUnavailable):
            await tts._song_audio("sad", "lyrics")

    async def test_provider_errors_are_actionable_and_do_not_leak_response(self):
        for status, expected in ((401, "credits"), (402, "credits"), (403, "permissions"),
                                 (429, "busy"), (500, "temporarily"), (None, "temporarily")):
            with self.subTest(status=status), \
                 patch.object(tts.eleven, "configured", return_value=True), \
                 patch.object(tts.eleven, "sing", new=AsyncMock(
                     side_effect=tts.eleven.ElevenUnavailable("private provider response", status))):
                with self.assertRaises(tts.AudioUnavailable) as err:
                    await tts._song_audio("sad", "lyrics")
                self.assertIn(expected, str(err.exception))
                self.assertNotIn("private provider response", str(err.exception))

    def callback(self, uid=7, style="sad"):
        tts._PENDING["singing-test"] = ("lyrics", 7, time.monotonic())
        return types.SimpleNamespace(
            data=f"tts|s:{style}|singing-test",
            from_user=types.SimpleNamespace(id=uid),
            message=types.SimpleNamespace(reply_text=AsyncMock()),
            answer=AsyncMock(),
        )

    async def test_all_visible_buttons_mix_deliver_and_clean_up_on_eleven_only_vps(self):
        for style in tts.PICKER_SONGS:
            with self.subTest(style=style), tempfile.TemporaryDirectory() as folder:
                tts._MEME_LAST.clear()
                callback = self.callback(style=style)

                async def mix(source, bed, level, dest):
                    self.assertEqual(Path(source).read_bytes(), b"song")
                    self.assertEqual(Path(bed).name, tts.SONG_VOICES[style][3])
                    Path(dest).write_bytes(b"mixed song")

                async def deliver(cq, path, label, text):
                    self.assertIs(cq, callback)
                    self.assertEqual(Path(path).read_bytes(), b"mixed song")
                    self.assertEqual(text, "lyrics")

                with patch.object(tts.eleven, "configured", return_value=True), \
                     patch.object(tts.eleven, "sing", new=AsyncMock(return_value=b"song")) as sing, \
                     patch.object(tts, "_mix_song", new=AsyncMock(side_effect=mix)), \
                     patch.object(tts, "_deliver", new=AsyncMock(side_effect=deliver)) as send, \
                     patch.object(tts.tempfile, "gettempdir", return_value=folder):
                    await tts._tts_cb(None, callback)
                sing.assert_awaited_once_with(style, "lyrics")
                send.assert_awaited_once()
                callback.answer.assert_awaited_once()
                callback.message.reply_text.assert_not_awaited()
                self.assertIn(7, tts._MEME_LAST)
                self.assertEqual(list(Path(folder).iterdir()), [])

    async def test_other_user_cannot_trigger_singing(self):
        callback = self.callback(uid=99)
        with patch.object(tts.eleven, "sing", new=AsyncMock()) as sing:
            await tts._tts_cb(None, callback)
            sing.assert_not_awaited()
        self.assertEqual(callback.answer.await_args.args[0], "This isn't your request.")
        self.assertFalse(tts._MEME_LAST)

    async def test_failed_provider_replies_once_and_does_not_deliver_audio(self):
        callback = self.callback()
        with patch.object(tts.eleven, "configured", return_value=True), \
             patch.object(tts.eleven, "sing", new=AsyncMock(
                 side_effect=tts.eleven.ElevenUnavailable("private response", 401))), \
             patch.object(tts, "_deliver", new=AsyncMock()) as send:
            await tts._tts_cb(None, callback)
        send.assert_not_awaited()
        callback.answer.assert_awaited_once()
        callback.message.reply_text.assert_awaited_once()
        self.assertIn("credits", callback.message.reply_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()