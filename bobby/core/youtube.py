# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic


import asyncio
import json
import os
import random
import re
import sys
import time

import aiohttp
import yt_dlp
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from py_yt import Playlist, VideosSearch

from bobby import config, logger
from bobby.core.audius import audius
from bobby.core.jiosaavn import clean_query, is_copy, saavn
from bobby.core import yuki
from bobby.core.spool import spool
from bobby.helpers import Track, utils


_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_LYRIC_HINT = re.compile(
    r"\b(?:lyrics?|lyrical|find\s+(?:this\s+)?song|"
    r"which\s+song|what\s+song|identify\s+(?:this\s+)?song|"
    r"song\s+(?:name|title))\b",
    re.IGNORECASE,
)
_NON_SONG_RESULT = re.compile(
    r"\b(?:reaction|interview|podcast|sound\s+effect|tutorial|"
    r"news\s+report|press\s+conference)\b",
    re.IGNORECASE,
)


def _normalise_query(query: str) -> str:
    """Turn pasted one-/multi-line text into one bounded search phrase.

    Telegram clients commonly send a lyric fragment with line breaks and
    indentation.  YouTube treats those characters inconsistently (and some
    clients turn tabs into literal spacing), while collapsing whitespace is
    lossless for search.  Do not truncate or invent words: the provider must
    still be the source of the resulting video id.
    """
    return re.sub(r"\s+", " ", str(query or "")).strip()


def _looks_like_lyrics(query: str) -> bool:
    """Recognise only useful, deterministic signs of a lyric lookup.

    A short title such as ``"The Sound of Silence"`` must keep the ordinary
    one-shot YouTube path.  Newlines, an explicit lyric/song-identification
    marker, or a sentence-sized fragment are enough to opt into the
    conservative retry below.  This is intentionally not a language model and
    never attempts to infer a song title locally.
    """
    raw = str(query or "")
    if "\n" in raw or "\r" in raw or _LYRIC_HINT.search(raw):
        return True
    words = re.findall(r"[^\W_]+", raw, flags=re.UNICODE)
    if len(words) < 6:
        return False
    # Sentence-like fragments usually contain a function word; this avoids
    # treating a long artist/title list as a lyric request.
    function_words = {
        "a", "an", "and", "are", "at", "but", "for", "from", "her", "his",
        "i", "in", "is", "it", "me", "my", "of", "on", "our", "that", "the",
        "to", "u", "we", "with", "you", "your",
    }
    return any(word.lower() in function_words for word in words)


def _obviously_non_song(title: str) -> bool:
    """Whether a lyric query's first hit is clearly not playable music."""
    return bool(_NON_SONG_RESULT.search(title or ""))


# How many results one search asks for.  The first one is still the default
# answer; the rest only exist so an obviously wrong-language or wrong-version
# upload at the top can lose to the real song underneath it.
_SEARCH_LIMIT = 8

# Devanagari through Malayalam — every major Indian script in one range.
_INDIC_SCRIPT = re.compile(r"[\u0900-\u0D7F]")
# Romanised words that only appear in Indian-language titles.  Deliberately
# excludes tokens that are ordinary English words too ("main", "se", "pal"),
# so an English request is never mistaken for a Hindi one.
_INDIC_WORDS = {
    "aankh", "aankhen", "aashiqui", "alvida", "banjaara", "barsaat", "bewafa",
    "bhajan", "bhakti", "bhangra", "bhojpuri", "bollywood", "chand", "chahat",
    "chahun", "dard", "deewana", "dhadkan", "dholna", "dil", "dilbar",
    "dildara", "diwana", "dua", "gaana", "gaane", "gana", "garba", "ghazal",
    "haryanvi", "hindi", "humsafar", "ishq", "jaan", "jaana", "jaanam",
    "janam", "jiya", "judaai", "kannada", "khuda", "khushi", "kyun", "maahi",
    "malayalam", "marathi", "mast", "maula", "mera", "mere", "meri",
    "mohabbat", "mujhe", "naat", "nazar", "piya", "punjabi", "pyaar", "pyar",
    "qawwali", "raat", "rula", "saajan", "saathi", "sajna", "sanam", "sapna",
    "sathiya", "saiyaan", "shayari", "soniye", "sufi", "tamil", "telugu",
    "tera", "tere", "teri", "tujhe", "tumhe", "yaad", "yaar", "zaalima",
    "zindagi",
}
# Versions nobody asked for.  Penalised only when the request itself does not
# contain the word — "/play dilbar remix" must still get the remix.
_VARIANT_MARKERS = (
    "cover", "karaoke", "instrumental", "remix", "mashup", "dj ", "slowed",
    "reverb", "nightcore", "lofi", "lo-fi", "8d", "bass boosted", "ringtone",
    "status", "reaction", "sped up", "speed up", "jukebox", "medley",
    "nonstop", "non stop", "tutorial", "chords", "guitar lesson", "full album",
)
# A pre-roll: the label/company promo that plays BEFORE the song.  Indian
# uploads carry these far more often, so the penalty is weighted there
# (owner 2026-10-07: "no pre-advertisement ... no promo in the song").
_PROMO_MARKERS = (
    "promo", "advertisement", "ad film", "ad song", "presented by",
    "powered by", "sponsored", "only on", "streaming now", "in cinemas",
    "coming soon", "pre release", "prerelease", "exclusive", "jingle",
)
# Fan-made / re-edited versions: never the original release.
_FANEDIT_MARKERS = (
    "fan made", "fanmade", "fan-made", "concept video", "made by",
    "whatsapp status", "status video", "instagram reels", "reels",
    "tiktok", "edit audio", "audio edit", "custom edit",
)
# Not the song itself: spoken intros, teasers, making-of, interviews.
_INTRO_MARKERS = (
    "teaser", "trailer", "behind the scenes", "behind the scene",
    "making of", "making video", "interview", "promo", "preview",
    "snippet", "intro", "unboxing", "podcast",
)
# Channels that upload the real release.
_OFFICIAL_MARKERS = (
    "- topic", "vevo", "official", "records", "music", "t-series", "saregama",
    "zee ", "sony ", "tips ", "speed ", "eros",
)
# Words that say "play me something" rather than naming the song.  They are
# ignored when measuring how much of the request a title covers, so
# "/play song dil se" is judged on "dil se", not on the word "song".
_REQUEST_WORDS = {
    "play", "please", "pls", "plz", "song", "songs", "track", "music",
    "gana", "gaana", "gane", "gaane", "geet", "bajao", "baja", "sunao",
    "suna", "chalao", "lagao", "de", "do", "mp3", "audio", "hd", "4k",
}
# Words that decorate almost every upload title.  They are not evidence that
# a result matches the request, so they never count as "extra" words either.
_TITLE_FILLER = {
    "official", "video", "audio", "song", "songs", "full", "lyrics",
    "lyrical", "music", "movie", "film", "hd", "4k", "new", "latest",
    "original", "soundtrack", "ost", "album", "feat", "ft", "featuring",
    "with", "and", "the", "a", "an", "of", "by", "from", "in", "on", "x",
    "out", "now", "hq", "mp3", "track", "presents", "records", "release",
    "tseries", "t", "series", "2020", "2021", "2022", "2023", "2024",
    "2025", "2026",
}


def _words(text: str) -> list[str]:
    """Lowercase word list — punctuation, brackets and symbols dropped."""
    return [w.lower() for w in re.findall(r"[^\W_]+", str(text or ""), re.UNICODE)]


def _phrase(text: str) -> str:
    """The same words as one spaced string, for phrase containment."""
    return " ".join(_words(text))


def _request_tokens(query: str) -> list[tuple[str, float]]:
    """The request as (word, weight) pairs, in order and without duplicates.

    Filler like "play"/"song"/"gaana" is not thrown away — a title can be
    "Song 2" — it simply counts for less than the words that name the song,
    so a result cannot look like a match merely by containing "song".
    Numbers are kept whole: "song 2" and "2" are part of real titles."""
    ordered: list[tuple[str, float]] = []
    seen = set()
    for word in _words(query):
        if word in seen:
            continue
        seen.add(word)
        # nothing is dropped for being short: "i", "U" and "2" are real
        # song titles, and dropping them loses the song that was named
        ordered.append((word, 0.3 if word in _REQUEST_WORDS else 1.0))
    if ordered and all(weight < 1.0 for _, weight in ordered):
        # the whole request was filler ("play the song") — judge on it anyway
        ordered = [(word, 1.0) for word, _ in ordered]
    return ordered


def _token_hit(token: str, title_words: set[str], channel_words: set[str]) -> float:
    """How well one requested word is present in a result.

    Full credit for the same word in the title or the channel, half credit
    for a clear prefix relation (``pyar``/``pyaar``, ``zindagi``/
    ``zindagii``).  Plain substring matching is deliberately avoided — it
    made "dil" match "dilbar" and picked the wrong song."""
    if token in title_words:
        return 1.0
    if token in channel_words:
        return 0.8
    if len(token) >= 4:
        for word in title_words:
            if len(word) >= 4 and (word.startswith(token) or token.startswith(word)):
                return 0.5
        # channel names are often written as one word ("ImagineDragons"),
        # so a named artist has to be found inside them as well
        for word in channel_words:
            if token in word:
                return 0.6
    return 0.0


# A catalogue mirror is an optimisation, never a requirement: if the lookup
# is slow the original source is used, so a deadline only ever makes playback
# start sooner (2026-09-30).
_MIRROR_DEADLINE = float(os.getenv("MIRROR_DEADLINE", "6"))


async def _with_deadline(factory, /, *args, what: str = "lookup", **kwargs):
    """Await a lookup with a deadline; None when it runs out.

    ``factory`` and the positional args are positional-only, so a stray
    keyword can never be mistaken for an argument.
    """
    try:
        return await asyncio.wait_for(factory(*args, **kwargs),
                                      timeout=_MIRROR_DEADLINE)
    except asyncio.TimeoutError:
        logger.info("%s exceeded %.0fs — using the original source",
                    what, _MIRROR_DEADLINE)
        return None
    except Exception as exc:
        logger.info("%s failed: %s", what, type(exc).__name__)
        return None


def _is_indian_query(query: str) -> bool:
    """Whether the words the user typed are an Indian-language request."""
    text = str(query or "")
    if _INDIC_SCRIPT.search(text):
        return True
    words = {word.lower() for word in re.findall(r"[^\W_]+", text, re.UNICODE)}
    return bool(words & _INDIC_WORDS)


# The audience is Indian, so the Indian market is the default rather than a
# special case.  A Latin-transliterated title ("bekhayali", "assi sajna")
# previously fell through to the US market and returned covers and look-alike
# uploads.  Override with YT_MARKET (e.g. YT_MARKET=US) if that ever changes.
# Local-first audio (owner 2026-10-11): download through the API and play the
# LOCAL file, so the voice chat never depends on a live network feed.  This is
# the permanent fix for VC lag -- a streamed source can starve the ffmpeg pipe
# mid-song (pipe fill hit 0 B while several groups streamed at once).  Set
# VC_LOCAL_FIRST=false in the env to fall back to stream-first.
LOCAL_FIRST = (os.getenv("VC_LOCAL_FIRST", "true") or "true").strip().lower() \
    not in ("0", "false", "off", "no")
LOCAL_FIRST_TIMEOUT = float(os.getenv("VC_LOCAL_FIRST_TIMEOUT", "12"))

# What kind of upload the user wants.  'lofi' prefers fan-made /
# slowed / reverb versions (the query gains a ' lofi' suffix);
# 'official' keeps the label master.  Switchable without a code edit
# (2026-10-01).
# Quality first (owner 2026-10-07): the catalogue is queried for the real
# studio upload unless the USER's own text asks for lofi/slowed/reverb.
_TASTE = (os.getenv('MUSIC_TASTE', 'normal') or 'normal').strip().lower()
_TASTE_SUFFIX = ' lofi' if _TASTE == 'lofi' else ''

_DEFAULT_MARKET = (os.getenv("YT_MARKET_LANG", "hi"),
                   os.getenv("YT_MARKET_REGION", "IN"))
_WESTERN_MARKET = ("en", "US")


def _query_locale(query: str) -> tuple[str, str]:
    """YouTube search locale for this query.

    Indian by default — the same words rank completely differently per market,
    and an Indian song title asked from the US market returns covers, reactions
    and look-alike uploads instead of the release the user means.  A query that
    is clearly not Indian still gets the western market, so an English request
    is not dragged into Hindi results.
    """
    if _is_indian_query(query):
        return _DEFAULT_MARKET
    # no Indic script and no Indian music word: only fall back to the western
    # market when the query looks like plain English
    words = {w.lower() for w in re.findall(r"[^\W_]+", str(query or ""), re.UNICODE)}
    if words and words <= _COMMON_ENGLISH:
        return _WESTERN_MARKET
    return _DEFAULT_MARKET


def _result_score(
    data: dict,
    index: int,
    total: int,
    tokens: list[tuple[str, float]],
    query: str,
    indian: bool,
) -> dict:
    """Rank one search result against the words the user actually typed.

    The comparison is word based, in both directions: how much of the
    request the result carries (recall) and how much unrequested material
    it adds on top (precision).  A mashup, a reaction or a look-alike title
    contains the requested words too — what separates it from the real song
    is everything else in its title.

    Returns the score together with the evidence behind it, because the top
    hit may only be displaced for a named reason (see ``_best_result``)."""
    title = str(data.get("title") or "")
    lower = title.lower()
    channel = data.get("channel") or {}
    channel_name = str(
        channel.get("name") if isinstance(channel, dict) else ""
    ).lower()
    query_lower = query.lower()
    title_words = set(_words(title))
    channel_words = set(_words(channel_name))
    # YouTube's own order stays the baseline; everything below only moves a
    # result off the top when the words clearly disagree with it.
    score = 1.2 * (1.0 - (index / max(1, total)))

    words = [token for token, _ in tokens]
    coverage = 0.0
    if tokens:
        weight_sum = sum(weight for _, weight in tokens)
        hits = [
            (_token_hit(token, title_words, channel_words), weight)
            for token, weight in tokens
        ]
        coverage = sum(hit * weight for hit, weight in hits) / weight_sum
        score += 4.5 * coverage
        missing = sum(weight for hit, weight in hits if hit == 0.0)
        # A title written in another script cannot be word-matched against a
        # Latin query: the official release of "Assi Sajna" is titled in
        # Devanagari, so it scored ZERO coverage and a lyrics upload won.
        # When the scripts differ the comparison is unassessable, so the
        # missing-word penalty is skipped (2026-09-29).
        if _INDIC_SCRIPT.search(title) == _INDIC_SCRIPT.search(query):
            score -= 1.0 * missing / weight_sum

    # the request as a phrase, in order, inside the title: the strongest
    # signal that this really is the song that was asked for
    title_phrase = _phrase(title)
    named = " ".join(token for token, weight in tokens if weight >= 1.0)
    phrase_match = bool(
        (words and " ".join(words) in title_phrase)
        or (named and named in title_phrase)
    )
    if phrase_match:
        score += 1.5

    # The song itself, straight in (owner 2026-10-07): "official audio" and
    # Topic-channel uploads start on the music, while teasers / trailers /
    # making-of clips open with talking.  Small nudges only -- they move a
    # result off the top just when the title clearly says what it is.
    # "- Topic" and "official audio" uploads begin on the music itself with no
    # spoken/promo pre-roll: the strongest signal that this is the clean
    # original.  Worth more on an Indian request (owner 2026-10-07).
    if ("- topic" in channel_name
            or any(m in lower for m in
                   ("official audio", " audio", "audio ", "audio song",
                    "full audio", "official full song"))):
        score += 0.9 if indian else 0.6
    if any(m in lower for m in _INTRO_MARKERS):
        score -= 1.2

    # The ORIGINAL song, nothing wrapped around it (owner 2026-10-07).
    # A promo/pre-roll or a fan re-edit is never the track the user asked
    # for; the Indian case is weighted harder because those uploads lead
    # with a label/company ad far more often.
    if not any(m in query_lower for m in _PROMO_MARKERS):
        promo = sum(1 for m in _PROMO_MARKERS if m in lower)
        if promo:
            score -= min(1.0 * promo, 2.0) * (1.6 if indian else 1.0)
    if not any(m in query_lower for m in _FANEDIT_MARKERS):
        fanedit = sum(1 for m in _FANEDIT_MARKERS if m in lower)
        if fanedit:
            score -= min(1.2 * fanedit, 2.4)

    official = any(marker in channel_name for marker in _OFFICIAL_MARKERS)
    # "Full Song" / "Full Video" / "Official" in the TITLE is release titling,
    # not filler — the extras below are movie and cast credits, which real
    # releases carry (2026-09-30).
    release_titled = any(m in lower for m in _RELEASE_TITLE_MARKERS)
    official = official or release_titled
    # an official release is often announced in the TITLE, not the channel:
    # आधिकारिक संगीत वीडियो = "official music video"
    indic_official = any(marker in lower for marker in _INDIC_OFFICIAL_MARKERS)
    official = official or indic_official

    # unrequested words in the title (other artists, movie names, "vs",
    # mashup partners) — each one makes this a little less the song asked
    # for.  A label/official channel is judged more leniently: its titles
    # routinely carry movie, cast and composer credits.
    extras = sum(
        1
        for word in title_words
        if word not in words and word not in _TITLE_FILLER and len(word) > 2
    )
    score -= min(0.15 * extras, 1.2) * (0.5 if official else 1.0)
    if release_titled:
        score += 0.4

    penalty = 0.0
    for marker in _VARIANT_MARKERS:
        if marker.strip() in query_lower:
            continue            # this version is exactly what was asked for
        if marker in lower:
            penalty += 1.5
        elif marker in channel_name:
            # a cover/remix/karaoke channel, even when its title hides it
            penalty += 0.75
    # Lyrics/cover/karaoke re-uploads are the main thing that beats a real
    # release; counted separately from _VARIANT_MARKERS so the cap below is
    # reached quickly (2026-09-29).
    # A song request is never a TV episode, however well the title matches.
    if not any(m in query_lower for m in _EPISODE_MARKERS):
        penalty += 3.0 * sum(1 for m in _EPISODE_MARKERS if m in lower)
    # Lyrics/cover re-uploads are still discouraged, but a lyrics video of the
    # RIGHT song must not lose to unrelated filler, so the weight is lighter
    # than the episode penalty (2026-09-30).
    if not any(m in query_lower for m in _UNWANTED_MARKERS):
        penalty += 1.5 * sum(1 for m in _UNWANTED_MARKERS if m in lower)
    score -= min(penalty, 6.0)

    # a reaction/interview/tutorial is never what a play request means
    non_song = bool(
        _NON_SONG_RESULT.search(title) and not _NON_SONG_RESULT.search(query)
    )
    if non_song:
        score -= 2.5

    if official:
        score += 1.2 if indic_official else 0.6
    # the channel is the artist the user named (or the label releasing them)
    if tokens and channel_words & set(words):
        score += 0.5

    title_indian = bool(_INDIC_SCRIPT.search(title)) or bool(
        title_words & _INDIC_WORDS
    )
    wrong_language = False
    if indian and title_indian:
        score += 0.8
    elif not indian and _INDIC_SCRIPT.search(title):
        # A Latin query with an Indic title is the transliteration case, not a
        # language mismatch — "assi sajna" asked in Latin still means the
        # Devanagari-titled official release.  Only a genuine mismatch (an
        # Indic query meeting a non-Indic title) is penalised (2026-09-29).
        if _INDIC_SCRIPT.search(query):
            wrong_language = True
            score -= 0.8

    duration_value = data.get("duration")
    try:
        seconds = utils.to_seconds(str(duration_value)) if duration_value else 0
    except (TypeError, ValueError):
        seconds = 0
    if 45 <= seconds <= 900:
        score += 0.4
    elif seconds and seconds > 2400:
        score -= 1.0
    elif seconds and seconds < 30:
        score -= 0.6
    return {
        "score": score,
        "coverage": coverage,
        "phrase": phrase_match,
        "extras": extras,
        "wrong_kind": bool(non_song or penalty or wrong_language),
    }


# How far ahead of YouTube's own top hit a lower result must score before it
# is allowed to replace it.  Selection stays YouTube's unless the words say
# otherwise clearly.
_DISPLACE_MARGIN = 0.6


def _best_result(results: list, query: str) -> dict | None:
    """Pick the result that matches the request, defaulting to the top hit.

    The top hit wins by default.  A lower result replaces it only when it
    scores clearly higher AND there is a named reason for it: the top hit
    is the wrong kind of upload (unrequested remix/cover/reaction, wrong
    language), or the lower result carries more of the typed words.

    A shorter title is never a reason by itself, and neither is a channel
    name: "Song | Movie | Cast | Composer" is how real releases are titled,
    and "official"/"music"/"records" appear in plenty of fan channels.
    Both still count inside the score, they just cannot overturn YouTube's
    own order on their own."""
    # BobbyXMusic behaviour: YouTube's own top result is the track — the
    # same pick a user makes on youtube.com.  Re-ranking kept overriding the
    # correct first hit, so it is off unless SEARCH_RERANK=1 (2026-09-30).
    if os.getenv("SEARCH_RERANK", "0") != "1":
        _pool = [c for c in (results or []) if isinstance(c, dict)]
        return _pool[0] if _pool else None
    candidates = [data for data in (results or []) if isinstance(data, dict)]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    tokens = _request_tokens(query)
    indian = _is_indian_query(query)
    scored = [
        _result_score(data, index, len(candidates), tokens, query, indian)
        for index, data in enumerate(candidates)
    ]
    top = scored[0]
    best_index = 0
    for index in range(1, len(candidates)):
        current = scored[index]
        if current["score"] <= scored[best_index]["score"]:
            continue
        better_match = current["coverage"] > top["coverage"] + 1e-6 or (
            # word order alone proves nothing: the user types "song artist"
            # while the release is titled "Artist - Song".  A phrase match
            # only counts when the top hit is actually missing something.
            current["phrase"]
            and not top["phrase"]
            and top["coverage"] < 1.0 - 1e-6
        )
        if not (top["wrong_kind"] or better_match):
            continue
        if current["score"] - top["score"] < _DISPLACE_MARGIN:
            continue
        best_index = index
    if best_index:
        # worth seeing in the log: the only cases where selection differs
        # from plain YouTube order are the ones users complain about
        logger.info(
            "yt search: picked result #%d (%r) over the top hit (%r)",
            best_index + 1,
            str(candidates[best_index].get("title"))[:60],
            str(candidates[0].get("title"))[:60],
        )
    return candidates[best_index]


class DummyLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass

# NO audio processing: the owner wants the original track sound, untouched.
# (History: bass+loudnorm caused volume pumping; bass+alimiter still coloured
# the sound. Any -af filter chain also costs a full re-encode per song on a
# 2-vCPU box. Stream the download as-is.)


_search_stats = {"empty": 0}


class _SecondarySearch:
    """Second search provider, shaped like the primary one's next()."""

    def __init__(self, query, limit=8):
        self._results = None
        try:
            from youtube_search import YoutubeSearch
            self._results = YoutubeSearch(query, max_results=limit).to_dict()
        except Exception:
            self._results = None

    async def next(self):
        if not self._results:
            return {"result": []}
        rows, self._results = self._results, None
        out = []
        for r in rows:
            try:
                out.append({
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "duration": r.get("duration"),
                    "channel": {"name": r.get("channel") or r.get("uploader")},
                    "thumbnails": [{"url": u.get("url")} for u in
                                   (r.get("thumbnails") or [])],
                })
            except Exception:
                continue
        return {"result": out}


async def _scrape_search(query: str, limit: int = 8):
    """Last resort: read YouTube's results page directly (no player API)."""
    import re as _re
    import urllib.parse
    import urllib.request
    url = ("https://www.youtube.com/results?search_query="
           + urllib.parse.quote(query))

    def _fetch():
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/124.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", "replace")
    try:
        html = await asyncio.to_thread(_fetch)
    except Exception as ex:  # noqa: BLE001
        logger.warning("scrape search failed: %s", type(ex).__name__)
        return []
    out, seen = [], set()
    for m in _re.finditer(
            r'"videoId":"([A-Za-z0-9_-]{11})".{0,400}?"text":"([^"]{3,120})"',
            html):
        vid = m.group(1)
        if vid in seen:
            continue
        seen.add(vid)
        out.append({"id": vid, "title": m.group(2).replace("\u0026", "&"),
                    "channel": {}, "thumbnails": []})
        if len(out) >= limit:
            break
    return out


class YouTube:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.cookies = []
        self.checked = False
        self.cookie_dir = "bobby/cookies"
        self.warned = False
        # in-flight downloads keyed by "<id>:<mode>" — the queue prefetcher
        # (misc.py) and play_next can race to grab the same track; both must
        # await one shared task so a single yt-dlp writes downloads/<id>.*
        self._inflight: dict[str, asyncio.Task] = {}
        # cap concurrent yt-dlp runs — downloads and the video merge bake
        # are ffmpeg on CPU; on this shared host even 3 parallel jobs can
        # starve the LIVE voice-chat encoder and the user hears stutter.
        # 2 keeps prefetch moving while the VC always wins the CPU.
        self._dl_sem = asyncio.Semaphore(2)
        # Downloads / metadata extraction run on DEDICATED nice+10 threads:
        # on Linux nice is per-thread and fork() inherits it, so yt-dlp's
        # python work AND every ffmpeg child it spawns (video merge bake)
        # permanently lose CPU to the live voice-chat encoder. Playback
        # always wins; a download can never garble the VC again.
        def _deprioritize():
            try:
                os.nice(10)
            except OSError:
                pass
        self._dl_pool = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="dl", initializer=_deprioritize
        )
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
        # pull the video id straight out of any youtube link shape
        # (watch?v=, youtu.be/, shorts/, live/, embed/) — /play <link>
        # must never depend on a text search of the URL string.
        # Anchored to the scheme (or string start) + a hostname allowlist
        # so lookalike hosts (notyoutube.com) can't match; the trailing
        # lookahead demands an exact 11-char id (rejects /shorts/<id>junk
        # and v=<id>junk truncation); playlists/channels match nothing.
        self.id_regex = re.compile(
            r"(?:^|https?://)(?:www\.|m\.|music\.)?"
            r"(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|shorts/|live/|embed/|v/)"
            r"|youtu\.be/)"
            r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
        )

    async def _low_cpu(self, func, *args):
        """Run blocking yt-dlp work on the deprioritized pool (see above)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._dl_pool, func, *args)

    async def track_from_url(self, url: str, m_id: int, video: bool = False) -> Track | None:
        """Build a Track straight from a YouTube video link — no search
        involved, so /play <link> can't die on a search miss. The video id
        comes from the URL itself; title/author/thumbnail from YouTube's
        oEmbed endpoint (no player API — immune to our IP's bot-check);
        duration is best-effort via an id search so DURATION_LIMIT still
        applies to links. Returns None only for non-video links."""
        match = self.id_regex.search(url)
        if not match:
            return None
        vid = match.group(1)
        title, author, thumb = None, None, None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://www.youtube.com/oembed",
                    params={"url": self.base + vid, "format": "json"},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = data.get("title")
                        author = data.get("author_name")
                        thumb = data.get("thumbnail_url")
        except Exception as ex:
            logger.warning("oembed failed for %s: %s", vid, type(ex).__name__)
        duration, duration_sec = "—", 0
        try:
            _search = VideosSearch(vid, limit=1, with_live=False)
            res = await _search.next()
            hit = (res or {}).get("result") or []
            if hit and hit[0].get("id") == vid and hit[0].get("duration"):
                duration = hit[0]["duration"]
                duration_sec = utils.to_seconds(duration)
        except Exception:
            pass  # duration stays unknown — the limit check just skips it
        return Track(
            id=vid,
            channel_name=author,
            duration=duration,
            duration_sec=duration_sec,
            message_id=m_id,
            title=(title or "YouTube Video")[:25],
            thumbnail=(thumb or "").split("?")[0] or None,
            url=self.base + vid,
            view_count="",
            video=video,
        )

    def get_cookies(self):
        if not self.checked:
            for file in os.listdir(self.cookie_dir):
                if file.endswith(".txt"):
                    self.cookies.append(f"{self.cookie_dir}/{file}")
            self.checked = True
        if not self.cookies:
            if not self.warned:
                self.warned = True
                logger.warning("Cookies are missing; downloads might fail.")
            return None
        return random.choice(self.cookies)

    async def save_cookies(self, urls: list[str]) -> None:
        logger.info("Saving cookies from urls...")
        async with aiohttp.ClientSession() as session:
            for url in urls:
                name = url.split("/")[-1]
                link = "https://batbin.me/raw/" + name
                async with session.get(link) as resp:
                    resp.raise_for_status()
                    with open(f"{self.cookie_dir}/{name}.txt", "wb") as fw:
                        fw.write(await resp.read())
        logger.info(f"Cookies saved in {self.cookie_dir}.")

    def valid(self, url: str) -> bool:
        return bool(re.match(self.regex, url))

    def invalid(self, url: str) -> bool:
        return bool(re.match(self.iregex, url))

    async def search(self, query: str, m_id: int, video: bool = False) -> Track | None:
        # ---- TASTE_QUERY_V3 ------------------------------------------
        # Lofi taste is applied to the PARAMETER, so every downstream
        # path (query building, ranking, logging) inherits it.  A plain
        # query returns only label uploads (T-Series, Zee, Shemaroo);
        # 'bekhayali lofi' returns the fan-made slowed/reverb version.
        # MUSIC_TASTE=official turns this off (2026-10-01).
        if _TASTE_SUFFIX and not video:
            query = (query + _TASTE_SUFFIX).strip()
            logger.info('taste=lofi: querying %r', query[:56])
        # ---- end TASTE_QUERY_V3 --------------------------------------
        """Original BobbyXMusic selection, kept exactly as given: the query
        goes to YouTube search and the TOP result is the track — the same
        pick the user would make on youtube.com. No catalogue
        reinterpretation: the perfect result for a query isn't necessarily
        a song (it can be a video, a scene, a podcast), so no Saavn/
        YTMusic/Audius guessing in between. Lyric-shaped input gets only a
        conservative ``lyrics`` retry when the first hit is empty or
        obviously non-musical; it never ranks a catalogue or fabricates a
        title. One retry rides on top — a transient blip must not cost a play."""
        raw_query = str(query or "")
        normalized = _normalise_query(raw_query)
        if not normalized:
            return None

        # ``/song`` and synthetic callers reach this method directly, unlike
        # /play which has a URL branch in its handler.  A standard YouTube
        # link must still be resolved from its id; searching the raw URL is
        # both unnecessary and returns an empty result on YouTube.
        if self.id_regex.search(raw_query):
            track = await self.track_from_url(raw_query, m_id, video)
            if track:
                return track




        language, region = _query_locale(raw_query)  # ranker only

        async def _search_top(search_query: str):
            """Best match among the first results, across providers.

            Two findings drive this (2026-10-13):
              1. A provider can return an empty page while another answers,
                 so a plain results-page scrape runs alongside the primary.
              2. **YouTube itself returns ZERO videos for some bare titles.**
                 "Gandi Baat" served an 847 KB page with not one videoId,
                 while "gandi baat song" returned 35+ videos.  So an empty
                 sweep is retried with a short suffix before giving up --
                 that is the difference between a real song playing and a
                 "Nothing Found" message.
            """

            async def _primary(q):
                for attempt in range(2):
                    try:
                        res = await VideosSearch(
                            q, limit=_SEARCH_LIMIT, with_live=False).next()
                        rows = (res or {}).get("result") if isinstance(res, dict) else None
                        if rows:
                            return rows
                    except Exception as ex:  # noqa: BLE001
                        logger.warning("yt search failed for %d-char query "
                                       "(attempt %d): %s", len(q), attempt + 1,
                                       type(ex).__name__)
                    if attempt == 0:
                        await asyncio.sleep(1)
                return None

            async def _scrape(q):
                return await _scrape_search(q, _SEARCH_LIMIT) or None

            async def _sweep(q):
                """Every provider once; the best ranked match wins."""
                for name, fetch in (("primary", _primary), ("scrape", _scrape)):
                    rows = await fetch(q)
                    if not rows:
                        continue
                    best = _best_result(rows, q)
                    if best:
                        if name != "primary" or q != search_query:
                            logger.info(
                                "search: %s served query (broadened=%s)",
                                name, q != search_query)
                        return best
                    logger.warning(
                        "search: %s returned %d rows but none ranked",
                        name, len(rows))
                return None

            hit = await _sweep(search_query)
            if hit:
                return hit
            # YouTube suppressed this exact phrase (bare profanity-looking
            # titles): broaden once, THEN report failure.
            words = search_query.split()
            if 0 < len(words) <= 5:
                for suffix in (" song", " audio"):
                    logger.warning(
                        "search: no results for %d-char query; retrying "
                        "broadened (+%s)", len(search_query), suffix.strip())
                    hit = await _sweep(search_query + suffix)
                    if hit:
                        return hit
            _search_stats["empty"] += 1
            logger.warning("search: ALL providers empty for %d-char query "
                           "(streak %d)", len(search_query),
                           _search_stats["empty"])
            return None

        def _track_from_result(data: dict) -> Track | None:
            if not isinstance(data, dict):
                return None
            # A lyric fragment is user text, never a YouTube id.  py_yt
            # normally guarantees this shape, but validating the provider
            # boundary prevents malformed/error payloads from reaching
            # playback as if they were a real video.
            video_id = data.get("id")
            if not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id):
                logger.warning("yt search returned an invalid video id")
                return None
            channel = data.get("channel") or {}
            thumbnails = data.get("thumbnails") or []
            thumbnail = (
                thumbnails[-1].get("url")
                if isinstance(thumbnails[-1], dict)
                else None
            ) if thumbnails else None
            duration_value = data.get("duration")
            duration = duration_value or "—"
            try:
                duration_sec = (
                    utils.to_seconds(str(duration_value))
                    if duration_value
                    else 0
                )
            except (TypeError, ValueError):
                duration_sec = 0
            title = str(data.get("title") or "YouTube Video")
            # Keep the result bound to the id returned by YouTube.  A broken
            # scraper payload may contain a stale/mismatched link; never let
            # that cause the queue to play a different video.
            result_url = data.get("link")
            link_id = (
                self.id_regex.search(result_url)
                if isinstance(result_url, str)
                else None
            )
            url = (
                result_url
                if isinstance(result_url, str)
                and link_id
                and link_id.group(1) == video_id
                else self.base + video_id
            )
            return Track(
                id=video_id,
                channel_name=(
                    channel.get("name") if isinstance(channel, dict) else None
                ),
                duration=duration,
                duration_sec=duration_sec,
                message_id=m_id,
                title=title[:25],
                thumbnail=(thumbnail or "").split("?")[0] or None,
                url=url,
                view_count=(data.get("viewCount") or {}).get("short")
                if isinstance(data.get("viewCount") or {}, dict)
                else None,
                video=video,
            )

        first_data = await _search_top(normalized)
        first_track = _track_from_result(first_data)
        lyric_query = _looks_like_lyrics(raw_query)
        first_is_non_song = bool(
            lyric_query
            and isinstance(first_data, dict)
            and _obviously_non_song(first_data.get("title", ""))
        )
        if first_track and not first_is_non_song:
            return first_track

        # YouTube usually identifies a song from the fragment directly.  If
        # it returns nothing (or an obvious reaction/interview/podcast for a
        # lyric-shaped request), ask the same provider once with an explicit
        # lyrics hint.  This remains top-hit selection, not catalogue-first
        # ranking, and a missing/ambiguous provider response stays None.
        if lyric_query and not re.search(r"\blyrics?\b", normalized, re.I):
            fallback_data = await _search_top(f"{normalized} lyrics")
            fallback_track = _track_from_result(fallback_data)
            if fallback_track and not _obviously_non_song(
                fallback_data.get("title", "")
            ):
                return fallback_track

        # A recognised lyric request must not silently play a reaction,
        # interview, or other obvious non-song when the provider cannot find
        # a music result.  This is the explicit ambiguous/no-result outcome.
        if first_is_non_song:
            return None

        # Preserve the original YouTube-top-hit behavior when the special
        # retry did not produce a usable result.
        return first_track

    async def search_multi(
        self, query: str, exclude_id: str = None, limit: int = 3
    ) -> list[Track]:
        """Alternate uploads of a song — used when the top search result is
        blocked by YouTube's per-video bot-check (LOGIN_REQUIRED), which is
        common for re-uploaded remixes. Skips the blocked id and entries
        without a duration (live/upcoming)."""
        try:
            _search = VideosSearch(query, limit=limit + 3, with_live=False)
            results = await _search.next()
        except Exception:
            return []
        tracks = []
        for data in (results or {}).get("result", []):
            vid = data.get("id")
            if not vid or vid == exclude_id or not data.get("duration"):
                continue
            tracks.append(
                Track(
                    id=vid,
                    channel_name=data.get("channel", {}).get("name"),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title", "")[:25],
                    thumbnail=data.get("thumbnails", [{}])[-1]
                    .get("url", "")
                    .split("?")[0],
                    url=data.get("link"),
                    view_count=data.get("viewCount", {}).get("short"),
                )
            )
        # originals first: partition the FULL fetched set so a clean upload
        # later in the results always beats a copy at the top — copies are
        # only returned when no clean candidate exists at all
        clean = [t for t in tracks if not is_copy(t.title, query)]
        return (clean or tracks)[:limit]

    async def download_with_fallback(
        self, track: Track, video: bool = False, progress_msg=None, lang=None,
        local_only: bool = False,
    ) -> str | None:
        """Download a track; if YouTube blocks that exact upload (per-video
        bot-check or region lock), automatically try alternate uploads of the
        same song found via its title. On a successful fallback the track's
        identity is switched to the working upload so the queue, the played
        cache and the now-playing message all stay consistent. local_only=True
        (live audio playback) accepts ONLY filesystem results — alternates are
        downloaded too, never returned as stream URLs — so a VC never ends up
        jittering on a network feed when the caller demanded local-first."""
        path = await self.download(
            track.id, video=video, progress_msg=progress_msg, lang=lang
        )
        if path or not track.title:
            return path
        cross_source = saavn.is_saavn(track.id) or audius.is_audius(track.id)
        # YouTube is ~100% bot-checked from this host (every player client +
        # the POT provider verified 2026-09-06) — but the SAME song on
        # JioSaavn/Audius downloads fine from their CDNs. Mirror it there
        # BEFORE burning time on alternate YouTube uploads (also blocked).
        # Audio only: videos have no catalogue equivalent.
        if not video and not cross_source:
            mirror_path = await _with_deadline(self._catalogue_mirror, track, progress_msg, lang, what='catalogue mirror')
            if mirror_path:
                return mirror_path
        retry_text = (
            lang.get(
                "play_retry_alt",
                "⚠️ <b>Upload Blocked</b>\n\nYouTube locked that version — "
                "trying another upload of the same song…",
            )
            if lang
            else None
        )
        # catalogue sources (JioSaavn/Audius) keep their identity: a YouTube
        # alternate is the LAST resort, matched by artist+title with a close
        # duration — never a blind same-title substitution that could play a
        # different recording (review 2026-09-06)
        alt_query = (
            f"{track.title} {track.channel_name}".strip()
            if cross_source and track.channel_name
            else track.title
        )
        for alt in await self.search_multi(alt_query, exclude_id=track.id):
            if alt.duration_sec > config.DURATION_LIMIT:
                continue
            if (
                cross_source
                and track.duration_sec
                and alt.duration_sec
                and abs(alt.duration_sec - track.duration_sec) > 20
            ):
                continue
            if progress_msg is not None and retry_text:
                try:
                    await progress_msg.edit_text(retry_text)
                except Exception:
                    pass
            # API tier per alternate too — the primary already failed it,
            # but a different upload is often NOT bot-checked on their
            # server (observed: lofi upload failed there, others pass).
            # Hard-capped: 2 quick polls + 12s overall, so a slow API can
            # never hold the local-download recovery hostage (review).
            # Skipped under local_only — a URL result would break the
            # caller's jitter-free guarantee (review 2026-09-06).
            path = None
            if not local_only:
                try:
                    path = await asyncio.wait_for(
                        self._api_direct_url(alt, video, max_polls=2), timeout=12
                    )
                except Exception:
                    path = None
            if not path:
                path = await self.download(
                    alt.id, video=video, progress_msg=progress_msg, lang=lang
                )
            if path:
                # adopt the working upload's identity
                track.id = alt.id
                track.title = alt.title
                track.channel_name = alt.channel_name
                track.duration = alt.duration
                track.duration_sec = alt.duration_sec
                track.url = alt.url
                track.thumbnail = alt.thumbnail
                track.view_count = alt.view_count
                return path
        return None

    async def _find_mirror(self, track: Track) -> Track | None:
        """First JioSaavn/Audius track matching this YouTube track.
        Wrong-recording guard: unknown mirror duration is rejected when the
        source duration IS known; ±20s when both known; both unknown =
        documented availability tradeoff; DURATION_LIMIT applies to the
        mirror too.

        Candidate order is strictly non-regressive: the legacy raw
        "title channel" JioSaavn hit and the Audius hit are judged FIRST
        (exactly the old behaviour), then a cleaned-title ladder recovers
        the misses the raw query caused — the raw title carries pipes,
        actor names and the LABEL as channel ("Maahi - Full Video |
        Kangana Ranaut, ... | Sony Music India"), which poisons a catalogue
        search. Ladder = pipe/bracket segment, its dash-prefix, whole
        title; each yields MULTIPLE ranked candidates because the top hit
        is often a different recording of the same title (duration guard
        rejects it and the runner-up is the right song). All searches run
        concurrently; the walk order decides, not the search order."""
        m_id = track.message_id or 0
        base = re.split(r"[|(]", track.title or "", maxsplit=1)[0]
        queries: list[str] = []
        for q in (
            clean_query(base),
            clean_query(base.split(" - ")[0]),
            clean_query(track.title or ""),
        ):
            if q and q not in queries:
                queries.append(q)
        legacy = f"{track.title} {track.channel_name or ''}".strip()

        labels = [legacy, legacy] + queries
        coros = [
            saavn.search(legacy, m_id),
            audius.search(legacy, m_id),
        ] + [saavn.search_many(q, m_id) for q in queries]
        results = await asyncio.gather(*coros, return_exceptions=True)

        candidates: list[Track] = []
        for label, res in zip(labels, results):
            if isinstance(res, asyncio.CancelledError):
                raise res
            if isinstance(res, Exception):
                logger.warning(
                    "mirror search failed for %r: %s", label, type(res).__name__
                )
                continue
            if isinstance(res, list):
                candidates += res
            elif res:
                candidates.append(res)

        seen = set()
        for mirror in candidates:
            if mirror.id in seen:
                continue
            seen.add(mirror.id)
            if track.duration_sec and not mirror.duration_sec:
                continue
            if (
                track.duration_sec
                and mirror.duration_sec
                and abs(mirror.duration_sec - track.duration_sec) > 20
            ):
                continue
            if mirror.duration_sec and mirror.duration_sec > config.DURATION_LIMIT:
                continue
            # remember the candidate on the track: when a mirror STREAM
            # fails and the download fallback runs next, it reuses this
            # instead of repeating the same catalogue searches (review)
            track._mirror = mirror
            return mirror
        # misses were invisible before — a silent miss read exactly like
        # "download tier -> FAILED" with no clue the catalogue was tried
        logger.info(
            "mirror miss for %r (%s) — no catalogue candidate passed",
            track.title, track.id,
        )
        return None

    @staticmethod
    def _adopt(track: Track, mirror: Track) -> None:
        """Switch the track's identity to the working mirror upload (same
        contract as the YouTube-alternate path) so the queue, cache probes
        and the now-playing card all stay consistent."""
        track.id = mirror.id
        track.title = mirror.title
        track.channel_name = mirror.channel_name
        track.duration = mirror.duration
        track.duration_sec = mirror.duration_sec
        track.url = mirror.url
        track.thumbnail = mirror.thumbnail
        track.view_count = mirror.view_count

    async def _catalogue_mirror(
        self, track: Track, progress_msg=None, lang=None
    ) -> str | None:
        """Download the mirror from the catalogue CDN (reachable from this
        host — YouTube is bot-checked here, catalogue CDNs are not). A
        mirror failure never blocks the remaining fallback tiers. Reuses a
        mirror candidate already found by the stream attempt."""
        mirror = getattr(track, "_mirror", None) or await _with_deadline(self._find_mirror, track, what='catalogue mirror')
        if not mirror:
            return None
        try:
            path = await self.download(
                mirror.id, video=False, progress_msg=progress_msg, lang=lang
            )
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            logger.warning(
                "mirror download failed for %r: %s",
                track.title, type(ex).__name__,
            )
            return None
        if path:
            logger.info("mirrored %r via catalogue: %s", track.title, mirror.id)
            self._adopt(track, mirror)
            return path
        return None

    async def _yuki_local(self, track: Track) -> str | None:
        """Fetch the track through the API and play the LOCAL file.

        Bounded by LOCAL_FIRST_TIMEOUT: a slow download returns None so the
        caller falls straight through to the streaming tiers instead of
        holding the queue.  Repeats hit the on-disk cache instantly.
        """
        if not LOCAL_FIRST:
            return None
        vid = getattr(track, "id", "") or ""
        try:
            path = await asyncio.wait_for(
                yuki.download(vid), timeout=LOCAL_FIRST_TIMEOUT)
        except asyncio.TimeoutError:
            logger.info("local-first: download timed out for %s; streaming", vid)
            return None
        except Exception as ex:  # noqa: BLE001
            logger.info("local-first: %s: %s", type(ex).__name__, vid)
            return None
        return path

    async def _yuki_stream(self, track: Track) -> str | None:
        """Yuki Music API (owner 2026-10-04): a direct audio URL for the
        track's YouTube id.  Returns None while no valid key is set."""
        return await yuki.stream_url(getattr(track, "id", "") or "")

    async def _catalogue_mirror_stream(self, track: Track) -> str | None:
        """Same mirror as _catalogue_mirror but returns a validated CDN
        STREAM url — no download, no storage, playback starts like a live
        stream. 320kbps Saavn ladder preferred inside stream_url."""
        mirror = await _with_deadline(self._find_mirror, track, what='catalogue mirror')
        if not mirror:
            return None
        url = await self._try(self.stream_url, mirror)
        if url:
            self._adopt(track, mirror)
            return url
        return None

    @staticmethod
    async def _cdn_ok(url: str) -> bool:
        """Pre-validate a direct media URL with a ranged GET."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={
                        "Range": "bytes=0-0",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
                    },
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    return resp.status in (200, 206)
        except Exception:
            return False

    async def _first_working(self, urls) -> str | None:
        for url in urls or []:
            if await self._cdn_ok(url):
                return url
        return None

    async def stream_url(self, track: Track) -> str | None:
        """Direct JioSaavn CDN stream URL — the "API mode": ffmpeg reads
        the song straight from JioSaavn's servers, no download step, so
        playback starts in about a second. Prefers the explicit 320kbps CDN
        ladder (guaranteed source bitrate — the page extractor can serve
        lower rungs); anything off (dead link, expiry, extractor change)
        returns None so the caller falls back to the download path."""
        try:
            # Audius: direct stream endpoint, no resolution step needed
            if audius.is_audius(track.id):
                return await self._first_working(audius.stream_candidates(track.id))

            page = await saavn.resolve_url(track.id)
            if not page:
                return None

            # 320 -> 160 -> 96 direct ladder first: no yt-dlp extraction
            # needed and the bitrate is explicit
            direct = await self._first_working(saavn.direct_for(track.id))
            if direct:
                return direct

            def _extract():
                with yt_dlp.YoutubeDL({
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "logger": DummyLogger(),
                    "nocheckcertificate": True,
                    "socket_timeout": 10,
                    "format": "bestaudio[protocol^=http]/best[protocol^=http]",
                    # highest bitrate first; Opus wins ties because the voice
                    # stream is Opus too, so it is not re-encoded twice
                    "format_sort": ["abr", "acodec:opus"],
                }) as ydl:
                    return ydl.extract_info(page, download=False)

            info = await self._low_cpu(_extract)
            url = info.get("url") if info else None
            if not url or not await self._cdn_ok(url):
                return None
            return url
        except Exception as ex:
            logger.warning("stream_url failed for %s: %s", track.id, ex)
            return None

    async def _yt_direct_url(self, track: Track, video: bool) -> str | None:
        """Direct googlevideo stream URL for YouTube tracks — playback
        starts in ~2s instead of waiting for a full download (the download
        wait was the main "bot feels laggy" complaint, worst of all for
        /vplay's big video files). Only PROGRESSIVE formats qualify — a
        streamed file can't merge separate video+audio legs — and every
        candidate URL is pre-validated with a ranged GET. Anything off
        (bot-check, throttle, no progressive format) returns None so the
        caller falls back to the armoured download pipeline (stall
        watchdog + client rotation + alternate uploads)."""
        if video:
            # progressive only: one file carrying both audio+video (HLS
            # renditions are video-only — useless without a merge step).
            # <=720p on EVERY rung — an unrestricted fallback could pick a
            # 4K stream and bury the little VC host in decode load
            fmt = (
                "best[height<=720][ext=mp4][vcodec!=none][acodec!=none][protocol^=http]"
                "/best[height<=720][vcodec!=none][acodec!=none][ext=mp4][protocol^=http]"
                "/best[height<=720][vcodec!=none][acodec!=none][protocol^=http]"
            )
        else:
            # http first (single seekable file); HLS audio last — fine to
            # STREAM (ffmpeg reads m3u8 natively; the no-HLS rule only
            # guards downloads, whose byte caps m3u8 bypasses)
            fmt = (
                "bestaudio[ext=webm][acodec=opus][protocol^=http]"
                "/bestaudio[protocol^=http]/bestaudio[protocol*=m3u8]"
                "/best[ext=mp4][protocol^=http]"
            )
        # android/web give plain-http formats; tv + web_embedded dodge
        # PO-token demands (yt-dlp PO-token guide, rev. 2026-07) but often
        # serve HLS-only — OK for audio streaming now. POT applies via the
        # bgutil plugin on :4416. No manual visitor_data/headers — yt-dlp
        # maintainers call those harmful (issue #16773).
        cookie = self.get_cookies()
        attempts = [
            (["android", "web"], cookie),
            (["tv"], cookie),
            (["web_embedded"], None),
        ]

        def _extract(clients, cookie):
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "logger": DummyLogger(),
                "nocheckcertificate": True,
                "socket_timeout": 10,
                "skip_download": True,
                "format": fmt,
                "format_sort": ["abr", "acodec:opus"],
                "remote_components": ["ejs:github"],
                "js_runtimes": {"deno": {}},
                "extractor_args": {"youtube": {"player_client": clients}},
            }
            if cookie:
                opts["cookiefile"] = cookie
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(self.base + track.id, download=False)

        for clients, cookie in attempts:
            try:
                info = await self._low_cpu(_extract, clients, cookie)
            except Exception as ex:
                logger.warning(
                    "direct-url extract failed for %s (%s): %s",
                    track.id, clients, ex,
                )
                continue
            if not info or info.get("requested_formats"):
                continue  # merge pair — can't stream two legs as one input
            url = info.get("url")
            if url and await self._cdn_ok(url):
                return url
        return None

    @staticmethod
    async def _live_feed_ready(url: str, protocol: str = "") -> bool:
        """Confirm that a freshly extracted live feed is still readable.

        YouTube can return successful live metadata while the signed HLS
        manifest is between refreshes (or has already expired).  Passing that
        URL straight to pytgcalls makes its ffprobe receive an empty response
        and the whole play attempt disappears.  A bounded ffprobe keeps live
        playback direct -- no download and no spool -- while rejecting a dead
        candidate before it reaches the voice layer.  This intentionally uses
        ffprobe rather than an aiohttp GET: YouTube's signed manifests can
        reject aiohttp's TLS/client fingerprint while accepting the ffmpeg
        client that will actually play the source.
        """
        if not isinstance(url, str) or not url:
            return False
        process = None

        async def _kill_and_reap() -> None:
            """Stop ffprobe and reap it without extending the resolver."""
            if process is None:
                return
            if process.returncode is None:
                try:
                    process.kill()
                except (ProcessLookupError, OSError):
                    pass
            try:
                # A broken pipe/child must never hold up the next client
                # indefinitely after a timeout or resolver exception.
                await asyncio.wait_for(process.communicate(), timeout=1)
            except Exception:
                pass

        try:
            process = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "error",
                # A live HLS manifest has no finite duration.  Limit both
                # format probing and packet reads so ffprobe does not spend
                # the whole resolver budget waiting for the next playlist
                # refresh before it can report its audio stream.
                "-analyzeduration",
                "4M",
                "-probesize",
                "4M",
                "-rw_timeout",
                "10000000",
                "-read_intervals",
                "%+3",
                "-show_entries",
                "stream=codec_type,codec_name",
                "-of",
                "json",
                url,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=15
            )
            if process.returncode != 0:
                return False
            data = json.loads(stdout.decode("utf-8"))
            return any(
                stream.get("codec_type") == "audio"
                for stream in data.get("streams", [])
            )
        except asyncio.CancelledError:
            # Cancellation must not orphan ffprobe.  The original
            # cancellation remains visible to callers (not a false feed
            # result), while cleanup is deliberately bounded.
            await _kill_and_reap()
            raise
        except Exception:
            await _kill_and_reap()
            return False

    async def _api_direct_url(
        self, track: Track, video: bool, max_polls: int = 10
    ) -> str | None:
        """External downloader-API tier (pattern from the AnnieX/Aviax
        repos): a clean-IP server does the YouTube fetch and hands back a
        ready CDN link — dodges our datacenter IP flag entirely. Dormant
        until NEXGEN_API_KEY is set (free key: console.nexgenbots.xyz).
        max_polls caps the server-side-download wait — alternate-upload
        attempts pass a small value so a slow API can't stall recovery."""
        api_key = os.getenv("NEXGEN_API_KEY")
        if not api_key:
            return None
        base = (
            os.getenv("NEXGEN_VIDEO_API_URL", "https://api.video.nexgenbots.xyz")
            if video
            else os.getenv("NEXGEN_API_URL", "https://pvtz.nexgenbots.xyz")
        )
        kind = "video" if video else "song"
        poll_url = f"{base}/{kind}/{track.id}?api={api_key}"
        try:
            async with aiohttp.ClientSession() as session:
                for attempt in range(max_polls):
                    if attempt:
                        await asyncio.sleep(1.0)
                    async with session.get(
                        poll_url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status != 200:
                            return None
                        data = await resp.json()
                    status = str(data.get("status", "")).lower()
                    if status == "downloading":
                        continue
                    if status != "done":
                        return None
                    link = data.get("link")
                    if link and await self._cdn_ok(link):
                        return link
                    return None
        except Exception as ex:
            # NEVER str(ex) here: aiohttp errors can embed the request URL,
            # whose query string carries the API key
            logger.warning(
                "api direct-url failed for %s (%s)", track.id, type(ex).__name__
            )
        return None

    async def _ytdlp_stream(self, track: Track) -> str | None:
        """YouTube audio streamed by yt-dlp's OWN downloader into the local
        RAM spool. Why not a plain googlevideo URL: since 2026-09 every
        client except yt-dlp itself (curl, ffmpeg, aiohttp, urllib — any
        header set) gets HTTP 403 from googlevideo for our extracted URLs,
        so the old "yt-direct" tier silently never served a song. yt-dlp
        -o - streams the bytes progressively; playback starts on the first
        chunk (no file, no waiting), and the whole song is local seconds
        later. Needs the user's cookies (bot-checked datacenter IP)."""
        cookie = self.get_cookies()
        if not cookie:
            return None
        argv = [
            "nice", "-n", "10", sys.executable, "-m", "yt_dlp",
            "--quiet", "--no-warnings", "--no-progress", "--no-playlist",
            "--no-part", "--no-cache-dir", "--no-mtime",
            "--socket-timeout", "8", "--retries", "1",
            "--remote-components", "ejs:github",
            "--js-runtimes", "deno",
            "--cookies", cookie,
            "-f", "bestaudio[ext=webm][acodec=opus][protocol^=http]"
                  "/bestaudio[protocol^=http]/best[protocol^=http]/bestaudio/best",
            "--format-sort", "abr,acodec:opus",
            "-o", "-", "--", f"https://www.youtube.com/watch?v={track.id}",
        ]
        local = await spool.from_command(argv, "audio/webm")
        # extraction (JS challenge via deno) + first bytes: ~5-15 s here
        return local if await spool.prime(local, timeout=45) else None

    @staticmethod
    async def _spooled(url: str | None, timeout: float = 20) -> str | None:
        """Route a validated remote audio URL through the local spool and
        confirm it actually produces bytes — a dead upstream then costs one
        tier, not the whole play (and never a mid-song break)."""
        if not url:
            return None
        local = await spool.wrap(url)
        return local if await spool.prime(local, timeout=timeout) else None

    async def _try(self, resolver, *args) -> str | None:
        """Run a stream-URL resolver with full exception containment — a
        resolver bug (e.g. get_cookies raising before its own try/except)
        must never skip the caller's next tier, above all the download
        fallback. Logs only the exception type: URLs can carry keys."""
        try:
            return await resolver(*args)
        except Exception as ex:
            logger.warning(
                "resolver %s failed: %s",
                getattr(resolver, "__name__", str(resolver)),
                type(ex).__name__,
            )
            return None

    async def play_source(
        self, track: Track, video: bool = False, progress_msg=None, lang=None
    ) -> str | None:
        """Where playback reads the track from. AUDIO = stream-always,
        download-free (owner call 2026-09-06 — "sab waise hi play ho jaye,
        download na karna pade"): (1) a finished local file still plays at
        once; (2) the song STREAMS off the JioSaavn/Audius CDN — YouTube
        picks are mirrored there by title (320kbps ladder, not bot-checked
        from this host); (3) NexGen relay stream; (4) yt-dlp streams the
        YouTube audio itself with the user's cookies (a bare googlevideo
        URL is 403 for every other client now — see _ytdlp_stream);
        (5) DOWNLOAD is the absolute last resort. EVERY remote audio tier
        is served through the local RAM spool (bobby/core/spool.py): the
        bytes land in memory at link speed and ffmpeg reads 127.0.0.1, so
        a CDN/relay hiccup can no longer become a mid-song break — that
        was the real cause of the stutters. VIDEO keeps stream-first
        (<=720p caps). Every tier logs which one served — mid-play break
        reports must be debuggable from log.txt alone."""
        # Signed YouTube HLS URLs are intentionally short-lived. A live
        # track can sit behind another queue item, so resolve its canonical
        # YouTube URL when it reaches the voice call instead of reusing a
        # feed extracted when /play was sent.
        if track.duration == "🔴 LIVE" or track.view_count == "LIVE":
            live = await self._try(
                self.get_live,
                track.url or self.base + track.id,
                track.message_id,
                video,
            )
            if not live or not live.file_path:
                return None
            track.file_path = live.file_path
            track.duration = live.duration
            track.duration_sec = 0
            track.title = live.title
            track.thumbnail = live.thumbnail
            track.view_count = "LIVE"
            return live.file_path

        if not video:
            cached = Path(f"downloads/{track.id}.webm")
            if cached.exists():
                logger.info("play_source[%s]: cached file", track.id)
                return str(cached)
            # LOCAL FIRST (owner 2026-10-11): a file on disk cannot be
            # starved by the network, which is what made the VC stutter
            # mid-song while several groups streamed at once.
            _local = await self._try(self._yuki_local, track)
            if _local:
                logger.info('play_source[' + str(track.id) + ']: local file (jitter-free)')
                return _local
            # streaming stays as the fallback when the download is slow/fails
            _u = await self._try(self._yuki_stream, track)
            _u = await self._try(self._spooled, _u)
            if _u:
                logger.info('play_source[' + str(track.id) + ']: yuki API stream (primary)')
                return _u
            if saavn.is_saavn(track.id) or audius.is_audius(track.id):
                url = await self._try(self.stream_url, track)
            else:
                url = await self._catalogue_mirror_stream(track)
            url = await self._try(self._spooled, url)
            if url:
                logger.info("play_source[%s]: catalogue CDN stream (spooled)", track.id)
                return url
            url = await self._try(self._api_direct_url, track, False, 3)
            url = await self._try(self._spooled, url)
            if url:
                logger.info("play_source[%s]: relay stream (spooled)", track.id)
                return url
            url = await self._try(self._ytdlp_stream, track)
            if url:
                logger.info("play_source[%s]: yt-dlp stream (spooled)", track.id)
                return url
            # ---- YUKI MUSIC API --------------------------------------------------
            # A direct audio URL for the video id - no YouTube bot-wall, no
            # download wait.  Inert (returns None) until a valid key is set.
            _u = await self._try(self._yuki_stream, track)
            _u = await self._try(self._spooled, _u)
            if _u:
                logger.info('play_source[' + str(track.id) + ']: yuki API stream')
                return _u
            # ---- end YUKI MUSIC API ----------------------------------------------
            # ---- CATALOGUE_STREAM_FALLBACK ----------------------------------------
            # Everything above failed to STREAM this YouTube track (bot-wall,
            # 403, no progressive format).  Before downloading it, try the same
            # song in the music catalogue and STREAM that: a different master,
            # but it plays at once instead of waiting for a download (2026-10-01).
            m_id = getattr(track, "message_id", 0) or 0
            try:
                _alt = await saavn.search(
                    getattr(track, 'title', '') or track.id, m_id
                )
            except Exception as _ex:
                _alt = None
                logger.info('catalogue fallback failed: ' + type(_ex).__name__)
            if _alt and str(getattr(_alt, 'id', '')).startswith('saavn:'):
                _u = await self._try(self.stream_url, _alt)
                _u = await self._try(self._spooled, _u)
                if _u:
                    logger.info(
                        'play_source[' + str(track.id) + ']: catalogue fallback stream via ' + str(_alt.id)
                    )
                    return _u
            logger.info('play_source[' + str(track.id) + ']: no stream anywhere - downloading')
            # ---- end CATALOGUE_STREAM_FALLBACK --------------------------------------

            path = await self.download_with_fallback(
                track, video=False, progress_msg=progress_msg, lang=lang,
                local_only=True,
            )
            logger.info(
                "play_source[%s]: download tier -> %s", track.id,
                "file" if path else "FAILED",
            )
            return path
        if not saavn.is_saavn(track.id) and not audius.is_audius(track.id):
            url = await self._try(self._api_direct_url, track, True)
            if not url:
                url = await self._try(self._yt_direct_url, track, True)
            if url:
                return url
        return await self.download_with_fallback(
            track, video=True, progress_msg=progress_msg, lang=lang
        )

    async def get_live(self, url: str, m_id: int, video: bool = False) -> Track | None:
        """If the URL is a YouTube live stream, return a Track whose file_path
        is the direct HLS feed (streamed by ffmpeg — never downloaded).
        Returns None for normal videos so the caller falls back to search.
        Player clients rotate like _yt_direct_url — our datacenter IP is
        bot-checked, and a live link must not die on the first client. A live
        metadata hit with no readable feed returns an explicit LIVE track
        without a file path; the command handler can then report the source
        as unavailable instead of silently treating it as a VOD."""

        def _probe(clients, cookie):
            from yt_dlp import YoutubeDL

            opts = {
                "quiet": True,
                "no_warnings": True,
                "logger": DummyLogger(),
                "noplaylist": True,
                # Audio playback does not need a 1080p HLS rendition. Keeping
                # the live feed at <=480p reduces manifest/segment startup
                # work while retaining an audio-bearing YouTube rendition.
                "format": (
                    "best[height<=480][protocol*=m3u8]/"
                    "best[protocol*=m3u8]/best"
                    if not video
                    else "best[height<=720]/best"
                ),
                "nocheckcertificate": True,
                "socket_timeout": 10,
                "remote_components": ["ejs:github"],
                "js_runtimes": {"deno": {}},
                "extractor_args": {"youtube": {"player_client": clients}},
            }
            if cookie:
                opts["cookiefile"] = cookie
            with YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)

        cookie = self.get_cookies()
        info = None
        live_info = None
        resolved_clients = None
        for clients, ck in (
            (["android", "web"], cookie),
            (["tv"], cookie),
            (["web_embedded"], None),
        ):
            try:
                info = await self._low_cpu(_probe, clients, ck)
            except Exception as ex:
                logger.warning(
                    "live probe failed for %s (%s): %s",
                    self.id_regex.search(url).group(1)
                    if self.id_regex.search(url)
                    else "unknown",
                    clients,
                    type(ex).__name__,
                )
                continue
            if not info or not (
                info.get("is_live") or info.get("live_status") == "is_live"
            ):
                # A later player client may observe an ended/ordinary VOD
                # after an earlier client already identified this URL as
                # live.  Do not lose that identity and let callers fall
                # through to the VOD resolver; preserve the LIVE sentinel
                # until all clients have been attempted.
                if live_info is None:
                    return None
                continue
            live_info = info
            candidate_url = info.get("url")
            if await self._live_feed_ready(
                candidate_url, info.get("protocol", "")
            ):
                info = live_info
                resolved_clients = clients
                break
            logger.warning(
                "live feed unavailable for %s (%s)",
                info.get("id") or "unknown",
                clients,
            )
            info = None

        if not info:
            # Preserve the distinction between a normal/ended VOD (which
            # returns None above) and a live metadata hit whose feed is
            # genuinely unavailable.
            info = live_info
        if not info:
            return None

        video_id = info.get("id")
        if not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id):
            logger.warning("live probe returned an invalid video id")
            return None
        feed = info.get("url") if resolved_clients else None
        logger.info(
            "live stream resolved: %s (%s)",
            video_id,
            resolved_clients or "unavailable",
        )

        return Track(
            id=video_id,
            channel_name=info.get("uploader"),
            duration="🔴 LIVE",
            duration_sec=0,
            file_path=feed,
            message_id=m_id,
            title=(info.get("title") or "Live Stream")[:25],
            thumbnail=(info.get("thumbnail") or "").split("?")[0] or None,
            url=self.base + video_id,
            view_count="LIVE",
            video=video,
        )

    async def playlist(self, limit: int, user: str, url: str, video: bool) -> list[Track | None]:
        tracks = []
        try:
            plist = await Playlist.get(url)
            for data in plist["videos"][:limit]:
                track = Track(
                    id=data.get("id"),
                    channel_name=data.get("channel", {}).get("name", ""),
                    duration=data.get("duration"),
                    duration_sec=utils.to_seconds(data.get("duration")),
                    title=data.get("title")[:25],
                    thumbnail=data.get("thumbnails")[-1].get("url").split("?")[0],
                    url=data.get("link").split("&list=")[0],
                    user=user,
                    view_count="",
                    video=video,
                )
                tracks.append(track)
        except Exception:
            pass
        return tracks

    async def download(
        self, video_id: str, video: bool = False, progress_msg=None, lang=None
    ) -> str | None:
        """De-duplicated entry point: share one in-flight task per video and
        media mode. Callers that race (prefetch vs playback) all await the
        same download; the first caller's progress message gets the edits."""
        key = f"{video_id}:{'v' if video else 'a'}"
        task = self._inflight.get(key)
        if task is None or task.done():
            async def _run() -> str | None:
                async with self._dl_sem:
                    return await self._download_locked(
                        video_id,
                        video=video,
                        progress_msg=progress_msg,
                        lang=lang,
                    )

            task = asyncio.create_task(_run())
            self._inflight[key] = task
            task.add_done_callback(lambda t, k=key: self._inflight.pop(k, None))
        return await task

    async def _download_locked(
        self, video_id: str, video: bool = False, progress_msg=None, lang=None
    ) -> str | None:
        is_saavn = saavn.is_saavn(video_id)
        is_audius = audius.is_audius(video_id)
        if is_saavn:
            page = await saavn.resolve_url(video_id)
            if not page:
                return None
            # explicit 320/160/96 CDN ladder before the song page — the
            # fallback download path gets the same guaranteed bitrate as
            # streaming (resolve_url filled the ladder cache as a side effect)
            url_candidates = saavn.direct_for(video_id) + [page]
        elif is_audius:
            # direct stream endpoint (302 -> content node), no extraction
            url_candidates = audius.stream_candidates(video_id)
        else:
            url_candidates = [self.base + video_id]
        # Yuki Music API download tier (owner 2026-10-06): fetch the file
        # through the API so the last-resort download never touches the
        # bot-walled YouTube origin.  Falls through on any failure.
        if not is_saavn and not is_audius and not video:
            yuki_path = await yuki.download(video_id)
            if yuki_path:
                logger.info("download[%s]: yuki API file", video_id)
                return yuki_path
        ext = "mp4" if video else "webm"
        filename = f"downloads/{video_id}.{ext}"

        def _resolve_downloaded() -> str | None:
            """The saved container follows the chosen format (progressive mp4
            via the android client), not our requested ext — find whatever
            actually landed and normalize it to the expected filename."""
            if Path(filename).exists():
                return filename
            for cand in sorted(Path("downloads").glob(f"{video_id}.*")):
                if ".fx." in cand.name or cand.suffix in (".part", ".ytdl"):
                    continue
                os.replace(cand, filename)
                return filename
            return None

        if _resolve_downloaded():
            return filename

        loop = asyncio.get_running_loop()
        _last_edit = [0.0]
        _done = [False]
        _edit_tasks: set[asyncio.Task] = set()
        _start = [time.time()]
        _win_t = [time.time()]
        _win_b = [0]
        _win_f = [None]  # filename the window belongs to

        class _StallError(Exception):
            """Raised when a download's throughput collapses (throttled
            trickle). Dead sockets never reach the hook — those are caught
            by socket_timeout instead. Either way the caller rotates to the
            next player client."""
            pass

        def _progress_hook(d: dict) -> None:
            """yt-dlp runs hooks on the download thread; bounce the status
            edit back to the event loop, throttled so Telegram doesn't
            rate-limit the message."""
            if d.get("status") != "downloading":
                return
            now = time.time()
            done_now = d.get("downloaded_bytes") or 0
            fname = d.get("filename")
            if fname != _win_f[0]:
                # new leg of the download (video downloads the video+audio
                # formats sequentially) — yt-dlp's byte counter resets per
                # file, so the window must too or the rate goes negative
                _win_f[0] = fname
                _win_t[0] = now
                _win_b[0] = done_now
            # sliding-window throughput: the hook fires on every received
            # chunk, so a throttled trickle is caught within ~15s no matter
            # the file size (long mixes stay safe — only RATE matters, never
            # an absolute time budget). A dead socket fires nothing at all —
            # socket_timeout covers that case.
            elif now - _win_t[0] >= 15:
                rate = (done_now - _win_b[0]) / (now - _win_t[0])
                if rate < 10 * 1024:
                    raise _StallError(
                        f"throttled at {rate / 1024:.0f} KB/s — rotating client"
                    )
                _win_t[0] = now
                _win_b[0] = done_now
            if progress_msg is None or not lang or _done[0]:
                return
            # stay silent for quick downloads — the progress text used to
            # flash on every song; only show it when a download is
            # genuinely slow (>5s in)
            if now - _start[0] < 5:
                return
            if now - _last_edit[0] < 4:
                return
            _last_edit[0] = now
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0
            if not total or not done:
                return
            eta = utils.format_eta(int((total - done) / speed)) if speed else "--:--"
            fmt = lang.get(
                "dl_progress",
                "<b>Downloading:</b> {0} / {1} [{2:.1f}%]\n<b>Speed:</b> {3}/s | <b>ETA:</b> {4}",
            )
            text = fmt.format(
                utils.format_size(done),
                utils.format_size(total),
                done * 100 / total,
                utils.format_size(speed),
                eta,
            )

            async def _edit() -> None:
                if _done[0]:
                    return
                try:
                    await progress_msg.edit_text(text)
                except Exception:
                    pass

            def _schedule() -> None:
                if _done[0]:
                    return
                task = asyncio.ensure_future(_edit())
                _edit_tasks.add(task)
                task.add_done_callback(_edit_tasks.discard)

            loop.call_soon_threadsafe(_schedule)

        cookie = self.get_cookies()
        base_opts = {
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "geo_bypass": True,
            "no_warnings": True,
            "overwrites": False,
            "logger": DummyLogger(),
            "nocheckcertificate": True,
            "progress_hooks": [_progress_hook],
            "cookiefile": cookie,
            # fail fast, rotate fast: a dead socket raises within 12s, and
            # there are deliberately NO same-client retries — the rotation
            # loop below moves straight to the next client instead
            "socket_timeout": 12,
            "retries": 0,
            "fragment_retries": 0,
            # never resume a stalled attempt's .part — each rotated client
            # starts clean (its format/container may differ anyway)
            "continuedl": False,
            "remote_components": ["ejs:github"],
            "js_runtimes": {"deno": {}},
            # throttle-busters (from HasiiMusicBot): 4 fragment legs at a
            # time + 512KB ranged chunks keep throughput up when YouTube
            # rate-limits a single connection
            "concurrent_fragment_downloads": 4,
            "http_chunk_size": 524288,
        }
        if video:
            fmt = "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio)/best[height<=?720][ext=mp4][protocol^=http]/best[ext=mp4][protocol^=http]"
        else:
            # strict webm/opus alone fails when YouTube serves SABR-only
            # formats; fall back to any HTTP audio, then progressive mp4
            # (the android client only offers itag 18 — py-tgcalls streams
            # its audio track fine as-is). never HLS/m3u8 — external
            # downloader bypasses size hooks.
            fmt = "bestaudio[ext=webm][acodec=opus][protocol^=http]/bestaudio[protocol^=http]/best[ext=mp4][protocol^=http]"

        # Rotate player clients across attempts. Anonymous android is the
        # fast unthrottled path for normal videos — NOTE: yt-dlp SKIPS the
        # android client whenever a cookiefile is set (it can't use
        # cookies), so cookied attempts really run web+POT first. mweb /
        # web_embedded rescue attempts that stall or get throttled
        # (VPS-tested: all cookied paths sustain ~1-1.4 MB/s).
        if is_saavn or is_audius:
            # plain CDN fetch — no youtube client games, one clean attempt
            client_rotation = [None]
        else:
            # tv + web_embedded currently dodge PO-token demands entirely
            # (yt-dlp PO-token guide, rev. 2026-07) — extra rescue rungs
            client_rotation = [["android", "web"], ["mweb"], ["web_embedded"], ["tv"]]

        def _download():
            for cand_url in url_candidates:
                for clients in client_rotation:
                    # fresh watchdog window + UI-silence window per attempt
                    _start[0] = time.time()
                    _win_t[0] = time.time()
                    _win_b[0] = 0
                    _win_f[0] = None
                    opts = {**base_opts, "format": fmt}
                    if clients:
                        opts["extractor_args"] = {"youtube": {"player_client": clients}}
                    if is_saavn or is_audius:
                        # land the file under OUR track id — yt-dlp's %(id)s is
                        # the platform's own id, not the prefixed one we glob for
                        opts["outtmpl"] = f"downloads/{video_id}.%(ext)s"
                    if video:
                        opts["merge_output_format"] = "mp4"
                    try:
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            ydl.download([cand_url])
                    except (yt_dlp.utils.DownloadError, yt_dlp.utils.ExtractorError) as ex:
                        logger.warning(
                            "Download failed for %s (clients=%s): %s",
                            cand_url, clients, ex,
                        )
                        # bot-check is per-video/per-IP, not per-client: rotating
                        # through more clients only sends extra flagged traffic
                        # (escalates the block) and delays the failure message.
                        if "Sign in to confirm" in str(ex):
                            return None
                        continue
                    except Exception as ex:
                        # includes _StallError raised by the progress watchdog
                        logger.warning(
                            "Download aborted for %s (clients=%s): %s: %s",
                            cand_url, clients, type(ex).__name__, ex,
                        )
                        continue
                    path = _resolve_downloaded()
                    if path:
                        return path
            return None

        try:
            return await self._low_cpu(_download)
        finally:
            # no progress edit may land after the caller's terminal edit
            _done[0] = True
            if _edit_tasks:
                await asyncio.gather(*_edit_tasks, return_exceptions=True)


# Official-release wording that appears in Indic-script titles.
_INDIC_OFFICIAL_MARKERS = (
    "\u0906\u0927\u093f\u0915\u093e\u0930\u093f\u0915",   # आधिकारिक (official)
    "\u0911\u092b\u093f\u0936\u093f\u092f\u0932",           # ऑफिशियल
    "\u0938\u0902\u0917\u0940\u0924 \u0935\u0940\u0921\u093f\u092f\u094b",  # संगीत वीडियो
)

# Re-uploads that must not win a play request.
# TV serial episodes, promos and other long-form uploads are never what a
# play request means, however well their title matches (2026-09-30).
_EPISODE_MARKERS = (
    "ep.", "ep ", "| ep", "episode", "full episode", "web series", "serial",
    "promo", "trailer", "teaser", "highlights", "full movie", "short film",
    "today's episode", "episode 1", "episode 2",
)

_UNWANTED_MARKERS = (
    "lyric", "lyrical", "cover", "karaoke", "reaction", "remix",
    "slowed", "sped up", "8d audio", "instrumental", "ringtone",
    "\u0932\u093f\u0930\u093f\u0915\u094d\u0938",  # लिरिक्स
)


# Wording that marks a genuine release inside the title itself.
_RELEASE_TITLE_MARKERS = (
    "full song", "full video", "full audio", "official video",
    "official music video", "official song", "audio song", "video song",
)


# Words that indicate a plainly English request, so it keeps the US market
# instead of being dragged into Hindi results (2026-09-30).
_COMMON_ENGLISH = frozenset({
    "the", "a", "an", "song", "songs", "music", "official", "video", "audio",
    "lyrics", "lyric", "remix", "cover", "live", "full", "new", "best",
    "top", "hits", "playlist", "album", "mix", "version", "feat", "ft",
})
