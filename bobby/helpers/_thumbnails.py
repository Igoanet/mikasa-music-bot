# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import math
import os
import random
import aiohttp
import numpy as np
from PIL import (Image, ImageDraw, ImageEnhance,
                 ImageFilter, ImageFont, ImageOps)

from bobby import config
from bobby.helpers import Track

_HELPERS_DIR = os.path.dirname(__file__)
_FONT_BOLD = os.path.join(_HELPERS_DIR, "Raleway-Bold.ttf")
_FONT_LIGHT = os.path.join(_HELPERS_DIR, "Inter-Light.ttf")


class Thumbnail:
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None
        try:
            self.font_bold = ImageFont.truetype(_FONT_BOLD, 46)
            self.font_sub = ImageFont.truetype(_FONT_BOLD, 40)
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
        # Circular play button matching reference
        r = 32
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
        tri_pts = [(cx - 7, cy - 13), (cx - 7, cy + 13), (cx + 12, cy)]
        draw.polygon(tri_pts, fill=(160, 15, 30, 255))

        # Previous button (|<<)
        px, py = cx - 95, cy
        draw.polygon([(px + 4, py - 13), (px + 4, py + 13), (px - 10, py)], fill=color)
        draw.polygon([(px + 18, py - 13), (px + 18, py + 13), (px + 4, py)], fill=color)
        draw.rectangle([px - 15, py - 13, px - 11, py + 13], fill=color)

        # Next button (>>|)
        nx, ny = cx + 95, cy
        draw.polygon([(nx - 4, ny - 13), (nx - 4, ny + 13), (nx + 10, ny)], fill=color)
        draw.polygon([(nx - 18, ny - 13), (nx - 18, ny + 13), (nx - 4, ny)], fill=color)
        draw.rectangle([nx + 11, ny - 13, nx + 15, ny + 13], fill=color)

        # Shuffle button
        sx, sy = cx - 190, cy
        draw.line([(sx - 16, sy + 9), (sx - 6, sy + 9), (sx + 6, sy - 9), (sx + 16, sy - 9)], fill=color, width=3)
        draw.polygon([(sx + 13, sy - 15), (sx + 20, sy - 9), (sx + 13, sy - 3)], fill=color)
        draw.line([(sx - 16, sy - 9), (sx - 6, sy - 9), (sx - 1, sy - 2)], fill=color, width=3)
        draw.line([(sx + 1, sy + 2), (sx + 6, sy + 9), (sx + 16, sy + 9)], fill=color, width=3)
        draw.polygon([(sx + 13, sy + 3), (sx + 20, sy + 9), (sx + 13, sy + 15)], fill=color)

        # Repeat button
        rx, ry = cx + 190, cy
        draw.rounded_rectangle([rx - 16, ry - 12, rx + 16, ry + 12], radius=6, outline=color, width=3)
        draw.polygon([(rx + 11, ry + 7), (rx + 19, ry + 12), (rx + 11, ry + 17)], fill=color)

    @staticmethod
    def _create_brushed_crimson_background(W: int, H: int, seed_id: str) -> Image.Image:
        arr = np.zeros((H, W, 4), dtype=np.uint8)

        # Radial gradient centered slightly left and above center
        cx, cy = W * 0.40, H * 0.38
        max_dist = math.sqrt((max(cx, W - cx))**2 + (max(cy, H - cy))**2)

        y_coords, x_coords = np.mgrid[0:H, 0:W]
        dist = np.sqrt((x_coords - cx)**2 + (y_coords - cy)**2) / max_dist
        dist = np.clip(dist, 0, 1)

        falloff = dist ** 1.5

        # Cherry red center → deep crimson edges
        r_c, g_c, b_c = 215, 30, 42
        r_e, g_e, b_e = 55, 3, 8

        arr[:, :, 0] = (r_c + (r_e - r_c) * falloff).astype(np.uint8)
        arr[:, :, 1] = (g_c + (g_e - g_c) * falloff).astype(np.uint8)
        arr[:, :, 2] = (b_c + (b_e - b_c) * falloff).astype(np.uint8)
        arr[:, :, 3] = 255

        base = Image.fromarray(arr, "RGBA")

        # Specular highlight — bright elliptical hotspot upper-left
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

        # Secondary subtle highlight for depth
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

        # Fine horizontal brushing — satin metal texture
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

        # Longer horizontal streaks for metallic depth
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

        # Subtle radial vignette
        vig = np.zeros((H, W, 4), dtype=np.uint8)
        v_cx, v_cy = W * 0.45, H * 0.45
        v_dist = np.sqrt(((x_coords - v_cx) / (W * 0.55))**2 + ((y_coords - v_cy) / (H * 0.55))**2)
        v_dist = np.clip(v_dist, 0, 1)
        v_mask = v_dist > 0.55
        v_alpha = np.zeros_like(v_dist)
        v_alpha[v_mask] = ((v_dist[v_mask] - 0.55) / 0.45) ** 2.2 * 100
        vig[:, :, 3] = np.clip(v_alpha, 0, 255).astype(np.uint8)

        base = Image.alpha_composite(base, Image.fromarray(vig, "RGBA"))

        # Final slight blur for smoothness
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

            # 1. Brushed Crimson Canvas (ditto reference)
            base = self._create_brushed_crimson_background(W, H, song.id)
            raw_thumb = Image.open(temp).convert("RGBA")

            # 2. Rounded Album Art with Drop Shadow
            cover_x = 110
            cover_y = 130
            cover_size = 460
            radius = 36

            shadow = Image.new("RGBA", (cover_size + 60, cover_size + 60), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow)
            s_draw.rounded_rectangle([30, 30, cover_size + 30, cover_size + 30], radius=radius, fill=(0, 0, 0, 220))
            shadow = shadow.filter(ImageFilter.GaussianBlur(18))
            base.alpha_composite(shadow, (cover_x - 30, cover_y - 30))

            cover_img = ImageOps.fit(raw_thumb, (cover_size, cover_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            mask = Image.new("L", (cover_size, cover_size), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=radius, fill=255)
            cover_img.putalpha(mask)
            base.paste(cover_img, (cover_x, cover_y), cover_img)

            # 3. Mini Green Waveform inside bottom of album cover (ditto reference)
            wave_w = 170
            wave_x = cover_x + (cover_size - wave_w) // 2
            wave_y = cover_y + cover_size - 40

            wave_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            w_draw = ImageDraw.Draw(wave_canvas)
            w_draw.rounded_rectangle([wave_x - 15, wave_y - 25, wave_x + wave_w + 15, wave_y + 25], radius=16, fill=(10, 14, 12, 230))

            num_bars = 24
            bw = 4
            spacing = (wave_w - (num_bars * bw)) // (num_bars - 1)
            for i in range(num_bars):
                bx = wave_x + i * (bw + spacing)
                dist = abs(i - num_bars / 2) / (num_bars / 2)
                factor = math.cos(dist * (math.pi / 2))
                h = max(4, int(5 + 26 * (factor ** 1.8) + (math.sin(i * 1.5) * 4)))
                w_draw.rounded_rectangle([bx, wave_y + 16 - h, bx + bw, wave_y + 16], radius=2, fill=(105, 235, 125, 255))

            base = Image.alpha_composite(base, wave_canvas)

            # 4. Right Side: Ditto Typography, Progress Bar & Playback Controls
            info_x = 640
            draw = ImageDraw.Draw(base)

            title_text = (song.title or "Unknown Track").strip()
            channel_name = (song.channel_name or "Mikasa Stream").strip()

            if " - " in title_text:
                parts = title_text.split(" - ", 1)
                line1 = f"{parts[0]} -"
                line2 = parts[1]
            else:
                line1 = f"{channel_name} -"
                line2 = title_text

            if len(line1) > 26:
                line1 = line1[:24] + "..."
            if len(line2) > 26:
                line2 = line2[:24] + "..."

            ty = 250
            draw.text((info_x, ty), line1, font=self.font_bold, fill=(255, 255, 255, 255))
            draw.text((info_x, ty + 56), line2, font=self.font_sub, fill=(255, 255, 255, 255))

            # Progress Bar
            bar_y = 405
            bar_len = 540

            draw.rounded_rectangle([info_x, bar_y, info_x + bar_len, bar_y + 8], radius=4, fill=(255, 255, 255, 255))
            knob_x = info_x + int(bar_len * 0.30)
            knob_y = bar_y + 4
            draw.ellipse([knob_x - 9, knob_y - 9, knob_x + 9, knob_y + 9], fill=(255, 255, 255, 255))

            draw.text((info_x, bar_y + 24), "0:46", font=self.font_time, fill=(255, 255, 255, 235))
            duration_text = str(song.duration or "00:00")
            draw.text((info_x + bar_len - 60, bar_y + 24), duration_text, font=self.font_time, fill=(255, 255, 255, 235))

            # Controls
            controls_cx = info_x + bar_len // 2
            controls_cy = 520
            self._draw_controls(draw, controls_cx, controls_cy, color=(255, 255, 255, 255))

            base.save(output, "PNG")
            try:
                os.remove(temp)
            except Exception:
                pass
            return output
        except Exception:
            return config.DEFAULT_THUMB
