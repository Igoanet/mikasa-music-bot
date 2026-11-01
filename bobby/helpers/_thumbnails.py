# Copyright (c) 2025 Bobby Maharaj
# Licensed under the MIT License.
# This file is part of BobbyXMusic

import math
import os
import aiohttp
from PIL import (Image, ImageDraw, ImageEnhance,
                 ImageFilter, ImageOps)

from bobby import config
from bobby.helpers import Track


class Thumbnail:
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None

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

    async def generate(self, song: Track, size=(1280, 480)) -> str:
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

            # 1. Base dark crimson canvas
            base = Image.new("RGBA", (W, H), (14, 3, 6, 255))
            raw_thumb = Image.open(temp).convert("RGBA")

            # 2. Ambient background blurred from thumbnail
            bg = raw_thumb.resize((W, H), Image.Resampling.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(35))
            bg = ImageEnhance.Brightness(bg).enhance(0.30)
            base = Image.alpha_composite(base, bg)

            # 3. Crimson vignette overlay
            vignette = Image.new("RGBA", (W, H), (180, 10, 30, 40))
            base = Image.alpha_composite(base, vignette)

            # 4. Neon halo aura behind center pod
            glow_canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            g_draw = ImageDraw.Draw(glow_canvas)
            cx, cy = W // 2, H // 2
            pod_r = 160

            for rad, alpha in [
                (pod_r + 60, 25),
                (pod_r + 40, 50),
                (pod_r + 25, 85),
                (pod_r + 10, 140),
                (pod_r + 4, 200),
            ]:
                g_draw.ellipse(
                    [cx - rad, cy - rad, cx + rad, cy + rad],
                    fill=(255, 30, 60, alpha),
                )
            glow_canvas = glow_canvas.filter(ImageFilter.GaussianBlur(16))
            base = Image.alpha_composite(base, glow_canvas)

            # 5. Cyber audio visualizer wavebars on left & right
            eq_draw = ImageDraw.Draw(base)
            for i in range(16):
                x = 90 + i * 28
                h = max(6, int(15 + 45 * abs(math.sin(i * 0.38)) + (i % 3) * 12))
                alpha = int(25 + (i / 16) * 110)
                eq_draw.rounded_rectangle([x, cy - h, x + 6, cy + h], radius=3, fill=(255, 45, 75, alpha))

            for i in range(16):
                x = W - 90 - i * 28
                h = max(6, int(15 + 45 * abs(math.sin(i * 0.38)) + (i % 3) * 12))
                alpha = int(25 + (i / 16) * 110)
                eq_draw.rounded_rectangle([x - 6, cy - h, x, cy + h], radius=3, fill=(255, 45, 75, alpha))

            # Corner cyber markers
            for cx_c, cy_c in [(35, 35), (W - 35, 35), (35, H - 35), (W - 35, H - 35)]:
                eq_draw.line([(cx_c - 10, cy_c), (cx_c + 10, cy_c)], fill=(255, 50, 80, 100), width=2)
                eq_draw.line([(cx_c, cy_c - 10), (cx_c, cy_c + 10)], fill=(255, 50, 80, 100), width=2)

            # 6. Central circular pod for album photo
            pod_dim = (pod_r * 2, pod_r * 2)
            pod_img = ImageOps.fit(raw_thumb, pod_dim, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

            mask = Image.new("L", pod_dim, 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.ellipse([0, 0, pod_dim[0], pod_dim[1]], fill=255)
            pod_img.putalpha(mask)

            base.paste(pod_img, (cx - pod_r, cy - pod_r), pod_img)

            # 7. Crisp circular neon border rings
            ring_draw = ImageDraw.Draw(base)
            ring_draw.ellipse([cx - pod_r - 4, cy - pod_r - 4, cx + pod_r + 4, cy + pod_r + 4], outline=(255, 40, 70, 230), width=5)
            ring_draw.ellipse([cx - pod_r - 1, cy - pod_r - 1, cx + pod_r + 1, cy + pod_r + 1], outline=(255, 120, 140, 200), width=2)

            base.save(output, "PNG")
            try:
                os.remove(temp)
            except Exception:
                pass
            return output
        except Exception:
            return config.DEFAULT_THUMB
