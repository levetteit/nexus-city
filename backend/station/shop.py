"""The Etsy shop, run by the crew end to end: print-on-demand through Printify.

  research   Market Research finds what's selling on Etsy right now (web search: best-sellers, the shops
             selling them, prices, reviews) and the Etsy Shop Manager turns it into product briefs
  design     the Product Designer renders each design from the brief: original typographic artwork,
             print-ready PNG (no clip art, no one else's text, marks or characters)
  QA         every listing goes through Compliance & QA like any post: trademarks, copyrighted phrases,
             claims, Etsy's rules. Fails get one revision, then they're dropped
  list       the Shop Manager creates the product in Printify (priced above cost, never below), and
             Printify publishes it to the Etsy shop. NEXUS_SHOP_LISTINGS_PER_DAY caps new listings
             (each costs $0.20 on Etsy)
  orders     every 6 hours the Shop Manager reads Printify's orders: units, retail sales, which listing

Competition research is for finding the niche, format and price that sell. Our listings are never
copies: copying another shop's design, wording or photos is infringement, and Etsy takes the listings
and the shop down for it. The crew sells in the same niches with its own designs.

Sales aren't booked into the treasury automatically (only you and Stripe book income): record Etsy
deposits in Finance as they land.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..env import env
from . import connectors, media
from .brain import Brain
from .store import Store, now_iso

VENTURE = "V-ETSY"
LISTINGS_PER_DAY = int(env("SHOP_LISTINGS_PER_DAY", "2"))
RESEARCH_EVERY = timedelta(hours=float(env("SHOP_RESEARCH_HOURS", "48")))
ORDERS_EVERY = timedelta(hours=6)
BRIEFS_PER_RUN = 4
MIN_PROFIT_CENTS = int(env("SHOP_MIN_PROFIT_CENTS", "400"))   # per item, after cost and Etsy's fees
ETSY_FEES = (0.065 + 0.03, 25 + 20)   # transaction + payment processing (share of price), processing + listing fee (cents)
OPEN = ("qa", "revise", "ready", "manual", "waiting_owner")
DISCLOSURE = ("\n\nDesigned by our studio with the help of AI tools. Made to order and shipped by our print partner, "
              "so please allow production time.")

APPAREL_SIZES = ["S", "M", "L", "XL", "2XL"]
PRODUCT_TYPES = {   # what the crew can list, with the Printify catalog names to look for (first match wins)
    "tshirt": {"key": "tshirt", "blueprints": ["Unisex Jersey Short Sleeve Tee", "Unisex Heavy Cotton Tee"],
               "size": (4500, 5400), "sizes": APPAREL_SIZES,
               "colors": {"dark": ["White", "Natural", "Ash"], "light": ["Black", "Navy", "Dark Grey Heather"]}},
    "sweatshirt": {"key": "sweatshirt", "blueprints": ["Unisex Heavy Blend™ Crewneck Sweatshirt", "Crewneck Sweatshirt"],
                   "size": (4500, 5400), "sizes": APPAREL_SIZES,
                   "colors": {"dark": ["White", "Sand", "Ash"], "light": ["Black", "Navy", "Dark Heather"]}},
    "hoodie": {"key": "hoodie", "blueprints": ["Unisex Heavy Blend™ Hooded Sweatshirt", "Hooded Sweatshirt"],
               "size": (4500, 5400), "sizes": APPAREL_SIZES,
               "colors": {"dark": ["White", "Sand", "Ash"], "light": ["Black", "Navy", "Dark Heather"]}},
    "mug": {"key": "mug", "blueprints": ["Ceramic Mug (11oz)", "Ceramic Mug 11oz", "Mug 11oz"], "size": (2700, 1050),
            "ink": "dark", "colors": {}},
    "poster": {"key": "poster", "blueprints": ["Matte Vertical Posters", "Rolled Posters"], "size": (4800, 6000),
               "ink": "dark", "background": True, "colors": {}},
}

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "market_notes": {"type": "string", "description": "What is selling now and the evidence, 3-6 sentences."},
        "products": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "niche": {"type": "string"},
                "product_type": {"type": "string", "enum": list(PRODUCT_TYPES)},
                "competitors": {"type": "array", "description": "Up to 3 listings that prove demand.", "items": {
                    "type": "object",
                    "properties": {"shop": {"type": "string"}, "listing": {"type": "string"}, "price_usd": {"type": "number"},
                                   "url": {"type": "string"}, "why_it_sells": {"type": "string"}},
                    "required": ["shop", "listing", "price_usd", "url", "why_it_sells"], "additionalProperties": False}},
                "our_angle": {"type": "string", "description": "How ours is different and better, not a copy."},
                "headline": {"type": "string", "description": "The main printed words, our own, max 40 characters."},
                "subline": {"type": "string", "description": "Optional smaller line, max 60 characters, or empty."},
                "ink": {"type": "string", "enum": ["dark", "light"], "description": "dark ink for light products, light ink for dark ones"},
                "accent": {"type": "string", "description": "Accent color as #RRGGBB."},
                "title": {"type": "string", "description": "Etsy listing title, max 140 characters, buyer's search words first."},
                "description": {"type": "string", "description": "Etsy description: what it is, who it's for, sizing/care notes."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Exactly 13 Etsy tags, each max 20 characters."},
                "price_usd": {"type": "number", "description": "Retail price in the band the competitors prove."},
            },
            "required": ["niche", "product_type", "competitors", "our_angle", "headline", "subline", "ink", "accent", "title",
                         "description", "tags", "price_usd"],
            "additionalProperties": False}},
    },
    "required": ["market_notes", "products"],
    "additionalProperties": False,
}

RULES = ("Etsy print-on-demand rules, binding: ORIGINAL designs only. Use competitors to learn the niche, the "
         "product, the price band and the buyer's search words; never copy their design, wording, photos or "
         "layout. No trademarks or brand names, no sports teams or leagues, no characters, celebrities, real "
         "people, song lyrics, film/TV/book quotes or catchphrases someone owns, no 'Disney-style' or 'inspired by' "
         "a brand. No medical, political-hate or adult content. No claims like 'best seller' or 'official'. Text-"
         "based designs (wordplay, occupations, hobbies, pets, seasons, milestones, personalization-free gifts) are "
         "what we can print well.")


def min_price(cost_cents: int) -> int:
    """Lowest price (cents) that covers the product cost, Etsy's fees and the minimum profit, ending in .99."""
    share, fixed = ETSY_FEES
    raw = (cost_cents + fixed + MIN_PROFIT_CENTS) / (1 - share)
    return int(math.ceil(raw / 100.0) * 100 - 1)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def clean(p: dict) -> dict:
    """Etsy's hard limits and our defaults, enforced in code rather than trusted to the model."""
    pt = PRODUCT_TYPES.get(p.get("product_type"), PRODUCT_TYPES["tshirt"])
    tags = []
    for t in p.get("tags") or []:
        t = re.sub(r"[^\w\s'-]", "", str(t)).strip()[:20]
        if t and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    return {**p, "product_type": pt["key"], "title": (p.get("title") or p.get("headline", ""))[:140].strip(),
            "headline": (p.get("headline") or "")[:40].strip(), "subline": (p.get("subline") or "")[:60].strip(),
            "ink": pt.get("ink") or (p.get("ink") if p.get("ink") in ("dark", "light") else "dark"),
            "tags": tags[:13], "price_usd": round(max(5.0, float(p.get("price_usd") or 0)), 2)}


def render(data_dir: str, p: dict) -> str:
    pt = PRODUCT_TYPES[p["product_type"]]
    return media.render_design(data_dir, p["headline"], p.get("subline", ""), p["ink"], p.get("accent", ""),
                               pt["size"], pt.get("background", False))


def listings(store: Store) -> list[dict]:
    return [a for a in store.find("actions", kind="shop.listing")]


def research_due(store: Store, cfg: dict, now: datetime) -> bool:
    v = store.get("ventures", VENTURE)
    if not v or v["stage"] in ("paused", "killed"):
        return False
    if sum(1 for a in listings(store) if a["status"] in OPEN) >= max(2, LISTINGS_PER_DAY * 2):
        return False   # enough in the pipeline: list those first
    last = cfg.get("shop_research_at")
    return not last or now - datetime.fromisoformat(last) >= RESEARCH_EVERY


def orders_due(cfg: dict, now: datetime) -> bool:
    last = cfg.get("shop_orders_at")
    return connectors.printify_configured() and (not last or now - datetime.fromisoformat(last) >= ORDERS_EVERY)


def research(store: Store, brain: Brain, now: datetime) -> dict:
    """Find what sells, write briefs, design them, send them to QA. Blocking: run in a thread."""
    from .crew import AGENT_RULES, lessons_text
    data_dir = os.path.dirname(store.dir)
    v = store.get("ventures", VENTURE)
    have = [a["payload"].get("title", "") for a in listings(store)][-60:]
    store.update("agents", "A-002", {"status": "WORKING", "current_task": "Etsy best-seller scan"}, "A-002",
                 "researching what sells on Etsy", kind="agent.state")
    notes, sources = brain.research("A-002", AGENT_RULES + " You are Market Research for the station's Etsy print-on-demand "
                                    "shop. " + RULES + lessons_text(store, "Market Research"), (
        f"Today is {now.strftime('%A %Y-%m-%d')}. Find what print-on-demand products are selling on Etsy right now "
        "and in the next 6-8 weeks (seasonal demand counts): t-shirts, sweatshirts, hoodies, mugs and posters with "
        "text-based designs. For each niche: proof of demand (best-seller badges, review counts, 'in N baskets'), "
        "2-3 shops selling it with their listing titles, prices and URLs, and the search words buyers use. Prefer "
        "niches where we can be different (a sharper joke, a specific occupation or hobby, better typography) over "
        "crowded generic ones.\n\nWe already list (don't repeat):\n" + ("\n".join(f"- {t}" for t in have) or "(nothing yet)")))
    store.update("agents", "A-002", {"status": "COMPLETED", "current_task": None, "last_output": "Etsy best-seller scan"},
                 "A-002", "Etsy scan done", kind="agent.state")
    store.update("agents", "A-SHOP", {"status": "WORKING", "current_task": "Writing product briefs"}, "A-SHOP",
                 "turning the scan into briefs", kind="agent.state")
    out = brain.structured("A-SHOP", AGENT_RULES + " You are the Etsy Shop Manager. " + RULES + lessons_text(store, "Etsy Strategist"), (
        f"Turn this research into the {BRIEFS_PER_RUN} best products to list next, ranked by how likely they sell. Each "
        "needs our own printed words (headline, optional subline), a listing that buyers searching those words will "
        "find, and a price inside the band the competitors prove. Use only what the research supports.\n\n"
        f"SHOP COMPLIANCE: {json.dumps((v or {}).get('compliance', []))}\n\n"
        f"RESEARCH:\n{notes}\n\nSOURCES:\n" + "\n".join(f"- {s['title']}: {s['url']}" for s in sources)
        + "\n\nALREADY LISTED:\n" + ("\n".join(have) or "(nothing yet)")), BRIEF_SCHEMA, venture=VENTURE)
    seen = {_key(a["payload"].get("headline")) for a in listings(store)}
    filed = []
    for raw in out["products"][:BRIEFS_PER_RUN]:
        p = clean(raw)
        if not p["headline"] or _key(p["headline"]) in seen:
            continue
        seen.add(_key(p["headline"]))
        p["image"] = render(data_dir, p)
        store.event("shop.design", "A-DSGN", f"designed '{p['headline']}' ({p['product_type']})", ref=VENTURE)
        a = store.create("actions", {"kind": "shop.listing", "agent": "A-SHOP", "venture": VENTURE, "payload": p, "status": "qa",
                                     "qa": None, "revisions": 0, "result": None,
                                     "why": f"{p['niche']}: {p['our_angle']}"[:300]}, "A-SHOP", f"shop.listing: {p['title'][:120]}")
        filed.append(a["id"])
    for aid in ("A-SHOP", "A-DSGN"):
        store.update("agents", aid, {"status": "COMPLETED", "current_task": None, "last_output": f"{len(filed)} product briefs"},
                     aid, "briefs filed", kind="agent.state")
    doc = {"at": now.isoformat(), "notes": notes, "sources": sources, "market_notes": out["market_notes"], "filed": filed}
    store.save_doc(f"shop-research-{now.strftime('%Y-%m-%d-%H%M')}.json", doc)
    store.event("shop.researched", "A-SHOP", f"Etsy scan: {len(filed)} new products to QA. {out['market_notes'][:160]}", ref=VENTURE)
    return doc


def publish(store: Store, action: dict) -> dict:
    """Create and publish one QA-passed listing. Called by actions.dispatch. Raises ConnectorError."""
    data_dir = os.path.dirname(store.dir)
    p = clean(action["payload"])
    pt = PRODUCT_TYPES[p["product_type"]]
    name = render(data_dir, p)   # from the words QA passed, so the print matches what was checked
    with open(media.path_for(data_dir, name), "rb") as f:
        png = f.read()
    desc = p["description"].strip()
    if "AI tools" not in desc:
        desc += DISCLOSURE
    res = connectors.printify_list(pt, p["title"], desc, p["tags"], int(round(p["price_usd"] * 100)), png,
                                   f"{_key(p['headline']).replace(' ', '-')[:40] or 'design'}.png",
                                   pt["colors"].get(p["ink"], []), min_price)
    store.event("shop.listed", "A-SHOP", f"listed on Etsy via Printify: {p['title'][:100]} (from ${min(res['price_cents']) / 100:.2f})",
                ref=VENTURE)
    return {**res, "image": name}


def sync_orders(store: Store, now: Optional[datetime] = None) -> dict:
    """Read Printify's orders (Etsy sales). Blocking (HTTP): run in a thread."""
    doc = store.load_doc("shop.json") or {"orders": {}}
    by_product = {(a.get("result") or {}).get("id"): a["id"] for a in listings(store) if (a.get("result") or {}).get("id")}
    new = 0
    for o in connectors.printify_orders():
        oid = str(o.get("id"))
        items = o.get("line_items") or []
        rec = {"at": o.get("created_at"), "status": o.get("status"),
               "retail_cents": int(o.get("total_price") or 0) + int(o.get("total_shipping") or 0),
               "cost_cents": sum(int(i.get("cost") or 0) + int(i.get("shipping_cost") or 0) for i in items),
               "units": sum(int(i.get("quantity") or 1) for i in items),
               "listings": [by_product.get(i.get("product_id")) for i in items],
               "titles": [(i.get("metadata") or {}).get("title", "") for i in items]}
        if oid not in doc["orders"]:
            new += 1
            store.event("shop.order", "A-SHOP", f"Etsy order: {', '.join(t for t in rec['titles'] if t)[:120] or 'item'} "
                        f"(${rec['retail_cents'] / 100:.2f}, {rec['units']} unit{'s' if rec['units'] != 1 else ''})",
                        ref=VENTURE, severity="OPPORTUNITY")
        doc["orders"][oid] = rec
    doc["synced_at"] = now_iso()
    store.save_doc("shop.json", doc)
    return {"orders": len(doc["orders"]), "new": new}


def summary(store: Store, days: int = 30) -> dict:
    doc = store.load_doc("shop.json") or {"orders": {}}
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    recent = [o for o in doc["orders"].values() if (o.get("at") or "") >= since[:10]]
    acts = listings(store)
    by_listing: dict = {}
    for o in doc["orders"].values():
        for lid in o.get("listings") or []:
            if lid:
                by_listing[lid] = by_listing.get(lid, 0) + 1
    live = sorted((a for a in acts if a["status"] == "sent"), key=lambda a: a.get("sent_at", ""), reverse=True)
    return {"connected": connectors.printify_configured(), "per_day": LISTINGS_PER_DAY,
            "pipeline": {s: sum(1 for a in acts if a["status"] == s) for s in OPEN + ("sent", "rejected", "failed")},
            "live": [{"id": a["id"], "title": a["payload"].get("title"), "type": a["payload"].get("product_type"),
                      "image": (a.get("result") or {}).get("image") or a["payload"].get("image"), "ink": a["payload"].get("ink"),
                      "price_cents": (a.get("result") or {}).get("price_cents"), "orders": by_listing.get(a["id"], 0),
                      "sent_at": a.get("sent_at")} for a in live[:40]],
            "drafts": [{"id": a["id"], "title": a["payload"].get("title"), "status": a["status"], "type": a["payload"].get("product_type"),
                        "image": a["payload"].get("image"), "ink": a["payload"].get("ink"), "price_usd": a["payload"].get("price_usd"), "niche": a["payload"].get("niche")}
                       for a in acts if a["status"] in OPEN][:20],
            f"orders_{days}d": len(recent), f"units_{days}d": sum(o["units"] for o in recent),
            f"retail_{days}d": round(sum(o["retail_cents"] for o in recent) / 100, 2),
            f"cost_{days}d": round(sum(o["cost_cents"] for o in recent) / 100, 2),
            "orders_total": len(doc["orders"]), "synced_at": doc.get("synced_at")}
