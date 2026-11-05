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
_FONT_BOLD = os.path.join(_HELPERS_DIR, "Raleway-Bold.ttf")
_FONT_LIGHT = os.path.join(_HELPERS_DIR, "Inter-Light.ttf")


def clean_song_name(raw_title: str) -> str:
    """Extract strictly the clean song name, removing actors, movies, and noise."""
    if not raw_title:
        return "Unknown Track"
    t = raw_title.strip()
    # Strip bracketed content: (Official Video), [4K], (From "Bajirao Mastani")
    t = re.sub(r'[\(\[].*?[\)\]]', '', t).strip()
    # Strip video/audio descriptors
    t = re.sub(r'(?i)\b(?:official\s*(?:music\s*)?video|official\s*audio|full\s*video(?:\s*song)?|video\s*song|lyric(?:s|al)?\s*video|hd|hq|4k|1080p|visualizer)\b', '', t).strip()

    # Split on pipe: first segment is universally the song title in Indian releases
    if "|" in t:
        parts = [p.strip() for p in t.split("|") if p.strip()]
        if parts:
            t = parts[0]

    # Split on dash
    if " - " in t or " – " in t or " — " in t:
        t = re.sub(r'\s*[–—]\s*', ' - ', t)
        parts = [p.strip() for p in t.split(" - ") if p.strip()]
        if len(parts) >= 2:
            p1, p2 = parts[0], parts[1]
            p2_lower = p2.lower()
            if any(k in p2_lower for k in ["deepika", "ranveer", "ranbir", "salman", "actor", "movie", "film", "audio", "video", "song"]):
                t = p1
            elif any(k in p1.lower() for k in ["xxxtentacion", "ed sheeran", "drake", "taylor swift", "ariana", "justin"]):
                t = p2
            else:
                t = p1

    # Strip trailing or standalone "Song", "Video", "Audio"
    t = re.sub(r'(?i)(?:Video\s*)?Song\b', '', t).strip()
    t = re.sub(r'(?i)\b(?:video|audio|full)\b', '', t).strip()

    # Clean dangling punctuation
    t = re.sub(r'\s*[-|:]\s*$', '', t).strip()
    t = re.sub(r'^\s*[-|:]\s*', '', t).strip()
    return t if t else raw_title.strip()


class Thumbnail:
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None
        try:
            self.font_bold = ImageFont.truetype(_FONT_BOLD, 48)
            self.font_sub = ImageFont.truetype(_FONT_BOLD, 36)
            self.font_time = ImageFont.truetype(_FONT_LIGHT, 22)
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
    def _draw_controls(draw: ImageDraw.ImageDraw, cx: int, cy: int, color=(255, 255, 255, 255)) -> None:
        glow_r = 42
        for gr in range(glow_r, 32, -1):
            alpha = int(25 * (1 - (gr - 32) / (glow_r - 32)))
            draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=(255, 255, 255, alpha))

        r = 32
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
        tri_pts = [(cx - 8, cy - 14), (cx - 8, cy + 14), (cx + 13, cy)]
        draw.polygon(tri_pts, fill=(160, 15, 30, 255))

        px, py = cx - 110, cy
        draw.polygon([(px + 12, py - 15), (px + 12, py + 15), (px - 8, py)], fill=color)
        draw.rectangle([px - 13, py - 15, px - 9, py + 15], fill=color)

        nx, ny = cx + 110, cy
        draw.polygon([(nx - 12, ny - 15), (nx - 12, ny + 15), (nx + 8, ny)], fill=color)
        draw.rectangle([nx + 9, ny - 15, nx + 13, ny + 15], fill=color)

        sx, sy = cx - 220, cy
        draw.line([(sx - 16, sy + 9), (sx - 6, sy + 9), (sx + 6, sy - 9), (sx + 16, sy - 9)], fill=color, width=3)
        draw.polygon([(sx + 13, sy - 15), (sx + 20, sy - 9), (sx + 13, sy - 3)], fill=color)
        draw.line([(sx - 16, sy - 9), (sx - 6, sy - 9), (sx - 1, sy - 2)], fill=color, width=3)
        draw.line([(sx + 1, sy + 2), (sx + 6, sy + 9), (sx + 16, sy + 9)], fill=color, width=3)
        draw.polygon([(sx + 13, sy + 3), (sx + 20, sy + 9), (sx + 13, sy + 15)], fill=color)

        rx, ry = cx + 220, cy
        draw.rounded_rectangle([rx - 16, ry - 12, rx + 16, ry + 12], radius=6, outline=color, width=3)
        draw.polygon([(rx + 11, ry + 7), (rx + 19, ry + 12), (rx + 11, ry + 17)], fill=color)

    @staticmethod
    def _create_metallic_candy_red_background(W: int, H: int, seed_id: str) -> Image.Image:
        y_coords, x_coords = np.mgrid[0:H, 0:W]

        d_tr = np.sqrt(((x_coords - W * 0.88) / (W * 0.55))**2 + ((y_coords - 0) / (H * 0.65))**2)
        d_bl = np.sqrt(((x_coords - 0) / (W * 0.55))**2 + ((y_coords - H) / (H * 0.55))**2)

        d_tl_dark = np.sqrt(((x_coords - 0) / (W * 0.45))**2 + ((y_coords - 0) / (H * 0.45))**2)
        d_br_dark = np.sqrt(((x_coords - W) / (W * 0.45))**2 + ((y_coords - H) / (H * 0.45))**2)
        d_rm_dark = np.sqrt(((x_coords - W * 0.65) / (W * 0.35))**2 + ((y_coords - H * 0.25) / (H * 0.35))**2)

        light = 0.50 * np.exp(-1.8 * d_tr**2) + 0.45 * np.exp(-1.8 * d_bl**2)
        light = light - 0.20 * np.exp(-1.2 * d_tl_dark**2) - 0.25 * np.exp(-1.2 * d_br_dark**2) - 0.15 * np.exp(-1.5 * d_rm_dark**2)
        light = np.clip(light, 0, 1)

        arr = np.zeros((H, W, 3), dtype=np.float32)
        r_base, g_base, b_base = 58.0, 2.0, 5.0
        r_bright, g_bright, b_bright = 250.0, 75.0, 85.0

        arr[:, :, 0] = r_base + (r_bright - r_base) * (light ** 1.1)
        arr[:, :, 1] = g_base + (g_bright - g_base) * (light ** 1.4)
        arr[:, :, 2] = b_base + (b_bright - b_base) * (light ** 1.4)

        seed = abs(hash(seed_id)) % 100000
        rng = np.random.RandomState(seed)
        micro_noise = rng.normal(0, 1, (H, W)).astype(np.float32)
        fine_noise = rng.normal(0, 1, (H, W)).astype(np.float32)

        arr[:, :, 0] += micro_noise * 13.0 + fine_noise * 7.0
        arr[:, :, 1] += micro_noise * 9.0 + fine_noise * 4.0
        arr[:, :, 2] += micro_noise * 9.0 + fine_noise * 4.0

        sparkle_mask = rng.random((H, W)) > 0.975
        sparkle_intensity = rng.uniform(15, 40, (H, W)).astype(np.float32) * sparkle_mask
        arr[:, :, 0] += sparkle_intensity
        arr[:, :, 1] += sparkle_intensity * 0.65
        arr[:, :, 2] += sparkle_intensity * 0.65

        arr = np.clip(arr, 0, 255).astype(np.uint8)
        base = Image.fromarray(arr, "RGB").filter(ImageFilter.GaussianBlur(0.35))
        return base.convert("RGBA")

    async def generate(self, song: Track, size=(1280, 720)) -> str:
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

            # 1. Metallic Candy Red Background with deeper darks
            base = self._create_metallic_candy_red_background(W, H, song.id)
            raw_thumb = Image.open(temp).convert("RGB")

            # 2. Rounded Left Frame / Album Card
            cover_x = 110
            cover_y = 130
            cover_size = 460
            radius = 36

            # Drop shadow
            shadow = Image.new("RGBA", (cover_size + 60, cover_size + 60), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow)
            s_draw.rounded_rectangle([30, 30, cover_size + 30, cover_size + 30], radius=radius, fill=(0, 0, 0, 230))
            shadow = shadow.filter(ImageFilter.GaussianBlur(18))
            base.alpha_composite(shadow, (cover_x - 30, cover_y - 30))

            # Artwork fits and fills the frame cleanly (no letterboxing)
            card_img = ImageOps.fit(raw_thumb, (cover_size, cover_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            card_rgba = card_img.convert("RGBA")

            # 3. Black Dark Bottom Frame Overlay
            black_overlay = Image.new("RGBA", (cover_size, cover_size), (0, 0, 0, 0))
            bo_draw = ImageDraw.Draw(black_overlay)

            grad_h = 135
            solid_black_h = 45
            start_y = cover_size - grad_h

            for i in range(grad_h - solid_black_h):
                alpha = int(255 * (i / (grad_h - solid_black_h))**1.8)
                cur_y = start_y + i
                bo_draw.line([(0, cur_y), (cover_size, cur_y)], fill=(0, 0, 0, alpha))

            bo_draw.rectangle([0, cover_size - solid_black_h, cover_size, cover_size], fill=(0, 0, 0, 255))
            card_rgba = Image.alpha_composite(card_rgba, black_overlay)

            # 4. Green Equalizer Bars (not in order, clear gaps, proper size)
            wave_margin = 35
            wave_w = cover_size - wave_margin * 2
            bw = 2
            gap = 3
            bar_step = bw + gap
            num_bars = wave_w // bar_step
            actual_wave_w = num_bars * bar_step - gap
            start_bx = (cover_size - actual_wave_w) // 2
            wave_baseline = cover_size - 14

            w_draw = ImageDraw.Draw(card_rgba)

            bar_seed = abs(hash(song.id + "_eq")) % 100000
            bar_rng = np.random.RandomState(bar_seed)

            for i in range(num_bars):
                bx = start_bx + i * bar_step
                t = i / (num_bars - 1)

                if t < 0.40:
                    bar_h = bar_rng.randint(6, 12) if bar_rng.random() < 0.25 else bar_rng.randint(2, 5)
                elif t < 0.58:
                    bar_h = int(bar_rng.randint(4, 22) * (0.6 + 0.4 * (t - 0.40) / 0.18))
                elif t < 0.88:
                    cluster_envelope = math.sin((t - 0.58) / 0.30 * math.pi)
                    raw_peak = bar_rng.choice([16, 25, 34, 42, 48, 22, 38, 28, 45, 18, 50, 32])
                    bar_h = max(4, int(raw_peak * (0.6 + 0.4 * cluster_envelope)))
                else:
                    bar_h = max(2, int(bar_rng.randint(3, 10) * (1.0 - (t - 0.88) / 0.12)))

                color = (95, 240, 120, 255)
                w_draw.rectangle([bx, wave_baseline - bar_h, bx + bw - 1, wave_baseline], fill=color)

            # Apply rounded corner mask to the entire card
            mask = Image.new("L", (cover_size, cover_size), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=radius, fill=255)
            card_rgba.putalpha(mask)

            base.paste(card_rgba, (cover_x, cover_y), card_rgba)

            # 5. Right Side: Just Song Name, Bold & Clean!
            info_x = 640
            draw = ImageDraw.Draw(base)

            pure_name = clean_song_name(song.title)

            # If title fits on one line (<= 20 chars), place nicely above the bar
            if len(pure_name) <= 20:
                draw.text((info_x, 305), pure_name, font=self.font_bold, fill=(255, 255, 255, 255))
            else:
                words = pure_name.split()
                mid = len(words) // 2
                l1 = " ".join(words[:mid])
                l2 = " ".join(words[mid:])
                if len(l1) > 22:
                    l1 = l1[:20] + "..."
                if len(l2) > 22:
                    l2 = l2[:20] + "..."
                draw.text((info_x, 260), l1, font=self.font_bold, fill=(255, 255, 255, 255))
                draw.text((info_x, 318), l2, font=self.font_bold, fill=(255, 255, 255, 255))

            # Progress Bar
            bar_y = 400
            bar_len = 540

            draw.rounded_rectangle([info_x, bar_y, info_x + bar_len, bar_y + 6], radius=3, fill=(255, 255, 255, 255))
            knob_x = info_x + int(bar_len * 0.30)
            draw.ellipse([knob_x - 8, bar_y - 5, knob_x + 8, bar_y + 11], fill=(255, 255, 255, 255))

            draw.text((info_x, bar_y + 20), "0:46", font=self.font_time, fill=(255, 255, 255, 235))
            duration_text = str(song.duration or "00:00")
            draw.text((info_x + bar_len - 60, bar_y + 20), duration_text, font=self.font_time, fill=(255, 255, 255, 235))

            # Playback Controls
            controls_cx = info_x + bar_len // 2
            controls_cy = 510
            self._draw_controls(draw, controls_cx, controls_cy, color=(255, 255, 255, 255))

            base.save(output, "PNG")
            try:
                os.remove(temp)
            except Exception:
                pass
            return output
        except Exception:
            return config.DEFAULT_THUMB
