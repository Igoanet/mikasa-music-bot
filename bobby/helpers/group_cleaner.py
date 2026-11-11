# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Background auto-delete janitor for bot messages posted to group chats.

Auto-deletes any message posted by the bot in a group chat (chat_id < 0)
once it reaches 1 hour (3600 seconds) old.
Persistent via SQLite so deletions survive bot restarts.
"""

import asyncio
import os
import sqlite3
import time
from typing import List, Tuple

from pyrogram import enums
from pyrogram.errors import (
    FloodWait,
    MessageDeleteForbidden,
    MessageIdInvalid,
    RPCError,
)

from bobby import logger

DB_PATH = "data/group_autodel.db"
DEFAULT_DELAY = 3600.0  # 1 hour in seconds
_SWEEP_INTERVAL = 30  # check every 30 seconds
_running_task: asyncio.Task | None = None


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_group_deletes (
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            delete_at REAL NOT NULL,
            PRIMARY KEY (chat_id, message_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_del_time ON pending_group_deletes(delete_at)"
    )
    conn.commit()
    return conn


def track_group_message(chat_id: int | str, message_id: int | str, delay_seconds: float = DEFAULT_DELAY) -> None:
    """Track a message sent by the bot in a group for auto-deletion after delay_seconds (default 1 hour).
    Only group chats (chat_id < 0) are tracked; private DMs are strictly ignored."""
    try:
        cid = int(chat_id)
        mid = int(message_id)
        if cid >= 0 or mid <= 0:
            return  # strictly ignore private DMs

        due_at = time.time() + float(delay_seconds)
        conn = _get_db()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO pending_group_deletes (chat_id, message_id, delete_at) VALUES (?, ?, ?)",
                (cid, mid, due_at),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as ex:
        logger.debug("group_cleaner track failed: %s", ex)


async def _sweep_loop(client) -> None:
    """Periodic worker that deletes group messages that reached 1 hour age."""
    logger.info("group_cleaner: 1-hour auto-delete sweep worker started.")
    while True:
        try:
            await asyncio.sleep(_SWEEP_INTERVAL)
            now = time.time()
            conn = _get_db()
            due_rows: List[Tuple[int, int]] = []
            try:
                cursor = conn.execute(
                    "SELECT chat_id, message_id FROM pending_group_deletes WHERE delete_at <= ? LIMIT 300",
                    (now,),
                )
                due_rows = cursor.fetchall()
            finally:
                conn.close()

            if not due_rows:
                continue

            # Group messages by chat_id so we can use batch delete (up to 100 per call)
            by_chat: dict[int, list[int]] = {}
            for cid, mid in due_rows:
                by_chat.setdefault(cid, []).append(mid)

            deleted_pairs: list[Tuple[int, int]] = []

            for cid, mids in by_chat.items():
                for i in range(0, len(mids), 100):
                    batch = mids[i : i + 100]
                    try:
                        await client.delete_messages(chat_id=cid, message_ids=batch)
                    except FloodWait as fw:
                        await asyncio.sleep(min(fw.value, 15))
                        try:
                            await client.delete_messages(chat_id=cid, message_ids=batch)
                        except Exception:
                            pass
                    except (MessageIdInvalid, MessageDeleteForbidden):
                        pass
                    except RPCError as rpc:
                        logger.debug("group_cleaner delete RPC error in %s: %s", cid, rpc)
                    except Exception as exc:
                        logger.debug("group_cleaner delete failed in %s: %s", cid, exc)

                    for m in batch:
                        deleted_pairs.append((cid, m))

            if deleted_pairs:
                conn = _get_db()
                try:
                    conn.executemany(
                        "DELETE FROM pending_group_deletes WHERE chat_id = ? AND message_id = ?",
                        deleted_pairs,
                    )
                    conn.commit()
                finally:
                    conn.close()

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("group_cleaner sweep error: %s", exc)


def start_group_cleaner(client) -> None:
    global _running_task
    if _running_task is None or _running_task.done():
        try:
            loop = asyncio.get_running_loop()
            _running_task = loop.create_task(_sweep_loop(client))
        except Exception as ex:
            logger.warning("group_cleaner start failed: %s", ex)
