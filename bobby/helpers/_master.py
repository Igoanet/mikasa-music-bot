# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

"""Mastering for /voiceover clips: make every category land where its real YouTube /
Instagram counterpart sits (measured in research/tts-reference-matching.md).

Raw engine output arrives at -19..-30 LUFS with a 17-22 dB crest and no
presence, so it sounds thin and quiet next to a real bhajan (-10 LUFS, crest
~13) or a funny-dub reel (-13 LUFS, crest ~12).  Each profile is a tone/glue
chain, then gain to the target loudness under a true-peak limiter — the same
three moves every reel editor's "loudness" preset makes.

Every ffmpeg pass works on a temp file; the source is replaced only when the
whole chain succeeded, so a failure here can never lose a clip.
"""

import asyncio
import os
import re

from bobby import logger

# profile -> (tone + glue chain, integrated-loudness target LUFS, mp3 bitrate)
# Targets are the medians of the measured references (research/
# tts-reference-matching.md): YouTube song masters -10..-12 LUFS, funny-dub
# channel mixes -8..-17 (centre -12), reel voice-overs -12..-16.
# Never put a lowpass at/above 12 kHz: gpt-audio/Edge clips are 24 kHz, and a
# biquad at Nyquist goes unstable (measured: -12 dB swings between encoders).
PROFILES = {
    # sung songs over a bed: gentle glue only — the bed carries the density
    "song": (
        "highpass=f=35,"
        "acompressor=threshold=-18dB:ratio=2:attack=25:release=250:knee=6",
        -11.0, "128k",
    ),
    # character / funny dubs: phone-mic low cut, forward 3 kHz, hard glue.
    # Dramatic pauses are part of the act, so silence is left alone.
    "dub": (
        "highpass=f=100,equalizer=f=250:t=q:w=1.2:g=-2,"
        "equalizer=f=3200:t=q:w=1:g=4,highshelf=f=7000:g=2,"
        "acompressor=threshold=-24dB:ratio=4:attack=5:release=100:knee=4",
        -12.0, "96k",
    ),
    # reel voice-overs: reel narrators barely pause (0-7 % silence vs ~30 % in
    # raw neural TTS), so gaps over 0.45 s are trimmed to 0.3 s; then clean
    # presence and air, moderate glue.
    "voiceover": (
        "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-45dB:start_silence=0.08:"
        "stop_periods=-1:stop_duration=0.45:stop_threshold=-40dB:stop_silence=0.3,"
        "highpass=f=80,equalizer=f=3500:t=q:w=1.2:g=3,highshelf=f=7000:g=3,"
        "acompressor=threshold=-22dB:ratio=3:attack=8:release=120:knee=4",
        -13.5, "96k",
    ),
}
_LIMIT = 0.85  # -1.4 dBFS sample ceiling; mp3 overshoot puts true peak around -0.5 dBTP
_TOLERANCE = 0.4  # LU: closer than this to the target counts as landed
_MAX_RENDERS = 3  # the limiter answers sub-linearly to more gain, so nudge at most twice


# file-level disclosure alongside the caption (India IT Rules amendment, Feb 2026, asks for metadata
# where feasible): every mastered clip carries it in its tag comment
AI_TAG = ("-metadata", "comment=AI-generated voice (Mikasa Music Bot)")


async def _ffmpeg(*args: str) -> str:
    """Run ffmpeg, return stderr; raise on failure."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-nostats", "-v", "info", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="replace")[-300:] or "ffmpeg failed")
    return err.decode(errors="replace")


async def loudness(path: str, chain: str | None = None) -> float:
    """Integrated loudness (LUFS, EBU R128) of `path`, optionally after `chain`."""
    af = (chain + "," if chain else "") + "ebur128=peak=none"
    err = await _ffmpeg("-i", path, "-af", af, "-f", "null", "-")
    summary = err[err.rfind("Summary:"):]
    m = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", summary)
    if not m or m.group(1) == "-inf":
        raise RuntimeError("no loudness measurement")
    return float(m.group(1))


async def master(path: str, profile: str) -> float | None:
    """Master `path` in place with `profile`; returns the landed LUFS.

    Failures are logged and leave the file untouched (returns None) — an
    unmastered clip still reaches the user.
    """
    chain, target, bitrate = PROFILES[profile]
    tmp = f"{path}.master{os.path.splitext(path)[1] or '.mp3'}"
    try:
        measured = await loudness(path, chain)
        gain = target - measured
        for _ in range(_MAX_RENDERS):
            landed = await _render(path, tmp, chain, gain, bitrate)
            short = target - landed
            if short <= _TOLERANCE:
                break
            # dense peaks keep the limiter busy: +3 dB in may give +1 LU out
            gain += min(short * 1.5, 4.0)
        os.replace(tmp, path)
        logger.info("mastered %s [%s]: %.1f -> %.1f LUFS (target %.1f)",
                    os.path.basename(path), profile, measured, landed, target)
        return landed
    except Exception as e:  # noqa: BLE001
        logger.warning("mastering failed (%s): %s — sending raw clip", profile, e)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None


async def _render(src: str, dst: str, chain: str, gain: float, bitrate: str) -> float:
    af = (f"{chain},volume={gain:.2f}dB,"
          f"alimiter=limit={_LIMIT}:attack=2:release=50:level=false,"
          "ebur128=peak=none")
    err = await _ffmpeg("-i", src, "-af", af, "-c:a", "libmp3lame", "-b:a", bitrate, *AI_TAG, dst)
    summary = err[err.rfind("Summary:"):]
    m = re.search(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", summary)
    if not m or m.group(1) == "-inf":
        raise RuntimeError("no loudness after render")
    return float(m.group(1))


async def bed_gain(vocal_path: str, bed_path: str, under_lu: float) -> float:
    """Linear gain that places `bed_path` `under_lu` LU below the vocal's loudness."""
    vocal, bed = await asyncio.gather(loudness(vocal_path), _bed_loudness(bed_path))
    return 10 ** ((vocal - under_lu - bed) / 20)


_bed_cache: dict[str, float] = {}


async def _bed_loudness(bed_path: str) -> float:
    key = f"{bed_path}:{os.path.getmtime(bed_path)}"
    if key not in _bed_cache:
        _bed_cache[key] = await loudness(bed_path)
    return _bed_cache[key]
