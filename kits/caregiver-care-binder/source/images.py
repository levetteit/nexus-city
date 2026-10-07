"""Listing images (5, 3000x2250) and pins (10, 1000x1500) built from the real binder pages.
Wording follows the compliance review's safe-phrasing list (Part F): no medical, outcome, endorsement,
security, 'fillable' or 'instant download' claims."""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = "/usr/share/fonts/opentype/inter"
TEAL, TEAL_D, CREAM, INK, MUTED = "#2f6f73", "#245659", "#f6f1e9", "#1f2a37", "#5b6675"


def font(w, size):
    return ImageFont.truetype(f"{FONTS}/Inter-{w}.otf", size)


def page(n):
    return Image.open(os.path.join(HERE, "pages110", f"p-{n:02d}.png")).convert("RGB")


def paste_page(canvas, n, center, width, angle=0):
    im = page(n)
    h = int(width * im.height / im.width)
    im = im.resize((width, h), Image.LANCZOS)
    pad = 60
    shadow = Image.new("RGBA", (width + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([pad, pad + 14, pad + width, pad + h + 14], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    card = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
    card.alpha_composite(shadow)
    card.paste(im, (pad, pad))
    if angle:
        card = card.rotate(angle, resample=Image.BICUBIC, expand=True)
    x, y = center[0] - card.width // 2, center[1] - card.height // 2
    canvas.alpha_composite(card, (x, y))


def text(d, xy, s, f, fill=INK, anchor="la", spacing=10):
    d.multiline_text(xy, s, font=f, fill=fill, anchor=anchor, spacing=spacing)


def wrap(d, s, f, width):
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return "\n".join(lines)


def base(w, h, color=CREAM):
    return Image.new("RGBA", (w, h), color)


def listing_images(out):
    W, H = 3000, 2250
    # 1. hero
    im = base(W, H)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 1250, H], fill=TEAL)
    text(d, (140, 330), "PRINTABLE ORGANIZER", font("SemiBold", 54), "#d7ecec")
    text(d, (140, 460), "Caregiver\nCare Binder", font("Bold", 170), "white", spacing=20)
    text(d, (140, 900), wrap(d, "Keep key care details in one place.", font("Medium", 72), 1000), font("Medium", 72), "white")
    for i, line in enumerate(["35 printable pages", "9 sections", "US Letter + A4"]):
        y = 1260 + i * 130
        d.ellipse([140, y + 18, 176, y + 54], fill="#f2c46d")
        text(d, (210, y), line, font("SemiBold", 70), "white")
    text(d, (140, 2050), "An organizer, not medical advice.", font("Regular", 46), "#d7ecec")
    paste_page(im, 9, (2420, 1150), 1050, angle=-6)
    paste_page(im, 5, (2080, 1110), 1050, angle=4)
    paste_page(im, 1, (1900, 1125), 1100)
    im.convert("RGB").save(os.path.join(out, "listing-1-cover.jpg"), quality=92)

    # 2. what's inside
    im = base(W, H)
    d = ImageDraw.Draw(im)
    text(d, (W // 2, 170), "What's inside", font("Bold", 130), INK, anchor="ma")
    text(d, (W // 2, 340), "35 pages in 9 sections, plus a cover, a how-to page and a review log", font("Medium", 60), MUTED, anchor="ma")
    secs = [("1", "Care Snapshot", "About them, daily routine"), ("2", "Care Team & Contacts", "Emergency info, providers, services"),
            ("3", "Medications", "List, changes, refills, daily checklist"), ("4", "Appointments", "Tracker, visit notes, questions to ask"),
            ("5", "Daily Care", "Care log, weekly summary, changes noticed"), ("6", "Documents Index", "Where insurance and papers are kept"),
            ("7", "Hand-Off", "Sheets for family or respite helpers"), ("8", "Family Task-Sharing", "Task grid, coverage calendar, meetings"),
            ("9", "Caregiver Self-Care", "Weekly check-in, breaks plan")]
    for i, (num, name, sub) in enumerate(secs):
        col, row = i % 3, i // 3
        x, y = 170 + col * 900, 560 + row * 520
        d.rounded_rectangle([x, y, x + 840, y + 460], 36, fill="white", outline="#d9e3e3", width=4)
        d.ellipse([x + 50, y + 50, x + 170, y + 170], fill=TEAL)
        text(d, (x + 110, y + 110), num, font("Bold", 64), "white", anchor="mm")
        text(d, (x + 50, y + 220), name, font("Bold", 62), INK)
        text(d, (x + 50, y + 310), wrap(d, sub, font("Regular", 46), 740), font("Regular", 46), MUTED)
    im.convert("RGB").save(os.path.join(out, "listing-2-whats-inside.jpg"), quality=92)

    # 3-4. spreads
    for name, pages_, title, sub in [
        ("listing-3-medications.jpg", (9, 13), "Medications, recorded as prescribed",
         "Copy each one exactly as on the label · change record · refill tracker · daily checklist"),
        ("listing-4-hand-off.jpg", (27, 30), "Easy hand-off sheet for family or respite helpers",
         "Today's essentials · routines & home · shift notes · family task-sharing grid")]:
        im = base(W, H)
        d = ImageDraw.Draw(im)
        text(d, (W // 2, 150), title, font("Bold", 110), INK, anchor="ma")
        text(d, (W // 2, 310), sub, font("Medium", 54), MUTED, anchor="ma")
        paste_page(im, pages_[0], (1060, 1330), 1150, angle=-2)
        paste_page(im, pages_[1], (1940, 1330), 1150, angle=2)
        im.convert("RGB").save(os.path.join(out, name), quality=92)

    # 5. how it works
    im = base(W, H)
    d = ImageDraw.Draw(im)
    text(d, (180, 200), "How it works", font("Bold", 130), INK)
    steps = [("Download the PDF", "US Letter and A4 versions are both included."),
             ("Print at home or at a print shop", "Fill it in by hand. Use pencil for anything that changes often."),
             ("Reprint the daily pages as needed", "Medication checklist, visit notes, care log, coverage calendar and more."),
             ("Keep it with you", "Bring it to appointments, and hand it over when someone else steps in.")]
    for i, (h1, h2) in enumerate(steps):
        y = 470 + i * 330
        d.ellipse([180, y, 300, y + 120], fill=TEAL)
        text(d, (240, y + 60), str(i + 1), font("Bold", 64), "white", anchor="mm")
        text(d, (360, y + 4), h1, font("Bold", 70), INK)
        text(d, (360, y + 96), wrap(d, h2, font("Regular", 48), 1330), font("Regular", 48), MUTED, spacing=6)
    d.rounded_rectangle([180, 1860, 1700, 2110], 30, fill="white", outline="#d9e3e3", width=4)
    text(d, (230, 1900), wrap(d, "An organizer, not medical, legal or financial advice. Once completed, this binder "
                             "contains private health information. Please store it securely.", font("Regular", 42), 1420),
         font("Regular", 42), MUTED)
    paste_page(im, 13, (2420, 1120), 900, angle=3)
    im.convert("RGB").save(os.path.join(out, "listing-5-how-it-works.jpg"), quality=92)


PINS = [
    (1, "Keep key care details in one place", "A printable caregiver binder"),
    (5, "Everything a helper needs, on one page", "Emergency contacts & quick info"),
    (27, "An easy hand-off sheet", "For family or respite helpers"),
    (14, "Track appointments in one place", "Plus visit notes for every appointment"),
    (9, "Record medications exactly as on the label", "A list, a change record and a refill tracker"),
    (30, "Share caregiving tasks with your family", "A task grid and a weekly coverage calendar"),
    (18, "Questions to ask at appointments", "A prompt page to copy onto your visit notes"),
    (24, "Know where the important papers are kept", "An index of locations, never the numbers"),
    (33, "A weekly check-in, just for you", "Caring for yourself while caring for them"),
    (2, "Printable caregiver organizer", "35 pages · US Letter + A4 · reprint as needed"),
]


def pins(out):
    W, H = 1000, 1500
    for i, (pg, head, sub) in enumerate(PINS, 1):
        dark = i % 2 == 0
        im = base(W, H, TEAL if dark else CREAM)
        d = ImageDraw.Draw(im)
        fg, mg = ("white", "#d7ecec") if dark else (INK, MUTED)
        f1 = font("Bold", 74)
        t1 = wrap(d, head, f1, 860)
        text(d, (70, 90), t1, f1, fg, spacing=8)
        y = 90 + (t1.count("\n") + 1) * 86 + 20
        f2 = font("Medium", 40)
        text(d, (70, y), wrap(d, sub, f2, 860), f2, mg)
        paste_page(im, pg, (W // 2, 960), 660, angle=-3 if i % 3 == 0 else 2 if i % 3 == 1 else 0)
        bar = TEAL_D if dark else TEAL
        d.rectangle([0, H - 110, W, H], fill=bar)
        text(d, (W // 2, H - 55), "Caregiver Care Binder · printable organizer", font("SemiBold", 34), "white", anchor="mm")
        im.convert("RGB").save(os.path.join(out, f"pin-{i:02d}.jpg"), quality=90)


if __name__ == "__main__":
    out = os.path.join(HERE, "out", "images")
    os.makedirs(out, exist_ok=True)
    listing_images(out)
    pins(out)
    print("images done")
