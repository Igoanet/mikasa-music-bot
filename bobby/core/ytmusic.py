# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.

"""YouTube Music helpers: search ranking + related-song lookups.

Raw ytsearch trusts YouTube's first hit, which is often a lofi/cover
re-upload. YT Music's catalogue gives proper song metadata (title, artists,
album, duration), so we can rank candidates the same way the JioSaavn source
does — query-word overlap up, unasked-for flavour markers down. The library
is sync (requests); all calls run in a thread. Any failure returns None so
the caller falls back to VideosSearch.

related() reads the same catalogue's "radio" for a video id — the songs YT
Music itself would queue after it. That endpoint is plain InnerTube JSON
(no player/watch page), so it is not affected by the datacenter IP's
bot-check on playback URLs.
"""

import asyncio
import html
import re

import requests

from bobby import logger
from bobby.core.jiosaavn import is_copy


_VIDEO_ID = re.compile(r"[0-9A-Za-z_-]{11}")


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2]


class _TimedSession(requests.Session):
    """Session with a hard per-request ceiling — wait_for() can cancel the
    coroutine but not the worker thread, so the requests call itself must
    die fast too or repeated outages would squat on the shared executor."""

    def request(self, *args, **kwargs):
        kwargs.setdefault("timeout", (4, 7))  # connect, read
        return super().request(*args, **kwargs)


def _search_sync(query: str):
    from ytmusicapi import YTMusic

    return YTMusic(requests_session=_TimedSession()).search(
        query, filter="songs", limit=8
    )


async def best_video(query: str) -> dict | None:
    """Best matching song as {video_id, title, artists, duration_sec, url,
    thumbnail}, or None when YT Music has nothing usable."""
    try:
        # bounded wait: a YT-Music network hang must fall through to
        # VideosSearch quickly instead of stalling the user's play request
        results = await asyncio.wait_for(
            asyncio.to_thread(_search_sync, query), timeout=12
        )
    except Exception as ex:
        logger.warning("ytmusic search failed: %s", ex)
        return None
    qwords = _words(query)
    best = None
    best_score = None
    for item in results or []:
        if item.get("resultType") != "song" or not item.get("videoId"):
            continue
        try:
            duration_sec = int(item.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            duration_sec = 0
        if not duration_sec:
            continue
        title = html.unescape(item.get("title") or "")
        artists = ", ".join(a.get("name", "") for a in item.get("artists") or [])
        album = (item.get("album") or {}).get("name") or ""

        score = 0.0
        if qwords:
            hay = set(_words(f"{title} {artists}"))
            score += 10 * sum(1 for w in qwords if w in hay) / len(qwords)
        if album:
            score += 2  # album presence ≈ official release, not an upload
        if item.get("category") == "Top result":
            score += 3
        if is_copy(f"{title} {album}", query):
            score -= 15  # same rule as JioSaavn: unasked flavours lose

        if best_score is None or score > best_score:
            best_score = score
            best = {
                "video_id": item["videoId"],
                "title": title,
                "artists": artists,
                "duration_sec": duration_sec,
                "url": f"https://www.youtube.com/watch?v={item['videoId']}",
                # keep the full URL — Google image sizing params live behind
                # '=', so splitting would strip them and degrade the thumb
                "thumbnail": (item.get("thumbnails") or [{}])[-1].get("url") or "",
            }
    return best


def _length_sec(text: str) -> int:
    """'3:45' / '1:02:03' → seconds; 0 when the field is missing/odd."""
    try:
        parts = [int(p) for p in (text or "").strip().split(":")]
    except ValueError:
        return 0
    if not parts or len(parts) > 3:
        return 0
    return sum(v * 60**i for i, v in enumerate(reversed(parts)))


def _related_sync(video_id: str, want: int):
    from ytmusicapi import YTMusic

    # radio=True is the "up next" list YT Music builds for this exact song;
    # the seed itself comes back as the first entry
    return YTMusic(requests_session=_TimedSession()).get_watch_playlist(
        videoId=video_id, radio=True, limit=want + 5
    )


async def related(video_id: str, limit: int = 15, max_sec: int = 0) -> list[dict]:
    """Songs YouTube Music queues after this one, as
    [{id, title, artists, duration_sec}] — seed excluded, deduplicated,
    nothing longer than max_sec (0 = no cap). Empty list on any failure:
    suggestions are decoration, they must never delay or break a play."""
    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(_related_sync, video_id, limit), timeout=12
        )
    except Exception as ex:
        logger.warning("ytmusic related failed for %s: %s", video_id, ex)
        return []
    out: list[dict] = []
    seen = {video_id}
    for item in (data or {}).get("tracks") or []:
        vid = item.get("videoId")
        # strict id shape: it travels inside callback data and becomes a URL
        if not vid or vid in seen or not _VIDEO_ID.fullmatch(vid):
            continue
        secs = _length_sec(item.get("length"))
        if not secs or (max_sec and secs > max_sec):
            continue
        title = html.unescape(item.get("title") or "").strip()
        if not title:
            continue
        seen.add(vid)
        out.append(
            {
                "id": vid,
                "title": title,
                "artists": ", ".join(
                    a["name"] for a in item.get("artists") or [] if a.get("name")
                ),
                "duration_sec": secs,
            }
        )
        if len(out) >= limit:
            break
    return out
