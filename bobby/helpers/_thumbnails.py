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
            self.font_sub = ImageFont.truetype(_FONT_LIGHT, 24)
            self.font_small = ImageFont.truetype(_FONT_LIGHT, 20)
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
    def _draw_controls(draw: ImageDraw.ImageDraw, cx: int, cy: int, color=(255, 255, 255, 240)) -> None:
        # 1. Play button (Circle with triangle)
        r = 28
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 250))
        tri_pts = [(cx - 6, cy - 11), (cx - 6, cy + 11), (cx + 10, cy)]
        draw.polygon(tri_pts, fill=(18, 18, 20, 255))

        # 2. Previous button (|<<)
        px, py = cx - 85, cy
        draw.polygon([(px + 4, py - 10), (px + 4, py + 10), (px - 7, py)], fill=color)
        draw.polygon([(px + 14, py - 10), (px + 14, py + 10), (px + 3, py)], fill=color)
        draw.rectangle([px - 11, py - 10, px - 8, py + 10], fill=color)

        # 3. Next button (>>|)
        nx, ny = cx + 85, cy
        draw.polygon([(nx - 4, ny - 10), (nx - 4, ny + 10), (nx + 7, ny)], fill=color)
        draw.polygon([(nx - 14, ny - 10), (nx - 14, ny + 10), (nx - 3, ny)], fill=color)
        draw.rectangle([nx + 8, ny - 10, nx + 11, ny + 10], fill=color)

        # 4. Shuffle button
        sx, sy = cx - 175, cy
        draw.line([(sx - 14, sy + 7), (sx - 5, sy + 7), (sx + 5, sy - 7), (sx + 14, sy - 7)], fill=color, width=3)
        draw.polygon([(sx + 11, sy - 12), (sx + 17, sy - 7), (sx + 11, sy - 2)], fill=color)
        draw.line([(sx - 14, sy - 7), (sx - 5, sy - 7), (sx - 1, sy - 2)], fill=color, width=3)
        draw.line([(sx + 1, sy + 2), (sx + 5, sy + 7), (sx + 14, sy + 7)], fill=color, width=3)
        draw.polygon([(sx + 11, sy + 2), (sx + 17, sy + 7), (sx + 11, sy + 12)], fill=color)

        # 5. Repeat button
        rx, ry = cx + 175, cy
        draw.arc([rx - 12, ry - 10, rx + 12, ry + 10], start=30, end=330, fill=color, width=3)
        draw.polygon([(rx + 8, ry - 14), (rx + 15, ry - 7), (rx + 7, ry - 4)], fill=color)

    @staticmethod
    def _create_vinyl(size: int = 400, thumb_crop: Image.Image | None = None) -> Image.Image:
        vinyl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(vinyl)
        cx, cy = size // 2, size // 2
        r = size // 2 - 2

        # Base obsidian disc
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(16, 16, 18, 255), outline=(40, 40, 45, 255), width=2)

        # Concentric grooves
        for gr in range(r - 12, 75, -3):
            alpha = 24 if (gr % 9 == 0) else (14 if gr % 3 == 0 else 6)
            draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], outline=(255, 255, 255, alpha), width=1)

        # Metallic sheen reflections (cone highlights)
        sheen = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(sheen)
        for angle in [30, 42, 54, 120, 210, 222, 234, 300]:
            rad = math.radians(angle)
            x1 = cx + math.cos(rad) * 75
            y1 = cy + math.sin(rad) * 75
            x2 = cx + math.cos(rad) * (r - 4)
            y2 = cy + math.sin(rad) * (r - 4)
            s_draw.line([(x1, y1), (x2, y2)], fill=(255, 255, 255, 14), width=8)
        sheen = sheen.filter(ImageFilter.GaussianBlur(6))
        vinyl = Image.alpha_composite(vinyl, sheen)

        # Center label with crimson border
        label_r = 75
        label_draw = ImageDraw.Draw(vinyl)
        label_draw.ellipse([cx - label_r, cy - label_r, cx + label_r, cy + label_r], fill=(150, 15, 32, 255), outline=(230, 40, 65, 255), width=3)

        if thumb_crop:
            mini_thumb = thumb_crop.resize((label_r * 2, label_r * 2), Image.Resampling.LANCZOS)
            mask = Image.new("L", (label_r * 2, label_r * 2), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.ellipse([0, 0, label_r * 2, label_r * 2], fill=255)
            mini_thumb.putalpha(mask)
            vinyl.paste(mini_thumb, (cx - label_r, cy - label_r), mini_thumb)

        # Inner spindle hole
        hole_draw = ImageDraw.Draw(vinyl)
        hole_draw.ellipse([cx - 24, cy - 24, cx + 24, cy + 24], fill=(22, 22, 25, 255), outline=(60, 60, 65, 255), width=2)
        hole_r = 10
        hole_draw.ellipse([cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r], fill=(10, 10, 12, 255))

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

            # 1. Base Dark Crimson & Obsidian Metallic Background
            base = Image.new("RGBA", (W, H), (18, 3, 7, 255))
            raw_thumb = Image.open(temp).convert("RGBA")

            # Ambient blurred glow from cover
            bg = raw_thumb.resize((W, H), Image.Resampling.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(55))
            bg = ImageEnhance.Brightness(bg).enhance(0.35)
            base = Image.alpha_composite(base, bg)

            # Rich crimson luxury wash
            crimson_wash = Image.new("RGBA", (W, H), (145, 12, 28, 120))
            base = Image.alpha_composite(base, crimson_wash)

            # Metallic texture & radial core highlights
            metal = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            m_draw = ImageDraw.Draw(metal)
            for r in range(850, 180, -35):
                alpha = int(28 * (1 - r / 850))
                m_draw.ellipse([340 - r, 360 - r, 340 + r, 360 + r], fill=(230, 20, 50, alpha))

            random.seed(hash(song.id) % 100000)
            for _ in range(14000):
                nx = random.randint(0, W - 1)
                ny = random.randint(0, H - 1)
                nalp = random.randint(4, 13)
                m_draw.point((nx, ny), fill=(255, 140, 160, nalp))

            # Dark obsidian vignette borders
            for i in range(140):
                alpha = int((1 - i / 140) * 170)
                m_draw.rectangle([0, i, W, i + 1], fill=(8, 1, 3, alpha))
                m_draw.rectangle([0, H - i - 1, W, H - i], fill=(8, 1, 3, int(alpha * 1.15)))
                m_draw.rectangle([i, 0, i + 1, H], fill=(8, 1, 3, int(alpha * 0.75)))
                m_draw.rectangle([W - i - 1, 0, W - i, H], fill=(8, 1, 3, int(alpha * 0.75)))

            base = Image.alpha_composite(base, metal)

            # Corner cyber markers
            decor_draw = ImageDraw.Draw(base)
            for cx_c, cy_c in [(45, 45), (W - 45, 45), (45, H - 45), (W - 45, H - 45)]:
                decor_draw.line([(cx_c - 12, cy_c), (cx_c + 12, cy_c)], fill=(255, 80, 105, 150), width=2)
                decor_draw.line([(cx_c, cy_c - 12), (cx_c, cy_c + 12)], fill=(255, 80, 105, 150), width=2)

            # 2. Vinyl Record protruding from behind Album Art
            cover_x = 90
            cover_y = 130
            cover_size = 420

            vinyl_size = 400
            vinyl_x = cover_x + 195
            vinyl_y = cover_y + (cover_size - vinyl_size) // 2
            vinyl_img = self._create_vinyl(vinyl_size, raw_thumb)
            base.paste(vinyl_img, (vinyl_x, vinyl_y), vinyl_img)

            # 3. Rounded Album Art with Drop Shadow
            shadow = Image.new("RGBA", (cover_size + 50, cover_size + 50), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow)
            s_draw.rounded_rectangle([25, 25, cover_size + 25, cover_size + 25], radius=24, fill=(0, 0, 0, 190))
            shadow = shadow.filter(ImageFilter.GaussianBlur(16))
            base.alpha_composite(shadow, (cover_x - 25, cover_y - 25))

            cover_img = ImageOps.fit(raw_thumb, (cover_size, cover_size), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            mask = Image.new("L", (cover_size, cover_size), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.rounded_rectangle([0, 0, cover_size, cover_size], radius=22, fill=255)
            cover_img.putalpha(mask)
            base.paste(cover_img, (cover_x, cover_y), cover_img)

            # Inner silver border
            border_draw = ImageDraw.Draw(base)
            border_draw.rounded_rectangle([cover_x, cover_y, cover_x + cover_size, cover_y + cover_size], radius=22, outline=(255, 255, 255, 75), width=2)

            # 4. Glowing Audio Waveform Equalizer
            eq_x = cover_x + 10
            eq_y = cover_y + cover_size + 45
            eq_width = cover_size - 20
            num_bars = 32
            bar_w = 6
            spacing = (eq_width - (num_bars * bar_w)) // (num_bars - 1)

            eq_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            eq_draw = ImageDraw.Draw(eq_canvas)

            for i in range(num_bars):
                bx = eq_x + i * (bar_w + spacing)
                factor = math.sin((i / (num_bars - 1)) * math.pi)
                h = max(5, int(6 + 32 * factor + (math.cos(i * 1.3) * 8)))
                alpha = int(140 + 115 * factor)
                eq_draw.rounded_rectangle([bx, eq_y - h, bx + bar_w, eq_y + h], radius=3, fill=(255, 50, 85, alpha))

            eq_glow = eq_canvas.filter(ImageFilter.GaussianBlur(8))
            base = Image.alpha_composite(base, eq_glow)
            base = Image.alpha_composite(base, eq_canvas)

            # 5. Right Side: Brand, Title, Channel, Timeline, Playback Controls
            info_x = 680
            draw = ImageDraw.Draw(base)

            # Top Tag: Live indicator dot + MIKASA MUSIC | NOW PLAYING
            draw.ellipse([info_x, 86, info_x + 10, 96], fill=(255, 45, 75, 255))
            draw.text((info_x + 20, 82), "MIKASA MUSIC  |  NOW PLAYING", font=self.font_micro, fill=(240, 240, 250, 215))

            # Title
            title_text = song.title or "Unknown Track"
            title_words = title_text.split()
            lines = []
            curr_line = ""
            for w in title_words:
                test_line = f"{curr_line} {w}".strip()
                if len(test_line) <= 24:
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
                lines = [title_text[:24]]
            if len(lines) == 2 and len(title_words) > len(" ".join(lines).split()):
                lines[1] += "..."

            ty = 150
            for line in lines[:2]:
                draw.text((info_x, ty), line, font=self.font_bold, fill=(255, 255, 255, 255))
                ty += 44

            # Artist / Channel
            channel_name = (song.channel_name or "Mikasa Stream")[:30]
            draw.text((info_x, ty + 12), f"{channel_name}  •  Mikasa Player", font=self.font_sub, fill=(210, 215, 225, 215))

            # Timeline Progress Bar
            bar_y = 360
            bar_len = 510

            draw.rounded_rectangle([info_x, bar_y, info_x + bar_len, bar_y + 8], radius=4, fill=(90, 90, 105, 130))
            played_len = int(bar_len * 0.36)
            draw.rounded_rectangle([info_x, bar_y, info_x + played_len, bar_y + 8], radius=4, fill=(255, 255, 255, 255))

            knob_x = info_x + played_len
            knob_y = bar_y + 4
            draw.ellipse([knob_x - 9, knob_y - 9, knob_x + 9, knob_y + 9], fill=(255, 255, 255, 255))

            # Timestamps
            draw.text((info_x, bar_y + 22), "01:28", font=self.font_small, fill=(205, 210, 220, 205))
            duration_text = str(song.duration or "00:00")
            draw.text((info_x + bar_len - 65, bar_y + 22), duration_text, font=self.font_small, fill=(205, 210, 220, 205))

            # Controls
            controls_cx = info_x + bar_len // 2
            controls_cy = 480
            self._draw_controls(draw, controls_cx, controls_cy, color=(255, 255, 255, 240))

            # Bottom brand line
            draw.line([(info_x, 570), (info_x + bar_len, 570)], fill=(255, 255, 255, 25), width=1)
            draw.text((info_x, 584), "High Fidelity Audio Stream  •  Mikasa System ©", font=self.font_brand, fill=(170, 175, 185, 140))

            base.save(output, "PNG")
            try:
                os.remove(temp)
            except Exception:
                pass
            return output
        except Exception:
            return config.DEFAULT_THUMB
