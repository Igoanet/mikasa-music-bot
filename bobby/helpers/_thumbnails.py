# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import math
import os
import re
import aiohttp
import numpy as np
from PIL import (Image, ImageDraw, ImageEnhance,
                 ImageFilter, ImageFont, ImageOps)

from bobby import config
from bobby.helpers import Track

_HELPERS_DIR = os.path.dirname(__file__)
_FONT_BOLD = os.path.join(_HELPERS_DIR, "CenturyGothic-Bold.ttf")
_FONT_LIGHT = os.path.join(_HELPERS_DIR, "Inter-Light.ttf")

KNOWN_LABELS = {
    "sony music", "sony music india", "t-series", "tseries", "zee music company",
    "zee music", "tips official", "tips", "yrf", "yash raj films", "saregama",
    "saregama music", "speed records", "lahari music", "aditya music", "geet mp3",
    "white hill music", "eros now", "shemaroo", "desimelodies", "desi melodies",
    "t-series apna punjab", "t-series bhakti sagar", "vevo", "sonymusicindiavevo"
}


def clean_song_name(raw_title: str) -> str:
    """Extract strictly the clean song name, removing actors, movies, and noise."""
    if not raw_title:
        return "Unknown Track"
    t = raw_title.strip()

    had_pipe = '|' in t

    # 1. Strip bracketed content: (Official Video), [4K], (From "Movie"), (Audio), (Lyrics), etc.
    t = re.sub(r'[\(\[].*?[\)\]]', '', t).strip()

    # 2. If title has pipe '|', split on '|'
    # In Indian / commercial tracks, everything after the first pipe is movie/actors/credits
    if '|' in t:
        parts = [p.strip() for p in t.split('|') if p.strip()]
        if parts:
            t = parts[0]

    # 3. Clean common noise words anywhere
    noise_patterns = [
        r'(?i)\b(?:official\s*(?:music\s*)?video|official\s*audio|official\s*lyric\s*video)\b',
        r'(?i)\b(?:full\s*(?:video\s*)?song|video\s*song|audio\s*song|lyric(?:s|al)?\s*video)\b',
        r'(?i)\b(?:music\s*video|lyric\s*video|visualizer|audio|video|lyrics?)\b',
        r'(?i)\b(?:hd|hq|4k|1080p|720p)\b',
        r'(?i)\b(?:remastered|remix|version)\b',
    ]
    for np in noise_patterns:
        t = re.sub(np, '', t).strip()

    # Handle cases where "Song" got glued like "Deewani MastaniSong"
    t = re.sub(r'(?i)(?<=[a-zA-Z])Song\b', '', t).strip()
    t = re.sub(r'(?i)\bSong\b', '', t).strip()

    # 4. Handle dashes: "Artist - Title" or "Channel - Song - Artist" or "Song - Movie"
    if ' - ' in t or ' – ' in t or ' — ' in t or '-' in t:
        dash_regex = r'\s*[\-–—]\s*'
        segments = [s.strip() for s in re.split(dash_regex, t) if s.strip()]

        # Filter out known label names from segments
        filtered = []
        for s in segments:
            s_clean = re.sub(r'[^a-zA-Z0-9 ]', '', s).strip().lower()
            if s_clean not in KNOWN_LABELS:
                filtered.append(s)
        if filtered:
            segments = filtered

        if len(segments) >= 2:
            s0, s1 = segments[0], segments[1]
            actor_keywords = ["deepika", "ranveer", "ranbir", "salman", "actor", "movie", "film",
                              "shreya", "arijit", "pritam", "anirudh", "shah rukh", "alia", "vicky"]
            if had_pipe:
                # If title originally had '|', the first part before '-' was the song, second part was movie/video
                t = s0
            elif any(k in s1.lower() for k in actor_keywords):
                t = s0
            elif any(k in s0.lower() for k in actor_keywords):
                t = s1
            else:
                # In western standard "Artist - Title", the song title is the right side (s1)
                t = s1 if len(segments) == 2 and not any(k in s1.lower() for k in ["movie", "ost", "soundtrack"]) else s0
        elif len(segments) == 1:
            t = segments[0]

    # Clean dangling punctuation and spaces
    t = re.sub(r'^\s*[-|:,.]+\s*', '', t)
    t = re.sub(r'\s*[-|:,.]+\s*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()

    return t if t else raw_title.strip()


class Thumbnail:
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None
        try:
            self.font_title_single = ImageFont.truetype(_FONT_BOLD, 44)
            self.font_title_multi = ImageFont.truetype(_FONT_BOLD, 36)
            self.font_brand = ImageFont.truetype(_FONT_BOLD, 18)
            self.font_time = ImageFont.truetype(_FONT_BOLD, 18)
        except Exception:
            self.font_title_single = ImageFont.load_default()
            self.font_title_multi = ImageFont.load_default()
            self.font_brand = ImageFont.load_default()
            self.font_time = ImageFont.load_default()

    async def start(self) -> None:
        self.session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    async def save_thumb(self, output_path: str, url: str) -> str:
        async with self.session.get(url) as resp:
            with open(output_path, "wb") as f:
                f.write(await resp.read())
        return output_path

    async def generate(self, song: Track, size=(1024, 576)) -> str:
        try:
            temp = f"cache/temp_{song.id}.jpg"
            output = f"cache/{song.id}_v5.png"
            if os.path.exists(output):
                try:
                    os.utime(output)
                except OSError:
                    pass
                return output

            await self.save_thumb(temp, song.thumbnail)
            W, H = size

            raw_thumb = Image.open(temp).convert("RGB")
            rw, rh = raw_thumb.size
            aspect = rw / float(rh) if rh > 0 else 1.777

            # 1. Base Layer: Full horizontal coverage
            if aspect >= 1.35:
                # 16:9 widescreen poster - full edge-to-edge bleed
                base = ImageOps.fit(raw_thumb, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            else:
                # Square or portrait cover: Rich ambient blurred backdrop + sharp centered album card
                bg = raw_thumb.resize((W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(36))
                bg = ImageEnhance.Brightness(bg).enhance(0.55)

                art_h = int(H * 0.88)
                art_w = int(art_h * aspect)
                art = raw_thumb.resize((art_w, art_h), Image.Resampling.LANCZOS)

                ax = (W - art_w) // 2
                ay = (H - art_h) // 2

                shadow = Image.new("RGBA", (art_w + 32, art_h + 32), (0, 0, 0, 0))
                s_draw = ImageDraw.Draw(shadow)
                s_draw.rounded_rectangle([16, 16, art_w + 16, art_h + 16], radius=22, fill=(0, 0, 0, 190))
                shadow = shadow.filter(ImageFilter.GaussianBlur(14))

                art_rgba = art.convert("RGBA")
                mask = Image.new("L", (art_w, art_h), 0)
                ImageDraw.Draw(mask).rounded_rectangle([0, 0, art_w, art_h], radius=20, fill=255)
                art_rgba.putalpha(mask)

                base_rgba = bg.convert("RGBA")
                base_rgba.alpha_composite(shadow, (ax - 16, ay - 16))
                base_rgba.paste(art_rgba, (ax, ay), art_rgba)
                base = base_rgba.convert("RGB")

            base_rgba = base.convert("RGBA")

            # 2. Sleek Cinematic Dark Gradients
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d_ol = ImageDraw.Draw(overlay)

            # Bottom gradient for typography and visualizer readability
            grad_start = H - 210
            for y in range(grad_start, H):
                prog = (y - grad_start) / float(H - grad_start)
                alpha = int(225 * (prog ** 1.6))
                d_ol.line([(0, y), (W, y)], fill=(8, 8, 12, alpha))

            # Top subtle vignette
            for y in range(0, 80):
                prog = 1.0 - (y / 80.0)
                alpha = int(110 * (prog ** 1.5))
                d_ol.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))

            base_rgba.alpha_composite(overlay)

            # 3. Audio Visualizer Spectrum Bars across the full bottom width
            eq_draw = ImageDraw.Draw(base_rgba)
            baseline_y = H - 12
            num_bars = 84
            bar_w = 7
            gap = 5
            total_w = num_bars * (bar_w + gap) - gap
            start_x = (W - total_w) // 2

            seed = abs(hash(song.id or song.title)) % 10000
            np.random.seed(seed)
            x_vals = np.linspace(0, 4.5 * np.pi, num_bars)
            wave = np.sin(x_vals) * 0.5 + 0.5
            wave = wave * (np.sin(x_vals * 0.35) * 0.3 + 0.7)
            noise = np.random.uniform(0.75, 1.25, num_bars)
            raw_h = 10 + 34 * wave * noise
            smooth_h = [raw_h[0]]
            for i in range(1, num_bars - 1):
                smooth_h.append(int((raw_h[i - 1] + raw_h[i] * 2 + raw_h[i + 1]) / 4))
            smooth_h.append(raw_h[-1])

            for idx, h in enumerate(smooth_h):
                bx = start_x + idx * (bar_w + gap)
                top_y = baseline_y - int(h)
                bar_color = (255, 60, 80, 230)
                eq_draw.rounded_rectangle([bx, top_y, bx + bar_w, baseline_y], radius=3, fill=bar_color)

            # 4. Top Header: MIKASA MUSIC Brand Pill (Left)
            eq_draw.rounded_rectangle([32, 24, 192, 56], radius=16, fill=(0, 0, 0, 160), outline=(255, 60, 80, 210), width=2)
            eq_draw.text((46, 29), "MIKASA MUSIC", font=self.font_brand, fill=(255, 255, 255, 240))

            # Top Header: Duration Pill (Right)
            duration_text = str(song.duration or "00:00")
            dur_w = 90
            dur_x = W - 32 - dur_w
            eq_draw.rounded_rectangle([dur_x, 24, W - 32, 56], radius=16, fill=(0, 0, 0, 160), outline=(255, 255, 255, 80), width=1)
            eq_draw.text((dur_x + 22, 29), duration_text, font=self.font_time, fill=(255, 255, 255, 240))

            # 5. Prominent Track Title
            clean_title = clean_song_name(song.title)
            if len(clean_title) <= 28:
                eq_draw.text((36, H - 76), clean_title, font=self.font_title_single, fill=(0, 0, 0, 230))
                eq_draw.text((34, H - 78), clean_title, font=self.font_title_single, fill=(255, 255, 255, 255))
            else:
                words = clean_title.split()
                mid = len(words) // 2
                l1 = " ".join(words[:mid])
                l2 = " ".join(words[mid:])
                if len(l1) > 30:
                    l1 = l1[:28] + "..."
                if len(l2) > 30:
                    l2 = l2[:28] + "..."
                eq_draw.text((36, H - 110), l1, font=self.font_title_multi, fill=(0, 0, 0, 230))
                eq_draw.text((34, H - 112), l1, font=self.font_title_multi, fill=(255, 255, 255, 255))
                eq_draw.text((36, H - 68), l2, font=self.font_title_multi, fill=(0, 0, 0, 230))
                eq_draw.text((34, H - 70), l2, font=self.font_title_multi, fill=(255, 255, 255, 255))

            base_rgba.convert("RGB").save(output, "PNG")
            try:
                os.remove(temp)
            except Exception:
                pass
            return output
        except Exception:
            return config.DEFAULT_THUMB
