"""Yuki Music API client (owner 2026-10-04).

Streams a YouTube video's audio through the Yuki gateway instead of letting
yt-dlp hit YouTube's bot-wall:

    GET {base}/stream/{VIDEO_ID}?key={API_KEY}&type=audio&quality={_QUALITY}

The tier is inert until a key is configured, and trips a circuit breaker
after a few rejections so a revoked/expired key can never slow playback.
"""
import os
import re
import time

import aiohttp

from bobby import logger

_QUALITY = os.getenv("YUKI_QUALITY", "128")  # API serves one master

_DEFAULT_PRIMARY = "https://music.yukiapi.site"
_DEFAULT_BACKUP = "https://play.yukiapi.site"

_TRIES = 0
_FAILS = 0
_PAUSED_UNTIL = 0.0
_base_down: dict[str, float] = {}   # base -> retry-after epoch
_BASE_COOLDOWN = 180.0            # a 5xx/timeout endpoint is parked this long


def mark_base_down(base: str) -> None:
    """Park an endpoint that just failed so later tiers skip it.

    Every tier used to re-try BOTH endpoints on every song; with the API
    answering HTTP 530 that was ~40s of dead air before a fallback played
    (owner 2026-10-13).
    """
    if base:
        _base_down[base] = time.time() + _BASE_COOLDOWN


def _bases_live(primary: str, backup: str) -> list:
    now = time.time()
    return [b for b in (primary, backup) if _base_down.get(b, 0.0) < now]
_BREAKER_AFTER = 3
_BREAKER_SECONDS = 900


def _key() -> str:
    try:
        from bobby import config
        key = getattr(config, "YUKI_API_KEY", "") or ""
    except Exception:
        key = ""
    return (key or os.getenv("YUKI_API_KEY", "")).strip()


def _bases() -> tuple[str, str]:
    try:
        from bobby import config
        pri = getattr(config, "YUKI_API_URL", "") or _DEFAULT_PRIMARY
        bak = getattr(config, "YUKI_API_BACKUP", "") or _DEFAULT_BACKUP
    except Exception:
        pri, bak = _DEFAULT_PRIMARY, _DEFAULT_BACKUP
    return pri, bak


def video_id(value: str) -> str | None:
    """YouTube id out of a URL or a bare id; None for catalogue ids."""
    v = (value or "").strip()
    if not v:
        return None
    if ":" in v and not v.startswith("http"):
        return None  # "saavn:xxx" / "audius:xxx" are not YouTube videos
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{6,})", v)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", v):
        return v
    return None


def stream_url_for(vid: str) -> str:
    pri, _ = _bases()
    return f"{pri}/stream/{vid}?key={_key()}&type=audio&quality={_QUALITY}"


video_id_of = video_id


async def stream_url(track_id: str) -> str | None:
    """A playable audio URL for this YouTube id, or None (never raises)."""
    global _TRIES, _FAILS, _PAUSED_UNTIL
    key = _key()
    if not key or key.upper().startswith("YOUR_API"):
        return None
    if time.time() < _PAUSED_UNTIL:
        return None
    vid = video_id(track_id)
    if not vid:
        return None
    pri, bak = _bases()
    for base in (_bases_live(pri, bak) or [pri]):
        url = f"{base}/stream/{vid}?key={key}&type=audio&quality={_QUALITY}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    url,
                    headers={"Range": "bytes=0-1"},
                    timeout=aiohttp.ClientTimeout(total=15, sock_connect=8),
                ) as r:
                    if r.status in (200, 206):
                        _FAILS = 0
                        return url
                    if r.status == 403:
                        # do not read the body: it can echo the key
                        logger.info("yuki: key rejected (403) by %s", base)
                    else:
                        logger.info("yuki: %s -> HTTP %s (parked %ds)", base, r.status,
                                    int(_BASE_COOLDOWN))
                        mark_base_down(base)
        except Exception as ex:  # noqa: BLE001
            logger.info("yuki: %s unreachable: %s (parked %ds)", base,
                        type(ex).__name__, int(_BASE_COOLDOWN))
            mark_base_down(base)
    _TRIES += 1
    _FAILS += 1
    if _FAILS >= _BREAKER_AFTER:
        _PAUSED_UNTIL = time.time() + _BREAKER_SECONDS
        logger.warning(
            "yuki: %d consecutive rejections - pausing this tier for %ds",
            _FAILS, _BREAKER_SECONDS,
        )
    return None


async def download(video_id: str, dest_dir: str = "downloads") -> str | None:
    """Fetch the audio file through the API and save it locally.

    Used as the download tier so the bot's last-resort path never has to
    touch YouTube directly (the datacenter IP is bot-walled).
    """
    vid = video_id_of(video_id)
    key = _key()
    if not vid or not key or key.upper().startswith("YOUR_API"):
        return None
    if time.time() < _PAUSED_UNTIL:
        return None
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError:
        return None
    dest = os.path.join(dest_dir, f"{vid}.mp3")
    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        return dest
    pri, bak = _bases()
    for base in (_bases_live(pri, bak) or [pri]):
        url = f"{base}/stream/{vid}?key={key}&type=audio&quality={_QUALITY}"
        tmp = dest + ".part"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(
                        total=300, sock_connect=15)) as r:
                    if r.status != 200:
                        if r.status >= 500:
                            mark_base_down(base)
                        continue
                    with open(tmp, "wb") as f:
                        async for chunk in r.content.iter_chunked(131072):
                            f.write(chunk)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 10000:
                os.replace(tmp, dest)
                return dest
        except Exception as ex:  # noqa: BLE001
            logger.info("yuki download failed: %s", type(ex).__name__)
        try:
            os.remove(tmp)
        except OSError:
            pass
    return None
