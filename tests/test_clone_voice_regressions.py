"""Offline regressions for saved-voice routing and clone quality refusal.

These tests import the two helpers with a tiny ``bobby`` stub.  They do not start either worker,
call Edge, invoke ffmpeg, or create audio; every engine boundary is replaced with an async stub.
"""
import asyncio
import importlib.util
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CloneVoiceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._module_names = (
            "bobby",
            "bobby.helpers",
            "bobby.helpers._localclone",
            "bobby.helpers._redub",
            "bobby.helpers._voiceconv",
            "bobby.helpers._shortclone",
            "vc_worker_offline_regressions",
        )
        cls._old_modules = {name: sys.modules.get(name) for name in cls._module_names}

        bobby = types.ModuleType("bobby")
        bobby.logger = logging.getLogger("clone-voice-regressions")
        helpers = types.ModuleType("bobby.helpers")
        helpers.__path__ = [str(ROOT / "bobby" / "helpers")]
        bobby.helpers = helpers
        sys.modules["bobby"] = bobby
        sys.modules["bobby.helpers"] = helpers

        cls.lc = _load("bobby.helpers._localclone", ROOT / "bobby/helpers/_localclone.py")

        redub = types.ModuleType("bobby.helpers._redub")

        class RedubError(Exception):
            pass

        redub.RedubError = RedubError
        redub.FFMPEG_TIMEOUT = 1
        redub.PYTHON = Path(sys.executable)
        redub.TOOLS = ROOT / "redub_tools.py"
        redub._ffmpeg = lambda *args: None
        redub._remove = lambda path: None
        helpers._redub = redub
        sys.modules["bobby.helpers._redub"] = redub

        voiceconv = types.ModuleType("bobby.helpers._voiceconv")

        class VoiceConvError(Exception):
            pass

        voiceconv.VoiceConvError = VoiceConvError
        voiceconv.available = lambda: True
        voiceconv.warm = lambda: False
        voiceconv._cpu_scale = lambda: 1.0
        voiceconv._convert_file = lambda *args, **kwargs: None
        helpers._voiceconv = voiceconv
        sys.modules["bobby.helpers._voiceconv"] = voiceconv
        cls.voiceconv = voiceconv
        cls.redub = redub
        cls.short = _load("bobby.helpers._shortclone", ROOT / "bobby/helpers/_shortclone.py")
        helpers._shortclone = cls.short
        stdout = sys.stdout
        cls.vcw = _load("vc_worker_offline_regressions", ROOT / "vc_worker.py")
        sys.stdout = stdout

        # clone_worker redirects stdout to keep its JSON protocol clean.  Restore the test
        # process's stdout immediately; no worker/model is loaded by importing it.
        stdout = sys.stdout
        cls.cw = _load("clone_worker_offline_regressions", ROOT / "clone_worker.py")
        sys.stdout = stdout

        cls.voice_store = _load(
            "voice_store_offline_regressions", ROOT / "bobby/core/voice_store.py"
        )

    @classmethod
    def tearDownClass(cls):
        try:
            cls.cw._proto.close()
        except Exception:
            pass
        sys.stdout = cls._old_stdout if hasattr(cls, "_old_stdout") else sys.stdout
        for name, old in cls._old_modules.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="clone_voice_regression_")
        self.root = Path(self.tmp.name)
        self.sample_dir = self.root / "voices"
        self.sample_dir.mkdir()
        self.sample1 = self.sample_dir / "owner-1.wav"
        self.sample2 = self.sample_dir / "owner-2.wav"
        self.extra1 = self.sample_dir / "owner-1-extra.wav"
        self.extra2 = self.sample_dir / "owner-1-extra-2.wav"
        for path in (self.sample1, self.sample2, self.extra1, self.extra2):
            path.write_bytes(b"reference")

    def tearDown(self):
        self.tmp.cleanup()

    def run_async(self, awaitable):
        return asyncio.run(awaitable)

    def _patch_local_boundary(self, prepare, *, warm=True):
        """Common no-worker localclone boundary for route tests."""
        async def no_check():
            return None

        return (
            patch.object(self.lc, "available", return_value=True),
            patch.object(self.lc, "_check_not_paused", return_value=None),
            patch.object(self.lc, "warm", return_value=warm),
            patch.object(self.lc, "_prepare_text", side_effect=prepare),
        )

    def test_two_saved_slots_keep_their_own_refs_and_conversion_target(self):
        store = self.voice_store
        old_dir, old_file = store.STORE_DIR, store.STORE_FILE
        try:
            store.STORE_DIR = self.root / "data"
            store.STORE_FILE = store.STORE_DIR / "voice_clones.json"
            voice_dir = store.STORE_DIR / "voices"
            voice_dir.mkdir(parents=True)
            one = voice_dir / "voice-1.wav"
            one_extra = voice_dir / "voice-1-extra.wav"
            two = voice_dir / "voice-2.wav"
            one.write_bytes(b"one")
            one_extra.write_bytes(b"one-extra")
            two.write_bytes(b"two")
            store.put("99", "Voice 1", engine="local", sample=str(one))
            store.put("99/2", "Voice 2", engine="local", sample=str(two))
            store.add_sample("99", str(one_extra), limit=4)
            self.assertEqual(store.samples_of(store.get("99")), [str(one), str(one_extra)])
            self.assertEqual(store.samples_of(store.get("99/2")), [str(two)])

            target = []

            async def convert(source, sample, out, **kwargs):
                target.append((sample, kwargs))
                return {"duration": 2.0, "seconds": 1.0}

            async def stock(text, voice, path):
                Path(path).write_bytes(b"stock")

            async def source(*args):
                Path(args[-1]).write_bytes(b"source")

            async def mp3(path):
                return b"converted"

            async def pick(lang, script, sample):
                return "stub-voice"

            with patch.object(self.short, "available", return_value=True), \
                 patch.object(self.short, "_pick_voice", side_effect=pick), \
                 patch.object(self.short, "_stock_reading", side_effect=stock), \
                 patch.object(self.redub, "_ffmpeg", side_effect=source), \
                 patch.object(self.voiceconv, "_convert_file", side_effect=convert), \
                 patch.object(self.short.localclone, "_to_mp3", side_effect=mp3):
                self.assertEqual(
                    self.run_async(self.short.speak("hello", "en", str(two), verify_saved_identity=True)),
                    b"converted",
                )
            self.assertEqual(target[0][0], str(two))
            self.assertNotEqual(target[0][0], str(one))
            self.assertEqual(target[0][1]["steps"], self.short.STEPS)
            self.assertEqual(target[0][1]["ref_seconds"], self.short.REF_SECONDS)
            self.assertTrue(target[0][1]["verify_target_identity"])
        finally:
            store.STORE_DIR, store.STORE_FILE = old_dir, old_file

    def test_unavailable_pronunciation_latin_and_urdu_never_reach_xtts(self):
        calls = []

        async def short_speak(text, lang, sample, *, verify_saved_identity=False):
            calls.append((text, lang, sample, verify_saved_identity))
            return b"converted"

        async def no_preload():
            raise AssertionError("conversion route must not prewarm XTTS")

        async def run_case(raw, lang):
            async def prepare(_):
                return raw, lang, []

            with patch.object(self.lc, "available", return_value=True), \
                 patch.object(self.lc, "_check_not_paused", return_value=None), \
                 patch.object(self.lc, "warm", return_value=False), \
                 patch.object(self.lc, "_prepare_text", side_effect=prepare), \
                 patch.object(self.lc, "_preload", side_effect=no_preload), \
                 patch.object(self.lc, "_worker", side_effect=AssertionError("XTTS worker used")), \
                 patch.object(self.short, "speak", side_effect=short_speak):
                return await self.lc.speak(raw, str(self.sample1))

        self.assertEqual(
            self.run_async(run_case("this is a long Latin reading", "en")),
            b"converted",
        )
        self.assertEqual(
            self.run_async(run_case("زندگی ایک سفر ہے اور یہ لمبا متن ہے", "ar")),
            b"converted",
        )
        self.assertEqual(calls[0][0], "this is a long Latin reading")
        self.assertEqual(calls[0][1:], ("en", str(self.sample1), False))
        self.assertEqual(calls[1][0], "زندگی ایک سفر ہے اور یہ لمبا متن ہے")
        self.assertEqual(calls[1][1:], ("ar", str(self.sample1), False))

    def test_valid_long_hindi_stays_xtts_and_keeps_all_refs_and_settings(self):
        script = "नमस्ते दोस्तों " * 4
        request = {}

        async def prepare(_):
            return script, "hi", [{"text": script, "energy": 3, "pace": "normal"}]

        async def worker():
            return object()

        async def request_stub(proc, req):
            request.update(req)
            return {"ok": True, "takes": 1, "chunks": 1, "retakes": 0, "rejected": 0, "checked": 0}

        async def mp3(path):
            return b"xtts"

        with patch.object(self.lc, "available", return_value=True), \
             patch.object(self.lc, "_check_not_paused", return_value=None), \
             patch.object(self.lc, "warm", return_value=True), \
             patch.object(self.lc, "_prepare_text", side_effect=prepare), \
             patch.object(self.lc, "_worker", side_effect=worker), \
             patch.object(self.lc, "_request", side_effect=request_stub), \
             patch.object(self.lc, "_to_mp3", side_effect=mp3), \
             patch.object(self.short, "speak", side_effect=AssertionError("short route used")):
            self.assertEqual(
                self.run_async(
                    self.lc.speak(
                        script,
                        str(self.sample1),
                        [str(self.extra1), str(self.extra2)],
                    )
                ),
                b"xtts",
            )
        self.assertEqual(request["ref"], str(self.sample1))
        self.assertEqual(
            request["refs"],
            [str(self.sample1), str(self.extra1), str(self.extra2)],
        )
        self.assertEqual(request["lang"], "hi")
        self.assertEqual(request["segments"][0]["text"], script)
        self.assertEqual(self.cw.TEMPERATURE, 0.7)
        self.assertEqual(self.cw.REPETITION_PENALTY, 10.0)
        self.assertEqual(self.cw.TOP_P, 0.85)
        self.assertEqual(self.cw.GATE_TAKES, 3)

    def test_short_word_route_stays_shortclone(self):
        calls = []

        async def prepare(_):
            return "नमस्ते", "hi", []

        async def short_speak(text, lang, sample, *, verify_saved_identity=False):
            calls.append((text, lang, sample, verify_saved_identity))
            return b"short"

        async def no_preload():
            raise AssertionError("short-word route must not prewarm XTTS")

        with patch.object(self.lc, "available", return_value=True), \
             patch.object(self.lc, "_check_not_paused", return_value=None), \
             patch.object(self.lc, "warm", return_value=False), \
             patch.object(self.lc, "_prepare_text", side_effect=prepare), \
             patch.object(self.lc, "_preload", side_effect=no_preload), \
             patch.object(self.lc, "_worker", side_effect=AssertionError("XTTS worker used")), \
             patch.object(self.short, "speak", side_effect=short_speak):
            self.assertEqual(
                self.run_async(self.lc.speak("नमस्ते", str(self.sample1))),
                b"short",
            )
        self.assertEqual(calls, [("नमस्ते", "hi", str(self.sample1), False)])

    def test_only_authoritative_saved_slot_enables_shortclone_identity_gate(self):
        calls = []

        async def prepare(_):
            return "नमस्ते", "hi", []

        async def short_speak(text, lang, sample, *, verify_saved_identity=False):
            calls.append((sample, verify_saved_identity))
            return b"short"

        common = (
            patch.object(self.lc, "available", return_value=True),
            patch.object(self.lc, "_check_not_paused", return_value=None),
            patch.object(self.lc, "warm", return_value=False),
            patch.object(self.lc, "_prepare_text", side_effect=prepare),
            patch.object(self.short, "speak", side_effect=short_speak),
        )
        with common[0], common[1], common[2], common[3], common[4]:
            self.assertEqual(self.run_async(self.lc.speak("नमस्ते", str(self.sample1))), b"short")
            self.assertEqual(
                self.run_async(self.lc.speak("नमस्ते", str(self.sample2), verify_saved_identity=True)),
                b"short",
            )
        self.assertEqual(calls, [(str(self.sample1), False), (str(self.sample2), True)])

    def test_ephemeral_shortclone_does_not_inherit_saved_identity_or_pitch_gate(self):
        convert_options = []

        async def pick(lang, script, sample):
            return "stub-voice"

        async def stock(text, voice, path):
            Path(path).write_bytes(b"stock")

        async def source(*args):
            Path(args[-1]).write_bytes(b"source")

        async def convert(*args, **kwargs):
            convert_options.append(kwargs)
            return {"duration": 2.0, "seconds": 1.0}

        async def mp3(path):
            return b"converted"

        with patch.object(self.short, "available", return_value=True), \
             patch.object(self.short, "_pick_voice", side_effect=pick), \
             patch.object(self.short, "_stock_reading", side_effect=stock), \
             patch.object(self.redub, "_ffmpeg", side_effect=source), \
             patch.object(self.voiceconv, "_convert_file", side_effect=convert), \
             patch.object(self.short, "_match_target_pitch", side_effect=AssertionError("ephemeral pitch gated")), \
             patch.object(self.short.localclone, "_to_mp3", side_effect=mp3):
            self.assertEqual(
                self.run_async(self.short.speak("hello", "en", str(self.sample1))),
                b"converted",
            )
        self.assertEqual(convert_options, [{
            "steps": self.short.STEPS,
            "ref_seconds": self.short.REF_SECONDS,
            "verify_target_identity": False,
        }])

    def test_shortclone_long_estimate_grows_and_conversion_error_is_explicit(self):
        self.assertGreater(self.short.estimate_seconds(250), self.short.estimate_seconds(20))

        async def pick(lang, script, sample):
            return "stub-voice"

        async def stock(text, voice, path):
            Path(path).write_bytes(b"stock")

        async def source(*args):
            Path(args[-1]).write_bytes(b"source")

        async def failed(*args, **kwargs):
            raise self.voiceconv.VoiceConvError("worker took longer than 321s")

        with patch.object(self.short, "available", return_value=True), \
             patch.object(self.short, "_pick_voice", side_effect=pick), \
             patch.object(self.short, "_stock_reading", side_effect=stock), \
             patch.object(self.redub, "_ffmpeg", side_effect=source), \
             patch.object(self.voiceconv, "_convert_file", side_effect=failed):
            with self.assertRaises(self.lc.Unavailable) as raised:
                self.run_async(self.short.speak("a longer reading", "en", str(self.sample1)))
        self.assertIn("worker took longer than 321s", str(raised.exception))

    def test_shortclone_pitch_refinement_uses_the_same_selected_reference(self):
        calls = []
        matched_audio = b"pitch-matched" * 100

        async def gap(reference, rendered, notes):
            calls.append(("gap", reference, rendered))
            return -1.75

        async def render(rendered, out, *, semitones, tempo, gain_db):
            self.assertTrue(out.endswith(".wav"))
            calls.append(("render", rendered, semitones, tempo, gain_db))
            Path(out).write_bytes(matched_audio)

        output = self.root / "converted.wav"
        output.write_bytes(b"converted")
        with patch.object(self.redub, "_pitch_gap", side_effect=gap, create=True), \
             patch.object(self.redub, "_render_voice", side_effect=render, create=True):
            self.run_async(self.short._match_target_pitch(str(self.sample2), str(output)))
        self.assertEqual(calls[0], ("gap", str(self.sample2), str(output)))
        self.assertEqual(calls[1], ("render", str(output), -1.75, 1.0, 0.0))
        self.assertEqual(output.read_bytes(), matched_audio)
        self.assertFalse(Path(f"{output}.pitch.part.wav").exists())

    def test_take_gate_rejects_mismatch_nonfinite_and_runaway_candidates(self):
        gate = object.__new__(self.cw.TakeGate)
        gate._resolve = lambda take: None
        gate._budget_left = lambda: False
        candidates = [
            self.cw.Take(None, 1.0, 0.30, False),  # wrong speaker
            self.cw.Take(None, float("nan"), 0.80, True),  # nonfinite duration
            self.cw.Take(None, 1.0, float("nan"), True),  # nonfinite speaker
            self.cw.Take(None, 9.0, 0.80, False),  # runaway duration
        ]
        with self.assertRaises(self.cw.QualityGateError) as raised:
            gate.settle(0, "hello", candidates, None, None)
        self.assertIn("quality gate rejected all", str(raised.exception))
        self.assertFalse(any(candidate.ok for candidate in candidates))

    def test_conversion_identity_gate_requires_the_selected_target_score(self):
        # Short conversion is only accepted after CAMPPlus compares its
        # rendered audio with the same selected saved reference.  A stock
        # reading (near zero), a different saved voice, and a nonfinite metric
        # cannot be relabelled as a successful clone.
        self.assertTrue(self.vcw._target_similarity_ok(self.vcw.MIN_TARGET_SIMILARITY))
        self.assertTrue(self.vcw._target_similarity_ok(0.45))
        self.assertFalse(self.vcw._target_similarity_ok(self.vcw.MIN_TARGET_SIMILARITY - 0.001))
        self.assertFalse(self.vcw._target_similarity_ok(float("nan")))
        self.assertFalse(self.vcw._target_similarity_ok(float("inf")))

    def test_displayed_wait_uses_conversion_budget_when_script_service_is_absent(self):
        with patch.dict(os.environ, {
            "AI_INTEGRATIONS_OPENAI_BASE_URL": "",
            "AI_INTEGRATIONS_OPENAI_API_KEY": "",
        }), patch.object(self.short, "estimate_seconds", return_value=480) as estimate:
            self.assertEqual(self.lc.estimate_seconds(40, text="Hello brother, how are you today?"), 480)
            estimate.assert_called_once_with(40)
            estimate.reset_mock()
            self.lc.estimate_seconds(40, text="यह एक स्पष्ट हिंदी वाक्य है।")
            estimate.assert_not_called()

    def test_worker_quality_failure_is_not_replaced_by_stock_fallback(self):
        class Input:
            def __init__(self, line):
                self.line = line
                self.used = False

            def readline(self):
                if self.used:
                    return b""
                self.used = True
                return self.line

        class TTS:
            def __init__(self):
                self.stock_calls = 0

            def tts_to_file(self, **kwargs):
                self.stock_calls += 1

        out = self.root / "quality.wav"
        request = {
            "id": "quality",
            "text": "hello",
            "ref": str(self.sample1),
            "out": str(out),
            "lang": "en",
        }
        stdin = Input((__import__("json").dumps(request) + "\n").encode())
        tts = TTS()
        replies = []

        def rejected(*args, **kwargs):
            raise self.cw.QualityGateError("quality gate rejected all 3 takes")

        ready = object()
        with patch.object(self.cw.sys, "stdin", stdin), \
             patch.object(self.cw.select, "select", side_effect=lambda *args: ([ready], [], [])), \
             patch.object(self.cw, "synthesize", side_effect=rejected), \
             patch.object(self.cw, "_emit", side_effect=replies.append):
            # select() returns a sentinel, while readline() is supplied by the patched stdin.
            # The worker only uses readiness as a gate and then reads sys.stdin.
            with patch.object(self.cw.select, "select", side_effect=lambda *args: ([stdin], [], [])):
                self.cw._serve(tts)

        self.assertEqual(tts.stock_calls, 0)
        self.assertEqual(len(replies), 1)
        self.assertFalse(replies[0]["ok"])
        self.assertIn("QualityGateError", replies[0]["error"])


if __name__ == "__main__":
    unittest.main()