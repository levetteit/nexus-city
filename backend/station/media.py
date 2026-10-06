"""Branded image cards for posts that need a picture (Instagram always does; Facebook does better with one).

Plain Pillow, no image model: a 1080x1350 card with the venture's colors, a headline, a few points and
the call to action. The words come from the Content Creator and go through QA with the post. Cards are
saved under data/station/media/ with unguessable names and served at /media/<name> without the
password, because Instagram has to fetch the image itself.
"""
from __future__ import annotations

import os
import re
import secrets
import textwrap
from typing import Optional

W, H = 1080, 1350
NAME_RE = re.compile(r"^[a-f0-9]{32}\.jpg$")
PALETTES = {   # background top, background bottom, accent, text
    "solar": ((8, 28, 66), (14, 70, 140), (255, 196, 44), (255, 255, 255)),
    "default": ((10, 14, 34), (28, 40, 90), (94, 231, 255), (255, 255, 255)),
}


def media_dir(data_dir: str) -> str:
    d = os.path.join(data_dir, "station", "media")
    os.makedirs(d, exist_ok=True)
    return d


def public_url(name: str) -> str:
    base = (os.getenv("STARNET_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    return f"{base}/media/{name}" if base else ""


FONTS = os.path.join(os.path.dirname(__file__), "fonts")   # Inter, SIL Open Font License (fonts/LICENSE-Inter.txt)


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(FONTS, "Inter-Bold.otf" if bold else "Inter-Regular.otf"), size)


def _wrap(draw, text: str, font, width: int) -> list[str]:
    lines = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for w in words:
            trial = f"{line} {w}".strip()
            if draw.textlength(trial, font=font) <= width:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = w
        if line:
            lines.append(line)
    return lines


def render_card(data_dir: str, brand: str, headline: str, points: Optional[list] = None, cta: str = "",
                palette: str = "default") -> str:
    """Draw the card, save it, return its file name."""
    from PIL import Image, ImageDraw
    top, bottom, accent, ink = PALETTES.get(palette, PALETTES["default"])
    img = Image.new("RGB", (W, H), top)
    d = ImageDraw.Draw(img)
    for y in range(H):   # vertical gradient
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    if palette == "solar":   # a sun in the corner, clear of the text
        d.ellipse((W - 230, -230, W + 230, 230), fill=(255, 196, 44))
        d.ellipse((W - 170, -170, W + 170, 170), fill=(255, 214, 102))
    m = 80
    d.rectangle((m, 120, m + 120, 132), fill=accent)
    d.text((m, 150), brand.upper(), font=_font(36, bold=True), fill=accent)
    size = 92 if len(headline) < 40 else 78 if len(headline) < 70 else 62
    y = 300
    for line in _wrap(d, headline, _font(size, bold=True), W - 2 * m)[:5]:
        d.text((m, y), line, font=_font(size, bold=True), fill=ink)
        y += int(size * 1.2)
    y += 50
    for p in (points or [])[:4]:
        lines = _wrap(d, str(p), _font(46), W - 2 * m - 60)[:2]
        d.ellipse((m, y + 14, m + 24, y + 38), fill=accent)
        for line in lines:
            d.text((m + 50, y), line, font=_font(46), fill=ink)
            y += 60
        y += 22
    if cta:
        box_h = 130
        d.rounded_rectangle((m, H - 80 - box_h, W - m, H - 80), radius=28, fill=accent)
        line = _wrap(d, cta, _font(46, bold=True), W - 2 * m - 60)[0]
        tw = d.textlength(line, font=_font(46, bold=True))
        d.text(((W - tw) / 2, H - 80 - box_h + 38), line, font=_font(46, bold=True), fill=top)
    name = secrets.token_hex(16) + ".jpg"
    img.save(os.path.join(media_dir(data_dir), name), "JPEG", quality=90)
    return name


def path_for(data_dir: str, name: str) -> Optional[str]:
    if not NAME_RE.match(name or ""):
        return None
    path = os.path.join(media_dir(data_dir), name)
    return path if os.path.exists(path) else None
