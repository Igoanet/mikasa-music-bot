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
            self.font_bold = ImageFont.truetype(_FONT_BOLD, 38)
            self.font_sub = ImageFont.truetype(_FONT_BOLD, 30)
            self.font_time = ImageFont.truetype(_FONT_LIGHT, 17)
        except Exception:
            self.font_bold = ImageFont.load_default()
            self.font_sub = ImageFont.load_default()
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

    @staticmethod
    def _draw_controls(draw: ImageDraw.ImageDraw, color=(255, 255, 255, 255)) -> None:
        cy = 410

        # 1. Play Button (Center = 732, 410)
        cx = 732
        glow_r = 28
        for gr in range(glow_r, 20, -1):
            alpha = int(30 * (1 - (gr - 20) / (glow_r - 20)))
            draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=(255, 255, 255, alpha))

        r = 20
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
        tri_pts = [(cx - 5, cy - 9), (cx - 5, cy + 9), (cx + 8, cy)]
        draw.polygon(tri_pts, fill=(160, 15, 30, 255))

        # 2. Previous Button (Center = 652, 410)
        px = 652
        draw.polygon([(px + 7, cy - 10), (px + 7, cy + 10), (px - 6, cy)], fill=color)
        draw.rectangle([px - 9, cy - 10, px - 7, cy + 10], fill=color)

        # 3. Next Button (Center = 814, 410)
        nx = 814
        draw.polygon([(nx - 7, cy - 10), (nx - 7, cy + 10), (nx + 6, cy)], fill=color)
        draw.rectangle([nx + 7, cy - 10, nx + 9, cy + 10], fill=color)

        # 4. Shuffle Button (Center = 536, 410)
        sx = 536
        draw.line([(sx - 12, cy + 7), (sx - 4, cy + 7), (sx + 4, cy - 7), (sx + 12, cy - 7)], fill=color, width=2)
        draw.polygon([(sx + 10, cy - 11), (sx + 15, cy - 7), (sx + 10, cy - 3)], fill=color)
        draw.line([(sx - 12, cy - 7), (sx - 4, cy - 7), (sx - 1, cy - 2)], fill=color, width=2)
        draw.line([(sx + 1, cy + 2), (sx + 4, cy + 7), (sx + 12, cy + 7)], fill=color, width=2)
        draw.polygon([(sx + 10, cy + 3), (sx + 15, cy + 7), (sx + 10, cy + 11)], fill=color)

        # 5. Repeat Button (Center = 925, 410)
        rx = 925
        draw.rounded_rectangle([rx - 12, cy - 9, rx + 12, cy + 9], radius=4, outline=color, width=2)
        draw.polygon([(rx + 8, cy + 5), (rx + 14, cy + 9), (rx + 8, cy + 13)], fill=color)

    @staticmethod
    def _create_metallic_candy_red_background(W: int, H: int, seed_id: str) -> Image.Image:
        y_coords, x_coords = np.mgrid[0:H, 0:W]

        diag = (x_coords * 0.75 + y_coords * 0.45) / (W * 0.75 + H * 0.45)

        h1 = np.exp(-((x_coords - W * 0.65) / (W * 0.45))**2 - ((y_coords - H * 0.25) / (H * 0.45))**2)
        h2 = np.exp(-((diag - 0.48) / 0.28)**2)
        h3 = np.exp(-((x_coords - W * 0.15) / (W * 0.35))**2 - ((y_coords - H * 0.85) / (H * 0.35))**2)

        corner_dist = np.sqrt(((x_coords - W * 0.5) / (W * 0.5))**2 + ((y_coords - H * 0.5) / (H * 0.5))**2)
        vignette = np.clip(1.0 - 0.25 * (corner_dist ** 2), 0.75, 1.0)

        light = (0.50 * h1 + 0.35 * h2 + 0.25 * h3) * vignette
        light = np.clip(light, 0.0, 1.0)

        r_dark, g_dark, b_dark = 104.0, 12.0, 18.0
        r_bright, g_bright, b_bright = 222.0, 52.0, 64.0

        arr = np.zeros((H, W, 3), dtype=np.float32)
        arr[:, :, 0] = r_dark + (r_bright - r_dark) * (light ** 0.95)
        arr[:, :, 1] = g_dark + (g_bright - g_dark) * (light ** 1.3)
        arr[:, :, 2] = b_dark + (b_bright - b_dark) * (light ** 1.3)

        seed = abs(hash(seed_id)) % 100000
        rng = np.random.RandomState(seed)

        brush_1d = rng.normal(0, 1, H).astype(np.float32)
        brush_2d = np.repeat(brush_1d[:, np.newaxis], W, axis=1)
        flake_noise = rng.normal(0, 1, (H, W)).astype(np.float32)

        arr[:, :, 0] += brush_2d * 5.0 + flake_noise * 7.0
        arr[:, :, 1] += brush_2d * 3.0 + flake_noise * 4.0
        arr[:, :, 2] += brush_2d * 3.0 + flake_noise * 4.0

        speck_mask = rng.random((H, W)) > 0.985
        speck_val = rng.uniform(10, 28, (H, W)).astype(np.float32) * speck_mask
        arr[:, :, 0] += speck_val
        arr[:, :, 1] += speck_val * 0.6
        arr[:, :, 2] += speck_val * 0.6

        arr = np.clip(arr, 0, 255).astype(np.uint8)
        base = Image.fromarray(arr, "RGB").filter(ImageFilter.GaussianBlur(0.3))
        return base.convert("RGBA")

    async def generate(self, song: Track, size=(1024, 576)) -> str:
        try:
            temp = f"cache/temp_{song.id}.jpg"
            output = f"cache/{song.id}.png"
            if os.path.exists(output):
                try:
                    os.utime(output)
                except OSError:
                    pass
                return output

            await self.save_thumb(temp, song.thumbnail)
            W, H = size

            # 1. Brushed Metallic Candy Red Background
            base = self._create_metallic_candy_red_background(W, H, song.id)
            raw_thumb = Image.open(temp).convert("RGB")

            # 2. Rounded Left Frame / Album Card
            cover_x = 88
            cover_y = 104
            cover_size = 368
            radius = 32

            # Drop shadow
            shadow = Image.new("RGBA", (cover_size + 40, cover_size + 40), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow)
            s_draw.rounded_rectangle([20, 20, cover_size + 20, cover_size + 20], radius=radius, fill=(0, 0, 0, 200))
            shadow = shadow.filter(ImageFilter.GaussianBlur(14))
            base.alpha_composite(shadow, (cover_x - 20, cover_y - 20))

            # Album Art Fitting (Un-cropped, entire artwork fully visible)
            bg_fill = ImageOps.fit(raw_thumb, (cover_size, cover_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            blurred_fill = bg_fill.filter(ImageFilter.GaussianBlur(18))
            blurred_fill = ImageEnhance.Brightness(blurred_fill).enhance(0.65)
            card_base = blurred_fill.convert("RGBA")

            contained = ImageOps.contain(raw_thumb, (cover_size, cover_size), method=Image.Resampling.LANCZOS)
            paste_x = (cover_size - contained.width) // 2
            paste_y = (cover_size - contained.height) // 2
            card_base.paste(contained.convert("RGBA"), (paste_x, paste_y))

            # 3. Bottom Black Gradient Overlay (Tray)
            black_overlay = Image.new("RGBA", (cover_size, cover_size), (0, 0, 0, 0))
            bo_draw = ImageDraw.Draw(black_overlay)

            grad_h = 110
            solid_black_h = 36
            start_y = cover_size - grad_h

            for i in range(grad_h - solid_black_h):
                alpha = int(255 * (i / (grad_h - solid_black_h))**1.6)
                cur_y = start_y + i
                bo_draw.line([(0, cur_y), (cover_size, cur_y)], fill=(0, 0, 0, alpha))

            bo_draw.rectangle([0, cover_size - solid_black_h, cover_size, cover_size], fill=(0, 0, 0, 255))
            card_base = Image.alpha_composite(card_base, black_overlay)

            # 4. Green Audio Equalizer Bars (Spanning full width of card)
            wave_margin = 22
            wave_w = cover_size - wave_margin * 2
            bw = 3
            gap = 3
            bar_step = bw + gap
            num_bars = wave_w // bar_step
            actual_wave_w = num_bars * bar_step - gap
            start_bx = (cover_size - actual_wave_w) // 2
            wave_baseline = cover_size - 12

            w_draw = ImageDraw.Draw(card_base)
            bar_seed = abs(hash(song.id + "_eq")) % 100000
            bar_rng = np.random.RandomState(bar_seed)

            for i in range(num_bars):
                bx = start_bx + i * bar_step
                norm = i / (num_bars - 1)

                envelope = math.exp(-6.5 * (norm - 0.58)**2)
                flutter = bar_rng.uniform(0.75, 1.25)
                bar_h = max(3, int((envelope * 32.0 + 3.0) * flutter))

                color = (88, 235, 112, 255)
                w_draw.rounded_rectangle([bx, wave_baseline - bar_h, bx + bw - 1, wave_baseline], radius=1, fill=color)

            # Apply rounded corner mask
            mask = Image.new("L", (cover_size, cover_size), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=radius, fill=255)
            card_base.putalpha(mask)

            base.paste(card_base, (cover_x, cover_y), card_base)

            # 5. Right Side Typography, Progress Bar & Controls
            info_x = 515
            draw = ImageDraw.Draw(base)

            pure_name = clean_song_name(song.title)

            # Song Title (Century Gothic Bold, clean single or two lines)
            if len(pure_name) <= 22:
                draw.text((info_x, 235), pure_name, font=self.font_bold, fill=(255, 255, 255, 255))
            else:
                words = pure_name.split()
                mid = len(words) // 2
                l1 = " ".join(words[:mid])
                l2 = " ".join(words[mid:])
                if len(l1) > 24:
                    l1 = l1[:22] + "..."
                if len(l2) > 24:
                    l2 = l2[:22] + "..."
                draw.text((info_x, 210), l1, font=self.font_bold, fill=(255, 255, 255, 255))
                draw.text((info_x, 255), l2, font=self.font_bold, fill=(255, 255, 255, 255))

            # Progress Bar
            bar_y = 320
            bar_len = 436
            draw.rounded_rectangle([info_x, bar_y, info_x + bar_len, bar_y + 4], radius=2, fill=(255, 255, 255, 255))
            knob_x = info_x + int(bar_len * 0.28)
            draw.ellipse([knob_x - 6, bar_y - 4, knob_x + 6, bar_y + 8], fill=(255, 255, 255, 255))

            draw.text((info_x, bar_y + 14), "0:46", font=self.font_time, fill=(255, 255, 255, 235))
            duration_text = str(song.duration or "00:00")
            draw.text((info_x + bar_len - 42, bar_y + 14), duration_text, font=self.font_time, fill=(255, 255, 255, 235))

            # Controls
            self._draw_controls(draw, color=(255, 255, 255, 255))

            base.save(output, "PNG")
            try:
                os.remove(temp)
            except Exception:
                pass
            return output
        except Exception:
            return config.DEFAULT_THUMB
