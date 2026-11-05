# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import math
import os
import random
import aiohttp
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
        base = Image.new("RGBA", (W, H), (155, 12, 30, 255))
        draw = ImageDraw.Draw(base)

        for y in range(H):
            ratio = y / H
            r = int(185 - 65 * ratio)
            g = int(16 - 10 * ratio)
            b = int(32 - 16 * ratio)
            draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

        brush = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(brush)
        random.seed(hash(seed_id) % 100000)

        for _ in range(1500):
            by = random.randint(0, H - 1)
            bx = random.randint(0, W - 150)
            bw = random.randint(100, 450)
            balp = random.randint(10, 32)
            b_draw.line([(bx, by), (bx + bw, by)], fill=(255, 130, 150, balp), width=1)

        for _ in range(50000):
            nx = random.randint(0, W - 1)
            ny = random.randint(0, H - 1)
            nalp = random.randint(12, 40)
            color = (255, 210, 220, nalp) if random.random() > 0.45 else (45, 2, 8, nalp)
            b_draw.point((nx, ny), fill=color)

        base = Image.alpha_composite(base, brush)

        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(glow)
        for rad in range(720, 100, -35):
            alpha = int(19 * (1 - rad / 720))
            g_draw.ellipse([640 - rad, 320 - rad, 640 + rad, 320 + rad], fill=(245, 45, 70, alpha))
        base = Image.alpha_composite(base, glow)

        vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        v_draw = ImageDraw.Draw(vignette)
        for i in range(110):
            alpha = int((1 - i / 110) * 110)
            v_draw.rectangle([0, i, W, i + 1], fill=(45, 2, 7, alpha))
            v_draw.rectangle([0, H - i - 1, W, H - i], fill=(35, 1, 6, int(alpha * 1.1)))
            v_draw.rectangle([i, 0, i + 1, H], fill=(40, 2, 7, int(alpha * 0.7)))
            v_draw.rectangle([W - i - 1, 0, W - i, H], fill=(40, 2, 7, int(alpha * 0.7)))
        base = Image.alpha_composite(base, vignette)

        return base

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
