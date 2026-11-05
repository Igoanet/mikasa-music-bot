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
            self.font_bold = ImageFont.truetype(_FONT_BOLD, 44)
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
        # Solid white circle play button with black triangle
        r = 30
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
        tri_pts = [(cx - 6, cy - 12), (cx - 6, cy + 12), (cx + 12, cy)]
        draw.polygon(tri_pts, fill=(18, 18, 20, 255))

        # Previous button (|<<)
        px, py = cx - 90, cy
        draw.polygon([(px + 4, py - 11), (px + 4, py + 11), (px - 8, py)], fill=color)
        draw.polygon([(px + 16, py - 11), (px + 16, py + 11), (px + 4, py)], fill=color)
        draw.rectangle([px - 13, py - 11, px - 9, py + 11], fill=color)

        # Next button (>>|)
        nx, ny = cx + 90, cy
        draw.polygon([(nx - 4, ny - 11), (nx - 4, ny + 11), (nx + 8, ny)], fill=color)
        draw.polygon([(nx - 16, ny - 11), (nx - 16, ny + 11), (nx - 4, ny)], fill=color)
        draw.rectangle([nx + 9, ny - 11, nx + 13, ny + 11], fill=color)

        # Shuffle button
        sx, sy = cx - 180, cy
        draw.line([(sx - 15, sy + 8), (sx - 5, sy + 8), (sx + 5, sy - 8), (sx + 15, sy - 8)], fill=color, width=3)
        draw.polygon([(sx + 12, sy - 13), (sx + 18, sy - 8), (sx + 12, sy - 3)], fill=color)
        draw.line([(sx - 15, sy - 8), (sx - 5, sy - 8), (sx - 1, sy - 2)], fill=color, width=3)
        draw.line([(sx + 1, sy + 2), (sx + 5, sy + 8), (sx + 15, sy + 8)], fill=color, width=3)
        draw.polygon([(sx + 12, sy + 3), (sx + 18, sy + 8), (sx + 12, sy + 13)], fill=color)

        # Repeat button
        rx, ry = cx + 180, cy
        draw.arc([rx - 13, ry - 11, rx + 13, ry + 11], start=30, end=330, fill=color, width=3)
        draw.polygon([(rx + 9, ry - 15), (rx + 16, ry - 8), (rx + 8, ry - 5)], fill=color)

    @staticmethod
    def _create_vinyl(size: int = 580) -> Image.Image:
        vinyl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(vinyl)
        cx, cy = size // 2, size // 2
        r = size // 2 - 2

        # Obsidian vinyl base
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(12, 12, 14, 255), outline=(26, 26, 30, 255), width=2)

        # Concentric groove rings
        for gr in range(r - 8, 100, -2):
            if gr % 14 == 0:
                alpha = 35
            elif gr % 4 == 0:
                alpha = 18
            else:
                alpha = 8
            draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], outline=(255, 255, 255, alpha), width=1)

        # Metallic sheen cone highlights matching Image 2
        sheen = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(sheen)
        angles_weights = [
            (35, 25), (42, 45), (48, 65), (55, 75), (62, 50), (68, 25),
            (215, 25), (222, 45), (228, 65), (235, 75), (242, 50), (248, 25)
        ]
        for angle, weight in angles_weights:
            rad = math.radians(angle)
            x1 = cx + math.cos(rad) * 100
            y1 = cy + math.sin(rad) * 100
            x2 = cx + math.cos(rad) * (r - 4)
            y2 = cy + math.sin(rad) * (r - 4)
            s_draw.line([(x1, y1), (x2, y2)], fill=(255, 255, 255, weight), width=12)
        sheen = sheen.filter(ImageFilter.GaussianBlur(8))
        vinyl = Image.alpha_composite(vinyl, sheen)

        # Dark center label
        label_r = 100
        label_draw = ImageDraw.Draw(vinyl)
        label_draw.ellipse([cx - label_r, cy - label_r, cx + label_r, cy + label_r], fill=(34, 35, 40, 255), outline=(52, 55, 60, 255), width=2)

        inner_r = 50
        label_draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=(22, 23, 26, 255), outline=(44, 46, 50, 255), width=2)

        hole_r = 12
        label_draw.ellipse([cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r], fill=(8, 8, 10, 255))

        return vinyl

    @staticmethod
    def _create_brushed_crimson_background(W: int, H: int, seed_id: str) -> Image.Image:
        base = Image.new("RGBA", (W, H), (145, 12, 28, 255))
        draw = ImageDraw.Draw(base)

        for y in range(H):
            ratio = y / H
            r = int(175 - 55 * ratio)
            g = int(14 - 8 * ratio)
            b = int(28 - 14 * ratio)
            draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

        brush = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        b_draw = ImageDraw.Draw(brush)
        random.seed(hash(seed_id) % 100000)

        # Horizontal brushed streaks
        for _ in range(1200):
            by = random.randint(0, H - 1)
            bx = random.randint(0, W - 150)
            bw = random.randint(80, 350)
            balp = random.randint(8, 26)
            b_draw.line([(bx, by), (bx + bw, by)], fill=(255, 120, 140, balp), width=1)

        # Fine metallic glitter grain
        for _ in range(45000):
            nx = random.randint(0, W - 1)
            ny = random.randint(0, H - 1)
            nalp = random.randint(12, 38)
            color = (255, 200, 210, nalp) if random.random() > 0.4 else (40, 2, 8, nalp)
            b_draw.point((nx, ny), fill=color)

        base = Image.alpha_composite(base, brush)

        # Center highlight glow
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        g_draw = ImageDraw.Draw(glow)
        for rad in range(700, 100, -35):
            alpha = int(18 * (1 - rad / 700))
            g_draw.ellipse([640 - rad, 300 - rad, 640 + rad, 300 + rad], fill=(240, 40, 60, alpha))
        base = Image.alpha_composite(base, glow)

        # Soft edge vignette
        vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        v_draw = ImageDraw.Draw(vignette)
        for i in range(100):
            alpha = int((1 - i / 100) * 120)
            v_draw.rectangle([0, i, W, i + 1], fill=(45, 2, 6, alpha))
            v_draw.rectangle([0, H - i - 1, W, H - i], fill=(35, 1, 5, int(alpha * 1.1)))
            v_draw.rectangle([i, 0, i + 1, H], fill=(40, 2, 6, int(alpha * 0.7)))
            v_draw.rectangle([W - i - 1, 0, W - i, H], fill=(40, 2, 6, int(alpha * 0.7)))
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

            # 1. Brushed Crimson Metallic Canvas (matches reference)
            base = self._create_brushed_crimson_background(W, H, song.id)
            raw_thumb = Image.open(temp).convert("RGBA")

            # 2. Large Dark Vinyl Record behind Album Art
            cover_x = 90
            cover_y = 135
            cover_size = 450

            vinyl_size = 580
            vinyl_x = cover_x + 130
            vinyl_y = cover_y + (cover_size - vinyl_size) // 2
            vinyl_img = self._create_vinyl(vinyl_size)
            base.paste(vinyl_img, (vinyl_x, vinyl_y), vinyl_img)

            # 3. Rounded Album Art with Drop Shadow
            shadow = Image.new("RGBA", (cover_size + 60, cover_size + 60), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow)
            s_draw.rounded_rectangle([30, 30, cover_size + 30, cover_size + 30], radius=32, fill=(0, 0, 0, 210))
            shadow = shadow.filter(ImageFilter.GaussianBlur(20))
            base.alpha_composite(shadow, (cover_x - 30, cover_y - 30))

            cover_img = ImageOps.fit(raw_thumb, (cover_size, cover_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            mask = Image.new("L", (cover_size, cover_size), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=30, fill=255)
            cover_img.putalpha(mask)
            base.paste(cover_img, (cover_x, cover_y), cover_img)

            # 4. Clean Pure White Typography matching reference
            info_x = 730
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

            if len(line1) > 22:
                line1 = line1[:20] + "..."
            if len(line2) > 22:
                line2 = line2[:20] + "..."

            ty = 230
            draw.text((info_x, ty), line1, font=self.font_bold, fill=(255, 255, 255, 255))
            draw.text((info_x, ty + 52), line2, font=self.font_sub, fill=(255, 255, 255, 255))

            # Progress Bar
            bar_y = 390
            bar_len = 480

            draw.rounded_rectangle([info_x, bar_y, info_x + bar_len, bar_y + 8], radius=4, fill=(255, 255, 255, 255))
            knob_x = info_x + int(bar_len * 0.35)
            knob_y = bar_y + 4
            draw.ellipse([knob_x - 9, knob_y - 9, knob_x + 9, knob_y + 9], fill=(255, 255, 255, 255))

            # Timestamps
            draw.text((info_x, bar_y + 22), "01:28", font=self.font_time, fill=(255, 255, 255, 235))
            duration_text = str(song.duration or "00:00")
            draw.text((info_x + bar_len - 60, bar_y + 22), duration_text, font=self.font_time, fill=(255, 255, 255, 235))

            # Playback Controls
            controls_cx = info_x + bar_len // 2
            controls_cy = 505
            self._draw_controls(draw, controls_cx, controls_cy, color=(255, 255, 255, 255))

            base.save(output, "PNG")
            try:
                os.remove(temp)
            except Exception:
                pass
            return output
        except Exception:
            return config.DEFAULT_THUMB
