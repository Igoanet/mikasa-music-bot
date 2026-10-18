# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.

"""JioSaavn source — the permanent fix for YouTube's per-video bot-check on
datacenter IPs. Plain-text audio queries resolve here first: fast CDN
downloads, no throttling, no locks, and it covers the Indian catalogue this
bot mostly serves. YouTube stays the fallback for anything JioSaavn doesn't
return (lofi uploads, remixes, non-Indian, video mode)."""

import base64
import html
import math
import re
from urllib.parse import urlsplit

import aiohttp

from bobby import logger
from bobby.helpers import Track

API = "https://www.jiosaavn.com/api.php"
_PREFIX = "saavn:"

# re-upload / cover markers. When the user did NOT ask for one of these, the
# original movie/album track must always outrank the flavour-of-the-week copy
COPY_TOKENS = (
    "lofi", "lo-fi", "slowed", "reverb", "cover", "remix", "mashup",
    "unplugged", "recreate", "recreated", "8d", "sped up", "speed up",
    "nightcore", "karaoke", "instrumental", "acoustic", "reprise",
    "tribute", "a cappella",
)


def _squash(text: str) -> str:
    """alphanumerics-only, so 'lo-fi' and 'lofi' compare equal."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


_FLUFF = re.compile(
    r"\b(official|video|lyrical|lyrics?|audio|full song|hd|4k|8d audio|status)\b",
    re.IGNORECASE,
)


def clean_query(query: str) -> str:
    """Strip video-platform fluff ('official video', '(lyrical)', ...) so a
    catalogue search hits the SONG, not a title pattern. Used for the
    JioSaavn retry — keeps even more plays off YouTube entirely."""
    q = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", query)
    q = _FLUFF.sub(" ", q)
    q = re.sub(r"\s+", " ", q).strip(" -|")
    return q or query


def is_copy(text: str, query: str = "") -> bool:
    """True when text looks like a re-upload/cover the user didn't ask for.
    When the query itself names a flavour ('tum hi ho lofi') NOTHING counts
    as a copy — the user is flavour-shopping, so catalogue relevance decides
    (owner rule 2026-09-05: asked-for flavours are never penalized)."""
    q = _squash(query)
    if any(_squash(t) in q for t in COPY_TOKENS):
        return False
    t = _squash(text)
    return any(_squash(tok) in t for tok in COPY_TOKENS)


_DES_KEY = b"38346591"  # JioSaavn's well-known public media-url key


def _decrypt_media_url(encrypted: str) -> str:
    """encrypted_media_url -> direct 96kbps full-track CDN URL (DES-ECB,
    PKCS5-padded). This hash — unlike the preview hash — is the one the CDN
    serves 320/160/96 encodes for. Empty string on any failure."""
    if not encrypted:
        return ""
    try:
        from Crypto.Cipher import DES

        raw = DES.new(_DES_KEY, DES.MODE_ECB).decrypt(base64.b64decode(encrypted))
        pad = raw[-1]
        if 1 <= pad <= 8:
            raw = raw[:-pad]
        return raw.decode("utf-8", "ignore").strip()
    except Exception:
        return ""


def _cdn_ladder(media_url: str) -> list[str]:
    """Full-track CDN candidates from a decrypted 96kbps media URL, best
    first: aac.saavncdn.com/<alb>/<hash>_96.mp4 -> 320/160/96 kbps rungs on
    the same path. Anything not provably in that exact shape returns NO
    ladder — a malformed synthetic URL would just burn ranged-GET validation
    time before the page-extraction fallback anyway (review 2026-09-06).
    """
    try:
        parts = urlsplit((media_url or "").strip())
    except ValueError:
        return []
    if parts.netloc.lower() not in ("preview.saavncdn.com", "aac.saavncdn.com"):
        return []
    match = re.match(r"^(.+)_\d{2,3}(?:_p)?\.mp4$", parts.path, flags=re.IGNORECASE)
    if not match:
        return []
    stem = match.group(1)
    # rebuilt clean: https scheme, aac host, no query/fragment
    return [f"https://aac.saavncdn.com{stem}_{q}.mp4" for q in (320, 160, 96)]


class JioSaavn:
    def __init__(self):
        # track id -> song page url, so download() can resolve the media page
        # again when the queue's prefetcher calls in by id alone
        self.urls: dict[str, str] = {}
        # track id -> direct full-track CDN urls (320 -> 160 -> 96 ladder)
        self.direct: dict[str, list[str]] = {}

    @staticmethod
    def is_saavn(track_id: str | None) -> bool:
        return bool(track_id) and track_id.startswith(_PREFIX)

    def url_for(self, track_id: str) -> str | None:
        return self.urls.get(track_id)

    def direct_for(self, track_id: str) -> list[str]:
        return self.direct.get(track_id) or []

    def _cache(self, track_id: str, page_url: str, media_url: str = "") -> None:
        if page_url:
            self.urls[track_id] = page_url
        ladder = _cdn_ladder(media_url)
        if ladder:
            self.direct[track_id] = ladder
        # bound the maps — entries are only read while their track is queued
        if len(self.urls) > 500:
            self.urls = dict(list(self.urls.items())[-250:])
        if len(self.direct) > 500:
            self.direct = dict(list(self.direct.items())[-250:])

    async def resolve_url(self, track_id: str) -> str | None:
        """Durable id -> page-url resolution. The in-memory map is only a
        cache: on a miss (process restart, queue import, eviction) ask the
        API for the song's perma_url again so queued saavn tracks always
        resolve, no matter when playback reaches them."""
        cached = self.urls.get(track_id)
        # a cached page url is NOT enough — search() fills it without the
        # direct ladder, so fall through to the API call whenever the ladder
        # is missing (once per track; thereafter both are cached)
        if cached and track_id in self.direct:
            return cached
        params = {
            "__call": "song.getDetails",
            "pids": track_id[len(_PREFIX):],
            "_format": "json",
            "_marker": "0",
            "ctx": "wap6dot0",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    API,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json(content_type=None)
        except Exception as ex:
            logger.warning("jiosaavn resolve failed for %s: %s", track_id, ex)
            return None
        songs = data.get("songs") or []
        if not songs:
            return None
        song = songs[0]
        url = song.get("perma_url")
        # the REAL full-track ladder comes from decrypting encrypted_media_url
        # — preview hashes 404 on the CDN (verified 2026-09-06); only the
        # encrypted full-track hash maps to the 320/160/96 encodes
        direct = _decrypt_media_url(song.get("encrypted_media_url") or "")
        self._cache(track_id, url or "", direct)
        return url

    async def _ranked(self, query: str, m_id: int, limit: int = 5) -> list[Track]:
        """Catalogue candidates for a query, best first. search() needs one
        winner; mirror matching needs the runner-ups too — the top hit can
        be a different recording of the same title (the duration guard then
        rejects it and the NEXT candidate is the right song)."""
        params = {
            "__call": "search.getResults",
            "q": query,
            "p": 1,
            "n": max(limit, 5),
            "_format": "json",
            "_marker": "0",
            "ctx": "wap6dot0",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    API,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json(content_type=None)
        except Exception as ex:
            logger.warning("jiosaavn search failed: %s", ex)
            return []

        results = data.get("results") or []
        # rank every candidate instead of trusting JioSaavn's first hit —
        # its top result is often a lofi/cover/recreation, and users want
        # the original famous track. Query-word overlap and play count pull
        # up; re-upload markers push down (unless the user asked for them).
        qwords = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
        scored = []
        for item in results:
            perma_url = item.get("perma_url")
            if not perma_url:
                continue
            try:
                duration_sec = int(item.get("duration") or 0)
            except (TypeError, ValueError):
                duration_sec = 0
            if not duration_sec:
                continue
            title = html.unescape(item.get("song") or item.get("title") or "")
            artists = html.unescape(
                item.get("primary_artists") or item.get("singers") or ""
            )
            album = html.unescape(item.get("album") or "")

            score = 0.0
            if qwords:
                hay = set(re.findall(r"[a-z0-9]+", f"{title} {artists}".lower()))
                score += 10 * sum(1 for w in qwords if w in hay) / len(qwords)
            if is_copy(f"{title} {album}", query):
                score -= 15
            try:
                plays = int(item.get("play_count") or 0)
            except (TypeError, ValueError):
                plays = 0
            if plays > 0:
                score += min(math.log10(plays), 8)

            scored.append((score, item, title, artists, duration_sec, perma_url))

        # stable sort: ties keep the API's original order, exactly like the
        # old first-best-wins loop
        scored.sort(key=lambda s: s[0], reverse=True)
        out = []
        for _score, item, title, artists, duration_sec, perma_url in scored[:limit]:
            track_id = _PREFIX + str(item.get("id"))
            # page url only — the direct ladder is filled by resolve_url from
            # the DECRYPTED full-track hash (preview hashes are dead on the CDN)
            self._cache(track_id, perma_url)
            image = (item.get("image") or "").replace("150x150", "500x500")
            minutes, seconds = divmod(duration_sec, 60)
            out.append(
                Track(
                    id=track_id,
                    channel_name=artists,
                    duration=f"{minutes}:{seconds:02d}",
                    duration_sec=duration_sec,
                    message_id=m_id,
                    title=title[:25],
                    thumbnail=image.replace("http://", "https://", 1) or None,
                    url=perma_url,
                    view_count="",
                    video=False,
                )
            )
        return out

    async def search(self, query: str, m_id: int) -> Track | None:
        ranked = await self._ranked(query, m_id, 1)
        return ranked[0] if ranked else None

    async def search_many(self, query: str, m_id: int, limit: int = 5) -> list[Track]:
        return await self._ranked(query, m_id, limit)


saavn = JioSaavn()
