"""Digital products the crew makes, sells and delivers on its own: the station's autonomous ventures.

  write     the Product Designer writes one product for the venture's niche (a guide, checklist, planner,
            workbook, template pack or printable), its sales page, its Etsy listing and its pin
  render    the PDF (letter size, cover + pages) and a 2:3 cover image, drawn with Pillow and Inter
  QA        Compliance & QA checks every word, like any post
  publish   a Stripe payment link that sends the buyer back to a verified download, the product's page on
            the station storefront (/shop/<slug>), an Etsy digital listing when Etsy is connected, and a
            pin when Pinterest is connected. NEXUS_DIGITAL_PER_DAY caps new products a day
  deliver   /shop/<slug>/thanks checks the Checkout Session with Stripe (paid, and from this product's
            link) before the download appears. The sale books itself into the treasury (and the webhook
            books it too; each sale is booked once)

Files: data/station/products/<random>.pdf (served only after a verified payment); covers in media/.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from ..env import env
from . import connectors, media
from .brain import Brain
from .store import Store

PER_DAY = int(env("DIGITAL_PER_DAY", "3"))
PRODUCT_EVERY = timedelta(hours=float(env("DIGITAL_EVERY_HOURS", "24")))   # per venture
MAX_PER_VENTURE = int(env("DIGITAL_MAX_PER_VENTURE", "6"))
OPEN = ("qa", "revise", "ready", "sending", "manual", "waiting_owner")
FORMATS = ["guide", "checklist", "planner", "workbook", "template_pack", "printable"]
STORE_NAME = env("STORE_NAME", "Nexus City Studio")
PAGE_W, PAGE_H = 1275, 1650   # US letter at 150 dpi
COVER = (1000, 1500)          # 2:3, the shape Pinterest and Etsy show best
FILE_RE = re.compile(r"^[a-f0-9]{32}\.pdf$")

PRODUCT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Product name, max 70 characters."},
        "subtitle": {"type": "string", "description": "One line: who it's for and the result, max 110 characters."},
        "format": {"type": "string", "enum": FORMATS},
        "audience": {"type": "string"},
        "sections": {"type": "array", "description": "8-24 sections; the whole product, finished and useful.", "items": {
            "type": "object",
            "properties": {
                "heading": {"type": "string"},
                "kind": {"type": "string", "enum": ["text", "bullets", "checklist", "table", "lines"],
                         "description": "text: paragraphs; bullets/checklist: items; table: columns + empty rows to fill in; lines: blank writing lines"},
                "text": {"type": "string", "description": "Paragraphs (text) or a short intro line (others). Blank lines separate paragraphs."},
                "items": {"type": "array", "items": {"type": "string"}},
                "columns": {"type": "array", "items": {"type": "string"}, "description": "table only, 2-6 columns"},
                "rows": {"type": "integer", "description": "table/lines: how many empty rows (1-30)"},
            },
            "required": ["heading", "kind", "text", "items", "columns", "rows"], "additionalProperties": False}},
        "price_usd": {"type": "number", "description": "Inside the band the niche's buyers pay."},
        "sales": {"type": "object", "properties": {
            "headline": {"type": "string"}, "subheadline": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "string"}, "description": "3-6 concrete things inside."},
            "faq": {"type": "array", "items": {"type": "object", "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                                               "required": ["q", "a"], "additionalProperties": False}}},
            "required": ["headline", "subheadline", "bullets", "faq"], "additionalProperties": False},
        "etsy": {"type": "object", "properties": {
            "title": {"type": "string", "description": "max 140 characters, buyer's search words first"},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "13 tags, max 20 characters each"}},
            "required": ["title", "description", "tags"], "additionalProperties": False},
        "pin": {"type": "object", "properties": {
            "title": {"type": "string", "description": "max 100 characters"},
            "description": {"type": "string", "description": "max 500 characters, with the search words"}},
            "required": ["title", "description"], "additionalProperties": False},
        "cover": {"type": "object", "properties": {
            "headline": {"type": "string", "description": "max 40 characters"}, "subline": {"type": "string"},
            "accent": {"type": "string", "description": "#RRGGBB"}},
            "required": ["headline", "subline", "accent"], "additionalProperties": False},
    },
    "required": ["title", "subtitle", "format", "audience", "sections", "price_usd", "sales", "etsy", "pin", "cover"],
    "additionalProperties": False,
}

RULES = ("Digital product rules, binding: the product must be complete and genuinely useful on its own (no filler, "
         "no 'coming soon'), original (never copy another seller's product, wording or layout), with no trademarks, "
         "characters, celebrities or quotes someone owns. No medical, legal or financial advice beyond general "
         "information; no income or results promises; no fake reviews, ratings or 'best seller' claims. Say it is a "
         "digital download (nothing is shipped). Plain, warm, specific writing.")


# ---------------------------------------------------------------------------- helpers
def products_dir(data_dir: str) -> str:
    d = os.path.join(data_dir, "station", "products")
    os.makedirs(d, exist_ok=True)
    return d


def _data_dir(store: Store) -> str:
    return os.path.dirname(store.dir)


def slugify(title: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "product") + "-" + secrets.token_hex(2)


def clean(p: dict) -> dict:
    tags = []
    for t in (p.get("etsy") or {}).get("tags") or []:
        t = re.sub(r"[^\w\s'-]", "", str(t)).strip()[:20]
        if t and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    secs = []
    for s in (p.get("sections") or [])[:30]:
        secs.append({"heading": str(s.get("heading", ""))[:120], "kind": s.get("kind") if s.get("kind") in
                     ("text", "bullets", "checklist", "table", "lines") else "text", "text": str(s.get("text", "")),
                     "items": [str(i) for i in (s.get("items") or [])][:40], "columns": [str(c) for c in (s.get("columns") or [])][:6],
                     "rows": max(1, min(30, int(s.get("rows") or 8)))})
    etsy = p.get("etsy") or {}
    pin = p.get("pin") or {}
    cover = p.get("cover") or {}
    return {**p, "title": str(p.get("title", ""))[:70].strip(), "subtitle": str(p.get("subtitle", ""))[:110].strip(),
            "format": p.get("format") if p.get("format") in FORMATS else "guide", "sections": secs,
            "price_usd": round(min(97.0, max(3.0, float(p.get("price_usd") or 0))), 2),
            "etsy": {"title": str(etsy.get("title") or p.get("title", ""))[:140], "description": str(etsy.get("description", "")),
                     "tags": tags[:13]},
            "pin": {"title": str(pin.get("title") or p.get("title", ""))[:100], "description": str(pin.get("description", ""))[:500]},
            "cover": {"headline": str(cover.get("headline") or p.get("title", ""))[:40], "subline": str(cover.get("subline", ""))[:80],
                      "accent": str(cover.get("accent", ""))}}


# ---------------------------------------------------------------------------- rendering
def render_cover(data_dir: str, p: dict) -> str:
    """2:3 cover (JPEG in media/, public): Pinterest, Etsy and the sales page show it."""
    from PIL import Image, ImageDraw
    w, h = COVER
    acc = media._hex(p["cover"]["accent"], (94, 120, 255))
    img = Image.new("RGB", (w, h), (247, 244, 238))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, int(h * 0.62)), fill=acc)
    m = 80
    d.text((m, 70), STORE_NAME.upper(), font=media._font(30, bold=True), fill=(255, 255, 255))
    d.text((m, 112), p["format"].replace("_", " ").upper() + " · PDF", font=media._font(28), fill=(255, 255, 255))
    for fs in range(120, 40, -4):
        lines = media._wrap(d, p["cover"]["headline"].upper(), media._font(fs, bold=True), w - 2 * m)
        if len(lines) <= 4:
            break
    y = int(h * 0.62) - len(lines) * int(fs * 1.12) - 60
    for line in lines:
        d.text((m, y), line, font=media._font(fs, bold=True), fill=(255, 255, 255))
        y += int(fs * 1.12)
    y = int(h * 0.62) + 60
    for line in media._wrap(d, p["cover"]["subline"] or p["subtitle"], media._font(44), w - 2 * m)[:3]:
        d.text((m, y), line, font=media._font(44), fill=(30, 30, 36))
        y += 60
    # a peek at the inside: three faint ruled lines and a checkbox, so it reads as a usable product
    y = h - 300
    for i in range(3):
        d.rounded_rectangle((m, y + i * 70, m + 36, y + i * 70 + 36), radius=6, outline=acc, width=4)
        d.line((m + 60, y + i * 70 + 32, w - m, y + i * 70 + 32), fill=(190, 186, 178), width=3)
    d.text((m, h - 70), "Instant digital download", font=media._font(30, bold=True), fill=acc)
    name = secrets.token_hex(16) + ".jpg"
    img.save(os.path.join(media.media_dir(data_dir), name), "JPEG", quality=90)
    return name


def render_pdf(data_dir: str, p: dict) -> tuple[str, int]:
    """The product itself. Returns (file name, pages)."""
    from PIL import Image, ImageDraw
    acc = media._hex(p["cover"]["accent"], (94, 120, 255))
    ink, soft = (28, 28, 34), (150, 146, 140)
    m, top, bottom = 110, 120, PAGE_H - 120
    pages: list = []

    def new_page():
        img = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
        pages.append(img)
        return img, ImageDraw.Draw(img), top

    # cover page
    img, d, _ = new_page()
    d.rectangle((0, 0, PAGE_W, 520), fill=acc)
    y = 170
    for line in media._wrap(d, p["title"], media._font(78, bold=True), PAGE_W - 2 * m)[:3]:
        d.text((m, y), line, font=media._font(78, bold=True), fill=(255, 255, 255))
        y += 92
    y = 600
    for line in media._wrap(d, p["subtitle"], media._font(38), PAGE_W - 2 * m)[:3]:
        d.text((m, y), line, font=media._font(38), fill=ink)
        y += 52
    d.text((m, PAGE_H - 180), f"{STORE_NAME} · for personal use", font=media._font(26), fill=soft)

    img, d, y = new_page()

    def room(need: int):
        nonlocal img, d, y
        if y + need > bottom:
            img, d, y = new_page()

    for s in p["sections"]:
        room(140)
        for line in media._wrap(d, s["heading"], media._font(44, bold=True), PAGE_W - 2 * m)[:2]:
            d.text((m, y), line, font=media._font(44, bold=True), fill=ink)
            y += 56
        d.rectangle((m, y + 4, m + 90, y + 10), fill=acc)
        y += 34
        for para in [x for x in s["text"].split("\n") if x.strip()]:
            for line in media._wrap(d, para.strip(), media._font(30), PAGE_W - 2 * m):
                room(44)
                d.text((m, y), line, font=media._font(30), fill=ink)
                y += 42
            y += 14
        if s["kind"] in ("bullets", "checklist"):
            for item in s["items"]:
                lines = media._wrap(d, item, media._font(30), PAGE_W - 2 * m - 60)
                room(44 * len(lines) + 12)
                if s["kind"] == "checklist":
                    d.rounded_rectangle((m, y + 4, m + 30, y + 34), radius=5, outline=acc, width=3)
                else:
                    d.ellipse((m + 6, y + 13, m + 20, y + 27), fill=acc)
                for line in lines:
                    d.text((m + 56, y), line, font=media._font(30), fill=ink)
                    y += 42
                y += 12
        elif s["kind"] == "table" and s["columns"]:
            cols = s["columns"]
            cw = (PAGE_W - 2 * m) / len(cols)
            room(64 + 56)
            d.rectangle((m, y, PAGE_W - m, y + 56), fill=acc)
            for i, c in enumerate(cols):
                d.text((m + i * cw + 12, y + 12), media._wrap(d, c, media._font(26, bold=True), cw - 20)[0] if c else "",
                       font=media._font(26, bold=True), fill=(255, 255, 255))
            y += 56
            for _ in range(s["rows"]):
                room(54)
                d.rectangle((m, y, PAGE_W - m, y + 54), outline=(205, 200, 192), width=2)
                for i in range(1, len(cols)):
                    d.line((m + i * cw, y, m + i * cw, y + 54), fill=(205, 200, 192), width=2)
                y += 54
        elif s["kind"] == "lines":
            for _ in range(s["rows"]):
                room(56)
                y += 50
                d.line((m, y, PAGE_W - m, y), fill=(205, 200, 192), width=2)
        y += 40
    for i, pg in enumerate(pages[1:], start=2):
        dd = ImageDraw.Draw(pg)
        dd.text((m, PAGE_H - 80), f"{p['title'][:60]}  ·  {i}", font=media._font(22), fill=soft)
    name = secrets.token_hex(16) + ".pdf"
    pages[0].save(os.path.join(products_dir(data_dir), name), "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return name, len(pages)


def pdf_path(data_dir: str, name: str) -> Optional[str]:
    if not FILE_RE.match(name or ""):
        return None
    path = os.path.join(products_dir(data_dir), name)
    return path if os.path.exists(path) else None


# ---------------------------------------------------------------------------- the crew's side
def ventures(store: Store) -> list[dict]:
    return [v for v in store.all("ventures") if v.get("autonomous") and v["stage"] not in ("paused", "killed")]


def due(store: Store, v: dict, now: datetime) -> bool:
    acts = [a for a in store.find("actions", kind="digital.publish") if a.get("venture") == v["id"]]
    if any(a["status"] in OPEN for a in acts):
        return False   # one product in the works per venture at a time
    if sum(1 for p in store.all("products") if p["venture"] == v["id"] and p.get("active")) >= MAX_PER_VENTURE:
        return False   # enough on the shelf: the War Room decides what's next
    last = v.get("product_at")
    return not last or now - datetime.fromisoformat(last) >= PRODUCT_EVERY


def create(store: Store, brain: Brain, v: dict, now: datetime) -> dict:
    """The Product Designer writes and renders the venture's next product, then files it for QA."""
    from .crew import AGENT_RULES, lessons_text
    opp = store.get("opportunities", v.get("opportunity") or "") or {}
    have = [p["title"] for p in store.all("products") if p["venture"] == v["id"]]
    store.update("ventures", v["id"], {"product_at": now.isoformat()}, "A-DSGN", "writing the next product", kind="venture.working")
    store.update("agents", "A-DSGN", {"status": "WORKING", "current_task": f"New product: {v['name'][:50]}"}, "A-DSGN",
                 "writing a product", kind="agent.state")
    out = brain.structured("A-DSGN", AGENT_RULES + " You are the Product Designer of an autonomous venture. " + RULES
                           + lessons_text(store, "Product Creation"), (
        f"VENTURE: {v['name']}\nNICHE AND EVIDENCE: {json.dumps({k: opp.get(k) for k in ('summary', 'evidence', 'price_point', 'platform_restrictions', 'risks')})}\n"
        f"FORMAT TO MAKE: {v.get('product_format') or opp.get('product_format') or 'pick the best fit'}\n"
        f"ALREADY MADE (make something different that the same buyer also wants):\n" + ("\n".join(f"- {t}" for t in have) or "(nothing yet)")
        + "\n\nWrite the complete product, its sales page, its Etsy listing and its Pinterest pin."), PRODUCT_SCHEMA,
        venture=v["id"])
    p = clean(out)
    dd = _data_dir(store)
    p["cover_image"] = render_cover(dd, p)
    p["pdf"], p["pages"] = render_pdf(dd, p)
    a = store.create("actions", {"kind": "digital.publish", "agent": "A-DSGN", "venture": v["id"], "payload": p, "status": "qa",
                                 "qa": None, "revisions": 0, "result": None, "why": f"{p['format']}: {p['subtitle']}"[:300]},
                     "A-DSGN", f"digital.publish: {p['title']}")
    store.event("digital.made", "A-DSGN", f"made '{p['title']}' ({p['pages']} pages) for {v['name']}", ref=v["id"])
    store.update("agents", "A-DSGN", {"status": "COMPLETED", "current_task": None, "last_output": p["title"]}, "A-DSGN",
                 "product filed for QA", kind="agent.state")
    return a


def rerender(store: Store, payload: dict) -> dict:
    p = clean(payload)
    dd = _data_dir(store)
    p["cover_image"] = render_cover(dd, p)
    p["pdf"], p["pages"] = render_pdf(dd, p)
    return p


def store_url(slug: str = "") -> str:
    base = media.public_url("x").rsplit("/media/", 1)[0]
    return f"{base}/shop" + (f"/{slug}" if slug else "")


def publish(store: Store, action: dict) -> dict:
    """Put a QA-passed product on sale. Called by actions.dispatch. Raises ConnectorError."""
    p = rerender(store, action["payload"])   # exactly the words QA passed
    v = store.get("ventures", action["venture"]) or {}
    slug = slugify(p["title"])
    url = store_url(slug)
    link = connectors.stripe_payment_link(p["title"], p["subtitle"], p["price_usd"], action["venture"],
                                          redirect=f"{url}/thanks?session_id={{CHECKOUT_SESSION_ID}}", extra={"nexus_product": slug},
                                          idempotency_key=action["id"])
    rec = store.create("products", {"venture": action["venture"], "slug": slug, "title": p["title"], "subtitle": p["subtitle"],
                                    "format": p["format"], "price_usd": p["price_usd"], "pdf": p["pdf"], "pages": p["pages"],
                                    "cover": p["cover_image"], "sales_page": p["sales"], "checkout_url": link["url"],
                                    "payment_link": link["payment_link"], "url": url, "action": action["id"], "active": True,
                                    "etsy": None, "pin": None}, "A-DSGN", f"on sale: {p['title']} (${p['price_usd']:.2f})")
    out = {"product": rec["id"], "url": url, "checkout": link["url"]}
    dd = _data_dir(store)
    if connectors.etsy_connected() and "etsy_digital" in (v.get("rails") or ["etsy_digital"]):
        try:
            with open(pdf_path(dd, p["pdf"]), "rb") as f:
                pdf = f.read()
            with open(media.path_for(dd, p["cover_image"]), "rb") as f:
                cover = f.read()
            desc = p["etsy"]["description"].strip() + ("\n\nInstant digital download (PDF). Nothing is shipped. "
                                                       "Made by our studio with the help of AI tools. For personal use.")
            et = connectors.etsy_digital_listing(p["etsy"]["title"], desc, p["etsy"]["tags"], p["price_usd"], pdf,
                                                 f"{slug}.pdf", cover, f"{slug}.jpg")
            store.update("products", rec["id"], {"etsy": et}, "A-SHOP", f"on Etsy too: {et['url']}", kind="product.etsy")
            out["etsy"] = et
        except connectors.ConnectorError as exc:
            out["etsy_error"] = str(exc)[:200]
            store.event("product.etsy_failed", "A-SHOP", f"Etsy listing for {p['title']} failed: {exc}"[:240], ref=action["venture"],
                        severity="WARNING")
    if connectors.pinterest_connected():
        try:
            pin = connectors.pinterest_pin(v.get("name", STORE_NAME), p["pin"]["title"], p["pin"]["description"], url,
                                           media.public_url(p["cover_image"]), p["title"])
            store.update("products", rec["id"], {"pin": {"id": pin.get("id")}}, "A-006", "pinned on Pinterest", kind="product.pinned")
            out["pin"] = pin.get("id")
        except connectors.ConnectorError as exc:
            out["pin_error"] = str(exc)[:200]
            store.event("product.pin_failed", "A-006", f"pin for {p['title']} failed: {exc}"[:240], ref=action["venture"],
                        severity="WARNING")
    store.event("digital.published", "A-DSGN", f"on sale: {p['title']} (${p['price_usd']:.2f})"
                + (" + Etsy" if out.get("etsy") else "") + (" + pin" if out.get("pin") else ""), ref=action["venture"])
    return out


def retire(store: Store, venture: str) -> int:
    """A killed venture's products come off sale (storefront and Etsy)."""
    n = 0
    for p in store.all("products"):
        if p["venture"] == venture and p.get("active"):
            if (p.get("etsy") or {}).get("listing_id") and connectors.etsy_connected():
                try:
                    connectors.etsy_deactivate(p["etsy"]["listing_id"])
                except connectors.ConnectorError:
                    pass
            store.update("products", p["id"], {"active": False}, "A-001", "off sale: venture closed")
            n += 1
    return n


# ---------------------------------------------------------------------------- the buyer's side
def find(store: Store, slug: str) -> Optional[dict]:
    return next((p for p in store.all("products") if p["slug"] == slug), None)


def verify_purchase(store: Store, product: dict, session_id: str) -> Optional[dict]:
    """The Checkout Session, if it's a paid purchase of this product. Cached once verified."""
    if not re.match(r"^cs_[A-Za-z0-9_]{10,200}$", session_id or ""):
        return None
    doc = store.load_doc("purchases.json") or {}
    if doc.get(session_id) == product["slug"]:
        return {"id": session_id, "cached": True}
    try:
        sess = connectors.stripe_request("GET", f"/checkout/sessions/{session_id}")
    except connectors.ConnectorError:
        return None
    if sess.get("payment_status") != "paid" or sess.get("payment_link") != product["payment_link"]:
        return None
    with store.lock:
        doc = store.load_doc("purchases.json") or {}
        doc[session_id] = product["slug"]
        store.save_doc("purchases.json", doc)
    return sess


def sales(treasury, product_id_or_slug: str) -> int:
    return sum(1 for e in treasury.entries if e["kind"] == "income" and product_id_or_slug in (e.get("note") or ""))


def summary(store: Store, treasury) -> dict:
    prods = sorted(store.all("products"), key=lambda p: p["created_at"], reverse=True)
    acts = store.find("actions", kind="digital.publish")
    return {"rails": connectors.rails(), "per_day": PER_DAY, "store_url": store_url() if media.public_url("x") else "",
            "pipeline": {s: sum(1 for a in acts if a["status"] == s) for s in OPEN + ("sent", "rejected", "failed")},
            "products": [{"id": p["id"], "venture": p["venture"], "title": p["title"], "format": p["format"], "price_usd": p["price_usd"],
                          "url": p["url"], "cover": p["cover"], "active": p.get("active"), "pages": p.get("pages"),
                          "etsy": (p.get("etsy") or {}).get("url"), "pinned": bool(p.get("pin")), "sales": sales(treasury, p["slug"]),
                          "created_at": p["created_at"]} for p in prods[:60]],
            "in_works": [{"id": a["id"], "venture": a["venture"], "title": a["payload"].get("title"), "status": a["status"],
                          "cover": a["payload"].get("cover_image"), "price_usd": a["payload"].get("price_usd")}
                         for a in acts if a["status"] in OPEN][:20]}


# ---------------------------------------------------------------------------- pages
CSS = """:root{--bg:#f7f4ee;--ink:#1c1c22;--muted:#6b6862;--acc:#3a5bff;--card:#fff;--edge:#e6e1d8}
@media (prefers-color-scheme:dark){:root{--bg:#121318;--ink:#f1efe9;--muted:#a3a09a;--card:#1b1d24;--edge:#2b2e38}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Inter,system-ui,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:24px 16px 60px}a{color:var(--acc)}header{display:flex;justify-content:space-between;
align-items:center;margin-bottom:22px}header b{letter-spacing:2px;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:28px}
@media(max-width:720px){.grid{grid-template-columns:1fr}}.cover{width:100%;border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.15)}
h1{font-size:30px;line-height:1.2;margin:4px 0 8px}.sub{color:var(--muted);font-size:18px}.price{font-size:28px;font-weight:800;margin:16px 0}
.buy{display:inline-block;background:var(--acc);color:#fff;text-decoration:none;font-weight:700;padding:14px 26px;border-radius:12px}
ul{padding-left:20px}.card{background:var(--card);border:1px solid var(--edge);border-radius:14px;padding:16px;margin-top:18px}
.small{font-size:13px;color:var(--muted)}.list{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:18px}
.list a{text-decoration:none;color:var(--ink)}.list img{width:100%;border-radius:10px}"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class='wrap'><header><b>"
            f"<a href='/shop' style='color:inherit;text-decoration:none'>{html.escape(STORE_NAME.upper())}</a></b></header>{body}"
            "<p class='small' style='margin-top:40px'><a href='/shop/privacy'>Privacy policy</a> · Digital downloads (PDF), for personal use. Nothing is shipped. Made by our studio "
            "with the help of AI tools. Payments by Stripe; we don't store your card. If a file doesn't open or isn't as described, "
            f"reply to your Stripe receipt within 14 days for a refund.</p></div></body></html>")


def page_privacy() -> str:
    contact = env("STORE_EMAIL", "").strip()
    reach = (f"email <a href='mailto:{html.escape(contact)}'>{html.escape(contact)}</a>" if contact
             else "reply to the receipt Stripe emails you after a purchase")
    return _page(f"Privacy policy · {STORE_NAME}", f"""<h1>Privacy policy</h1><p class='small'>{html.escape(STORE_NAME)} · last updated October 6, 2026</p>
<h3>What we collect</h3><p>Nothing directly. When you buy, Stripe processes your payment and receives your email address and card
details under <a href='https://stripe.com/privacy'>Stripe's privacy policy</a>. We receive the purchase record from Stripe (what you
bought, the amount, your email) so we can deliver your download and handle refunds. We never see or store your card number.</p>
<h3>Cookies and tracking</h3><p>This store sets no advertising or tracking cookies.</p>
<h3>Our own social and marketplace accounts</h3><p>We publish our products to our own Etsy shop and our own Pinterest account
through their official APIs. Those connections act only on our own accounts: we don't read, collect or store anyone else's
Pinterest or Etsy data.</p>
<h3>How long we keep it</h3><p>Purchase records are kept as long as tax and accounting rules require.</p>
<h3>Your choices</h3><p>To ask what we hold about you, or to have it deleted where the law allows, {reach}.</p>""")


def page_index(store: Store) -> str:
    live = [p for p in store.all("products") if p.get("active")]
    cards = "".join(f"<a href='/shop/{html.escape(p['slug'])}'><img src='/media/{html.escape(p['cover'])}' alt=''>"
                    f"<div><b>{html.escape(p['title'])}</b></div><div class='small'>${p['price_usd']:.2f}</div></a>" for p in live)
    return _page(STORE_NAME, f"<h1>{html.escape(STORE_NAME)}</h1><p class='sub'>Printable planners, checklists and guides.</p>"
                 + (f"<div class='list'>{cards}</div>" if cards else "<p>New products are on their way.</p>"))


def page_product(p: dict) -> str:
    sp = p.get("sales_page") or {}
    bullets = "".join(f"<li>{html.escape(b)}</li>" for b in sp.get("bullets", []))
    faq = "".join(f"<p><b>{html.escape(f['q'])}</b><br>{html.escape(f['a'])}</p>" for f in sp.get("faq", []))
    buy = (f"<a class='buy' href='{html.escape(p['checkout_url'])}'>Buy now · ${p['price_usd']:.2f}</a>" if p.get("active")
           else "<p><b>This product is no longer available.</b></p>")
    return _page(p["title"], f"<div class='grid'><div><img class='cover' src='/media/{html.escape(p['cover'])}' alt='{html.escape(p['title'])}'></div>"
                 f"<div><div class='small'>{html.escape(p['format'].replace('_', ' ').upper())} · PDF · {p.get('pages', '')} pages</div>"
                 f"<h1>{html.escape(sp.get('headline') or p['title'])}</h1><p class='sub'>{html.escape(sp.get('subheadline') or p['subtitle'])}</p>"
                 f"<ul>{bullets}</ul><div class='price'>${p['price_usd']:.2f}</div>{buy}"
                 "<p class='small'>Download right after checkout. Nothing is shipped.</p>"
                 + (f"<p class='small'>{html.escape(p['notice'])}</p>" if p.get("notice") else "") + "</div></div>"
                 + (f"<div class='card'><h3>Questions</h3>{faq}</div>" if faq else ""))


def page_thanks(p: dict, session_id: str, ok: bool) -> str:
    if not ok:
        return _page("Checking your payment", "<h1>We couldn't confirm this payment yet</h1><p>If you just paid, give it a minute "
                     "and refresh this page. If it still doesn't work, reply to your Stripe receipt and we'll send the file.</p>")
    files = p.get("files") or [{"pdf": p["pdf"], "label": ""}]
    links = "".join(
        f"<p><a class='buy' href='/shop/{html.escape(p['slug'])}/download?session_id={html.escape(session_id)}&file={i}'>"
        f"Download the PDF{' (' + html.escape(f['label']) + ')' if len(files) > 1 and f.get('label') else ''}</a></p>"
        for i, f in enumerate(files))
    return _page("Thank you", f"<h1>Thank you!</h1><p class='sub'>Your copy of <b>{html.escape(p['title'])}</b> is ready.</p>"
                 + links + "<p class='small'>Bookmark this page: the link keeps working for your purchase.</p>")
