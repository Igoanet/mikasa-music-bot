# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.

"""Audius — free, legal, no-auth music source sitting between JioSaavn and
YouTube in the search chain. Public API: /tracks/search returns metadata,
/tracks/{id}/stream 302-redirects to a content node serving the audio. No
keys, no bot-checks, no cookies — every track found here is one fewer
YouTube request from a flagged IP (the structural fix, 2026-09-06)."""

import html
import math
import re

import aiohttp

from bobby import logger
from bobby.core.jiosaavn import is_copy
from bobby.helpers import Track

API = "https://api.audius.co/v1"
APP_NAME = "MikasaMusicBot"
_PREFIX = "audius:"


class Audius:
    @staticmethod
    def is_audius(track_id: str | None) -> bool:
        return bool(track_id) and track_id.startswith(_PREFIX)

    @staticmethod
    def stream_candidates(track_id: str) -> list[str]:
        """Direct stream endpoint (302 -> content node). ffmpeg and yt-dlp
        both follow the redirect; callers validate with a ranged GET first."""
        return [f"{API}/tracks/{track_id[len(_PREFIX):]}/stream?app_name={APP_NAME}"]

    async def search(self, query: str, m_id: int) -> Track | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{API}/tracks/search",
                    params={"query": query, "app_name": APP_NAME, "limit": 8},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json(content_type=None)
        except Exception as ex:
            logger.warning("audius search failed: %s", ex)
            return None

        # same ranking philosophy as the JioSaavn path: query-word overlap
        # pulls up, unasked-for flavour markers push down, popularity breaks
        # ties — never trust the API's first hit
        qwords = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
        best = None
        best_score = None
        for item in data.get("data") or []:
            if item.get("is_delete") or item.get("is_unlisted"):
                continue
            try:
                duration_sec = int(item.get("duration") or 0)
            except (TypeError, ValueError):
                continue
            if not 30 <= duration_sec <= 900:
                continue
            title = html.unescape(item.get("title") or "")
            artists = html.unescape((item.get("user") or {}).get("name") or "")

            score = 0.0
            if qwords:
                hay = set(re.findall(r"[a-z0-9]+", f"{title} {artists}".lower()))
                score += 10 * sum(1 for w in qwords if w in hay) / len(qwords)
            if is_copy(f"{title} {artists}", query):
                score -= 15
            try:
                favs = int(item.get("favorite_count") or 0) + int(
                    item.get("repost_count") or 0
                )
            except (TypeError, ValueError):
                favs = 0
            if favs > 0:
                score += min(math.log10(favs), 4)

            if best_score is None or score > best_score:
                best_score = score
                best = (item, title, artists, duration_sec)
        if best is None:
            return None

        item, title, artists, duration_sec = best
        art = item.get("artwork") or {}
        image = art.get("1000x1000") or art.get("480x480") or ""
        # permalink is just a slug ('/artist/track') — build the full URL
        slug = item.get("permalink") or ""
        link = f"https://audius.co{slug}" if slug.startswith("/") else (slug or "https://audius.co/")
        minutes, seconds = divmod(duration_sec, 60)
        return Track(
            id=_PREFIX + str(item.get("id")),
            channel_name=artists,
            duration=f"{minutes}:{seconds:02d}",
            duration_sec=duration_sec,
            message_id=m_id,
            title=title[:25],
            thumbnail=image or None,
            url=link,
            view_count="",
            video=False,
        )


audius = Audius()
