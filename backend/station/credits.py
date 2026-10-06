"""Claude API credits: how much is left, for the owner and for ULTRON.

Anthropic has no API that reports a prepaid credit balance, so the station keeps the count itself:
  added       every top-up the owner records on the board (amount, when)
  used        every Claude call the station and the trading desk make is already priced from its usage
              block (economy.usage_cost) and booked as ai_usage; usage since the first top-up is subtracted
  reported    with ANTHROPIC_ADMIN_KEY (an Admin API key, sk-ant-admin...), the Auditor also reads Anthropic's
              own cost report every hour (daily buckets, USD) and the larger of the two counts, so usage the
              station can't see (the Console, other apps on the same organization) still comes off
  empty       when Anthropic answers "credit balance is too low", the count shows empty until a top-up is
              recorded or a call succeeds again

ULTRON reads it too: when Anthropic says the balance is empty he stops starting Claude jobs (they wait,
they aren't failed) and tries one every 20 minutes, and he warns the owner once per top-up when it runs low.
"""
from __future__ import annotations

import os
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

from .store import Store, now_iso

LOW = float(os.getenv("STARNET_CREDITS_LOW", "5"))   # warn below this many dollars
RECONCILE_EVERY = timedelta(hours=1)
PROBE_EVERY = timedelta(minutes=20)   # while empty, how often one Claude job tries anyway
DOC = "credits.json"


def _doc(store: Store) -> dict:
    return store.load_doc(DOC) or {"topups": [], "empty_at": None, "warned_for": None, "reported": None}


def add(store: Store, amount: float, note: str = "") -> dict:
    """The owner added credits in the Anthropic Console."""
    amount = round(float(amount), 2)
    if not 0 < amount <= 10000:
        raise ValueError("amount must be between $0.01 and $10,000")
    with store.lock:
        d = _doc(store)
        d["topups"].append({"at": now_iso(), "amount": amount, "note": note[:120]})
        d["empty_at"] = None
        store.save_doc(DOC, d)
    store.event("credits.added", "owner", f"added ${amount:,.2f} of Claude credits" + (f" ({note})" if note else ""))
    return d


def mark_empty(store: Store, now: Optional[datetime] = None) -> None:
    """Anthropic said the balance is too low (again: the time moves, the alert is raised once)."""
    with store.lock:
        d = _doc(store)
        first = not d.get("empty_at")
        d["empty_at"] = (now.astimezone(timezone.utc).isoformat(timespec="seconds") if now else now_iso())
        store.save_doc(DOC, d)
    if first:
            store.event("credits.empty", "A-004", "Claude credits are used up: add credits in the Anthropic Console, then record "
                    "them on the board", severity="ACTION NEEDED")


def summary(store: Store, treasury) -> dict:
    d = _doc(store)
    ups = d["topups"]
    added = round(sum(t["amount"] for t in ups), 2)
    since = min((t["at"] for t in ups), default=None)
    ai = [e for e in treasury.entries if e["kind"] == "ai_usage"]
    tracked = round(sum(e["amount"] for e in ai if since and e["at"] >= since), 2)
    rep = d.get("reported") or {}
    reported = rep.get("spent") if rep.get("since") == since else None
    used = round(max(tracked, reported or 0.0), 2)
    remaining = round(added - used, 2) if ups else None
    last_ok = max((e["at"] for e in ai), default="")
    empty = bool(d.get("empty_at")) and d["empty_at"] > last_ok
    if empty:
        state = "empty"
    elif remaining is None:
        state = "unknown"
    elif remaining <= 0:
        state = "empty"
    elif remaining < LOW:
        state = "low"
    else:
        state = "ok"
    today = datetime.now(timezone.utc).date().isoformat()
    burn = [e for e in ai if e["at"] >= (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()]
    per_day = round(sum(e["amount"] for e in burn) / 7, 2)
    return {"state": state, "remaining": max(remaining, 0.0) if remaining is not None else None, "added": added,
            "used": used, "tracked": tracked, "reported": reported, "reported_at": rep.get("at"),
            "since": since, "topups": ups[-10:], "today": round(sum(e["amount"] for e in ai if e["at"].startswith(today)), 2),
            "per_day_7d": per_day, "days_left": round(remaining / per_day, 1) if remaining and per_day > 0 else None,
            "admin_key": bool(os.getenv("ANTHROPIC_ADMIN_KEY", "").strip()), "low_at": LOW}


def blocks_ai(store: Store, treasury, now: Optional[datetime] = None) -> bool:
    """Anthropic just said the balance is empty: don't start Claude jobs for a while (they'd only fail). After
    PROBE_EVERY one job tries again, so credits added without being recorded are picked up on their own."""
    d = _doc(store)
    if summary(store, treasury)["state"] != "empty" or not d.get("empty_at"):
        return False
    now = now or datetime.now(timezone.utc)
    return now - datetime.fromisoformat(d["empty_at"]) < PROBE_EVERY


def watch(store: Store, treasury, notify) -> None:
    """Warn the owner once per top-up when credits run low."""
    s = summary(store, treasury)
    if s["state"] != "low":
        return
    with store.lock:
        d = _doc(store)
        key = s["since"] and f"{len(d['topups'])}"
        if d.get("warned_for") == key:
            return
        d["warned_for"] = key
        store.save_doc(DOC, d)
    store.event("credits.low", "A-004", f"Claude credits low: ${s['remaining']:.2f} left"
                + (f" (about {s['days_left']} days at this week's pace)" if s["days_left"] else ""), severity="WARNING")
    notify("🛰️ Claude credits low", f"${s['remaining']:.2f} left: top up in the Anthropic Console, then record it on the board")


def reconcile_due(store: Store, now: datetime) -> bool:
    if not os.getenv("ANTHROPIC_ADMIN_KEY", "").strip():
        return False
    d = _doc(store)
    if not d["topups"]:
        return False
    at = (d.get("reported") or {}).get("at")
    return not at or now - datetime.fromisoformat(at) >= RECONCILE_EVERY


def reconcile(store: Store) -> dict:
    """Anthropic's own cost report since the first top-up (Admin API key). Blocking (HTTP)."""
    from .connectors import _http_json
    d = _doc(store)
    since = min(t["at"] for t in d["topups"])
    start = datetime.fromisoformat(since).astimezone(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    headers = {"x-api-key": os.getenv("ANTHROPIC_ADMIN_KEY", "").strip(), "anthropic-version": "2023-06-01"}
    total_cents, page = 0.0, None
    for _ in range(20):
        q = {"starting_at": start, "bucket_width": "1d", "limit": 31}
        if page:
            q["page"] = page
        out = _http_json("GET", "https://api.anthropic.com/v1/organizations/cost_report?" + urllib.parse.urlencode(q), headers)
        for bucket in out.get("data") or []:
            for r in bucket.get("results") or []:
                try:
                    total_cents += float(r.get("amount") or 0)   # decimal string, in cents
                except (TypeError, ValueError):
                    pass
        if not out.get("has_more"):
            break
        page = out.get("next_page")
    with store.lock:
        d = _doc(store)
        d["reported"] = {"since": since, "spent": round(total_cents / 100, 2), "at": now_iso()}
        store.save_doc(DOC, d)
    return d["reported"]
