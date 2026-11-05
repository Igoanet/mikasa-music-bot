# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import os
import shutil
import sys
from pathlib import Path

from bobby import logger


def ensure_dirs():
    """
    Ensure that the necessary directories exist.
    """
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
            val, _ = winreg.QueryValueEx(key, "Path")
            for p in val.split(";"):
                if p and p not in os.environ.get("PATH", "").split(os.pathsep):
                    os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass

    if not shutil.which("deno") or not shutil.which("ffmpeg"):
        raise RuntimeError("Deno and FFmpeg must be installed and accessible in the system PATH.")

    for dir in ["cache", "downloads"]:
        Path(dir).mkdir(parents=True, exist_ok=True)
    logger.info("Cache directories updated.")
