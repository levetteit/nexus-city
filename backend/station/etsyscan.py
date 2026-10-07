"""Etsy market scans through the Etsy API, run by the station itself.

The crew can't browse etsy.com (it blocks automated visitors), so validation scans used to be owner tasks:
an hour of copying listings by hand. With the Etsy app connected, the server reads the same market through
the Open API instead:

  * search      /listings/active?keywords=…&sort_on=score  (Etsy's relevance ranking for the API)
  * per listing title, price, favorites, listing type (download / physical / both), its review count
  * per shop    total sales and review count

Only digital listings count (download or both); physical ones are skipped and counted, as the scan protocols ask.
A listing already seen under an earlier phrase is marked DUP and not re-counted.

What the API does not show, and the scan says so instead of guessing: ads (API results have none),
Bestseller / Popular now badges, sale prices, and the exact order of the website's search page.
Pinterest isn't part of it (no Pinterest access yet).
"""
from __future__ import annotations

import csv
import io
import os
import re
import statistics
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from . import connectors

FIELDS = ["scan_date", "search_term", "rank", "listing_title", "shop", "price_usd", "listing_review_count",
          "shop_sales_count", "shop_review_count", "favorites", "listing_type", "page_count", "fillable",
          "year_in_title", "listing_url", "notes"]
NS = "NS"
PAUSE = 0.15   # Etsy allows 10 requests a second; stay well under


def parse_terms(text: str, default: int = 20) -> list[tuple[str, int]]:
    """One phrase per line, optionally 'phrase | 20'. Quotes and backticks are stripped."""
    out, seen = [], set()
    for line in (text or "").splitlines():
        line = line.strip().strip("`'\"• -").strip()
        if not line:
            continue
        term, _, n = line.partition("|")
        term = term.strip().strip("`'\"").lower()
        try:
            k = max(1, min(50, int(n.strip()))) if n.strip() else default
        except ValueError:
            k = default
        if term and term not in seen:
            seen.add(term)
            out.append((term, k))
    return out[:15]


def suggest_terms(text: str) -> list[str]:
    """Search phrases written in `backticks` in a task's instructions or inputs (how the crew writes them)."""
    found = []
    for m in re.findall(r"`([^`\n]{3,60})`", text or ""):
        m = m.strip().lower()
        if re.fullmatch(r"[a-z0-9 &'\-]+", m) and " " in m and m not in found and not m.endswith(".csv"):
            found.append(m)
    return found[:12]


def _pages(text: str) -> str:
    nums = [int(x) for x in re.findall(r"(\d{1,3})\s*(?:\+\s*)?(?:pages|page|pg)\b", text, re.I)]
    return str(max(nums)) if nums else NS


def _fillable(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("fillable", "editable", "goodnotes", "notability", "ipad", "google sheets", "canva")):
        return "Y"
    return "N" if "printable" in t else "U"


def scan(terms: list[tuple[str, int]], call: Optional[Callable[[str], dict]] = None, today: Optional[str] = None,
         pause: float = PAUSE) -> dict:
    """Run the scan. Blocking (a few minutes for ~70 listings). `call(path)` does one GET against the Etsy API."""
    call = call or (lambda path: connectors._etsy("GET", path, auth=False))
    today = today or datetime.now(timezone.utc).date().isoformat()
    shops: dict[int, dict] = {}
    seen: set[int] = set()
    rows, per_term = [], []

    def get(path: str) -> dict:
        out = call(path)
        if pause:
            time.sleep(pause)
        return out

    for term, n in terms:
        took, physical, offset = 0, 0, 0
        while took < n and offset < 300:
            q = f"/application/listings/active?keywords={_q(term)}&sort_on=score&limit=50&offset={offset}"
            batch = get(q).get("results", [])
            if not batch:
                break
            offset += len(batch)
            for li in batch:
                if took >= n:
                    break
                if str(li.get("listing_type", "")).lower() == "physical":
                    physical += 1
                    continue
                lid = int(li["listing_id"])
                url = f"https://www.etsy.com/listing/{lid}"
                took += 1
                if lid in seen:
                    rows.append({**{k: "" for k in FIELDS}, "scan_date": today, "search_term": term, "rank": took,
                                 "listing_url": url, "notes": "DUP"})
                    continue
                seen.add(lid)
                sid = li.get("shop_id")
                if sid and sid not in shops:
                    try:
                        shops[sid] = get(f"/application/shops/{sid}")
                    except connectors.ConnectorError:
                        shops[sid] = {}
                shop = shops.get(sid) or {}
                try:
                    reviews = get(f"/application/listings/{lid}/reviews?limit=1").get("count", NS)
                except connectors.ConnectorError:
                    reviews = NS
                price = li.get("price") or {}
                amount = round(price["amount"] / price["divisor"], 2) if price.get("divisor") else NS
                text = f"{li.get('title', '')} {li.get('description', '')}"
                years = sorted(set(re.findall(r"\b(20[2-3]\d)\b", li.get("title", ""))))
                rows.append({"scan_date": today, "search_term": term, "rank": took,
                             "listing_title": re.sub(r"[,\n]", " ", li.get("title", ""))[:90],
                             "shop": shop.get("shop_name", NS), "price_usd": amount if price.get("currency_code") in (None, "USD") else f"{amount} {price.get('currency_code')}",
                             "listing_review_count": reviews, "shop_sales_count": shop.get("transaction_sold_count", NS),
                             "shop_review_count": shop.get("review_count", NS), "favorites": li.get("num_favorers", NS),
                             "listing_type": li.get("listing_type", NS), "page_count": _pages(text),
                             "fillable": _fillable(text), "year_in_title": "+".join(years) or "N",
                             "listing_url": url, "notes": ""})
        per_term.append({"term": term, "wanted": n, "found": took, "physical_skipped": physical})
    return {"date": today, "rows": rows, "terms": per_term, "summary": summarize(rows)}


def _q(term: str) -> str:
    import urllib.parse
    return urllib.parse.quote(term)


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize(rows: list[dict]) -> dict:
    uniq = [r for r in rows if r["notes"] != "DUP"]
    prices = sorted(p for p in (_num(r["price_usd"]) for r in uniq) if p is not None)
    pct = lambda q: round(statistics.quantiles(prices, n=100, method="inclusive")[q - 1], 2) if len(prices) >= 2 else (prices[0] if prices else None)
    sales = [_num(r["shop_sales_count"]) for r in uniq]
    revs = [_num(r["listing_review_count"]) for r in uniq]
    return {"unique_listings": len(uniq), "duplicates": len(rows) - len(uniq), "priced": len(prices),
            "median_price": round(statistics.median(prices), 2) if prices else None, "p25_price": pct(25), "p75_price": pct(75),
            "min_price": prices[0] if prices else None, "max_price": prices[-1] if prices else None,
            "listings_50plus_reviews": sum(1 for r in revs if r is not None and r >= 50),
            "shops_under_1000_sales": sum(1 for s in sales if s is not None and s < 1000),
            "shops_10000plus_sales": sum(1 for s in sales if s is not None and s >= 10000),
            "fillable": sum(r["fillable"] == "Y" for r in uniq), "year_in_title": sum(r["year_in_title"] not in ("N", "") for r in uniq),
            "page_count_stated": sum(r["page_count"] != NS for r in uniq)}


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, FIELDS)
    w.writeheader()
    for r in rows:
        w.writerow({k: (NS if r.get(k) in (None, "") and r.get("notes") != "DUP" else r.get(k, "")) for k in FIELDS})
    return buf.getvalue()


def readiness() -> list[str]:
    """What the station can confirm about the selling accounts, from the server (no login needed)."""
    r = connectors.rails()
    return [f"Etsy: {'connected (the app can create digital-download listings)' if r['etsy_digital'] else 'NOT connected'}",
            f"Stripe: {'configured (payment links can be created)' if connectors.stripe_configured() else 'NOT configured'}",
            f"Station storefront: {'live (it can host a product page)' if r['storefront'] else 'not live (needs Stripe and STARNET_PUBLIC_URL)'}",
            f"Pinterest: {'connected' if r['pinterest'] else 'not checked: no Pinterest access yet (trial pending)'}"]


def deliverable(result: dict, csv_url: str, limit: int = 5800) -> str:
    """What the next agent reads: the method and its limits, the summary, then the table (trimmed to fit)."""
    s = result["summary"]
    lines = [f"ETSY MARKET SCAN via the Etsy Open API, {result['date']} (run by the station, not by hand).",
             "Method: Etsy API relevance ranking (sort_on=score), digital listings only (download/both); physical skipped; "
             "repeats across phrases marked DUP. NOT available from the API, so recorded as NS rather than guessed: "
             "ads, Bestseller/Popular now badges, sale prices, the website's exact result order. Pinterest: not checked.",
             "Per phrase: " + "; ".join(f"'{t['term']}' {t['found']}/{t['wanted']} (physical skipped {t['physical_skipped']})" for t in result["terms"]),
             "Summary: " + ", ".join(f"{k}={v}" for k, v in s.items()),
             "Account readiness: " + " | ".join(readiness()),
             f"Full CSV: {csv_url}",
             "Table (term|rank|price|listing reviews|shop sales|favorites|pages|fillable|year|title):"]
    out = "\n".join(lines)
    for r in result["rows"]:
        if r["notes"] == "DUP":
            line = f"\n{r['search_term']}|{r['rank']}|DUP {r['listing_url']}"
        else:
            line = (f"\n{r['search_term']}|{r['rank']}|{r['price_usd']}|{r['listing_review_count']}|{r['shop_sales_count']}|"
                    f"{r['favorites']}|{r['page_count']}|{r['fillable']}|{r['year_in_title']}|{r['listing_title'][:50]}")
        if len(out) + len(line) > limit:
            out += "\n(table trimmed to fit: the full CSV has every row)"
            break
        out += line
    return out


def save_csv(data_dir: str, task_id: str, rows: list[dict]) -> str:
    d = os.path.join(data_dir, "scans")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{task_id}.csv"), "w", newline="") as f:
        f.write(to_csv(rows))
    return f"/api/station/scans/{task_id}.csv"
