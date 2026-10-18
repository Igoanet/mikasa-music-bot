# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


from pyrogram import Client

from bobby import config, logger
from bobby.core import session_store


class Userbot(Client):
    def __init__(self):
        """
        Initializes the userbot with multiple clients.

        Env sessions (SESSION1-3) are optional. Assistants can also be added
        from inside the bot via /accounts; those are persisted by
        session_store and restored here on boot.
        """
        self.clients = []
        self.saved = {}  # telegram_user_id (str) -> Client, for in-bot added accounts
        clients = {"one": "SESSION1", "two": "SESSION2", "three": "SESSION3"}
        for key, string_key in clients.items():
            name = f"AnonyUB{key[-1]}"
            session = getattr(config, string_key)
            setattr(
                self,
                key,
                Client(
                    name=name,
                    api_id=config.API_ID,
                    api_hash=config.API_HASH,
                    session_string=session,
                ),
            )

    async def _start_client(self, client: Client, tag: str, strict: bool = True):
        """
        Start one assistant client and register it in self.clients.

        strict=True (boot): failing to reach the log group aborts startup.
        strict=False (in-bot add): failure stops the client and raises so the
        caller can report the error to the user.
        """
        await client.start()
        if config.LOGGER_ID:  # log group optional; skip the check when unset
            try:
                await client.send_message(config.LOGGER_ID, "Assistant Started")
            except Exception:
                await client.stop()
                if strict:
                    raise SystemExit(f"Assistant {tag} failed to send message in log group.")
                raise RuntimeError(
                    "Account works, but it couldn't message the log group. "
                    "Add the account to the log group first."
                )

        client.id = client.me.id
        client.name = client.me.first_name
        client.username = client.me.username
        client.mention = client.me.mention
        self.clients.append(client)
        logger.info(f"Assistant {tag} started as @{client.username}")

        # Keep the stored identity in step with Telegram, so a name or
        # username changed on Telegram shows up in the bot after any restart
        # (2026-09-29).
        try:
            if session_store.update_identity(
                client.me.id, client.me.first_name, client.me.username
            ):
                logger.info(
                    f"Assistant {tag}: stored name/username refreshed to "
                    f"{client.me.first_name!r} @{client.me.username}"
                )
        except Exception as ex:
            logger.warning(f"Assistant {tag}: identity refresh skipped ({ex})")

        # silently warm the bot's peer cache so later get_chat_member /
        # approve_chat_join_request calls don't hit PEER_ID_INVALID
        if client.username:
            try:
                from bobby import app as _bot  # late import: built before boot

                await _bot.get_users(client.username)
            except Exception:
                pass

    async def boot_client(self, num: int, ub: Client):
        """
        Boot a client and perform initial setup.
        Args:
            num (int): The client number to boot (1, 2, or 3).
            ub (Client): The userbot client instance.
        Raises:
            SystemExit: If the client fails to send a message in the log group.
        """
        clients = {
            1: self.one,
            2: self.two,
            3: self.three,
        }
        await self._start_client(clients[num], str(num))

    async def refresh_identities(self) -> int:
        """Re-read every running assistant's name/username from Telegram.

        Updates the live client objects and the persisted store.  Safe to call
        repeatedly: nothing is written when nothing changed.  Used by the
        janitor loop so changes made on Telegram arrive automatically
        (2026-09-29).
        """
        changed = 0
        for client in list(self.clients):
            try:
                me = await client.get_me()
            except Exception as ex:
                logger.warning(f"identity refresh: get_me failed ({ex})")
                continue
            client.name = me.first_name
            client.username = me.username
            client.mention = me.mention
            try:
                if session_store.update_identity(me.id, me.first_name, me.username):
                    changed += 1
                    logger.info(
                        f"identity auto-refresh: {me.id} -> "
                        f"{me.first_name!r} @{me.username}"
                    )
            except Exception as ex:
                logger.warning(f"identity refresh: store update failed ({ex})")
        return changed

    async def boot(self):
        """
        Asynchronously starts the assistants: env sessions first, then
        accounts added in-bot (persisted via session_store).
        """
        if config.SESSION1:
            await self.boot_client(1, self.one)
        if config.SESSION2:
            await self.boot_client(2, self.two)
        if config.SESSION3:
            await self.boot_client(3, self.three)

        try:
            saved = session_store.load()
        except RuntimeError as ex:
            # corrupt store was moved aside for manual recovery — keep booting
            logger.error(f"{ex}")
            saved = {}
        for uid, entry in saved.items():
            try:
                client = Client(
                    name=f"SavedUB{uid}",
                    api_id=config.API_ID,
                    api_hash=config.API_HASH,
                    session_string=entry["session"],
                )
                await self._start_client(client, f"saved:{uid}")
                self.saved[uid] = client
            except Exception as ex:
                logger.warning(f"Saved assistant {uid} failed to start: {ex}")

    async def add_saved(self, session: str) -> Client:
        """
        Start and register an assistant at runtime (added via /accounts).
        Probes the session first to learn the account's user id, rejects
        duplicates, then binds a PyTgCalls instance so it can join voice
        chats immediately. Keyed by the ACCOUNT's user id.
        """
        import time

        probe = Client(
            name=f"probe_{int(time.time() * 1000)}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=session,
            in_memory=True,
        )
        await probe.start()  # raises if the string is malformed/revoked
        uid = str(probe.me.id)
        await probe.stop()

        if uid in self.saved or session_store.get(int(uid)):
            raise RuntimeError("That account is already added.")

        client = Client(
            name=f"SavedUB{uid}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            session_string=session,
        )
        await self._start_client(client, f"saved:{uid}", strict=False)
        self.saved[uid] = client

        from bobby import anon  # late import: anon is built after userbot

        await anon.add_client(client)
        return client

    async def remove_saved(self, uid: str) -> Client | None:
        """Stop and unregister an in-bot added assistant."""
        client = self.saved.pop(uid, None)
        if client is None:
            return None
        try:
            idx = self.clients.index(client)
        except ValueError:
            idx = None
        if idx is not None:
            self.clients.remove(client)
            from bobby import anon

            if idx < len(anon.clients):
                call = anon.clients.pop(idx)
                try:
                    await call.stop()
                except Exception:
                    pass
        try:
            await client.stop()
        except Exception:
            pass
        return client

    async def exit(self):
        """
        Asynchronously stops the assistants.
        """
        if config.SESSION1:
            await self.one.stop()
        if config.SESSION2:
            await self.two.stop()
        if config.SESSION3:
            await self.three.stop()
        for client in self.saved.values():
            try:
                await client.stop()
            except Exception:
                pass
        logger.info("Assistants stopped.")
