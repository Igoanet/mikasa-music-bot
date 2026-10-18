# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Persistent store for assistant session strings added from inside the bot.

Mirrors the all_in_one_bot approach: sessions live in a JSON file readable
only by the owner (chmod 600), never in chat history or logs.
"""

import json
import os
import tempfile
from pathlib import Path

STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STORE_FILE = STORE_DIR / "sessions.json"


def load() -> dict:
    """Return {telegram_user_id_str: {"session": str, "name": str, "username": str}}.

    Fail-closed: a corrupt/unreadable file is moved aside (never silently
    overwritten later) so saved sessions can be recovered manually.
    """
    try:
        return json.loads(STORE_FILE.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as ex:
        backup = STORE_FILE.with_suffix(".corrupt")
        try:
            os.replace(STORE_FILE, backup)
            os.chmod(backup, 0o600)
        except OSError:
            pass
        raise RuntimeError(
            f"sessions file was corrupt ({ex}); moved to {backup.name} for manual recovery"
        ) from ex


def save(data: dict) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    # mkstemp creates a UNIQUE file with mode 0600 from the start — a stale
    # world-readable fixed-name .tmp can never be reused for credentials
    fd, tmp = tempfile.mkstemp(dir=STORE_DIR, prefix="sessions_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, STORE_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(user_id: int, session: str, name: str, username: str | None) -> None:
    data = load()
    data[str(user_id)] = {"session": session, "name": name, "username": username}
    save(data)


def update_identity(user_id: int, name: str, username: str | None) -> bool:
    """Refresh the stored display name / username for an assistant.

    Returns True when something actually changed.  The session string is never
    touched — only the display identity — so this is safe to call on every
    boot (2026-09-29).
    """
    data = load()
    entry = data.get(str(user_id))
    if not entry:
        return False
    if entry.get("name") == name and entry.get("username") == username:
        return False
    entry["name"] = name
    entry["username"] = username
    save(data)
    return True


def remove(user_id: int) -> dict | None:
    data = load()
    entry = data.pop(str(user_id), None)
    if entry is not None:
        save(data)
    return entry


def get(user_id: int) -> dict | None:
    return load().get(str(user_id))
