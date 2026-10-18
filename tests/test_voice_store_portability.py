import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "voice_store_portability_under_test", ROOT / "bobby" / "core" / "voice_store.py"
)
voice_store = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(voice_store)


class VoiceStorePortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_dir = voice_store.STORE_DIR
        self.old_file = voice_store.STORE_FILE
        voice_store.STORE_DIR = self.root / "data"
        voice_store.STORE_FILE = voice_store.STORE_DIR / "voice_clones.json"
        (voice_store.STORE_DIR / "voices").mkdir(parents=True)

    def tearDown(self):
        voice_store.STORE_DIR = self.old_dir
        voice_store.STORE_FILE = self.old_file
        self.tmp.cleanup()

    def _write(self, records):
        voice_store.STORE_DIR.mkdir(parents=True, exist_ok=True)
        voice_store.STORE_FILE.write_text(json.dumps(records))

    def test_old_absolute_primary_and_extra_paths_rebase_everywhere(self):
        primary = "8781280491-5812b3fc.wav"
        extra = "8781280491-6a13aca8.wav"
        (voice_store.STORE_DIR / "voices" / primary).write_bytes(b"sample")
        (voice_store.STORE_DIR / "voices" / extra).write_bytes(b"extra")
        old_root = "/home/runner/workspace/bots/bobby_music/data/voices"
        self._write({
            "8781280491": {
                "engine": "local",
                "label": "Owner",
                "created": 2,
                "sample": f"{old_root}/{primary}",
                "extra": [f"{old_root}/{extra}"],
            }
        })

        expected = [str(voice_store.STORE_DIR / "voices" / primary),
                    str(voice_store.STORE_DIR / "voices" / extra)]
        self.assertEqual(voice_store.get("8781280491")["sample"], expected[0])
        self.assertEqual(voice_store.users()["8781280491"]["extra"], [expected[1]])
        self.assertEqual(voice_store.samples_of(voice_store.get("8781280491")), expected)
        self.assertEqual(voice_store.samples(), set(expected))

    def test_save_persists_rebased_paths_and_keeps_record_order(self):
        old_root = "/home/runner/workspace/bots/bobby_music/data/voices"
        data = {
            "2": {"label": "Second", "created": 2, "sample": f"{old_root}/second.wav"},
            "1": {"label": "First", "created": 1, "sample": f"{old_root}/first.wav"},
        }
        voice_store.save(data)
        persisted = json.loads(voice_store.STORE_FILE.read_text())
        self.assertEqual(list(persisted), ["2", "1"])
        self.assertEqual(
            persisted["2"]["sample"],
            str(voice_store.STORE_DIR / "voices" / "second.wav"),
        )
        self.assertEqual(
            [voice_store.label_of(record) for _, record in
             sorted(voice_store.users().items(), key=lambda item: item[1]["created"])],
            ["First", "Second"],
        )

    def test_arbitrary_paths_are_not_rebased_to_a_matching_basename(self):
        arbitrary = "/srv/imports/voice.wav"
        traversal = "/old/data/voices/../voice.wav"
        self._write({
            "1": {"sample": arbitrary},
            "2": {"sample": traversal},
        })
        records = voice_store.users()
        self.assertEqual(records["1"]["sample"], arbitrary)
        self.assertEqual(records["2"]["sample"], traversal)
        self.assertEqual(voice_store.samples_of(records["1"]), [arbitrary])

    def test_symlink_outside_voices_is_not_rebased(self):
        outside = self.root / "not-a-voice.wav"
        outside.write_bytes(b"outside")
        (voice_store.STORE_DIR / "voices" / "escape.wav").symlink_to(outside)
        old = "/home/runner/workspace/bots/bobby_music/data/voices/escape.wav"
        self._write({"1": {"sample": old}})
        self.assertEqual(voice_store.get("1")["sample"], old)


if __name__ == "__main__":
    unittest.main()