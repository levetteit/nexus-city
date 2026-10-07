"""Owner-made products ("kits"): finished files that ship with the app and go on sale when the owner says so.

A kit is a folder in kits/ with a kit.json: the product files (PDFs), the listing images, a 2:3 cover, pins
and the listing copy, already written and compliance-checked. Nothing here needs the crew's AI.

  import    on startup every new kit is copied into the station: PDFs to the private products folder (served
            only after a verified payment, like the crew's products), images to media/. The kit is attached
            to its venture (by id, checked against a name match).
  publish   the owner presses Publish on the kit's card and sets the price (that is the go decision):
            a Stripe payment link and a storefront page, an Etsy digital listing with every image and file
            when Etsy is connected (Etsy charges its listing fee), and the first pin when Pinterest is.
  pins      the rest of the kit's pins go out one a day once Pinterest is connected.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
from datetime import datetime, timedelta
from typing import Optional

from . import connectors, digital, media
from .store import Store, now_iso

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "kits")
PIN_EVERY = timedelta(hours=24)
DOC = "kits.json"


def manifests(root: str = ROOT) -> list[dict]:
    out = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name, "kit.json")
            if os.path.exists(path):
                with open(path) as f:
                    out.append({**json.load(f), "dir": os.path.join(root, name)})
    return out


def _venture_for(store: Store, want: dict) -> Optional[str]:
    match = (want.get("match") or "").lower()
    v = store.get("ventures", want.get("id") or "")
    if v and (not match or match in v.get("name", "").lower()):
        return v["id"]
    for v in store.all("ventures"):
        if match and match in v.get("name", "").lower():
            return v["id"]
    return None


def sync(store: Store, root: str = ROOT) -> dict:
    """Import new kits; attach any kit still without a venture. Cheap after the first run."""
    doc = store.load_doc(DOC) or {}
    dd = digital._data_dir(store)
    changed = False
    for m in manifests(root):
        k = doc.get(m["id"])
        if k is None:
            files = []
            for i, fname in enumerate(m["files"]):
                name = secrets.token_hex(16) + ".pdf"
                shutil.copyfile(os.path.join(m["dir"], fname), os.path.join(digital.products_dir(dd), name))
                files.append({"pdf": name, "label": "US Letter" if "letter" in fname.lower() else "A4" if "a4" in fname.lower() else f"File {i + 1}",
                              "filename": fname})

            def img(fname):
                name = secrets.token_hex(16) + os.path.splitext(fname)[1].lower()
                shutil.copyfile(os.path.join(m["dir"], fname), os.path.join(media.media_dir(dd), name))
                return name
            k = doc[m["id"]] = {"id": m["id"], "name": m["name"], "want_venture": m.get("venture") or {}, "venture": None,
                                "files": files, "images": [img(f) for f in m["listing_images"]], "cover": img(m["cover"]),
                                "pins": [img(f) for f in m.get("pins", [])], "pages": m.get("pages"), "copy": m["copy"],
                                "imported_at": now_iso(), "product": None}
            store.event("kit.imported", "A-DSGN", f"owner kit ready: {m['name']} ({len(files)} files, "
                        f"{len(k['images'])} listing images, {len(k['pins'])} pins)")
            changed = True
        if not k.get("venture"):
            v = _venture_for(store, k.get("want_venture") or {})
            if v:
                k["venture"] = v
                changed = True
    if changed:
        store.save_doc(DOC, doc)
    return doc


def status(store: Store) -> list[dict]:
    out = []
    for k in (store.load_doc(DOC) or {}).values():
        p = store.get("products", k["product"]) if k.get("product") else None
        out.append({"id": k["id"], "name": k["name"], "venture": k.get("venture"), "cover": k["cover"], "images": k["images"],
                    "pins": len(k["pins"]), "files": [f["label"] for f in k["files"]], "pages": k.get("pages"),
                    "title": k["copy"]["title"], "etsy_title": k["copy"]["etsy_title"],
                    "product": {"id": p["id"], "url": p["url"], "price_usd": p["price_usd"], "active": p.get("active"),
                                "etsy": (p.get("etsy") or {}).get("url"), "pins_left": len(p.get("pins_queue") or [])} if p else None,
                    "rails": connectors.rails()})
    return out


def publish(store: Store, kit_id: str, price: float, venture: Optional[str] = None) -> dict:
    """The owner's go: put the kit on sale everywhere it can go. Raises ValueError / ConnectorError."""
    doc = store.load_doc(DOC) or {}
    k = doc.get(kit_id)
    if not k:
        raise KeyError(kit_id)
    if k.get("product") and (store.get("products", k["product"]) or {}).get("active"):
        raise ValueError("already on sale")
    if not 3 <= float(price) <= 97:
        raise ValueError("price must be $3-$97")
    v_id = venture or k.get("venture")
    if not v_id or not store.get("ventures", v_id):
        raise ValueError("this kit has no venture yet: pick one")
    if not connectors.rails()["storefront"]:
        raise ValueError("the storefront needs Stripe and STARNET_PUBLIC_URL first")
    c, dd, price = k["copy"], digital._data_dir(store), round(float(price), 2)
    slug = digital.slugify(c["title"])
    url = digital.store_url(slug)
    link = connectors.stripe_payment_link(c["title"], c["subtitle"], price, v_id,
                                          redirect=f"{url}/thanks?session_id={{CHECKOUT_SESSION_ID}}", extra={"starnet_product": slug})
    rec = store.create("products", {"venture": v_id, "slug": slug, "title": c["title"], "subtitle": c["subtitle"], "format": "printable",
                                    "price_usd": price, "pdf": k["files"][0]["pdf"], "files": k["files"], "pages": k.get("pages"),
                                    "cover": k["cover"], "sales_page": {"headline": c["title"], "subheadline": c["subtitle"],
                                                                        "bullets": c.get("bullets", []), "faq": c.get("faq", [])},
                                    "notice": ("An information organizer only. Not medical, legal or financial advice. "
                                               "Once completed, it contains private information: please store it securely."),
                                    "checkout_url": link["url"], "payment_link": link["payment_link"], "url": url, "action": None,
                                    "kit": kit_id, "active": True, "etsy": None, "pin": None, "pins_queue": list(k["pins"]),
                                    "pinned_at": None}, "owner", f"on sale: {c['title']} (${price:.2f}), the owner's kit")
    k["product"], k["venture"] = rec["id"], v_id
    store.save_doc(DOC, doc)
    out = {"product": rec["id"], "url": url, "checkout": link["url"]}
    if connectors.etsy_connected():
        try:
            read = lambda folder, name: open(os.path.join(folder, name), "rb").read()
            images = [(f"{slug}-{i + 1}.jpg", read(media.media_dir(dd), n)) for i, n in enumerate(k["images"])]
            files = [(f["filename"], read(digital.products_dir(dd), f["pdf"])) for f in k["files"]]
            et = connectors.etsy_digital_listing(c["etsy_title"], c["description"], c["tags"], price, files[0][1], files[0][0],
                                                 images[0][1], images[0][0], more_images=images[1:], more_files=files[1:])
            store.update("products", rec["id"], {"etsy": et}, "A-SHOP", f"on Etsy too: {et['url']}", kind="product.etsy")
            out["etsy"] = et
        except connectors.ConnectorError as exc:
            out["etsy_error"] = str(exc)[:200]
            store.event("product.etsy_failed", "A-SHOP", f"Etsy listing for {c['title']} failed: {exc}"[:240], ref=v_id, severity="WARNING")
    pin = next_pin(store, rec["id"])
    if pin:
        out["pin"] = pin
    store.event("digital.published", "owner", f"on sale: {c['title']} (${price:.2f})" + (" + Etsy" if out.get("etsy") else ""), ref=v_id)
    return out


def next_pin(store: Store, product_id: str) -> Optional[str]:
    """Post the product's next queued pin (when Pinterest is connected)."""
    p = store.get("products", product_id)
    if not p or not p.get("active") or not p.get("pins_queue") or not connectors.pinterest_connected():
        return None
    c = (store.load_doc(DOC) or {}).get(p.get("kit"), {}).get("copy", {})
    image = p["pins_queue"][0]
    try:
        board = (store.get("ventures", p["venture"]) or {}).get("name") or p["title"]
        pin = connectors.pinterest_pin(board, c.get("pin_title") or p["title"], c.get("pin_description") or p["subtitle"],
                                       (p.get("etsy") or {}).get("url") or p["url"], media.public_url(image), p["title"])
    except connectors.ConnectorError as exc:
        store.event("product.pin_failed", "A-006", f"pin for {p['title']} failed: {exc}"[:240], ref=p["venture"], severity="WARNING")
        store.update("products", product_id, {"pinned_at": now_iso()}, "A-006", "pin failed: retry tomorrow")
        return None
    store.update("products", product_id, {"pins_queue": p["pins_queue"][1:], "pinned_at": now_iso(), "pin": {"id": pin.get("id")}},
                 "A-006", f"pinned ({len(p['pins_queue']) - 1} left)", kind="product.pinned")
    return pin.get("id")


def pins_due(store: Store, now: datetime) -> list[str]:
    if not connectors.pinterest_connected():
        return []
    due = []
    for p in store.all("products"):
        if p.get("kit") and p.get("active") and p.get("pins_queue"):
            last = p.get("pinned_at")
            if not last or now - datetime.fromisoformat(last) >= PIN_EVERY:
                due.append(p["id"])
    return due
