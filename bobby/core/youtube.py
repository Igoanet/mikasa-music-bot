# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import asyncio
import json
import os
import random
import re
import shlex
import shutil
import string
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Union

import aiohttp
import requests
import yt_dlp
from py_yt import Playlist, VideosSearch
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bobby import config, logger
from bobby.helpers import Track, utils

try:
    from py_yt.extras import Recommendations
except ImportError:
    try:
        from youtubesearchpython.future.extras import Recommendations
    except ImportError:
        Recommendations = None

# Worker API settings from Youtube (3).py
WORKER_FALLBACK_API_URL = os.getenv(
    "WORKER_FALLBACK_API_URL",
    "https://youtubenewapi.skybotsdeveloper.workers.dev",
).strip()
WORKER_FALLBACK_API_KEY = os.getenv("WORKER_FALLBACK_API_KEY", "itsmesid").strip()
YTPROXY_URL = os.getenv("YTPROXY_URL", "").strip().rstrip("/")
YT_API_KEY = os.getenv("YT_API_KEY", "").strip()
MIN_CACHED_MEDIA_BYTES = 128 * 1024
DOWNLOAD_CACHE_EXTENSIONS = (".m4a", ".mp3", ".mp4", ".webm")


def int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def bool_env(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "off", "no"}


STREAM_HTTP_PROBE_TIMEOUT = max(2, int_env("YOUTUBE_STREAM_HTTP_PROBE_TIMEOUT", 5))
STREAM_PREFLIGHT_TIMEOUT = max(3, int_env("YOUTUBE_STREAM_PREFLIGHT_TIMEOUT", 15))
STREAM_PREFLIGHT_ENABLED = bool_env("YOUTUBE_STREAM_PREFLIGHT", True)
DOWNLOAD_CACHE_MAX_BYTES = max(0, int_env("DOWNLOAD_CACHE_MAX_MB", 2048)) * 1024 * 1024
DOWNLOAD_CACHE_MIN_FREE_BYTES = max(0, int_env("DOWNLOAD_CACHE_MIN_FREE_MB", 512)) * 1024 * 1024
WORKER_FALLBACK_API_ATTEMPTS = min(3, max(1, int_env("WORKER_FALLBACK_API_ATTEMPTS", 3)))
WORKER_FALLBACK_API_RETRY_DELAY_MS = min(
    5000,
    max(0, int_env("WORKER_FALLBACK_API_RETRY_DELAY_MS", 1000)),
)


def build_subprocess_env():
    return os.environ.copy()


def build_yt_dlp_args(args: list[str]) -> list[str]:
    return list(args)


async def shell_cmd(cmd):
    if isinstance(cmd, (list, tuple)):
        args = [str(item) for item in cmd]
    else:
        args = shlex.split(str(cmd))
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=build_subprocess_env(),
    )
    out, errorz = await proc.communicate()
    stdout = out.decode("utf-8", errors="replace")
    stderr = errorz.decode("utf-8", errors="replace")
    if stdout and proc.returncode == 0:
        return stdout
    if stderr:
        if "unavailable videos are hidden" in stderr.lower():
            return stdout
        return stderr
    return stdout


async def validate_playable_stream_url(url: str, media_type: str = "audio") -> bool:
    if not url:
        return False

    loop = asyncio.get_running_loop()

    def http_probe():
        session = None
        try:
            session = requests.Session()
            response = session.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Range": "bytes=0-0",
                },
                stream=True,
                timeout=STREAM_HTTP_PROBE_TIMEOUT,
            )
            if response.status_code not in {200, 206}:
                return False
            for chunk in response.iter_content(chunk_size=1):
                return bool(chunk)
            return True
        except Exception:
            return False
        finally:
            if session:
                session.close()

    if not await loop.run_in_executor(None, http_probe):
        return False
    if not STREAM_PREFLIGHT_ENABLED:
        return True

    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        url,
        "-map",
        "0:a:0",
        "-t",
        "1",
        "-f",
        "null",
        "-",
    ]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=build_subprocess_env(),
        )
        _, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=STREAM_PREFLIGHT_TIMEOUT,
        )
        if proc.returncode == 0:
            return True
        return False
    except asyncio.TimeoutError:
        if proc and proc.returncode is None:
            proc.kill()
            try:
                await proc.communicate()
            except Exception:
                pass
        return False
    except FileNotFoundError:
        return True
    except Exception:
        return False


class DummyLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = re.compile(
            r"(https?://)?(www\.|m\.|music\.)?"
            r"(youtube\.com/(watch\?([^#\s]*&)?v=|shorts/|live/|embed/|v/|playlist\?list=)|youtu\.be/)"
            r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
        )
        self.iregex = re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)"
            r"(?!/(watch\?(?:[^#\s]*&)?v=[A-Za-z0-9_-]{11}|shorts/[A-Za-z0-9_-]{11}"
            r"|live/[A-Za-z0-9_-]{11}|embed/[A-Za-z0-9_-]{11}|v/[A-Za-z0-9_-]{11}"
            r"|playlist\?list=PL[A-Za-z0-9_-]+|[A-Za-z0-9_-]{11}))\S*"
        )
        self.id_regex = re.compile(
            r"(?:^|https?://)(?:www\.|m\.|music\.)?"
            r"(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|shorts/|live/|embed/|v/)"
            r"|youtu\.be/)"
            r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
        )
        self.listbase = "https://youtube.com/playlist?list="
        self.cookies = []
        self.checked = False
        self.cookie_dir = "bobby/cookies"
        self.warned = False
        self._background_cache_tasks = {}
        self._inflight = {}
        self._dl_sem = asyncio.Semaphore(4)
        self._dl_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="yt_dl")

    def _has_disallowed_url_chars(self, link: str) -> bool:
        return any(char in link for char in [";", "&", "|", "$", "\n", "\r", "`"])

    def _clean_autoplay_query(self, title: str) -> str:
        if not title:
            return ""
        title = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", title)
        title = re.sub(
            r"\b(official|video|audio|lyrics?|lyrical|fullscreen|4k|hd|hq|remix|status|song|songs|music|feat\.?|ft\.?|prod\.?|visualizer)\b",
            " ",
            title,
            flags=re.IGNORECASE,
        )
        title = re.sub(r"\s+", " ", title).strip()
        return title[:100]

    def _duration_to_seconds(self, duration: str) -> int:
        if not duration or str(duration) == "None":
            return 0
        try:
            return int(utils.to_seconds(duration))
        except Exception:
            return 0

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    def get_cookies(self):
        if not self.checked:
            if os.path.exists(self.cookie_dir):
                for file in os.listdir(self.cookie_dir):
                    if file.endswith(".txt"):
                        self.cookies.append(f"{self.cookie_dir}/{file}")
            self.checked = True
        if not self.cookies:
            return None
        return random.choice(self.cookies)

    async def save_cookies(self, urls: list[str]) -> None:
        if not urls:
            return
        os.makedirs(self.cookie_dir, exist_ok=True)
        async with aiohttp.ClientSession() as session:
            for url in urls:
                name = url.split("/")[-1]
                link = "https://batbin.me/raw/" + name
                try:
                    async with session.get(link) as resp:
                        resp.raise_for_status()
                        with open(f"{self.cookie_dir}/{name}.txt", "wb") as fw:
                            fw.write(await resp.read())
                except Exception as e:
                    logger.warning("Failed to save cookie from %s: %s", url, e)

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset in (None,):
            return None
        return text[offset : offset + length]

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        if "?si=" in link:
            link = link.split("?si=")[0]
        elif "&si=" in link:
            link = link.split("&si=")[0]

        results = VideosSearch(link, limit=1)
        res_data = await results.next()
        for result in res_data.get("result", []):
            title = result["title"]
            duration_min = result.get("duration")
            thumbnail = result["thumbnails"][0]["url"].split("?")[0] if result.get("thumbnails") else ""
            vidid = result["id"]
            if str(duration_min) == "None" or not duration_min:
                duration_sec = 0
            else:
                duration_sec = self._duration_to_seconds(duration_min)
            return title, duration_min, duration_sec, thumbnail, vidid
        return None, None, 0, None, None

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next()).get("result", []):
            return result["title"]
        return None

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next()).get("result", []):
            return result.get("duration")
        return None

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next()).get("result", []):
            return result["thumbnails"][0]["url"].split("?")[0]
        return None

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        args = build_yt_dlp_args(["yt-dlp", "-g", "-f", "best[height<=?720][width<=?1280]", f"{link}"])
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=build_subprocess_env(),
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
        return 0, stderr.decode()

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next()).get("result", []):
            title = result["title"]
            duration_min = result.get("duration")
            vidid = result["id"]
            yturl = result.get("link") or f"{self.base}{vidid}"
            thumbnail = result["thumbnails"][0]["url"].split("?")[0] if result.get("thumbnails") else ""
            track_details = {
                "title": title,
                "link": yturl,
                "vidid": vidid,
                "duration_min": duration_min,
                "thumb": thumbnail,
            }
            return track_details, vidid
        return None, None

    async def track_from_url(self, url: str, m_id: int, video: bool = False) -> Track | None:
        match = self.id_regex.search(url)
        if not match:
            return None
        vid = match.group(1)
        title, dur_min, dur_sec, thumb, res_id = await self.details(vid, videoid=True)
        if not title:
            title = "YouTube Video"
        return Track(
            id=vid,
            duration=dur_min or "—",
            duration_sec=dur_sec,
            message_id=m_id,
            title=title[:100],
            thumbnail=thumb,
            url=self.base + vid,
            video=video,
        )

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        if not query or not query.strip():
            return None
        query = query.strip()
        match = self.id_regex.search(query)
        if match:
            return await self.track_from_url(query, m_id, video=video)

        # If direct JioSaavn URL passed in query, resolve directly
        if "jiosaavn.com" in query:
            try:
                from bobby.core.jiosaavn import saavn
                s_track = await saavn.track_from_url(query, m_id)
                if s_track:
                    return s_track
            except Exception as e:
                logger.warning("JioSaavn url track resolution error: %s", e)

        # Clean tracking params if query looks like a link
        clean_query = query
        if ("http://" in clean_query or "https://" in clean_query or "youtu" in clean_query) and "&" in clean_query:
            clean_query = clean_query.split("&")[0]
        if "?si=" in clean_query:
            clean_query = clean_query.split("?si=")[0]
        elif "&si=" in clean_query:
            clean_query = clean_query.split("&si=")[0]

        try:
            results = []
            search = VideosSearch(clean_query, limit=10)
            search_results = (await search.next()).get("result", [])

            # Filter videos longer than 1 hour (matching Youtube (3).py)
            for item in search_results:
                dur_str = item.get("duration", "0:00")
                dur_sec = self._duration_to_seconds(dur_str)
                if dur_sec <= 3600:
                    results.append((item, dur_sec, dur_str))

            if not results:
                return None

            # Pick candidate 0 (top YouTube match). If candidate 0 is a teaser (< 30s) and candidate 1 is full song, pick candidate 1.
            selected, dur_sec, dur_str = results[0]
            if dur_sec < 30 and len(results) > 1 and results[1][1] >= 30:
                selected, dur_sec, dur_str = results[1]

            vid = selected["id"]
            title = selected.get("title") or "YouTube Track"
            thumb = (
                selected["thumbnails"][0]["url"].split("?")[0]
                if selected.get("thumbnails")
                else f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
            )
            chan_dict = selected.get("channel") if isinstance(selected.get("channel"), dict) else {}
            chan_name = chan_dict.get("name") or None

            return Track(
                id=vid,
                channel_name=chan_name,
                duration=dur_str,
                duration_sec=dur_sec,
                message_id=m_id,
                title=title[:100],
                thumbnail=thumb,
                url=selected.get("link") or f"{self.base}{vid}",
                video=video,
            )
        except Exception as e:
            logger.warning("YouTube search failed for %r: %s", query, e)
            return None

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track]:
        if "&" in url:
            url = url.split("&")[0]
        args = build_yt_dlp_args(
            [
                "yt-dlp",
                "-i",
                "--get-id",
                "--flat-playlist",
                "--playlist-end",
                str(limit),
                "--skip-download",
                url,
            ]
        )
        out = await shell_cmd(args)
        ids = [k.strip() for k in out.split("\n") if k.strip()]
        tracks = []
        for vid in ids[:limit]:
            try:
                t = await self.track_from_url(vid, 0, video=video)
                if t:
                    t.user = user
                    tracks.append(t)
            except Exception:
                continue
        return tracks

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = []
        search = VideosSearch(link, limit=10)
        search_results = (await search.next()).get("result", [])
        for result in search_results:
            duration_str = result.get("duration", "0:00")
            sec = self._duration_to_seconds(duration_str)
            if sec <= 3600:
                results.append(result)
        if not results or query_type >= len(results):
            raise ValueError("No suitable videos found within duration limit")
        selected = results[query_type]
        thumb = selected["thumbnails"][0]["url"].split("?")[0] if selected.get("thumbnails") else ""
        return selected["title"], selected.get("duration"), thumb, selected["id"]

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        ydl_opts = {"quiet": True}
        ydl = yt_dlp.YoutubeDL(ydl_opts)
        formats_available = []
        r = ydl.extract_info(link, download=False)
        for fmt in r.get("formats", []):
            if "dash" not in str(fmt.get("format", "")).lower():
                formats_available.append(
                    {
                        "format": fmt.get("format"),
                        "filesize": fmt.get("filesize"),
                        "format_id": fmt.get("format_id"),
                        "ext": fmt.get("ext"),
                        "format_note": fmt.get("format_note"),
                        "yturl": link,
                    }
                )
        return formats_available, link

    async def autoplay(
        self,
        videoid: str,
        title: str = "",
        max_duration: Union[int, None] = None,
    ) -> Union[dict, None]:
        candidates = []
        if videoid and Recommendations is not None and hasattr(Recommendations, "get"):
            try:
                candidates = await Recommendations.get(videoid, timeout=5) or []
            except Exception as err:
                logger.warning("Autoplay recommendations failed for %s: %s", videoid, err)

        if not candidates:
            query = self._clean_autoplay_query(title)
            if not query:
                query = "popular songs"
            try:
                search = VideosSearch(query, limit=12)
                candidates = (await search.next()).get("result", [])
            except Exception as err:
                logger.warning("Autoplay fallback search failed for %s: %s", query, err)
                return None

        limit_sec = max_duration or config.DURATION_LIMIT
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            cand_id = candidate.get("id")
            if not cand_id or cand_id == videoid:
                continue
            cand_dur = candidate.get("duration")
            dur_sec = self._duration_to_seconds(cand_dur)
            if dur_sec and dur_sec > limit_sec:
                continue
            cand_title = candidate.get("title")
            thumbs = candidate.get("thumbnails") or []
            cand_thumb = thumbs[0].get("url").split("?")[0] if thumbs else ""
            return {
                "title": cand_title,
                "duration_min": cand_dur,
                "duration_sec": dur_sec,
                "thumb": cand_thumb,
                "vidid": cand_id,
                "link": candidate.get("link") or f"{self.base}{cand_id}",
            }
        return None

    async def get_live(self, url: str, m_id: int, video: bool = False) -> Track | None:
        match = self.id_regex.search(url)
        if not match:
            return None
        video_id = match.group(1)

        def _probe():
            opts = {
                "quiet": True,
                "no_warnings": True,
                "logger": DummyLogger(),
                "noplaylist": True,
                "format": "best[height<=480][protocol*=m3u8]/best[protocol*=m3u8]/best" if not video else "best[height<=720]/best",
                "nocheckcertificate": True,
                "socket_timeout": 10,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            info = await asyncio.to_thread(_probe)
            if not info or not (info.get("is_live") or info.get("live_status") == "is_live"):
                return None
            feed = info.get("url")
            return Track(
                id=video_id,
                channel_name=info.get("uploader"),
                duration="🔴 LIVE",
                duration_sec=0,
                file_path=feed,
                message_id=m_id,
                title=(info.get("title") or "Live Stream")[:100],
                thumbnail=(info.get("thumbnail") or "").split("?")[0] or None,
                url=self.base + video_id,
                view_count="LIVE",
                video=video,
            )
        except Exception:
            return None

    # --- Worker API & Download Engine from Youtube (3).py ---

    async def download(
        self,
        link: str,
        mystic=None,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
        stream: Union[bool, str] = None,
        progress_msg=None,
        lang=None,
    ) -> Union[str, tuple]:
        if videoid:
            vid_id = link
        else:
            match = self.id_regex.search(link)
            vid_id = match.group(1) if match else link

        os.makedirs("downloads", exist_ok=True)
        loop = asyncio.get_running_loop()

        def create_session():
            session = requests.Session()
            retries = Retry(total=1, backoff_factor=0.1, status_forcelist=[502, 503, 504])
            session.mount("http://", HTTPAdapter(max_retries=retries))
            session.mount("https://", HTTPAdapter(max_retries=retries))
            return session

        def cached_media_ready(filepath):
            try:
                return os.path.exists(filepath) and os.path.getsize(filepath) >= MIN_CACHED_MEDIA_BYTES
            except Exception:
                return False

        def partial_path(filepath):
            return f"{filepath}.downloading"

        def first_media_url(value, media_format=None):
            if isinstance(value, str):
                v = value.strip()
                return v or None
            if isinstance(value, dict):
                preferred_keys = (
                    media_format,
                    "url",
                    "link",
                    "downloadUrl",
                    "download_url",
                    "directLink",
                    "streamLink",
                    "audio_url",
                    "video_url",
                )
                for key in preferred_keys:
                    if not key:
                        continue
                    u = first_media_url(value.get(key), media_format)
                    if u:
                        return u
                for item in value.values():
                    u = first_media_url(item, media_format)
                    if u:
                        return u
            if isinstance(value, (list, tuple)):
                for item in value:
                    u = first_media_url(item, media_format)
                    if u:
                        return u
            return None

        def select_media_links(data, media_format, prefer_stream=False):
            stream_keys = (
                "streamingUrl",
                "streaming_url",
                "playbackUrl",
                "playback_url",
                "streamLink",
                "streamUrl",
                "stream_url",
                "audioUrl",
                "audio_url",
            )
            download_keys = (
                "directLink",
                "directUrl",
                "downloadLink",
                "downloadUrl",
                "download_url",
                "downloads",
            )
            play_keys = stream_keys + download_keys if prefer_stream else download_keys + stream_keys
            cache_keys = download_keys + stream_keys

            def pick(keys):
                for key in keys:
                    u = first_media_url(data.get(key), media_format)
                    if u:
                        return key, u
                return None, None

            play_key, play_url = pick(play_keys)
            cache_key, cache_url = pick(cache_keys)
            return {
                "play_key": play_key,
                "play_url": play_url,
                "cache_key": cache_key or play_key,
                "cache_url": cache_url or play_url,
            }

        async def download_with_requests_fallback(url, filepath, headers=None):
            session = None
            temp_filepath = partial_path(filepath)
            try:
                session = create_session()
                response = session.get(url, headers=headers, stream=True, timeout=60)
                response.raise_for_status()
                chunk_size = 1024 * 1024
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
                with open(temp_filepath, "wb") as file:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            file.write(chunk)
                os.replace(temp_filepath, filepath)
                return filepath
            except Exception as e:
                logger.error("Requests download failed for %s: %s", filepath, e)
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
                return None
            finally:
                if session:
                    session.close()

        async def download_with_ytdlp(url, filepath, headers=None):
            temp_filepath = partial_path(filepath)

            def run_dl():
                ydl_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "noprogress": True,
                    "outtmpl": temp_filepath,
                    "force_overwrites": True,
                    "nopart": True,
                    "retries": 3,
                    "http_headers": headers or {},
                    "concurrent_fragment_downloads": 8,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

            try:
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
                await loop.run_in_executor(None, run_dl)
                if os.path.exists(temp_filepath):
                    os.replace(temp_filepath, filepath)
                    return filepath
            except Exception as e:
                logger.error("yt-dlp download failed: %s", e)
            if os.path.exists(temp_filepath):
                os.remove(temp_filepath)
            return None

        async def download_from_source(url, filepath, headers=None):
            result = await download_with_requests_fallback(url, filepath, headers)
            if result:
                return result
            return await download_with_ytdlp(url, filepath, headers)

        def fetch_worker_fallback_links_sync(v_id, media_format):
            if not WORKER_FALLBACK_API_URL or not WORKER_FALLBACK_API_KEY:
                return None
            session = None
            try:
                session = create_session()
                api_url = f"{WORKER_FALLBACK_API_URL.rstrip('/')}/api"
                payload = {
                    "key": WORKER_FALLBACK_API_KEY,
                    "url": f"https://youtube.com/watch?v={v_id}",
                    "format": media_format,
                }
                response = None
                for attempt in range(1):
                    response = session.get(api_url, params=payload, timeout=12)
                    if response.status_code not in {429, 500, 502, 503, 504}:
                        break
                    time.sleep(1.0)
                response.raise_for_status()
                data = response.json()
                if not data.get("success"):
                    return None
                return select_media_links(data, media_format, prefer_stream=bool(stream))
            except Exception as e:
                logger.error("Worker fallback API failed for %s: %s", v_id, e)
                return None
            finally:
                if session:
                    session.close()

        async def get_worker_fallback_links(v_id, media_format):
            return await loop.run_in_executor(None, fetch_worker_fallback_links_sync, v_id, media_format)

        async def audio_dl(v_id):
            filepath = os.path.join("downloads", f"{v_id}.mp3")
            if cached_media_ready(filepath):
                return filepath, True
            worker_audio = await get_worker_fallback_links(v_id, "mp3")
            if worker_audio:
                worker_audio_url = worker_audio.get("play_url")
                worker_audio_cache_url = worker_audio.get("cache_url") or worker_audio_url
                if stream and await validate_playable_stream_url(worker_audio_url, "audio"):
                    # Stream directly and download in background
                    asyncio.create_task(download_from_source(worker_audio_cache_url, filepath))
                    return worker_audio_url, False
                res = await download_from_source(worker_audio_cache_url, filepath)
                if res:
                    return res, True

            # yt-dlp direct download fallback
            cookie = self.get_cookies()
            opts = {
                "format": "bestaudio/best",
                "outtmpl": filepath,
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
            if cookie:
                opts["cookiefile"] = cookie
            try:
                await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).download([f"{self.base}{v_id}"]))
                if cached_media_ready(filepath):
                    return filepath, True
            except Exception as e:
                logger.warning("Direct yt-dlp audio download failed for %s: %s", v_id, e)
            return None, True

        async def video_dl(v_id):
            filepath = os.path.join("downloads", f"{v_id}.mp4")
            if cached_media_ready(filepath):
                return filepath, True
            worker_video = await get_worker_fallback_links(v_id, "mp4")
            if worker_video:
                worker_video_url = worker_video.get("play_url")
                worker_video_cache_url = worker_video.get("cache_url") or worker_video_url
                if stream and await validate_playable_stream_url(worker_video_url, "video"):
                    asyncio.create_task(download_from_source(worker_video_cache_url, filepath))
                    return worker_video_url, False
                res = await download_from_source(worker_video_cache_url, filepath)
                if res:
                    return res, True

            # yt-dlp direct download fallback
            cookie = self.get_cookies()
            opts = {
                "format": "best[height<=?720][width<=?1280]/best",
                "outtmpl": filepath,
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
            }
            if cookie:
                opts["cookiefile"] = cookie
            try:
                await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).download([f"{self.base}{v_id}"]))
                if cached_media_ready(filepath):
                    return filepath, True
            except Exception as e:
                logger.warning("Direct yt-dlp video download failed for %s: %s", v_id, e)
            return None, True

        if songvideo:
            fpath = f"downloads/{title}.mp4"
            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(
                    {"format": f"{format_id}+140", "outtmpl": fpath, "quiet": True, "no_warnings": True}
                ).download([link]),
            )
            return fpath
        elif songaudio:
            fpath = f"downloads/{title}.mp3"
            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(
                    {
                        "format": format_id,
                        "outtmpl": fpath,
                        "quiet": True,
                        "no_warnings": True,
                        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
                    }
                ).download([link]),
            )
            return fpath
        elif video:
            res_file, direct = await video_dl(vid_id)
        else:
            res_file, direct = await audio_dl(vid_id)

        # For compatibility: if called by bobby.core.calls, return string if expected
        if res_file:
            return res_file
        return None

    async def play_source(
        self, track: Track, video: bool = False, progress_msg=None, lang=None
    ) -> str | None:
        if track.duration == "🔴 LIVE" or track.view_count == "LIVE":
            live = await self.get_live(track.url or self.base + track.id, track.message_id, video)
            if live and live.file_path:
                track.file_path = live.file_path
                return live.file_path
            return None

        # Handle JioSaavn CDN streaming and downloads
        if track.id.startswith("saavn:"):
            from bobby.core.jiosaavn import saavn
            import urllib.request
            ext = "mp3"
            clean_id = track.id.replace(":", "_")
            cached_file = os.path.join("downloads", f"{clean_id}.{ext}")
            if os.path.exists(cached_file) and os.path.getsize(cached_file) >= MIN_CACHED_MEDIA_BYTES:
                logger.info("play_source[%s]: local cache hit (%s)", track.id, ext)
                return cached_file
            direct_urls = saavn.direct_for(track.id)
            if not direct_urls:
                await saavn.resolve_url(track.id)
                direct_urls = saavn.direct_for(track.id)

            loop = asyncio.get_event_loop()
            def _fetch_cdn(url, dest):
                temp = dest + ".tmp"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=20) as resp, open(temp, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                    if os.path.exists(temp) and os.path.getsize(temp) >= MIN_CACHED_MEDIA_BYTES:
                        os.replace(temp, dest)
                        return dest
                except Exception as e:
                    if os.path.exists(temp):
                        try:
                            os.remove(temp)
                        except Exception:
                            pass
                    return None
                return None

            for cdn_url in direct_urls:
                try:
                    res = await loop.run_in_executor(None, _fetch_cdn, cdn_url, cached_file)
                    if res and os.path.exists(res):
                        logger.info("play_source[%s]: JioSaavn direct CDN download success", track.id)
                        return res
                except Exception as ex:
                    logger.warning("saavn download failed from %s: %s", cdn_url, ex)

            # Fallback to YouTube search if JioSaavn CDN stream fails
            yt_track = await self.search(f"{track.title} {track.channel_name or ''}", track.message_id, video=video)
            if yt_track and yt_track.id != track.id:
                return await self.play_source(yt_track, video=video, progress_msg=progress_msg, lang=lang)
            return None

        # Check local cache first (instant 0ms latency!)
        ext = "mp4" if video else "mp3"
        cached_file = os.path.join("downloads", f"{track.id}.{ext}")
        if os.path.exists(cached_file) and os.path.getsize(cached_file) >= MIN_CACHED_MEDIA_BYTES:
            logger.info("play_source[%s]: local cache hit (%s)", track.id, ext)
            return cached_file

        # Download via Worker API backend (enable instant stream while caching in background)
        result = await self.download(
            track.id,
            mystic=progress_msg,
            video=video,
            videoid=True,
            stream=True,
            progress_msg=progress_msg,
            lang=lang,
        )
        if isinstance(result, tuple):
            result = result[0]
        if result and os.path.exists(result):
            logger.info("play_source[%s]: worker API backend downloaded successfully", track.id)
            return result
        elif result and str(result).startswith("http"):
            logger.info("play_source[%s]: worker API stream URL", track.id)
            return result

        logger.error("play_source[%s]: failed to resolve playable source", track.id)
        return None

    async def download_with_fallback(
        self, track: Track, video: bool = False, progress_msg=None, lang=None, local_only: bool = False
    ) -> str | None:
        return await self.play_source(track, video=video, progress_msg=progress_msg, lang=lang)
