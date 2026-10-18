import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlayQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_modules = {
            name: sys.modules.get(name)
            for name in (
                "bobby",
                "bobby.helpers",
                "bobby.helpers._selfdel",
                "pyrogram",
            )
        }
        bobby = types.ModuleType("bobby")
        bobby.app = types.SimpleNamespace()
        bobby.config = types.SimpleNamespace()
        bobby.db = types.SimpleNamespace()
        bobby.logger = types.SimpleNamespace()
        bobby.queue = types.SimpleNamespace()
        bobby.yt = types.SimpleNamespace()

        helpers = types.ModuleType("bobby.helpers")
        helpers.utils = types.SimpleNamespace()
        selfdel = types.ModuleType("bobby.helpers._selfdel")
        selfdel.arm_delete = lambda *_args, **_kwargs: None
        selfdel.clean_reply = None

        pyrogram = types.ModuleType("pyrogram")
        pyrogram.enums = types.SimpleNamespace()
        pyrogram.errors = types.SimpleNamespace()
        pyrogram.types = types.SimpleNamespace(Message=object)
        sys.modules.update(
            {
                "bobby": bobby,
                "bobby.helpers": helpers,
                "bobby.helpers._selfdel": selfdel,
                "pyrogram": pyrogram,
            }
        )
        spec = importlib.util.spec_from_file_location(
            "bobby_test_play_query", ROOT / "bobby" / "helpers" / "_play.py"
        )
        cls.play_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.play_module
        spec.loader.exec_module(cls.play_module)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("bobby_test_play_query", None)

    def test_multiline_caption_keeps_lyric_lines_and_drops_force_flag(self):
        message = types.SimpleNamespace(
            text=None,
            caption="/vplay -f  hello darkness\n  my old friend",
            command=["vplay", "-f", "hello", "darkness", "my", "old", "friend"],
        )

        self.assertEqual(
            self.play_module.play_query(message),
            "hello darkness\n  my old friend",
        )

    def test_text_payload_is_not_reconstructed_from_command_tokens(self):
        message = types.SimpleNamespace(
            text="/play\nwhen you try your best\nbut you don't succeed",
            caption=None,
            command=[
                "play",
                "when",
                "you",
                "try",
                "your",
                "best",
                "but",
                "you",
                "don't",
                "succeed",
            ],
        )

        self.assertEqual(
            self.play_module.play_query(message),
            "when you try your best\nbut you don't succeed",
        )