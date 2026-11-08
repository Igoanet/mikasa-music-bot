"""
Persistent store for runtime-overridable bot settings (support URL, owner URL).
Values written here take precedence over config.py env-vars at runtime.
File: data/bot_settings.json  —  mode 600, written atomically via mkstemp.
"""

import json
import os
import tempfile
from pathlib import Path

STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STORE_FILE = STORE_DIR / "bot_settings.json"

_DEFAULTS: dict[str, str] = {}


def load() -> dict:
    try:
        return json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STORE_DIR, prefix="bot_settings_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STORE_FILE)
        try:
            os.chmod(STORE_FILE, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get(key: str, default: str = "") -> str:
    return load().get(key, default)


def set(key: str, value: str) -> None:  # noqa: A001
    data = load()
    data[key] = value
    save(data)


def delete(key: str) -> bool:
    data = load()
    if key in data:
        del data[key]
        save(data)
        return True
    return False
