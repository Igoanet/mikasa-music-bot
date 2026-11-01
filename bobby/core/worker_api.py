"""Worker API client for YouTube audio/video downloading.
API URL: https://youtubenewapi.skybotsdeveloper.workers.dev/api
Key: itsmesid
"""
import asyncio
import logging
import os
import re
import aiohttp

logger = logging.getLogger("bobby.worker_api")

WORKER_API_URL = os.getenv(
    "WORKER_API_URL",
    "https://youtubenewapi.skybotsdeveloper.workers.dev/api",
).strip()
WORKER_API_KEY = os.getenv("WORKER_API_KEY", "itsmesid").strip()


def video_id_of(value: str) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if ":" in v and not v.startswith("http"):
        return None
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{6,})", v)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", v):
        return v
    return None


async def get_worker_media(vid_id: str, media_format: str = "mp3") -> dict | None:
    if not WORKER_API_URL or not WORKER_API_KEY:
        return None
    vid = video_id_of(vid_id)
    if not vid:
        return None

    params = {
        "key": WORKER_API_KEY,
        "url": f"https://youtube.com/watch?v={vid}",
        "format": media_format,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(WORKER_API_URL, params=params, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                if resp.status != 200:
                    logger.warning("Worker API returned HTTP %s for %s", resp.status, vid)
                    return None
                data = await resp.json()
                if not data.get("success"):
                    logger.warning("Worker API error for %s: %s", vid, data.get("error"))
                    return None
                return data
    except Exception as ex:
        logger.warning("Worker API request failed for %s: %s", vid, ex)
        return None


async def download(video_id: str, video: bool = False, dest_dir: str = "downloads") -> str | None:
    vid = video_id_of(video_id)
    if not vid:
        return None

    os.makedirs(dest_dir, exist_ok=True)
    ext = "mp4" if video else "mp3"
    dest = os.path.join(dest_dir, f"{vid}.{ext}")

    # 1. Local Cache check: if file already exists and is non-empty, use it immediately
    if os.path.exists(dest) and os.path.getsize(dest) > 100000:
        return dest

    # 2. Query Worker API
    fmt = "mp4" if video else "mp3"
    data = await get_worker_media(vid, fmt)
    if not data:
        return None

    dl_url = data.get("downloads") or data.get("downloadUrl") or data.get("directLink")
    if not dl_url:
        return None

    # 3. Stream download to disk
    tmp = f"{dest}.downloading"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(dl_url, timeout=aiohttp.ClientTimeout(total=180)) as resp:
                if resp.status != 200:
                    logger.warning("Worker download URL returned %s for %s", resp.status, vid)
                    return None
                with open(tmp, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)

        if os.path.exists(tmp) and os.path.getsize(tmp) > 100000:
            if os.path.exists(dest):
                try:
                    os.remove(dest)
                except OSError:
                    pass
            os.replace(tmp, dest)
            logger.info("Worker API successfully downloaded %s (%s bytes)", vid, os.path.getsize(dest))
            return dest
    except Exception as ex:
        logger.warning("Worker stream download failed for %s: %s", vid, ex)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    return None
