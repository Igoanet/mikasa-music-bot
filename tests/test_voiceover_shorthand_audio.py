"""Admission and input-retention tests for the direct /voa audio path."""
import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent.parent / "research" / "tools"))
from voiceconv_module_harness import load_voiceconv  # noqa: E402


voiceconv = load_voiceconv()


class _User:
    def __init__(self, uid):
        self.id = uid


class _Media:
    duration = 1
    file_size = 100
    mime_type = "audio/ogg"


class _Message:
    _next_id = 100

    def __init__(self, uid=7, *, media=False, fail_download=False):
        self.id = _Message._next_id
        _Message._next_id += 1
        self.from_user = _User(uid)
        self.chat = types.SimpleNamespace(id=700, title="test")
        self.command = ["voa"]
        self.text = "/voa"
        self.caption = None
        self.voice = _Media() if media else None
        self.reply_to_message = None
        self.fail_download = fail_download
        self.deleted = False
        self.downloaded = False
        self.replies = []

    async def download(self, file_name):
        self.downloaded = True
        if self.fail_download:
            raise RuntimeError("download failed")
        Path(file_name).write_bytes(b"captured recording")

    async def delete(self):
        self.deleted = True

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class VoiceoverShorthandAudioTests(unittest.TestCase):
    def setUp(self):
        voiceconv._REQS.clear()
        voiceconv.mv._BUSY.clear()
        voiceconv.mv._PUBLIC_SHOTS.clear()
        voiceconv.mv._LAST_SHOT.clear()
        voiceconv.app.sent.clear()

    def _patch_job(self):
        result = types.SimpleNamespace(path="/tmp/generated-shorthand.ogg", kind="voice", duration=1, bed=False)
        return patch.multiple(
            voiceconv,
            _may_post=AsyncMock(return_value=True),
            voiceconv=types.SimpleNamespace(
                available=lambda: True,
                estimate_seconds=lambda *_args, **_kwargs: 1,
                VoiceConvError=voiceconv.voiceconv.VoiceConvError,
                convert=AsyncMock(return_value=result),
            ),
        ), result

    def test_admission_refusal_keeps_command_and_recording(self):
        command = _Message(media=True)
        voiceconv.mv._PUBLIC_SHOTS.update({1, 2, 3})

        with patch.object(voiceconv.tts, "shorthand_text_available", return_value=True):
            asyncio.run(voiceconv.start_shorthand_audio(command))

        self.assertFalse(command.deleted)
        self.assertFalse(command.downloaded)
        self.assertFalse(voiceconv._REQS)
        self.assertIn("public busy", voiceconv.app.sent[-1][2])

    def test_download_failure_keeps_both_captured_inputs(self):
        command = _Message(media=False)
        source = _Message(media=True, fail_download=True)
        command.reply_to_message = source
        job_patch, _result = self._patch_job()

        with patch.object(voiceconv.tts, "shorthand_text_available", return_value=True), job_patch:
            asyncio.run(voiceconv.start_shorthand_audio(command))

        self.assertFalse(command.deleted)
        self.assertFalse(source.deleted)
        self.assertTrue(source.downloaded)
        self.assertFalse(voiceconv.mv._BUSY)
        self.assertFalse(voiceconv.mv._PUBLIC_SHOTS)

    def test_success_downloads_then_deletes_inputs_and_sends_audio_only(self):
        command = _Message(media=False)
        source = _Message(media=True)
        command.reply_to_message = source
        job_patch, _result = self._patch_job()

        with patch.object(voiceconv.tts, "shorthand_text_available", return_value=True), \
             patch.object(voiceconv.tts, "preset_reference", new=AsyncMock(return_value="/tmp/reference.wav")), \
             job_patch:
            asyncio.run(voiceconv.start_shorthand_audio(command))

        self.assertTrue(command.deleted)
        self.assertTrue(source.deleted)
        self.assertEqual([kind for kind, _chat, _payload in voiceconv.app.sent if kind == "audio"], ["audio"])
        audio_payload = next(payload for kind, _chat, payload in voiceconv.app.sent if kind == "audio")
        self.assertNotIn("caption", audio_payload)
        self.assertNotIn("reply_to_message_id", audio_payload)
        self.assertFalse(voiceconv.mv._BUSY)
        self.assertFalse(voiceconv.mv._PUBLIC_SHOTS)


if __name__ == "__main__":
    unittest.main()