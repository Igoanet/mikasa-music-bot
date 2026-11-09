# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Intelligent candidate scoring and deduplication to ensure the highest-quality
authentic studio/master audio track is picked across JioSaavn and YouTube."""

import html
import math
import re

COPY_TOKENS = (
    "status", "whatsapp", "shorts", "short", "reels",
    "slowed", "reverb", "sped up", "speed up", "nightcore",
    "8d", "8d audio", "bass boosted", "bassboost",
    "ringtone", "teaser", "trailer", "promo", "preview",
    "cover", "unplugged", "karaoke", "instrumental",
    "vocals only", "acapella", "remake", "mashup",
)

AUDIO_BOOST_TOKENS = (
    "full audio", "audio song", "official audio", "original audio",
    "original track", "studio version", "original motion picture",
    "pure audio", "hq audio", "320kbps",
)

OFFICIAL_CHANNELS = (
    "t-series", "zeemusiccompany", "zee music company", "sony music",
    "yrf", "tips official", "speed records", "saregama", "aditya music",
    "lahari music", "geet mp3", "white hill music", "eros now", "vevo",
    "topic", "tseries", "sonymusicindia", "warner", "universal",
    "desimusicfactory", "dmfc", "svf", "madhura audio", "anand audio",
)

COMPILATION_TOKENS = (
    "romantic sad songs", "best of", "hits of", "collection of",
    "compilation", "various artists", "top 50", "top 10", "vol.", "vol 1",
    "vol 2", "love songs 20", "mashup", "jukebox",
)


def normalize_phonetics(s: str) -> str:
    """Normalize common Hindi/Hinglish phonetic variations so typos and spelling
    variants (e.g. 'Ek Mulaqat' vs 'Ik Mulaqaat') match accurately."""
    if not s:
        return ""
    s = html.unescape(s).lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    replacements = [
        (r"\bee?k\b", "ek"),
        (r"\biik?\b", "ek"),
        (r"mulaaq?a?a?t", "mulaqat"),
        (r"pya+r", "pyar"),
        (r"jaa+n", "jan"),
        (r"zindagi|jindagi", "zindagi"),
        (r"dil+", "dil"),
        (r"mer[ei]ya+", "mereya"),
        (r"chan+a", "channa"),
        (r"raat[a-z]*", "raat"),
    ]
    for pattern, rep in replacements:
        s = re.sub(pattern, rep, s)
    return re.sub(r"\s+", " ", s).strip()


def clean_title(title: str) -> str:
    """Strip bracketed fluff, delimiters and noise from video/song titles."""
    if not title:
        return ""
    t = html.unescape(title)
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)
    t = re.sub(r"[|–—\-:]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_official_channel(channel: str) -> bool:
    if not channel:
        return False
    chan = channel.lower()
    return any(oc in chan for oc in OFFICIAL_CHANNELS)


def is_compilation_album(album: str) -> bool:
    if not album:
        return False
    alb = album.lower()
    return any(ct in alb for ct in COMPILATION_TOKENS)


def score_audio_candidate(
    title: str,
    artist: str = "",
    album: str = "",
    channel: str = "",
    plays_or_views: int = 0,
    duration_sec: int = 0,
    is_320k: bool = False,
    query: str = "",
    is_video_mode: bool = False,
) -> float:
    """Compute an audio quality score for a candidate song against the query.
    Higher score indicates higher relevance, official source, and best audio."""
    q_norm = normalize_phonetics(query)
    q_tokens = [w for w in q_norm.split() if len(w) >= 2]

    t_clean = clean_title(title)
    t_norm = normalize_phonetics(t_clean)
    t_tokens = [w for w in t_norm.split() if len(w) >= 2]

    score = 0.0

    # 1. Title matching
    if q_norm == t_norm:
        score += 65.0  # Exact title match
    elif q_norm and q_norm in t_norm:
        score += 45.0  # Query is substring in title
        extra_words = max(0, len(t_tokens) - len(q_tokens))
        score -= min(extra_words * 2.5, 25.0)  # Penalize extraneous words
    else:
        # Word overlap
        hay = set(t_tokens)
        if artist:
            hay.update(normalize_phonetics(artist).split())
        if album:
            hay.update(normalize_phonetics(album).split())
        if q_tokens:
            matched = sum(1 for w in q_tokens if w in hay)
            score += 40.0 * (matched / len(q_tokens))

    # 2. Audio quality boosts
    full_text = f"{title} {album} {channel}".lower()
    if is_320k and not is_video_mode:
        score += 30.0  # Pristine 320kbps studio master

    for ab in AUDIO_BOOST_TOKENS:
        if ab in full_text:
            score += 20.0
            break

    # 3. Fluff / non-standard audio penalty (unless user explicitly searched for it)
    q_lower = query.lower()
    for tok in COPY_TOKENS:
        if tok in q_lower:
            continue
        if re.search(r"\b" + re.escape(tok) + r"\b", full_text):
            score -= 45.0
            break

    # 4. Compilation album penalty vs original album/movie bonus
    if is_compilation_album(album):
        score -= 15.0
    elif album:
        score += 5.0

    # 5. Channel Authority
    if is_official_channel(channel):
        score += 20.0

    # 6. Popularity / Play/View Count (logarithmic scale)
    try:
        p = int(plays_or_views or 0)
        if p > 0:
            score += min(math.log10(p) * 2.5, 25.0)
    except Exception:
        pass

    # 7. Duration sanity
    if duration_sec:
        if duration_sec < 60:
            score -= 60.0  # Short / ringtone / status clip
        elif 120 <= duration_sec <= 420:
            score += 10.0  # Standard song length
        elif duration_sec > 600 and not any(k in q_lower for k in ("qawwali", "album", "jukebox", "hour", "long")):
            score -= 30.0  # 10+ min movie scene or compilation

    return score
