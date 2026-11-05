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

# Common YouTube title noise to strip
_TITLE_NOISE = re.compile(
    r'\s*[\|\-\(\[]\s*(?:'
    r'Official\s*(?:Music\s*)?Video|'
    r'Official\s*Audio|'
    r'Full\s*(?:Video\s*)?Song|'
    r'Video\s*Song|'
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
    def _clean_title(title: str) -> str:
        cleaned = _TITLE_NOISE.sub('', title).strip()
        cleaned = re.sub(r'\s*\|\s*$', '', cleaned).strip()
        cleaned = re.sub(r'\s*[\(\[].*$', '', cleaned).strip()
        return cleaned if cleaned else title.strip()

    @staticmethod
    def _draw_controls(draw: ImageDraw.ImageDraw, cx: int, cy: int, color=(255, 255, 255, 255)) -> None:
        # Play button with subtle glow
        glow_r = 42
        for gr in range(glow_r, 32, -1):
            alpha = int(25 * (1 - (gr - 32) / (glow_r - 32)))
            draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=(255, 255, 255, alpha))

        r = 32
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
        tri_pts = [(cx - 8, cy - 14), (cx - 8, cy + 14), (cx + 13, cy)]
        draw.polygon(tri_pts, fill=(160, 15, 30, 255))

        # Previous — simple single triangle ◀
        px, py = cx - 110, cy
        draw.polygon([(px + 12, py - 15), (px + 12, py + 15), (px - 8, py)], fill=color)
        draw.rectangle([px - 13, py - 15, px - 9, py + 15], fill=color)

        # Next — simple single triangle ▶
        nx, ny = cx + 110, cy
        draw.polygon([(nx - 12, ny - 15), (nx - 12, ny + 15), (nx + 8, ny)], fill=color)
        draw.rectangle([nx + 9, ny - 15, nx + 13, ny + 15], fill=color)

        # Shuffle — crossed arrows
        sx, sy = cx - 220, cy
        draw.line([(sx - 16, sy + 9), (sx - 6, sy + 9), (sx + 6, sy - 9), (sx + 16, sy - 9)], fill=color, width=3)
        draw.polygon([(sx + 13, sy - 15), (sx + 20, sy - 9), (sx + 13, sy - 3)], fill=color)
        draw.line([(sx - 16, sy - 9), (sx - 6, sy - 9), (sx - 1, sy - 2)], fill=color, width=3)
        draw.line([(sx + 1, sy + 2), (sx + 6, sy + 9), (sx + 16, sy + 9)], fill=color, width=3)
        draw.polygon([(sx + 13, sy + 3), (sx + 20, sy + 9), (sx + 13, sy + 15)], fill=color)

        # Repeat — loop rectangle with arrow
        rx, ry = cx + 220, cy
        draw.rounded_rectangle([rx - 16, ry - 12, rx + 16, ry + 12], radius=6, outline=color, width=3)
        draw.polygon([(rx + 11, ry + 7), (rx + 19, ry + 12), (rx + 11, ry + 17)], fill=color)

    @staticmethod
    def _create_brushed_crimson_background(W: int, H: int, seed_id: str) -> Image.Image:
        arr = np.zeros((H, W, 4), dtype=np.uint8)

        cx, cy = W * 0.40, H * 0.38
        max_dist = math.sqrt((max(cx, W - cx))**2 + (max(cy, H - cy))**2)

        y_coords, x_coords = np.mgrid[0:H, 0:W]
        dist = np.sqrt((x_coords - cx)**2 + (y_coords - cy)**2) / max_dist
        dist = np.clip(dist, 0, 1)

        falloff = dist ** 1.5

        r_c, g_c, b_c = 215, 30, 42
        r_e, g_e, b_e = 55, 3, 8

        arr[:, :, 0] = (r_c + (r_e - r_c) * falloff).astype(np.uint8)
        arr[:, :, 1] = (g_c + (g_e - g_c) * falloff).astype(np.uint8)
        arr[:, :, 2] = (b_c + (b_e - b_c) * falloff).astype(np.uint8)
        arr[:, :, 3] = 255

        base = Image.fromarray(arr, "RGBA")

        h_arr = np.zeros((H, W, 4), dtype=np.uint8)
        hx, hy = W * 0.36, H * 0.32
        h_dist = np.sqrt(((x_coords - hx) / (W * 0.35))**2 + ((y_coords - hy) / (H * 0.42))**2)
        h_dist = np.clip(h_dist, 0, 1)
        h_alpha = np.exp(-4.0 * h_dist**2) * 85
        h_arr[:, :, 0] = 255
        h_arr[:, :, 1] = 180
        h_arr[:, :, 2] = 175
        h_arr[:, :, 3] = h_alpha.astype(np.uint8)
        base = Image.alpha_composite(base, Image.fromarray(h_arr, "RGBA"))

        h2_arr = np.zeros((H, W, 4), dtype=np.uint8)
        h2x, h2y = W * 0.55, H * 0.50
        h2_dist = np.sqrt(((x_coords - h2x) / (W * 0.50))**2 + ((y_coords - h2y) / (H * 0.60))**2)
        h2_dist = np.clip(h2_dist, 0, 1)
        h2_alpha = np.exp(-5.0 * h2_dist**2) * 30
        h2_arr[:, :, 0] = 255
        h2_arr[:, :, 1] = 120
        h2_arr[:, :, 2] = 120
        h2_arr[:, :, 3] = h2_alpha.astype(np.uint8)
        base = Image.alpha_composite(base, Image.fromarray(h2_arr, "RGBA"))

        b_arr = np.zeros((H, W, 4), dtype=np.uint8)
        rng = np.random.RandomState(hash(seed_id) % 100000)

        for y in range(H):
            if rng.random() < 0.75:
                alpha = rng.randint(2, 9)
                if rng.random() > 0.45:
                    b_arr[y, :, 0] = 255
                    b_arr[y, :, 1] = 200
                    b_arr[y, :, 2] = 195
                    b_arr[y, :, 3] = alpha
                else:
                    b_arr[y, :, 0] = 25
                    b_arr[y, :, 1] = 1
                    b_arr[y, :, 2] = 4
                    b_arr[y, :, 3] = alpha

        base = Image.alpha_composite(base, Image.fromarray(b_arr, "RGBA"))

        streak = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(streak)

        for _ in range(2500):
            sy = rng.randint(0, H - 1)
            sx = rng.randint(0, W)
            sw = rng.randint(W // 4, W)
            salp = rng.randint(1, 4)
            if rng.random() > 0.4:
                s_draw.line([(sx, sy), (min(sx + sw, W - 1), sy)], fill=(255, 170, 170, salp), width=1)
            else:
                s_draw.line([(sx, sy), (min(sx + sw, W - 1), sy)], fill=(40, 2, 6, salp), width=1)

        base = Image.alpha_composite(base, streak)

        vig = np.zeros((H, W, 4), dtype=np.uint8)
        v_cx, v_cy = W * 0.45, H * 0.45
        v_dist = np.sqrt(((x_coords - v_cx) / (W * 0.55))**2 + ((y_coords - v_cy) / (H * 0.55))**2)
        v_dist = np.clip(v_dist, 0, 1)
        v_mask = v_dist > 0.55
        v_alpha = np.zeros_like(v_dist)
        v_alpha[v_mask] = ((v_dist[v_mask] - 0.55) / 0.45) ** 2.2 * 100
        vig[:, :, 3] = np.clip(v_alpha, 0, 255).astype(np.uint8)

        base = Image.alpha_composite(base, Image.fromarray(vig, "RGBA"))

        base_rgb = base.convert("RGB")
        base_rgb = base_rgb.filter(ImageFilter.GaussianBlur(0.7))
        return base_rgb.convert("RGBA")

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

            base = self._create_brushed_crimson_background(W, H, song.id)
            raw_thumb = Image.open(temp).convert("RGBA")

            # Rounded Album Art with Drop Shadow
            cover_x = 100
            cover_y = 100
            cover_size = 500
            radius = 36

            shadow = Image.new("RGBA", (cover_size + 60, cover_size + 60), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow)
            s_draw.rounded_rectangle([30, 30, cover_size + 30, cover_size + 30], radius=radius, fill=(0, 0, 0, 220))
            shadow = shadow.filter(ImageFilter.GaussianBlur(18))
            base.alpha_composite(shadow, (cover_x - 30, cover_y - 30))

            # Scale thumbnail to fill the square — blur-extend to fill gaps, no black bars
            thumb_rgb = raw_thumb.convert("RGB")
            # Fit thumbnail to fill the square (crop to fill, centered)
            fill_img = ImageOps.fit(thumb_rgb, (cover_size, cover_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.3))
            # Also get contained version (full image, no crop)
            contained = ImageOps.contain(thumb_rgb, (cover_size, cover_size), method=Image.Resampling.LANCZOS)
            # Build blurred background from the fill version
            blurred_bg = fill_img.filter(ImageFilter.GaussianBlur(20))
            # Darken the blurred bg slightly
            blurred_bg = ImageEnhance.Brightness(blurred_bg).enhance(0.4)
            cover_bg = blurred_bg.convert("RGBA")
            # Paste the contained (full) image centered on top
            paste_x = (cover_size - contained.width) // 2
            paste_y = (cover_size - contained.height) // 2
            cover_bg.paste(contained.convert("RGBA"), (paste_x, paste_y))
            # Apply rounded mask
            mask = Image.new("L", (cover_size, cover_size), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=radius, fill=255)
            cover_bg.putalpha(mask)
            base.paste(cover_bg, (cover_x, cover_y), cover_bg)

            # Green Waveform — full width of album art, at the very bottom, no pill background
            wave_margin = 20
            wave_x = cover_x + wave_margin
            wave_w = cover_size - wave_margin * 2
            wave_bottom = cover_y + cover_size - 14   # sits just above the rounded bottom edge

            wave_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            w_draw = ImageDraw.Draw(wave_canvas)

            num_bars = 38
            bw = 5
            gap = 3
            total_bar_width = num_bars * bw + (num_bars - 1) * gap
            wave_start_x = cover_x + (cover_size - total_bar_width) // 2

            for i in range(num_bars):
                bx = wave_start_x + i * (bw + gap)
                # Natural waveform shape — higher in the center, lower at edges
                norm = i / (num_bars - 1)   # 0 → 1
                # bell curve with some variation
                bell = math.exp(-6.0 * (norm - 0.5) ** 2)
                variation = abs(math.sin(i * 0.8 + 1.2)) * 0.4
                bar_h = max(4, int((bell * 0.7 + variation * 0.3) * 42 + 4))
                # gradient green: brighter at top
                g_color = (80, 220, 100, 255)
                w_draw.rounded_rectangle(
                    [bx, wave_bottom - bar_h, bx + bw, wave_bottom],
                    radius=2, fill=g_color
                )

            base = Image.alpha_composite(base, wave_canvas)

            # Right Side: Typography, Progress Bar & Controls
            info_x = 640
            draw = ImageDraw.Draw(base)

            title_text = self._clean_title(song.title or "Unknown Track")

            # Smart title split: "Artist - Song" → line1=Artist, line2=Song
            # Avoid using channel_name as line1 when the title already has an artist
            if " - " in title_text:
                parts = title_text.split(" - ", 1)
                line1 = parts[0].strip()
                line2 = parts[1].strip()
            else:
                # No dash in title — just show on two lines
                words = title_text.split()
                mid = max(1, len(words) // 2)
                line1 = " ".join(words[:mid])
                line2 = " ".join(words[mid:])

            if len(line1) > 20:
                line1 = line1[:18] + "..."
            if len(line2) > 20:
                line2 = line2[:18] + "..."

            ty = 250
            draw.text((info_x, ty), line1, font=self.font_bold, fill=(255, 255, 255, 255))
            draw.text((info_x, ty + 52), line2, font=self.font_sub, fill=(255, 255, 255, 255))

            # Progress Bar
            bar_y = 400
            bar_len = 540

            draw.rounded_rectangle([info_x, bar_y, info_x + bar_len, bar_y + 6], radius=3, fill=(255, 255, 255, 255))
            knob_x = info_x + int(bar_len * 0.30)
            knob_y = bar_y + 3
            draw.ellipse([knob_x - 8, knob_y - 8, knob_x + 8, knob_y + 8], fill=(255, 255, 255, 255))

            draw.text((info_x, bar_y + 20), "0:46", font=self.font_time, fill=(255, 255, 255, 235))
            duration_text = str(song.duration or "00:00")
            draw.text((info_x + bar_len - 60, bar_y + 20), duration_text, font=self.font_time, fill=(255, 255, 255, 235))

            # Controls
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
