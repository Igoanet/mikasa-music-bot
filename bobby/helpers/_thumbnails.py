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
            self.font_bold = ImageFont.truetype(_FONT_BOLD, 36)
            self.font_sub = ImageFont.truetype(_FONT_LIGHT, 22)
            self.font_small = ImageFont.truetype(_FONT_LIGHT, 19)
            self.font_micro = ImageFont.truetype(_FONT_BOLD, 15)
            self.font_brand = ImageFont.truetype(_FONT_LIGHT, 16)
        except Exception:
            self.font_bold = ImageFont.load_default()
            self.font_sub = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
            self.font_micro = ImageFont.load_default()
            self.font_brand = ImageFont.load_default()

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
    def _draw_controls(draw: ImageDraw.ImageDraw, cx: int, cy: int, color=(225, 230, 235, 220)) -> None:
        r = 28
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(245, 245, 250, 245))
        tri_pts = [(cx - 6, cy - 11), (cx - 6, cy + 11), (cx + 10, cy)]
        draw.polygon(tri_pts, fill=(14, 15, 17, 255))

        px, py = cx - 85, cy
        draw.polygon([(px + 4, py - 10), (px + 4, py + 10), (px - 7, py)], fill=color)
        draw.polygon([(px + 14, py - 10), (px + 14, py + 10), (px + 3, py)], fill=color)
        draw.rectangle([px - 11, py - 10, px - 8, py + 10], fill=color)

        nx, ny = cx + 85, cy
        draw.polygon([(nx - 4, ny - 10), (nx - 4, ny + 10), (nx + 7, ny)], fill=color)
        draw.polygon([(nx - 14, ny - 10), (nx - 14, ny + 10), (nx - 3, ny)], fill=color)
        draw.rectangle([nx + 8, ny - 10, nx + 11, ny + 10], fill=color)

        sx, sy = cx - 175, cy
        draw.line([(sx - 14, sy + 7), (sx - 5, sy + 7), (sx + 5, sy - 7), (sx + 14, sy - 7)], fill=color, width=3)
        draw.polygon([(sx + 11, sy - 12), (sx + 17, sy - 7), (sx + 11, sy - 2)], fill=color)
        draw.line([(sx - 14, sy - 7), (sx - 5, sy - 7), (sx - 1, sy - 2)], fill=color, width=3)
        draw.line([(sx + 1, sy + 2), (sx + 5, sy + 7), (sx + 14, sy + 7)], fill=color, width=3)
        draw.polygon([(sx + 11, sy + 2), (sx + 17, sy + 7), (sx + 11, sy + 12)], fill=color)

        rx, ry = cx + 175, cy
        draw.arc([rx - 12, ry - 10, rx + 12, ry + 10], start=30, end=330, fill=color, width=3)
        draw.polygon([(rx + 8, ry - 14), (rx + 15, ry - 7), (rx + 7, ry - 4)], fill=color)

    @staticmethod
    def _create_vinyl(size: int = 620) -> Image.Image:
        vinyl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(vinyl)
        cx, cy = size // 2, size // 2
        r = size // 2 - 2

        # Obsidian vinyl disc base
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(10, 10, 12, 255), outline=(22, 22, 26, 255), width=2)

        # Concentric groove rings
        for gr in range(r - 8, 115, -2):
            if gr % 14 == 0:
                alpha = 35
            elif gr % 4 == 0:
                alpha = 18
            else:
                alpha = 7
            draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], outline=(255, 255, 255, alpha), width=1)

        # Anisotropic metallic cone reflections matching Image 2
        sheen = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(sheen)
        angles_weights = [
            (32, 22), (38, 38), (44, 55), (50, 68), (56, 52), (62, 34), (68, 18),
            (212, 22), (218, 38), (224, 55), (230, 68), (236, 52), (242, 34), (248, 18)
        ]
        for angle, weight in angles_weights:
            rad = math.radians(angle)
            x1 = cx + math.cos(rad) * 115
            y1 = cy + math.sin(rad) * 115
            x2 = cx + math.cos(rad) * (r - 4)
            y2 = cy + math.sin(rad) * (r - 4)
            s_draw.line([(x1, y1), (x2, y2)], fill=(255, 255, 255, weight), width=14)
        sheen = sheen.filter(ImageFilter.GaussianBlur(10))
        vinyl = Image.alpha_composite(vinyl, sheen)

        # Matte center disc label
        label_r = 115
        label_draw = ImageDraw.Draw(vinyl)
        label_draw.ellipse([cx - label_r, cy - label_r, cx + label_r, cy + label_r], fill=(36, 38, 42, 255), outline=(55, 58, 64, 255), width=3)

        inner_r = 58
        label_draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=(24, 25, 28, 255), outline=(46, 48, 54, 255), width=2)

        hole_r = 14
        label_draw.ellipse([cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r], fill=(8, 8, 10, 255), outline=(20, 20, 24, 255), width=2)

        return vinyl

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

            # 1. Dark matte textured canvas
            base = Image.new("RGBA", (W, H), (13, 14, 16, 255))
            raw_thumb = Image.open(temp).convert("RGBA")

            bg = raw_thumb.resize((W, H), Image.Resampling.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(65))
            bg = ImageEnhance.Brightness(bg).enhance(0.14)
            base = Image.alpha_composite(base, bg)

            # Matte texture & dark vignette
            dark_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d_draw = ImageDraw.Draw(dark_overlay)

            for r in range(650, 120, -35):
                alpha = int(12 * (1 - r / 650))
                d_draw.ellipse([220 - r, 360 - r, 220 + r, 360 + r], fill=(150, 15, 25, alpha))

            random.seed(hash(song.id) % 100000)
            for _ in range(16000):
                nx = random.randint(0, W - 1)
                ny = random.randint(0, H - 1)
                nalp = random.randint(3, 8)
                d_draw.point((nx, ny), fill=(255, 255, 255, nalp))

            for i in range(130):
                alpha = int((1 - i / 130) * 190)
                d_draw.rectangle([0, i, W, i + 1], fill=(7, 8, 9, alpha))
                d_draw.rectangle([0, H - i - 1, W, H - i], fill=(7, 8, 9, int(alpha * 1.1)))
                d_draw.rectangle([i, 0, i + 1, H], fill=(7, 8, 9, int(alpha * 0.75)))
                d_draw.rectangle([W - i - 1, 0, W - i, H], fill=(7, 8, 9, int(alpha * 0.75)))

            base = Image.alpha_composite(base, dark_overlay)

            # Corner cyber markers
            decor_draw = ImageDraw.Draw(base)
            for cx_c, cy_c in [(45, 45), (W - 45, 45), (45, H - 45), (W - 45, H - 45)]:
                decor_draw.line([(cx_c - 12, cy_c), (cx_c + 12, cy_c)], fill=(110, 115, 125, 110), width=2)
                decor_draw.line([(cx_c, cy_c - 12), (cx_c, cy_c + 12)], fill=(110, 115, 125, 110), width=2)

            # 2. Large Dark Vinyl Record matching Image 2
            cover_x = 75
            cover_y = 135
            cover_size = 450

            vinyl_size = 620
            vinyl_x = cover_x + 130
            vinyl_y = cover_y + (cover_size - vinyl_size) // 2
            vinyl_img = self._create_vinyl(vinyl_size)
            base.paste(vinyl_img, (vinyl_x, vinyl_y), vinyl_img)

            # 3. Rounded Album Art with Drop Shadow
            shadow = Image.new("RGBA", (cover_size + 60, cover_size + 60), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow)
            s_draw.rounded_rectangle([30, 30, cover_size + 30, cover_size + 30], radius=26, fill=(0, 0, 0, 230))
            shadow = shadow.filter(ImageFilter.GaussianBlur(20))
            base.alpha_composite(shadow, (cover_x - 30, cover_y - 30))

            cover_img = ImageOps.fit(raw_thumb, (cover_size, cover_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            mask = Image.new("L", (cover_size, cover_size), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=24, fill=255)
            cover_img.putalpha(mask)
            base.paste(cover_img, (cover_x, cover_y), cover_img)

            border_draw = ImageDraw.Draw(base)
            border_draw.rounded_rectangle([cover_x, cover_y, cover_x + cover_size, cover_y + cover_size], radius=24, outline=(255, 255, 255, 50), width=2)

            # 4. Right Side: Typography and Controls
            info_x = 730
            draw = ImageDraw.Draw(base)

            draw.ellipse([info_x, 95, info_x + 9, 104], fill=(225, 45, 65, 240))
            draw.text((info_x + 18, 91), "MIKASA MUSIC  |  NOW PLAYING", font=self.font_micro, fill=(175, 180, 190, 220))

            title_text = song.title or "Unknown Track"
            title_words = title_text.split()
            lines = []
            curr_line = ""
            for w in title_words:
                test_line = f"{curr_line} {w}".strip()
                if len(test_line) <= 22:
                    curr_line = test_line
                else:
                    if curr_line:
                        lines.append(curr_line)
                    curr_line = w
                    if len(lines) >= 2:
                        break
            if curr_line and len(lines) < 2:
                lines.append(curr_line)
            if not lines:
                lines = [title_text[:22]]
            if len(lines) == 2 and len(title_words) > len(" ".join(lines).split()):
                lines[1] += "..."

            ty = 160
            for line in lines[:2]:
                draw.text((info_x, ty), line, font=self.font_bold, fill=(245, 245, 250, 255))
                ty += 44

            channel_name = (song.channel_name or "Mikasa Stream")[:28]
            draw.text((info_x, ty + 12), f"{channel_name}  •  Mikasa Player", font=self.font_sub, fill=(155, 160, 170, 220))

            # Progress Bar
            bar_y = 370
            bar_len = 480

            draw.rounded_rectangle([info_x, bar_y, info_x + bar_len, bar_y + 7], radius=4, fill=(55, 58, 65, 160))
            played_len = int(bar_len * 0.36)
            draw.rounded_rectangle([info_x, bar_y, info_x + played_len, bar_y + 7], radius=4, fill=(240, 240, 245, 240))

            knob_x = info_x + played_len
            knob_y = bar_y + 3
            draw.ellipse([knob_x - 8, knob_y - 8, knob_x + 8, knob_y + 8], fill=(255, 255, 255, 255))

            draw.text((info_x, bar_y + 22), "01:28", font=self.font_small, fill=(145, 150, 160, 200))
            duration_text = str(song.duration or "00:00")
            draw.text((info_x + bar_len - 60, bar_y + 22), duration_text, font=self.font_small, fill=(145, 150, 160, 200))

            controls_cx = info_x + bar_len // 2
            controls_cy = 490
            self._draw_controls(draw, controls_cx, controls_cy, color=(225, 230, 235, 220))

            line_y = 580
            draw.line([(info_x, line_y), (info_x + bar_len, line_y)], fill=(255, 255, 255, 25), width=1)
            for gl in range(110):
                alpha = int((1 - gl / 110) * 115)
                draw.line([(info_x + bar_len // 2 - gl, line_y), (info_x + bar_len // 2 + gl, line_y)], fill=(255, 255, 255, alpha), width=1)

            draw.text((info_x, line_y + 15), "Mikasa Audio Experience ©", font=self.font_brand, fill=(130, 135, 145, 180))

            base.save(output, "PNG")
            try:
                os.remove(temp)
            except Exception:
                pass
            return output
        except Exception:
            return config.DEFAULT_THUMB
