"""Lay out the Caregiver Care Binder (content.py) as print-ready PDFs: US Letter and A4."""
import os
import sys

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from content import C2, PAGES, SECTIONS

HERE = os.path.dirname(os.path.abspath(__file__))
for name in ("Regular", "Bold", "SemiBold", "Italic", "Medium"):
    pdfmetrics.registerFont(TTFont(f"Inter-{name}", os.path.join(HERE, f"Inter-{name}.ttf")))

INK = HexColor("#1f2a37")
MUTED = HexColor("#5b6675")
ACCENT = HexColor("#2f6f73")      # calm teal
SOFT = HexColor("#e8f1f1")
RULE = HexColor("#9aa6b2")
GRID = HexColor("#b9c3cc")
TOTAL = len(PAGES)
FOOT = f"Caregiver Care Binder · Page {{n}} of {TOTAL} · An organizer only. Not medical, legal or financial advice."


def wrap(text, font, size, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(t, font, size) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


class Page:
    def __init__(self, c, size, k=1.0):
        self.c, (self.W, self.H), self.k = c, size, k
        self.M = 46                                   # ~0.64 in margins: safe for home printers
        self.x0, self.x1 = self.M, self.W - self.M
        self.w = self.x1 - self.x0
        self.bottom = 52
        self.y = 0

    def s(self, v):
        return v * self.k

    # ---------------------------------------------------------------- frame
    def frame(self, n, code, title, instruction):
        c, sec = self.c, code.split(".")[0]
        c.setFillColor(ACCENT)
        c.rect(0, self.H - 30, self.W, 30, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Inter-SemiBold", 8.5)
        label = "SECTION " + sec + " · " + SECTIONS[sec] if sec not in ("0", "10") else SECTIONS[sec]
        c.drawString(self.x0, self.H - 19, label)
        c.setFont("Inter-Bold", 10)
        c.drawRightString(self.x1, self.H - 19.5, code)
        c.setFillColor(MUTED)
        c.setFont("Inter-Regular", 7)
        c.drawCentredString(self.W / 2, 24, FOOT.format(n=n))
        c.setStrokeColor(GRID)
        c.setLineWidth(0.5)
        c.line(self.x0, 36, self.x1, 36)
        self.y = self.H - 62
        c.setFillColor(INK)
        c.setFont("Inter-Bold", 19)
        c.drawString(self.x0, self.y, title)
        self.y -= 8
        if instruction:
            c.setFont("Inter-Italic", 9.5)
            c.setFillColor(MUTED)
            for line in wrap(instruction, "Inter-Italic", 9.5, self.w):
                self.y -= 13
                c.drawString(self.x0, self.y, line)
        self.y -= 18

    # ---------------------------------------------------------------- blocks
    def h(self, text):
        self.y -= self.s(6)
        self.c.setFillColor(ACCENT)
        self.c.setFont("Inter-Bold", self.s(11))
        for line in wrap(text, "Inter-Bold", self.s(11), self.w):
            self.c.drawString(self.x0, self.y, line)
            self.y -= self.s(14)

    def p(self, text):
        self.c.setFillColor(INK)
        self.c.setFont("Inter-Regular", self.s(9.5))
        for line in wrap(text, "Inter-Regular", self.s(9.5), self.w):
            self.c.drawString(self.x0, self.y, line)
            self.y -= self.s(13)
        self.y -= self.s(4)

    def f(self, labels):
        c = self.c
        for label in labels:
            step = self.s(21)
            c.setFillColor(INK)
            c.setFont("Inter-Medium", self.s(9.5))
            lw = pdfmetrics.stringWidth(label + ":" if label and not label.endswith(".") else label, "Inter-Medium", self.s(9.5)) if label else 0
            if label:
                c.drawString(self.x0, self.y, label + ("" if label.endswith(".") else ":"))
            c.setStrokeColor(RULE)
            c.setLineWidth(0.6)
            start = self.x0 + lw + 6 if label else self.x0
            c.line(start, self.y - 2.5, self.x1, self.y - 2.5)
            self.y -= step

    def box_mark(self, x, y, size):
        self.c.setStrokeColor(INK)
        self.c.setLineWidth(0.8)
        self.c.rect(x, y - 1, size, size, stroke=1, fill=0)

    def checks(self, label, options):
        c, size, fs = self.c, self.s(8.5), self.s(9.5)
        c.setFillColor(INK)
        c.setFont("Inter-Medium", fs)
        c.drawString(self.x0, self.y, label)
        x = self.x0 + pdfmetrics.stringWidth(label, "Inter-Medium", fs) + 10
        c.setFont("Inter-Regular", fs)
        for o in options:
            text = o.replace(": ______", ":")
            need = size + 4 + pdfmetrics.stringWidth(text, "Inter-Regular", fs) + (60 if o.endswith("______") else 14)
            if x + need > self.x1:
                self.y -= self.s(18)
                x = self.x0 + 14
            self.box_mark(x, self.y, size)
            c.drawString(x + size + 4, self.y, text)
            x += size + 4 + pdfmetrics.stringWidth(text, "Inter-Regular", fs)
            if o.endswith("______"):
                c.setStrokeColor(RULE)
                c.line(x + 4, self.y - 2.5, x + 54, self.y - 2.5)
                x += 60
            else:
                x += 14
        self.y -= self.s(21)

    def table(self, headers, rows, prefill):
        c = self.c
        fs = self.s(7.6)
        sw = pdfmetrics.stringWidth
        need = [max([sw(word, "Inter-SemiBold", fs) for word in h.split()] or [0]) + 10 for h in headers]
        if prefill:
            need[0] = max(need[0], max(sw(x, "Inter-Medium", self.s(8.3)) for x in prefill) + 12)
        weights = [max(1.0, min(3.2, len(h) / 9)) for h in headers]
        spare = self.w - sum(need)
        if spare >= 0:
            widths = [n + spare * wt / sum(weights) for n, wt in zip(need, weights)]
        else:
            widths = [n * self.w / sum(need) for n in need]
        head_lines = [wrap(h, "Inter-SemiBold", fs, wd - 6) if h else [""] for h, wd in zip(headers, widths)]
        hh = max(len(x) for x in head_lines) * fs * 1.2 + 8
        avail = self.y - self.bottom - self.reserve
        cap = self.s(30) if rows > 8 else self.s(46)   # few rows: give each more writing room
        rh = max(self.s(15), min(cap, (avail - hh) / rows))
        top = self.y + 4
        c.setFillColor(SOFT)
        c.rect(self.x0, top - hh, self.w, hh, stroke=0, fill=1)
        x = self.x0
        c.setFillColor(INK)
        for lines, wd in zip(head_lines, widths):
            ty = top - 5 - fs
            for line in lines:
                c.setFont("Inter-SemiBold", fs)
                c.drawString(x + 3, ty, line)
                ty -= fs * 1.2
            x += wd
        c.setStrokeColor(GRID)
        c.setLineWidth(0.6)
        bottom = top - hh - rh * rows
        c.rect(self.x0, bottom, self.w, top - bottom, stroke=1, fill=0)
        for i in range(rows + 1):
            yy = top - hh - rh * i
            c.line(self.x0, yy, self.x1, yy)
        x = self.x0
        for wd in widths[:-1]:
            x += wd
            c.line(x, top, x, bottom)
        if prefill:
            c.setFont("Inter-Medium", self.s(8.3))
            for i, label in enumerate(prefill):
                if label:
                    yy = top - hh - rh * i - rh / 2 - 3
                    c.drawString(self.x0 + 4, yy, label)
        self.y = bottom - self.s(18)

    def numbered(self, items, bullet=False):
        c, fs = self.c, self.s(9.5)
        for i, item in enumerate(items, 1):
            mark = "•" if bullet else f"{i}."
            c.setFillColor(ACCENT)
            c.setFont("Inter-Bold", fs)
            c.drawString(self.x0 + 2, self.y, mark)
            c.setFillColor(INK)
            c.setFont("Inter-Regular", fs)
            for line in wrap(item, "Inter-Regular", fs, self.w - 18):
                c.drawString(self.x0 + 18, self.y, line)
                self.y -= self.s(13)
            self.y -= self.s(2)
        self.y -= self.s(4)

    def box(self, title, text):
        c, fs = self.c, self.s(8.6)
        lines = wrap(text, "Inter-Regular", fs, self.w - 20)
        h = len(lines) * fs * 1.35 + (self.s(16) if title else 0) + 14
        self.y -= 2
        c.setFillColor(SOFT)
        c.setStrokeColor(ACCENT)
        c.setLineWidth(0.8)
        c.roundRect(self.x0, self.y - h + 10, self.w, h, 6, stroke=1, fill=1)
        yy = self.y - 2
        if title:
            c.setFillColor(ACCENT)
            c.setFont("Inter-Bold", self.s(10))
            c.drawString(self.x0 + 10, yy - 4, title)
            yy -= self.s(16)
        c.setFillColor(INK)
        c.setFont("Inter-Regular", fs)
        for line in lines:
            c.drawString(self.x0 + 10, yy - 4, line)
            yy -= fs * 1.35
        self.y -= h + 6

    def lines(self):
        c = self.c
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        while self.y > self.bottom + 10:
            c.line(self.x0, self.y, self.x1, self.y)
            self.y -= 22

    def render(self, blocks):
        # tables share the space left over after the other blocks; estimate what comes after each table
        for i, b in enumerate(blocks):
            self.reserve = self.after(blocks[i + 1:])
            kind = b[0]
            if kind == "f":
                self.f(b[1])
            elif kind == "c":
                self.checks(b[1], b[2])
            elif kind == "t":
                self.table(b[1], b[2], b[3])
            elif kind == "h":
                self.h(b[1])
            elif kind == "p":
                self.p(b[1])
            elif kind == "n":
                self.numbered(b[1])
            elif kind == "b":
                self.numbered(b[1], bullet=True)
            elif kind == "box":
                self.box(b[1], b[2])
            elif kind == "lines":
                self.lines()

    def after(self, blocks):
        h = 0
        for b in blocks:
            if b[0] == "f":
                h += len(b[1]) * self.s(21)
            elif b[0] == "c":
                h += self.s(21) + (self.s(18) if len(b[2]) > 4 else 0)
            elif b[0] in ("h",):
                h += self.s(20)
            elif b[0] == "p":
                h += self.s(17) * max(1, len(b[1]) // 95 + 1)
            elif b[0] == "t":
                h += self.s(15) * b[2] + 40
            elif b[0] == "box":
                h += 80
        return h


def cover(pg, n):
    c, W, H = pg.c, pg.W, pg.H
    c.setFillColor(ACCENT)
    c.rect(0, H * 0.52, W, H * 0.48, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Inter-SemiBold", 11)
    c.drawString(pg.x0, H - 70, "PRINTABLE ORGANIZER")
    c.setFont("Inter-Bold", 44)
    c.drawString(pg.x0, H * 0.73, "Caregiver")
    c.drawString(pg.x0, H * 0.73 - 50, "Care Binder")
    c.setFont("Inter-Italic", 15)
    c.drawString(pg.x0, H * 0.73 - 86, "Keep key care details in one place.")
    pg.y = H * 0.52 - 40
    pg.reserve = 0
    pg.f(["Prepared for (first name or initials)", "Kept by", "Phone", "Binder started (date)", "Last reviewed (date)"])
    pg.y -= 6
    pg.f(["If found, please return to", ""])
    c.setFont("Inter-Italic", 9)
    c.setFillColor(MUTED)
    c.drawString(pg.x0, pg.y + 4, "Please do not read further. This binder contains private information.")
    c.setFont("Inter-Regular", 7.5)
    for i, line in enumerate(wrap(C2, "Inter-Regular", 7.5, pg.w)):
        c.drawString(pg.x0, 70 - i * 10, line)
    c.setFont("Inter-Regular", 7)
    c.drawCentredString(W / 2, 24, FOOT.format(n=n))


def build(path, size):
    c = canvas.Canvas(path, pagesize=size, initialFontName="Inter-Regular")
    c.setTitle("Caregiver Care Binder")
    c.setAuthor("")
    c.setSubject("Printable caregiver organizer. An organizer only; not medical, legal or financial advice.")
    for n, (code, title, instruction, blocks) in enumerate(PAGES, 1):
        if blocks == "COVER":
            cover(Page(c, size), n)
        else:
            def fits(k):
                probe = canvas.Canvas(os.devnull, pagesize=size)
                pg = Page(probe, size, k)
                pg.frame(n, code, title, instruction)
                pg.render(blocks)
                return pg.y >= pg.bottom + 4
            # grow the page to use its height (more writing room), or shrink a crowded one a little
            k = 1.0
            if any(b[0] == "lines" for b in blocks):
                k = 1.0
            elif fits(1.0):
                while k < 1.35 and fits(round(k + 0.03, 2)):
                    k = round(k + 0.03, 2)
            else:
                while k > 0.8 and not fits(k):
                    k = round(k - 0.03, 2)
            pg = Page(c, size, k)
            pg.frame(n, code, title, instruction)
            pg.render(blocks)
            if pg.y < pg.bottom - 6:
                print(f"WARNING page {n} ({code}) overflows by {pg.bottom - pg.y:.0f}pt", file=sys.stderr)
        c.showPage()
    c.save()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "out")
    os.makedirs(out, exist_ok=True)
    build(os.path.join(out, "Caregiver-Care-Binder-US-Letter.pdf"), LETTER)
    build(os.path.join(out, "Caregiver-Care-Binder-A4.pdf"), A4)
    print("built")
