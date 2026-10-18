# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import time
import asyncio
import logging
from logging.handlers import RotatingFileHandler

logging.basicConfig(
    format="[%(asctime)s - %(levelname)s] - %(name)s: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    handlers=[
        RotatingFileHandler("log.txt", maxBytes=10485760, backupCount=5),
        logging.StreamHandler(),
    ],
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("pymongo").setLevel(logging.ERROR)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
# Keep transport/pulse summaries, not every participant update. Debug dumps
# contain people's call metadata and are unnecessary on the playback hot path.
logging.getLogger("pytgcalls").setLevel(logging.WARNING)
logging.getLogger("ntgcalls").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)


__version__ = "3.0.3"

from config import Config

config = Config()
config.check()
tasks = []
boot = time.time()

from bobby.core.bot import Bot
app = Bot()

from bobby.rateguard import install_guard as _install_guard

# voice conversion / owner tools that legitimately run for minutes
_NO_TIMEOUT_CMDS = frozenset({
    "voiceover", "voiceovertext", "say", "vot",
    "clonevoice", "meriawaaz", "clonevoicetext", "cvt",
    "addvoice", "newvoice", "aurawaaz", "nayiawaaz",
    "clonevoiceaudio", "cva", "changevoice", "convertvoice", "vc",
    "voiceoveraudio", "voa", "redub", "dub", "awaazbadlo",
    "speed", "playback",
    "broadcast", "eval", "exec",
})


async def _is_staff(uid: int) -> bool:
    if uid == app.owner:
        return True
    try:
        return uid in await db.get_sudoers()
    except Exception:
        return False


_install_guard(
    app,
    _is_staff,
    _NO_TIMEOUT_CMDS,
    # voice-generation jobs are launched from callback buttons and run for
    # minutes on CPU — they must not be cancelled by the callback timeout
    cb_exempt_modules={
    },
)

from bobby.core.dir import ensure_dirs
ensure_dirs()

from bobby.core.userbot import Userbot
userbot = Userbot()

from bobby.core.mongo import MongoDB
db = MongoDB()

from bobby.core.lang import Language
lang = Language()

from bobby.core.telegram import Telegram
from bobby.core.youtube import YouTube
tg = Telegram()
yt = YouTube()

from bobby.helpers import Queue, Thumbnail
queue = Queue()
thumb = Thumbnail()

from bobby.core.calls import TgCall
anon = TgCall()


async def stop() -> None:
    logger.info("Stopping...")
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.exceptions.CancelledError:
            pass

    await app.exit()
    await userbot.exit()
    await db.close()
    await thumb.close()

    logger.info("Stopped.\n")
