"""Storage hygiene: what the bot may keep on disk / in RAM between songs, and the
manual /clean behind it.

Rules (owner, 2026-09-10: "for play it's fine, but it must not store a lot more
stuff in the background"):

- downloads/  playback files.  Only files some queue still references may stay;
              orphans go at boot, every 30 min once older than 30 min (crash
              leftovers), and on /clean at any age past a 2-min write guard.
- cache/      generated now-playing thumbnails.  Kept 24 h (a replayed song
              reuses its card), swept with the janitor, all gone on /clean.
- RAM spool   remote audio buffered for playback.  A song is released the moment
              no queue references it (Queue.purge_item -> spool.forget); /clean
              drops every idle entry.
- /tmp        voice-feature scratch (tts_/clone_/redub_/vconv_/myvoice_ ...).  Each
              feature deletes its own files; the sweep catches what a crash left
              behind after 2 h, /clean after 10 min.

Everything under data/ (voices people saved, the engines' models) is deliberately
NOT touched here: those are the bot's working set, not accumulated leftovers.
"""

import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path

from bobby import logger, queue

ROOT = Path(__file__).resolve().parent.parent.parent  # bots/bobby_music
DOWNLOADS = Path("downloads")
CACHE = Path("cache")
TMP = Path(tempfile.gettempdir())
TMP_PREFIXES = (
    "tts_", "clone_", "redub_", "vconv_", "myvoice_", "voice_ref_", "queue_",
)

JANITOR_EVERY = 1800
# How often the assistant name/username is re-read from Telegram, so a
# rename there shows up in the bot on its own (2026-09-29).
ASSISTANT_REFRESH_EVERY = int(os.getenv("ASSISTANT_REFRESH_EVERY", "21600"))
DOWNLOAD_MAX_AGE = 1800   # unreferenced playback files older than this are orphans
CACHE_MAX_AGE = 24 * 3600
TMP_MAX_AGE = 2 * 3600
WRITE_GUARD = 120         # never touch a file written within the last 2 min (download in flight)


def _remove(path: Path) -> int:
    """Delete a file or directory tree; returns the bytes it held (0 on failure)."""
    try:
        if path.is_dir() and not path.is_symlink():
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            shutil.rmtree(path, ignore_errors=True)
            return size
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0


def _age(path: Path) -> float:
    """Seconds since the last write — for a directory, the newest write anywhere
    inside it (a job's work dir keeps its own mtime while files inside change)."""
    try:
        newest = path.stat().st_mtime
        if path.is_dir() and not path.is_symlink():
            for f in path.rglob("*"):
                try:
                    newest = max(newest, f.stat().st_mtime)
                except OSError:
                    pass
        return time.time() - newest
    except OSError:
        return 0.0


def sweep_downloads(max_age_sec: float = 0) -> tuple[int, int]:
    """Delete orphaned playback files from downloads/ — files NO queue references
    (the per-track purge in calls.py/_queue.py is the primary cleanup; this catches
    crashes and any path that skipped it).  Files younger than max_age_sec (never
    younger than WRITE_GUARD) are left alone.  Returns (files, bytes) removed."""
    referenced = queue.referenced_paths()
    floor = max(max_age_sec, WRITE_GUARD)
    files = size = 0
    for f in DOWNLOADS.glob("*"):
        if not f.is_file() or str(f) in referenced or _age(f) < floor:
            continue
        freed = _remove(f)
        files += 1
        size += freed
    return files, size


def sweep_cache(max_age_sec: float = 0) -> tuple[int, int]:
    """Drop generated thumbnails (cache/*.png and the temp_*.jpg sources) older than
    max_age_sec; the card is regenerated the next time the song plays."""
    files = size = 0
    for f in CACHE.glob("*"):
        if not f.is_file() or f.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        age = _age(f)
        if age < WRITE_GUARD or (age < max_age_sec and not f.name.startswith("temp_")):
            continue  # a card being generated/uploaded right now is left alone
        size += _remove(f)
        files += 1
    return files, size


def sweep_tmp(max_age_sec: float = TMP_MAX_AGE) -> tuple[int, int]:
    """Voice-feature scratch in the temp dir that outlived its job."""
    files = size = 0
    try:
        entries = list(TMP.iterdir())
    except OSError:
        return 0, 0
    for p in entries:
        if not p.name.startswith(TMP_PREFIXES) or _age(p) < max(max_age_sec, WRITE_GUARD):
            continue
        size += _remove(p)
        files += 1
    return files, size


def _dir_size(path: Path) -> tuple[int, int]:
    files = size = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                files += 1
                size += f.stat().st_size
    except OSError:
        pass
    return files, size


def _rss_mb(pid: int | None) -> float:
    if not pid:
        return 0.0
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def _log_size() -> tuple[int, int]:
    logs = [f for f in Path(".").glob("log.txt*") if f.is_file()]
    return len(logs), sum(f.stat().st_size for f in logs)


async def usage() -> dict:
    """What the bot holds right now — for the /clean report."""
    from bobby.core.spool import spool  # lazy: keeps this module import-light
    # [voice stack removed] from bobby.helpers import _localclone, _voiceconv

    scratch = [p for p in TMP.iterdir() if p.name.startswith(TMP_PREFIXES)] if TMP.exists() else []
    scratch_size = 0
    for p in scratch:
        scratch_size += _dir_size(p)[1] if p.is_dir() else (p.stat().st_size if p.exists() else 0)
    workers = []
    for name, mod in ():  # [voice stack removed]
        proc = getattr(mod, "_proc", None)
        if proc is not None and proc.returncode is None:
            workers.append((name, _rss_mb(proc.pid)))
    return {
        "downloads": _dir_size(DOWNLOADS),
        "cache": _dir_size(CACHE),
        "scratch": (len(scratch), scratch_size),
        "spool": await spool.stats(),
        "voices": _dir_size(ROOT / "data" / "voices"),
        "models": _dir_size(ROOT / "data" / "models"),
        "log": _log_size(),
        "workers": workers,
    }


async def clean() -> dict:
    """The manual clean: everything a song or a voice job could have left behind.
    Returns {"files": n, "bytes": n, "spool_bytes": n}."""
    from bobby.core.spool import spool

    files = size = 0
    for n, b in (sweep_downloads(0), sweep_cache(0), sweep_tmp(600)):
        files += n
        size += b
    spool_bytes = await spool.clear_idle()
    logger.info("clean: removed %d files (%.1f MB), released %.1f MB of spool RAM",
                files, size / 1048576, spool_bytes / 1048576)
    return {"files": files, "bytes": size, "spool_bytes": spool_bytes}


def boot_sweep() -> None:
    """At boot nothing plays: every playback file is an orphan; stale thumbnails and
    scratch go too."""
    d = sweep_downloads(0)
    c = sweep_cache(CACHE_MAX_AGE)
    t = sweep_tmp(TMP_MAX_AGE)
    if any(x[0] for x in (d, c, t)):
        logger.info("boot sweep: downloads %d, thumbnails %d, scratch %d", d[0], c[0], t[0])


async def janitor() -> None:
    import time as _time

    logger.info(
        "janitor: assistant identity auto-refresh every %ds",
        ASSISTANT_REFRESH_EVERY,
    )
    last_identity = _time.time()
    while True:
        await asyncio.sleep(JANITOR_EVERY)
        try:
            sweep_downloads(DOWNLOAD_MAX_AGE)
            sweep_cache(CACHE_MAX_AGE)
            sweep_tmp(TMP_MAX_AGE)
        except Exception as e:  # noqa: BLE001
            logger.warning("janitor: %r", e)

        if _time.time() - last_identity >= ASSISTANT_REFRESH_EVERY:
            last_identity = _time.time()
            try:
                from bobby import userbot

                await userbot.refresh_identities()
            except Exception as e:  # noqa: BLE001
                logger.warning("janitor: identity refresh skipped: %r", e)
