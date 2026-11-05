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

# Clean common YouTube noise from titles
_TITLE_NOISE = re.compile(
    r'\s*[\|\-\(\[]\s*(?:'
    r'Official\s*(?:Music\s*)?Video|'
    r'Official\s*Audio|'
    r'Full\s*(?:Video\s*)?Song|'
    r'Full\s*Video|'
    r'Video\s*Song|'
    r'Video|'
    r'Lyric(?:s|al)?\s*Video|'
    r'Audio|'
    r'HD|'
    r'HQ|'
    r'4K|'
    r'1080p|'
    r'Visuali[sz]er'
    r')[\)\]]?\s*',
    re.IGNORECASE,
)


class Thumbnail:
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None
        try:
            self.font_bold = ImageFont.truetype(_FONT_BOLD, 42)
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
    def _clean_and_split_title(title: str, channel: str) -> tuple[str, str]:
        t = _TITLE_NOISE.sub('', title or "Unknown Track").strip()
        t = re.sub(r'[\(\[].*?[\)\]]', '', t).strip()
        t = re.sub(r'\s*\|\s*', ' - ', t).strip()
        t = re.sub(r'\s*-\s*-\s*', ' - ', t).strip()
        t = re.sub(r'\s*-\s*$', '', t).strip()
        t = re.sub(r'^\s*-\s*', '', t).strip()

        if " - " in t:
            parts = [p.strip() for p in t.split(" - ") if p.strip()]
            if len(parts) >= 2:
                return parts[0] + " -", parts[1]
            elif len(parts) == 1:
                return parts[0] + " -", ""

        words = t.split()
        if len(words) <= 3:
            return t + " -", ""
        mid = len(words) // 2
        return " ".join(words[:mid]) + " -", " ".join(words[mid:])

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

        # Multi-point lighting sheen matching reference
        d_tr = np.sqrt(((x_coords - W * 0.85) / (W * 0.7))**2 + ((y_coords - 0) / (H * 0.8))**2)
        d_bl = np.sqrt(((x_coords - 0) / (W * 0.6))**2 + ((y_coords - H) / (H * 0.6))**2)
        d_c = np.sqrt(((x_coords - W * 0.35) / (W * 0.5))**2 + ((y_coords - H * 0.25) / (H * 0.5))**2)

        light = 0.45 * np.exp(-1.5 * d_tr**2) + 0.35 * np.exp(-1.8 * d_bl**2) + 0.40 * np.exp(-1.2 * d_c**2)
        light = np.clip(light, 0, 1)

        arr = np.zeros((H, W, 3), dtype=np.float32)
        r_base, g_base, b_base = 85.0, 5.0, 10.0
        r_bright, g_bright, b_bright = 245.0, 70.0, 80.0

        arr[:, :, 0] = r_base + (r_bright - r_base) * (light ** 0.9)
        arr[:, :, 1] = g_base + (g_bright - g_base) * (light ** 1.3)
        arr[:, :, 2] = b_base + (b_bright - b_base) * (light ** 1.3)

        # Micro-metallic flake noise
        seed = abs(hash(seed_id)) % 100000
        rng = np.random.RandomState(seed)
        micro_noise = rng.normal(0, 1, (H, W)).astype(np.float32)
        fine_noise = rng.normal(0, 1, (H, W)).astype(np.float32)

        arr[:, :, 0] += micro_noise * 14.0 + fine_noise * 8.0
        arr[:, :, 1] += micro_noise * 10.0 + fine_noise * 5.0
        arr[:, :, 2] += micro_noise * 10.0 + fine_noise * 5.0

        sparkle_mask = rng.random((H, W)) > 0.97
        sparkle_intensity = rng.uniform(15, 45, (H, W)).astype(np.float32) * sparkle_mask
        arr[:, :, 0] += sparkle_intensity
        arr[:, :, 1] += sparkle_intensity * 0.7
        arr[:, :, 2] += sparkle_intensity * 0.7

        arr = np.clip(arr, 0, 255).astype(np.uint8)
        base = Image.fromarray(arr, "RGB").filter(ImageFilter.GaussianBlur(0.4))
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

            # 1. Metallic Candy Red Canvas (exact match to reference)
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
            s_draw.rounded_rectangle([30, 30, cover_size + 30, cover_size + 30], radius=radius, fill=(0, 0, 0, 220))
            shadow = shadow.filter(ImageFilter.GaussianBlur(18))
            base.alpha_composite(shadow, (cover_x - 30, cover_y - 30))

            # Artwork fits and fills the frame cleanly (no letterboxing)
            card_img = ImageOps.fit(raw_thumb, (cover_size, cover_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
            card_rgba = card_img.convert("RGBA")

            # 3. Black Dark Bottom Frame Overlay
            # Fades to solid black where the equalizer sits
            black_overlay = Image.new("RGBA", (cover_size, cover_size), (0, 0, 0, 0))
            bo_draw = ImageDraw.Draw(black_overlay)

            grad_h = 130
            solid_black_h = 45
            start_y = cover_size - grad_h

            for i in range(grad_h - solid_black_h):
                alpha = int(255 * (i / (grad_h - solid_black_h))**1.8)
                cur_y = start_y + i
                bo_draw.line([(0, cur_y), (cover_size, cur_y)], fill=(0, 0, 0, alpha))

            bo_draw.rectangle([0, cover_size - solid_black_h, cover_size, cover_size], fill=(0, 0, 0, 255))
            card_rgba = Image.alpha_composite(card_rgba, black_overlay)

            # 4. Green Equalizer Waveform Bars (covering nearly the whole frame)
            wave_margin = 25
            wave_w = cover_size - wave_margin * 2
            bw = 3
            gap = 2
            bar_step = bw + gap
            num_bars = wave_w // bar_step
            actual_wave_w = num_bars * bar_step - gap
            start_bx = (cover_size - actual_wave_w) // 2
            wave_baseline = cover_size - 12

            w_draw = ImageDraw.Draw(card_rgba)

            for i in range(num_bars):
                bx = start_bx + i * bar_step
                t = i / (num_bars - 1)

                base_h = 4.0
                swell = 8.0 * math.exp(-35.0 * (t - 0.28)**2)
                peak = 34.0 * math.exp(-22.0 * (t - 0.72)**2)
                flutter = (math.sin(i * 1.8) * 0.5 + math.cos(i * 3.1) * 0.5) * (swell + peak + 2.0) * 0.25

                bar_h = max(3, int(base_h + swell + peak + flutter))
                color = (85, 230, 115, 255)
                w_draw.rounded_rectangle([bx, wave_baseline - bar_h, bx + bw, wave_baseline], radius=1, fill=color)

            # Apply rounded corner mask to the entire card
            mask = Image.new("L", (cover_size, cover_size), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=radius, fill=255)
            card_rgba.putalpha(mask)

            base.paste(card_rgba, (cover_x, cover_y), card_rgba)

            # 5. Right Side: Clean 2-Line Typography, Progress Bar & Controls
            info_x = 640
            draw = ImageDraw.Draw(base)

            line1, line2 = self._clean_and_split_title(song.title, song.channel_name)

            if len(line1) > 24:
                line1 = line1[:22] + "..."
            if len(line2) > 24:
                line2 = line2[:22] + "..."

            ty = 250
            draw.text((info_x, ty), line1, font=self.font_bold, fill=(255, 255, 255, 255))
            if line2:
                draw.text((info_x, ty + 54), line2, font=self.font_sub, fill=(255, 255, 255, 255))

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
