import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LivePrefetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = (
            "bobby",
            "bobby.core",
            "bobby.core.group_exit",
            "bobby.helpers",
            "pyrogram",
        )
        cls._saved_modules = {name: sys.modules.get(name) for name in names}

        class App:
            logger = object()

            @staticmethod
            def on_message(*args, **kwargs):
                return lambda function: function

        bobby = types.ModuleType("bobby")
        bobby.anon = types.SimpleNamespace()
        bobby.app = App()
        bobby.config = types.SimpleNamespace(AUTO_END=False, AUTO_LEAVE=False)
        bobby.db = types.SimpleNamespace()
        bobby.lang = types.SimpleNamespace()
        bobby.logger = types.SimpleNamespace()
        bobby.queue = types.SimpleNamespace()
        bobby.tasks = []
        bobby.userbot = types.SimpleNamespace()
        bobby.yt = types.SimpleNamespace()

        core = types.ModuleType("bobby.core")
        core.__path__ = []
        group_exit = types.ModuleType("bobby.core.group_exit")
        group_exit.install = lambda *args: types.SimpleNamespace()

        helpers = types.ModuleType("bobby.helpers")
        helpers.buttons = types.SimpleNamespace()

        pyrogram = types.ModuleType("pyrogram")
        pyrogram.enums = types.SimpleNamespace(
            ChatType=types.SimpleNamespace(GROUP="group", SUPERGROUP="supergroup")
        )
        pyrogram.errors = types.SimpleNamespace(MessageIdInvalid=Exception)
        pyrogram.filters = types.SimpleNamespace(
            video_chat_started=object(),
            video_chat_ended=object(),
        )
        pyrogram.types = types.SimpleNamespace(Message=object)

        sys.modules.update(
            {
                "bobby": bobby,
                "bobby.core": core,
                "bobby.core.group_exit": group_exit,
                "bobby.helpers": helpers,
                "pyrogram": pyrogram,
            }
        )
        spec = importlib.util.spec_from_file_location(
            "bobby_test_misc", ROOT / "bobby" / "plugins" / "misc.py"
        )
        cls.misc_module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.misc_module
        old_create_task = asyncio.create_task

        def ignore_task(coroutine):
            coroutine.close()
            return object()

        asyncio.create_task = ignore_task
        try:
            spec.loader.exec_module(cls.misc_module)
        finally:
            asyncio.create_task = old_create_task

    @classmethod
    def tearDownClass(cls):
        for name, module in cls._saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        sys.modules.pop("bobby_test_misc", None)

    def test_live_tracks_are_never_prefetch_candidates(self):
        live_duration = types.SimpleNamespace(
            duration="🔴 LIVE",
            view_count="LIVE",
            file_path=None,
            _prefetch_tried=False,
        )
        live_marker = types.SimpleNamespace(
            duration="00:00",
            view_count="LIVE",
            file_path=None,
            _prefetch_tried=False,
        )
        finite = types.SimpleNamespace(
            duration="03:00",
            view_count="",
            file_path=None,
            _prefetch_tried=False,
        )

        self.assertFalse(self.misc_module._prefetchable(live_duration))
        self.assertFalse(self.misc_module._prefetchable(live_marker))
        self.assertTrue(self.misc_module._prefetchable(finite))


if __name__ == "__main__":
    unittest.main()