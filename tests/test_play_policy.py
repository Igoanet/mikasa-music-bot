"""Offline regressions for strict group-owned playback policy.

These tests load the small permission/storage modules with fakes instead of
starting Pyrogram, contacting Telegram, downloading media, or touching the
bot's real JSON/session files.
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]


class FakeApp:
    def __init__(self):
        self.statuses = {}
        self.sudoers = set()
        self.calls = []

    async def get_chat_member(self, chat_id, user_id):
        self.calls.append((chat_id, user_id))
        status = self.statuses.get(user_id)
        if isinstance(status, BaseException):
            raise status
        return types.SimpleNamespace(status=status)


class FakeDB:
    def __init__(self):
        self.play_mode = True
        self.auth = set()
        self.cached_admins = [55]
        self.cache_reads = 0

    async def get_play_mode(self, _chat_id):
        return self.play_mode

    async def get_admins(self, _chat_id):
        self.cache_reads += 1
        return self.cached_admins

    async def is_auth(self, _chat_id, user_id):
        return user_id in self.auth


class PlayPolicyTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = {
            name: sys.modules.get(name)
            for name in (
                "bobby",
                "bobby.helpers",
                "bobby.helpers._admins",
                "bobby.helpers._selfdel",
                "bobby.core",
                "bobby.core.lang",
                "pyrogram",
            )
        }
        cls.app = FakeApp()
        cls.db = FakeDB()
        bobby = types.ModuleType("bobby")
        bobby.app = cls.app
        bobby.db = cls.db
        bobby.config = types.SimpleNamespace(LANG_CODE="en")
        bobby.logger = types.SimpleNamespace(info=lambda *_a, **_k: None)
        bobby.userbot = types.SimpleNamespace(clients=[])

        class Message:
            pass

        class CallbackQuery:
            pass

        pyrogram = types.ModuleType("pyrogram")
        pyrogram.StopPropagation = type("StopPropagation", (Exception,), {})
        pyrogram.enums = types.SimpleNamespace(
            ChatType=types.SimpleNamespace(PRIVATE="private", SUPERGROUP="supergroup"),
            ChatMemberStatus=types.SimpleNamespace(
                ADMINISTRATOR="administrator", OWNER="owner"
            ),
        )
        pyrogram.types = types.SimpleNamespace(
            Message=Message,
            CallbackQuery=CallbackQuery,
        )
        sys.modules.update({"bobby": bobby, "pyrogram": pyrogram})

        cls.admins = cls._load("bobby_policy_admins", "bobby/helpers/_admins.py")
        sys.modules["bobby.helpers._admins"] = cls.admins

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name in (
            "bobby_policy_admins",
            "bobby_policy_mongo",
            "bobby_policy_inline",
            "bobby_policy_play",
        ):
            sys.modules.pop(name, None)

    @staticmethod
    def _load(name, relative):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _user(uid=55, bot=False):
        return types.SimpleNamespace(id=uid, is_bot=bot, mention=f"<u{uid}>")

    def _update(self, uid=55, *, sender_chat=None, callback=False):
        update = (
            types.SimpleNamespace(message=types.SimpleNamespace(sender_chat=sender_chat))
            if callback
            else types.SimpleNamespace(sender_chat=sender_chat)
        )
        update.from_user = self._user(uid)
        return update

    async def test_live_owner_and_admin_are_distinct_from_cached_admin(self):
        self.app.statuses[55] = "administrator"
        update = self._update()
        self.assertFalse(await self.admins.is_group_owner(-100, update))
        self.assertTrue(await self.admins.is_live_group_admin(-100, update))

        self.app.statuses[55] = "owner"
        self.assertTrue(await self.admins.is_group_owner(-100, update))

        self.app.statuses[55] = "member"
        self.assertFalse(await self.admins.is_live_group_admin(-100, update))
        self.assertEqual(self.app.calls[-1], (-100, 55))

    async def test_anonymous_channel_and_native_rpc_denial_cannot_configure(self):
        self.app.statuses[55] = "owner"
        self.assertFalse(
            await self.admins.is_group_owner(
                -100, self._update(sender_chat=types.SimpleNamespace(id=-7))
            )
        )
        self.assertFalse(
            await self.admins.is_group_owner(
                -100,
                self._update(
                    55,
                    callback=True,
                    sender_chat=types.SimpleNamespace(id=-7),
                ),
            )
        )

        self.app.statuses[55] = PermissionError("Telegram denied lookup")
        self.assertFalse(await self.admins.is_group_owner(-100, self._update()))
        self.assertFalse(await self.admins.is_live_group_admin(-100, self._update()))

    async def test_strict_play_denies_auth_sudo_and_force_all_without_cache_lookup(self):
        play = types.ModuleType("bobby.helpers")
        play.utils = types.SimpleNamespace(get_url=lambda _m: None)
        selfdel = types.ModuleType("bobby.helpers._selfdel")
        denied = []

        async def clean_reply(_m, text, **_kwargs):
            denied.append(text)
            return text

        selfdel.clean_reply = clean_reply
        selfdel.arm_delete = lambda *_a, **_k: None
        sys.modules["bobby.helpers"] = play
        sys.modules["bobby.helpers._selfdel"] = selfdel

        bobby = sys.modules["bobby"]
        bobby.queue = types.SimpleNamespace(get_queue=lambda _chat: [])
        bobby.yt = types.SimpleNamespace()
        bobby.logger = types.SimpleNamespace(warning=lambda *_a, **_k: None)
        bobby.config = types.SimpleNamespace(QUEUE_LIMIT=20, VIDEO_PLAY=True)
        bobby.app.sudoers = {55}
        self.db.auth = {55}
        self.app.statuses[55] = "member"

        pyrogram = sys.modules["pyrogram"]
        pyrogram.errors = types.SimpleNamespace(
            PeerIdInvalid=type("PeerIdInvalid", (Exception,), {}),
            ChatAdminRequired=type("ChatAdminRequired", (Exception,), {}),
            UserNotParticipant=type("UserNotParticipant", (Exception,), {}),
            UserAlreadyParticipant=type("UserAlreadyParticipant", (Exception,), {}),
            InviteRequestSent=type("InviteRequestSent", (Exception,), {}),
            HideRequesterMissing=type("HideRequesterMissing", (Exception,), {}),
        )
        pyrogram.enums.ChatType.SUPERGROUP = "supergroup"
        pyrogram.types.Message = type("Message", (), {})
        module = self._load("bobby_policy_play", "bobby/helpers/_play.py")

        for command in (["play", "song"], ["playforce", "song"]):
            message = types.SimpleNamespace(
                chat=types.SimpleNamespace(id=-100, type="supergroup", username=None),
                from_user=self._user(),
                text="/play song",
                caption=None,
                command=command,
                reply_to_message=None,
                lang={"play_admin": "admins only"},
            )
            await module.checkUB(AsyncMock())(None, message)

        self.assertEqual(denied, ["admins only", "admins only"])
        self.assertEqual(self.db.cache_reads, 0)

    async def test_stale_force_and_replay_callbacks_require_live_admin(self):
        self.db.play_mode = True
        self.db.auth = {55}
        self.db.cached_admins = [55]
        self.app.sudoers = {55}
        self.app.statuses[55] = "member"

        async def target(*_args, **_kwargs):
            return "started"

        wrapped = self.admins.can_manage_vc(target)
        pyrogram = sys.modules["pyrogram"]
        query = pyrogram.types.CallbackQuery()
        query.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=-100))
        query.from_user = self._user()
        query.lang = {"play_admin": "admins only", "user_no_perms": "no"}
        answers = []

        async def answer(text=None, **kwargs):
            answers.append((text, kwargs))

        query.answer = answer
        for action in ("force", "replay"):
            query.data = f"controls {action} -100 item"
            self.assertIsNone(await wrapped(None, query))
        self.assertEqual(len(answers), 2)
        self.assertEqual(self.db.cache_reads, 0)

        self.app.statuses[55] = "administrator"
        query.data = "controls replay -100 item"
        self.assertEqual(await wrapped(None, query), "started")

    async def test_play_mode_defaults_false_and_false_round_trips_to_local_json(self):
        module = self._load("bobby_policy_mongo", "bobby/core/mongo.py")
        with tempfile.TemporaryDirectory() as directory:
            module.STORE_DIR = Path(directory)
            module.STORE_FILE = Path(directory) / "db.json"

            first = module.MongoDB()
            await first.connect()
            self.assertFalse(await first.get_play_mode(-100))
            await first.set_play_mode(-100, True)
            await first.close()

            second = module.MongoDB()
            await second.connect()
            self.assertTrue(await second.get_play_mode(-100))
            await second.set_play_mode(-100, False)
            await second.close()

            stored = json.loads(module.STORE_FILE.read_text())
            self.assertFalse(stored["chats"]["-100"]["admin_play"])
            third = module.MongoDB()
            await third.connect()
            self.assertFalse(await third.get_play_mode(-100))

    def test_settings_state_labels_and_explicit_desired_callbacks(self):
        pyrogram = sys.modules["pyrogram"]
        pyrogram.enums.ButtonStyle = types.SimpleNamespace(PRIMARY="primary")

        class Button:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class Markup:
            def __init__(self, rows):
                self.inline_keyboard = rows

        pyrogram.types.InlineKeyboardButton = Button
        pyrogram.types.InlineKeyboardMarkup = Markup
        core = types.ModuleType("bobby.core")
        core_lang = types.ModuleType("bobby.core.lang")
        core_lang.lang_codes = {"en": "English"}
        sys.modules.update({"bobby.core": core, "bobby.core.lang": core_lang})
        bobby = sys.modules["bobby"]
        bobby.app.username = "bot"
        bobby.config.SUPPORT_CHAT = "https://t.me/support"
        bobby.config.SUPPORT_CHANNEL = "https://t.me/channel"
        bobby.lang = types.SimpleNamespace(get_languages=lambda: {"en": "English"})
        module = self._load("bobby_policy_inline", "bobby/helpers/_inline.py")
        labels = {
            "play_mode": "Playback access",
            "play_everyone": "Everyone 🌍",
            "play_admins": "Admins only 🔒",
            "force_mode": "Force play",
            "force_everyone": "Everyone 🌍",
            "force_admins": "Admins only 🔒",
            "cmd_delete": "Command delete",
            "language": "Language",
        }
        markup = module.Inline().settings_markup(labels, False, False, "en", -100)
        self.assertEqual(markup.inline_keyboard[0][1].text, "Everyone 🌍")
        self.assertEqual(markup.inline_keyboard[0][1].callback_data, "settings play admins")
        markup = module.Inline().settings_markup(labels, True, False, "en", -100)
        self.assertEqual(markup.inline_keyboard[0][1].text, "Admins only 🔒")
        self.assertEqual(markup.inline_keyboard[0][1].callback_data, "settings play everyone")

    def test_recommendations_and_media_playlist_funnels_keep_real_play_gate(self):
        play_source = (ROOT / "bobby/plugins/play.py").read_text()
        recs_source = (ROOT / "bobby/plugins/recs.py").read_text()
        callbacks_source = (ROOT / "bobby/plugins/callbacks.py").read_text()
        self.assertIn("@checkUB", play_source)
        self.assertIn("media = tg.get_media", play_source)
        self.assertIn("tracks = await yt.playlist", play_source)
        self.assertIn("await play_hndlr(app, fake)", recs_source)
        self.assertIn("query.message.chat.id != chat_id", callbacks_source)


if __name__ == "__main__":
    unittest.main()