# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

import pyrogram

from bobby import config, logger


class Bot(pyrogram.Client):
    def __init__(self):
        super().__init__(
            name="bobby",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            parse_mode=pyrogram.enums.ParseMode.HTML,
            max_concurrent_transmissions=7,
            link_preview_options=pyrogram.types.LinkPreviewOptions(is_disabled=True),
        )
        self.owner = config.OWNER_ID
        self.logger = config.LOGGER_ID
        self.bl_users = pyrogram.filters.user()
        self.sudoers = pyrogram.filters.user(self.owner)

    async def leave_chat(self, chat_id, delete=False):
        """Leave a chat and notify the scoped assistant-exit cleanup hook.

        Telegram may omit the corresponding membership update for an
        explicitly requested leave.  The hook is installed by the plugin once
        the database/userbot/call objects exist; keeping this override lazy
        also makes Bot construction independent of those runtime objects.
        """
        result = await super().leave_chat(chat_id, delete=delete)
        hook = getattr(self, "_group_exit_hook", None)
        if hook is not None:
            try:
                await hook(chat_id, source="bot.leave_chat")
            except Exception as ex:
                logger.warning(
                    "group-exit hook failed after leaving %s: %s",
                    chat_id,
                    type(ex).__name__,
                )
        return result

    # --- session vs token reconciliation -------------------------------------
    # Pyrogram uses bot_token only for the FIRST login; afterwards the auth key
    # stored in bobby.session wins and the token is ignored.  So swapping
    # BOT_TOKEN for another bot silently keeps the OLD bot running (the new one
    # never answers), and regenerating the same bot's token leaves a dead auth
    # key behind (start fails with AuthKeyUnregistered).  Both cases are fixed
    # by moving the stale session aside and logging in fresh with the token.

    _TOKEN_RE = re.compile(r"^(\d+):[A-Za-z0-9_-]{30,}$")

    def _session_path(self):
        path = getattr(self.storage, "database", None)
        return path if isinstance(path, Path) else None

    def _token_bot_id(self):
        """Bot id baked into BOT_TOKEN, or None when the token is malformed
        (a half-typed token must never retire a working session)."""
        m = self._TOKEN_RE.match(config.BOT_TOKEN or "")
        return int(m.group(1)) if m else None

    def _close_storage(self) -> None:
        conn = getattr(self.storage, "conn", None)
        if conn is not None:
            try:
                conn.close()  # no-op when start() already closed it
            except sqlite3.Error:
                pass

    @staticmethod
    def _free_backup_name(path: Path) -> Path:
        stamp = time.time_ns()
        while True:
            backup = path.with_name(f"{path.name}.{stamp}.bak")
            if not backup.exists() and not backup.with_name(backup.name + "-journal").exists():
                return backup
            stamp += 1

    def _retire_session(self, path: Path, reason: str) -> Path:
        """Move bobby.session (+ its sqlite journal) to a .bak so the next
        start() authorizes with BOT_TOKEN.  Nothing is deleted; the backup
        path is returned so a failed fresh login can put it back."""
        self._close_storage()
        backup = self._free_backup_name(path)
        journal = path.with_name(path.name + "-journal")
        backup_journal = backup.with_name(backup.name + "-journal")
        # journal first: a hot journal left behind would be replayed into the
        # brand-new session file SQLite creates under the same name
        had_journal = journal.exists()
        if had_journal:
            journal.replace(backup_journal)
        try:
            path.replace(backup)
        except OSError:
            if had_journal:
                backup_journal.replace(journal)
            raise
        logger.warning(f"{reason}; old session moved to {backup.name}, logging in fresh")
        return backup

    def _restore_session(self, path: Path, backup: Path) -> None:
        """Undo _retire_session after the fresh login failed."""
        self._close_storage()
        for leftover in (path, path.with_name(path.name + "-journal")):
            if leftover.exists():
                leftover.unlink()  # the never-authorized session start() just created
        backup_journal = backup.with_name(backup.name + "-journal")
        if backup_journal.exists():
            backup_journal.replace(path.with_name(path.name + "-journal"))
        backup.replace(path)
        logger.warning(f"fresh login failed; {backup.name} restored as {path.name}")

    def _reconcile_session(self) -> Optional[Path]:
        """Retire the saved session when BOT_TOKEN now belongs to a different
        bot.  Returns the backup path when a session was retired."""
        token_bot_id = self._token_bot_id()
        path = self._session_path()
        if path is None or not path.is_file():
            return None
        if token_bot_id is None:
            logger.warning("BOT_TOKEN does not look like a bot token; keeping the saved session as is")
            return None
        try:
            # plain (rw) open on purpose: a hot journal left by a crash is
            # rolled back here exactly as Pyrogram's own open() would do it,
            # while a read-only open would just fail the check
            conn = sqlite3.connect(path, timeout=1)
            try:
                row = conn.execute("SELECT user_id FROM sessions").fetchone()
            finally:
                conn.close()
        except sqlite3.Error as ex:
            logger.warning(f"could not read {path.name} to compare it with BOT_TOKEN: {ex}")
            return None
        session_bot_id = row[0] if row else None
        if not session_bot_id or session_bot_id == token_bot_id:
            return None
        return self._retire_session(
            path,
            f"BOT_TOKEN belongs to bot {token_bot_id} but {path.name} is bot {session_bot_id}",
        )

    async def _reset_connection(self) -> None:
        """Bring a half-started client back to the disconnected state so
        start() can run again (a 401 from get_me() leaves it connected)."""
        if getattr(self, "is_initialized", False):
            try:
                await self.terminate()
            except Exception:
                pass
        if getattr(self, "is_connected", False):
            try:
                await self.disconnect()
            except Exception:
                pass

    async def _fresh_login(self, path: Path, backup: Path) -> None:
        try:
            await super().start()
        except BaseException:
            await self._reset_connection()
            self._restore_session(path, backup)
            raise

    async def _start_with_recovery(self):
        path = self._session_path()
        if path is None:  # in-memory / custom storage: nothing to reconcile
            await super().start()
            return
        backup = self._reconcile_session()
        if backup is not None:
            await self._fresh_login(path, backup)
            return
        try:
            await super().start()
        except pyrogram.errors.Unauthorized as ex:
            # same bot, but its token was regenerated -> stored auth key is dead
            await self._reset_connection()
            if not path.is_file():
                raise
            backup = self._retire_session(path, f"saved session rejected by Telegram ({ex.__class__.__name__})")
            await self._fresh_login(path, backup)

    async def boot(self):
        """
        Starts the bot and performs initial setup.

        Raises:
            SystemExit: If the bot fails to access the log group or is not an administrator in the logger group.
        """
        await self._start_with_recovery()
        self.id = self.me.id
        self.name = self.me.first_name
        self.username = self.me.username
        self.mention = self.me.mention

        if self.logger:  # log group is optional (LOGGER_ID=0 disables it)
            try:
                await self.send_message(self.logger, "Bot Started")
                get = await self.get_chat_member(self.logger, self.id)
            except Exception as ex:
                raise SystemExit(f"Bot has failed to access the log group: {self.logger}\nReason: {ex}")

            if get.status != pyrogram.enums.ChatMemberStatus.ADMINISTRATOR:
                raise SystemExit("Please promote the bot as an admin in logger group.")

        # "/" command popup.  The first list is worldwide; the second is
        # scoped to the owner's chat only, so the group console
        # (/manage /massban /chatlink /unban /bans) is never offered to
        # anyone else (2026-09-29).
        try:
            await self.set_bot_commands([
                pyrogram.types.BotCommand("play", "Play a song in the voice chat"),
                pyrogram.types.BotCommand("playforce", "Skip current & play now (admins)"),
                pyrogram.types.BotCommand("vplay", "Play a video in the voice chat"),
                pyrogram.types.BotCommand("vplayforce", "Skip current & play video now (admins)"),
                pyrogram.types.BotCommand("queue", "Show the current queue"),
                pyrogram.types.BotCommand("skip", "Skip to the next song"),
                pyrogram.types.BotCommand("pause", "Pause the stream"),
                pyrogram.types.BotCommand("resume", "Resume the stream"),
                pyrogram.types.BotCommand("seek", "Seek forward (seconds)"),
                pyrogram.types.BotCommand("seekback", "Seek back (seconds)"),
                pyrogram.types.BotCommand("loop", "Loop the song or the whole queue"),
                pyrogram.types.BotCommand("shuffle", "Shuffle the queue"),
                pyrogram.types.BotCommand("song", "Download a song as audio"),
                pyrogram.types.BotCommand("speed", "Change playback speed"),
                pyrogram.types.BotCommand("export", "Export the queue as a file"),
                pyrogram.types.BotCommand("import", "Import an exported queue"),
                pyrogram.types.BotCommand("stop", "Stop and clear the queue"),
                pyrogram.types.BotCommand("playmode", "Playback settings"),
                pyrogram.types.BotCommand("lang", "Change bot language"),
                pyrogram.types.BotCommand("ping", "Check bot status"),
                pyrogram.types.BotCommand("help", "Help & all commands"),
            ])
            await self.set_bot_commands(
                [
                    pyrogram.types.BotCommand("owner", "Owner panel"),
                    pyrogram.types.BotCommand("manage", "Group console: rights, link, bans"),
                    pyrogram.types.BotCommand("chatlink", "Invite link for a group"),
                    pyrogram.types.BotCommand("bans", "Banned users in a group"),
                    pyrogram.types.BotCommand("unban", "Lift one ban in a group"),
                    pyrogram.types.BotCommand("massban", "Silent: ban all members of a group"),
                    pyrogram.types.BotCommand("setlog", "Bind a log channel"),
                    pyrogram.types.BotCommand("refreshassistant", "Re-read assistant names"),
                    pyrogram.types.BotCommand("accounts", "Manage assistant accounts"),
                    pyrogram.types.BotCommand("broadcast", "Broadcast a message"),
                    pyrogram.types.BotCommand("stats", "Bot statistics"),
                    pyrogram.types.BotCommand("clean", "Delete leftover files & buffered songs"),
                    pyrogram.types.BotCommand("restart", "Restart the bot"),
                    pyrogram.types.BotCommand("addsudo", "Add a sudo user"),
                    pyrogram.types.BotCommand("listsudo", "List sudo users"),
                ],
                scope=pyrogram.types.BotCommandScopeChat(self.owner),
            )
        except Exception as ex:
            logger.warning(f"set_bot_commands failed: {ex}")
        logger.info(f"Bot started as @{self.username}")

    async def exit(self):
        """
        Asynchronously stops the bot.
        """
        await super().stop()
        logger.info("Bot stopped.")
