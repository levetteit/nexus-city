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
from ..env import env

W, H = 1080, 1350
NAME_RE = re.compile(r"^[a-f0-9]{32}\.(jpg|png)$")
PALETTES = {   # background top, background bottom, accent, text
    "solar": ((8, 28, 66), (14, 70, 140), (255, 196, 44), (255, 255, 255)),
    "default": ((10, 14, 34), (28, 40, 90), (94, 231, 255), (255, 255, 255)),
}


def media_dir(data_dir: str) -> str:
    d = os.path.join(data_dir, "station", "media")
    os.makedirs(d, exist_ok=True)
    return d


def public_url(name: str) -> str:
    base = (env("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
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


def _hex(color: str, fallback: tuple) -> tuple:
    c = (color or "").lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) == 6 else fallback
    except ValueError:
        return fallback


def render_design(data_dir: str, headline: str, subline: str = "", ink: str = "dark", accent: str = "",
                  size: tuple = (4500, 5400), background: bool = False) -> str:
    """A print-ready typographic design: transparent PNG (garments, mugs) or on paper white (posters).
    Original artwork from the crew's own words: no clip art, no fonts or marks we don't have rights to."""
    from PIL import Image, ImageDraw
    w, h = size
    main = (24, 24, 28) if ink == "dark" else (250, 248, 242)
    acc = _hex(accent, (214, 92, 60) if ink == "dark" else (255, 196, 44))
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255) if background else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = int(w * 0.08)
    words = headline.upper().strip() or "HELLO"
    # biggest headline that fits in at most 4 lines and the top 60% of the canvas
    for fs in range(int(min(w, h) * 0.4), 40, -int(max(4, min(w, h) * 0.006))):
        lines = _wrap(d, words, _font(fs, bold=True), w - 2 * m)
        if len(lines) <= 4 and len(lines) * fs * 1.12 <= h * 0.6 and all(d.textlength(x, font=_font(fs, bold=True)) <= w - 2 * m for x in lines):
            break
    sub_fs = max(40, int(fs * 0.32))
    sub_lines = _wrap(d, subline.strip(), _font(sub_fs), w - 2 * m)[:2] if subline.strip() else []
    rule_h = max(8, int(fs * 0.08))
    block = len(lines) * fs * 1.12 + (rule_h + fs * 0.5 if sub_lines else 0) + len(sub_lines) * sub_fs * 1.3
    y = (h - block) / 2 if size[0] >= size[1] else h * 0.12   # garments: high on the chest; wide items: centered
    for line in lines:
        tw = d.textlength(line, font=_font(fs, bold=True))
        d.text(((w - tw) / 2, y), line, font=_font(fs, bold=True), fill=main)
        y += fs * 1.12
    if sub_lines:
        y += fs * 0.2
        d.rectangle(((w - fs * 1.6) / 2, y, (w + fs * 1.6) / 2, y + rule_h), fill=acc)
        y += rule_h + fs * 0.3
        for line in sub_lines:
            tw = d.textlength(line, font=_font(sub_fs))
            d.text(((w - tw) / 2, y), line, font=_font(sub_fs), fill=acc)
            y += sub_fs * 1.3
    name = secrets.token_hex(16) + ".png"
    img.save(os.path.join(media_dir(data_dir), name), "PNG", optimize=True)
    return name


def path_for(data_dir: str, name: str) -> Optional[str]:
    if not NAME_RE.match(name or ""):
        return None
    path = os.path.join(media_dir(data_dir), name)
    return path if os.path.exists(path) else None
