# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Local JSON storage — drop-in replacement for the original MongoDB layer.

The upstream project stored everything in MongoDB; this build keeps the exact
same async interface but persists to data/db.json (atomic writes, chmod 600)
so the bot runs with zero external services.
"""

import json
import os
import tempfile
from pathlib import Path
from random import randint

from bobby import config, logger, userbot

STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STORE_FILE = STORE_DIR / "db.json"

_EMPTY = {
    "auth": {},        # chat_id(str) -> [user_id]
    "assistant": {},   # chat_id(str) -> assistant number
    "chats": {},       # chat_id(str) -> {"cmd_delete": bool, "admin_play": bool, "force_all": bool}
    "lang": {},        # chat_id(str) -> language code
    "users": [],       # [user_id]
    "blacklist": {"chats": [], "users": []},
    "sudoers": [],     # [user_id]
    "logger": False,   # logging toggle
}


class MongoDB:
    def __init__(self):
        """Initialize the local store (loaded from disk in connect())."""
        self._data = json.loads(json.dumps(_EMPTY))  # deep copy

        # runtime-only caches (were in-memory in the Mongo version too)
        self.admin_list = {}
        self.active_calls = {}
        self.admin_play = []
        self.force_all = []
        self.autoplay = []
        self.blacklisted = []
        self.cmd_delete = []
        self.loop = {}
        self.notified = []
        self.logger = False

        self.assistant = {}
        self.auth = {}
        self.chats = []
        self.lang = {}
        self.users = []

    # STORAGE
    async def connect(self) -> None:
        """Load the local database file."""
        try:
            if STORE_FILE.exists():
                stored = json.loads(STORE_FILE.read_text())
                for key, default in _EMPTY.items():
                    self._data[key] = stored.get(key, default)
            logger.info("Database loaded (local file).")
            await self.load_cache()
        except Exception as e:
            raise SystemExit(f"Database load failed: {type(e).__name__}: {e}") from e

    def _save(self) -> None:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        # mkstemp: unique file, mode 0600 from creation — no stale-tmp reuse
        fd, tmp = tempfile.mkstemp(dir=STORE_DIR, prefix="db_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f)
            os.replace(tmp, STORE_FILE)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    async def close(self) -> None:
        """Flush to disk."""
        self._save()
        logger.info("Database saved.")

    # CACHE
    async def get_call(self, chat_id: int) -> bool:
        return chat_id in self.active_calls

    async def add_call(self, chat_id: int) -> None:
        self.active_calls[chat_id] = 1

    async def remove_call(self, chat_id: int) -> None:
        self.active_calls.pop(chat_id, None)

    async def playing(self, chat_id: int, paused: bool = None) -> bool | None:
        if paused is not None:
            self.active_calls[chat_id] = int(not paused)
        return bool(self.active_calls.get(chat_id, 0))

    async def get_admins(self, chat_id: int, reload: bool = False) -> list[int]:
        from bobby.helpers._admins import reload_admins

        if chat_id not in self.admin_list or reload:
            self.admin_list[chat_id] = await reload_admins(chat_id)
        return self.admin_list[chat_id]

    async def get_loop(self, chat_id: int) -> int:
        return self.loop.get(chat_id, 0)

    async def set_loop(self, chat_id: int, count: int) -> None:
        self.loop[chat_id] = count

    # AUTH METHODS
    async def _get_auth(self, chat_id: int) -> set[int]:
        if chat_id not in self.auth:
            self.auth[chat_id] = set(self._data["auth"].get(str(chat_id), []))
        return self.auth[chat_id]

    async def is_auth(self, chat_id: int, user_id: int) -> bool:
        return user_id in await self._get_auth(chat_id)

    async def add_auth(self, chat_id: int, user_id: int) -> None:
        users = await self._get_auth(chat_id)
        if user_id not in users:
            users.add(user_id)
            self._data["auth"][str(chat_id)] = sorted(users)
            self._save()

    async def rm_auth(self, chat_id: int, user_id: int) -> None:
        users = await self._get_auth(chat_id)
        if user_id in users:
            users.discard(user_id)
            self._data["auth"][str(chat_id)] = sorted(users)
            self._save()

    # ASSISTANT METHODS
    async def set_assistant(self, chat_id: int) -> int:
        if not userbot.clients:
            raise RuntimeError("No assistant accounts — add one via /accounts first.")
        num = randint(1, len(userbot.clients))
        self._data["assistant"][str(chat_id)] = num
        self._save()
        self.assistant[chat_id] = num
        return num

    async def get_assistant(self, chat_id: int):
        from bobby import anon

        if chat_id not in self.assistant:
            num = self._data["assistant"].get(str(chat_id))
            if not num or num > len(anon.clients):
                num = await self.set_assistant(chat_id)
            self.assistant[chat_id] = num

        return anon.clients[self.assistant[chat_id] - 1]

    async def get_client(self, chat_id: int):
        if chat_id not in self.assistant:
            await self.get_assistant(chat_id)

        num = self.assistant[chat_id]
        if num > len(userbot.clients):
            num = await self.set_assistant(chat_id)
            self.assistant[chat_id] = num

        # index the live list: assistants added in-bot go beyond one/two/three
        return userbot.clients[num - 1]

    # BLACKLIST METHODS
    async def add_blacklist(self, chat_id: int) -> None:
        if str(chat_id).startswith("-"):
            self.blacklisted.append(chat_id)
            lst = self._data["blacklist"]["chats"]
        else:
            lst = self._data["blacklist"]["users"]
        if chat_id not in lst:
            lst.append(chat_id)
        self._save()

    async def del_blacklist(self, chat_id: int) -> None:
        if str(chat_id).startswith("-"):
            self.blacklisted.remove(chat_id)
            lst = self._data["blacklist"]["chats"]
        else:
            lst = self._data["blacklist"]["users"]
        if chat_id in lst:
            lst.remove(chat_id)
        self._save()

    async def get_blacklisted(self, chat: bool = False) -> list[int]:
        if chat:
            if not self.blacklisted:
                self.blacklisted.extend(self._data["blacklist"]["chats"])
            return self.blacklisted
        return list(self._data["blacklist"]["users"])

    # CHAT METHODS
    async def is_chat(self, chat_id: int) -> bool:
        return chat_id in self.chats

    async def add_chat(self, chat_id: int) -> None:
        if not await self.is_chat(chat_id):
            self.chats.append(chat_id)
            self._data["chats"].setdefault(str(chat_id), {})
            self._save()

    async def rm_chat(self, chat_id: int) -> None:
        if await self.is_chat(chat_id):
            self.chats.remove(chat_id)
            self._data["chats"].pop(str(chat_id), None)
            self._save()

    async def get_chats(self) -> list:
        if not self.chats:
            self.chats.extend(int(cid) for cid in self._data["chats"])
        return self.chats

    # COMMAND DELETE
    async def get_cmd_delete(self, chat_id: int) -> bool:
        if chat_id not in self.cmd_delete:
            if self._data["chats"].get(str(chat_id), {}).get("cmd_delete"):
                self.cmd_delete.append(chat_id)
        return chat_id in self.cmd_delete

    async def set_cmd_delete(self, chat_id: int, delete: bool = False) -> None:
        if delete:
            self.cmd_delete.append(chat_id)
        else:
            self.cmd_delete.remove(chat_id)
        self._data["chats"].setdefault(str(chat_id), {})["cmd_delete"] = delete
        self._save()

    # LANGUAGE METHODS
    async def set_lang(self, chat_id: int, lang_code: str):
        self._data["lang"][str(chat_id)] = lang_code
        self._save()
        self.lang[chat_id] = lang_code

    async def get_lang(self, chat_id: int) -> str:
        if chat_id not in self.lang:
            self.lang[chat_id] = self._data["lang"].get(str(chat_id), config.LANG_CODE)
        return self.lang[chat_id]

    # LOGGER METHODS
    async def is_logger(self) -> bool:
        return self.logger

    async def get_logger(self) -> bool:
        self.logger = bool(self._data["logger"])
        return self.logger

    async def set_logger(self, status: bool) -> None:
        self.logger = status
        self._data["logger"] = status
        self._save()

    # PLAY MODE METHODS
    async def get_play_mode(self, chat_id: int) -> bool:
        if chat_id not in self.admin_play:
            if self._data["chats"].get(str(chat_id), {}).get("admin_play"):
                self.admin_play.append(chat_id)
        return chat_id in self.admin_play

    async def set_play_mode(self, chat_id: int, admin_only: bool = False) -> None:
        """admin_only=True restricts playback to admins; False allows everyone.

        Takes the enabled-state directly (same semantics as get_play_mode) —
        previously this took an inverted 'remove' flag that wrote the opposite
        of what the settings panel displayed."""
        if admin_only and chat_id not in self.admin_play:
            self.admin_play.append(chat_id)
        elif not admin_only and chat_id in self.admin_play:
            self.admin_play.remove(chat_id)
        self._data["chats"].setdefault(str(chat_id), {})["admin_play"] = admin_only
        self._save()

    # FORCE PLAY MODE METHODS
    async def get_force_mode(self, chat_id: int) -> bool:
        """True = anyone in this group may /playforce. False (default) = admins only."""
        if chat_id not in self.force_all:
            if self._data["chats"].get(str(chat_id), {}).get("force_all"):
                self.force_all.append(chat_id)
        return chat_id in self.force_all

    async def set_force_mode(self, chat_id: int, status: bool) -> None:
        if status and chat_id not in self.force_all:
            self.force_all.append(chat_id)
        elif not status and chat_id in self.force_all:
            self.force_all.remove(chat_id)
        self._data["chats"].setdefault(str(chat_id), {})["force_all"] = status
        self._save()

    # AUTOPLAY METHODS
    async def get_autoplay_all(self, chat_id: int) -> bool:
        """True = every member sees the autoplay switch, not just admins.

        Admin-only by default; a group can open it up with
        /autoplay everyone (2026-09-29).
        """
        return bool(
            self._data["chats"].get(str(chat_id), {}).get("autoplay_all", False)
        )

    async def set_autoplay_all(self, chat_id: int, status: bool) -> None:
        self._data["chats"].setdefault(str(chat_id), {})["autoplay_all"] = status
        self._save()

    async def get_autoplay(self, chat_id: int) -> bool:
        """True = when the queue runs dry, keep the music going by itself."""
        if chat_id not in self.autoplay:
            if self._data["chats"].get(str(chat_id), {}).get("autoplay"):
                self.autoplay.append(chat_id)
        return chat_id in self.autoplay

    async def set_autoplay(self, chat_id: int, status: bool) -> None:
        if status and chat_id not in self.autoplay:
            self.autoplay.append(chat_id)
        elif not status and chat_id in self.autoplay:
            self.autoplay.remove(chat_id)
        self._data["chats"].setdefault(str(chat_id), {})["autoplay"] = status
        self._save()

    # SUDO METHODS
    async def add_sudo(self, user_id: int) -> None:
        if user_id not in self._data["sudoers"]:
            self._data["sudoers"].append(user_id)
            self._save()

    async def del_sudo(self, user_id: int) -> None:
        if user_id in self._data["sudoers"]:
            self._data["sudoers"].remove(user_id)
            self._save()

    async def get_sudoers(self) -> list[int]:
        return list(self._data["sudoers"])

    # USER METHODS
    async def is_user(self, user_id: int) -> bool:
        return user_id in self.users

    async def add_user(self, user_id: int) -> None:
        if not await self.is_user(user_id):
            self.users.append(user_id)
            self._data["users"].append(user_id)
            self._save()

    async def rm_user(self, user_id: int) -> None:
        if await self.is_user(user_id):
            self.users.remove(user_id)
            self._data["users"].remove(user_id)
            self._save()

    async def get_users(self) -> list:
        if not self.users:
            self.users.extend(self._data["users"])
        return self.users

    async def load_cache(self) -> None:
        await self.get_chats()
        await self.get_users()
        await self.get_blacklisted(True)
        await self.get_logger()
        logger.info("Database cache loaded.")
