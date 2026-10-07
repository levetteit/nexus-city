"""Results: what the posts and ventures actually produce. This is what the War Room learns from.

  Post engagement   every 6 hours, reactions/comments/shares (Facebook) and likes/comments (Instagram)
                    for each post sent in the last 14 days, read straight from Meta. Plain code, no model.
  Leads             one tap on the board per DM, WhatsApp message or call, optionally tied to the post
                    that brought it; then quoted → won (with the amount, booked as real income) or lost.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import connectors
from .store import Store, now_iso

METRICS_EVERY = timedelta(hours=6)
METRICS_WINDOW = timedelta(days=14)
SOURCES = ("dm", "whatsapp", "call", "comment", "referral", "email", "other")
STATUSES = ("new", "quoted", "won", "lost")


def _engagement(m: dict) -> int:
    return sum(v for k, v in (m or {}).items() if isinstance(v, int))


def posts_to_check(store: Store, now: datetime) -> list[dict]:
    since = (now - METRICS_WINDOW).astimezone(timezone.utc).isoformat()
    out = []
    for a in store.find("actions", kind="social.post", status="sent"):
        res, plat = a.get("result") or {}, a["payload"].get("platform")
        if plat in ("facebook", "instagram") and res.get("id") and (a.get("sent_at") or "") >= since:
            out.append(a)
    return out


def refresh_metrics(store: Store, now: Optional[datetime] = None) -> dict:
    """Read engagement for recent posts. Blocking (HTTP): run in a thread."""
    now = now or datetime.now(timezone.utc)
    checked, errors = 0, []
    for a in posts_to_check(store, now):
        res, plat = a["result"], a["payload"]["platform"]
        try:
            m = connectors.facebook_post_metrics(res["id"]) if plat == "facebook" else connectors.instagram_media_metrics(res["id"])
        except connectors.ConnectorError as exc:
            errors.append(f"{a['id']}: {exc}"[:160])
            continue
        before = _engagement(res.get("metrics"))
        with store.lock:   # live numbers, not a decision: update in place, log only the first reading and jumps
            rec = store.data["actions"][a["id"]]
            rec["result"] = {**rec["result"], "metrics": m, "metrics_at": now_iso()}
            store._save("actions")
        if not res.get("metrics") or _engagement(m) >= before + 10:
            store.event("action.metrics", "A-009", f"{plat} post {a['id']}: {', '.join(f'{v} {k}' for k, v in m.items())}",
                        ref=a.get("venture"))
        checked += 1
    return {"checked": checked, "errors": errors}


def add_lead(store: Store, venture: str, source: str, note: str = "", action: Optional[str] = None) -> dict:
    if not store.get("ventures", venture):
        raise KeyError(venture)
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")
    if action and not store.get("actions", action):
        raise ValueError("unknown post")
    return store.create("leads", {"venture": venture, "source": source, "note": note[:300], "action": action or None,
                                  "status": "new", "amount": None}, "owner",
                        f"new lead for {venture} via {source}" + (f" (from post {action})" if action else ""))


def set_lead(store: Store, lead_id: str, status: str, amount: Optional[float] = None, note: str = "",
             record_income=None) -> dict:
    lead = store.get("leads", lead_id)
    if not lead:
        raise KeyError(lead_id)
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    if lead["status"] == "won":
        raise ValueError("already won: record any change as income or expense")
    changes = {"status": status}
    if note:
        changes["note"] = (lead.get("note", "") + " | " + note)[:500].strip(" |")
    if status == "won":
        if amount is None or amount <= 0:
            raise ValueError("a won lead needs the amount you earned")
        changes["amount"] = round(float(amount), 2)
    out = store.update("leads", lead_id, changes, "owner", f"lead {lead_id} {status}" + (f": ${amount:,.2f}" if status == "won" else ""),
                       kind=f"lead.{status}")
    if status == "won" and record_income:
        record_income("income", float(amount), "station", f"Won lead {lead_id} ({lead['source']})", venture=lead["venture"])
    return out


def summary(store: Store, venture: str, days: int = 30) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    leads = [l for l in store.find("leads", venture=venture) if l["created_at"] >= since]
    posts = [a for a in store.find("actions", kind="social.post", venture=venture, status="sent") if (a.get("sent_at") or "") >= since]
    by_post = Counter(l["action"] for l in leads if l.get("action"))
    perf = sorted(({"post": a["id"], "platform": a["payload"]["platform"], "angle": a.get("why", "")[-80:],
                    "text": a["payload"].get("text", "")[:140], "metrics": (a.get("result") or {}).get("metrics"),
                    "engagement": _engagement((a.get("result") or {}).get("metrics")), "leads": by_post.get(a["id"], 0)}
                   for a in posts), key=lambda p: (-p["leads"], -p["engagement"]))
    return {"days": days, "leads": len(leads), "by_source": dict(Counter(l["source"] for l in leads)),
            "by_status": dict(Counter(l["status"] for l in leads)),
            "won_value": round(sum(l.get("amount") or 0 for l in leads if l["status"] == "won"), 2),
            "posts_sent": len(posts), "best_posts": perf[:5], "worst_posts": [p for p in perf[::-1] if p["engagement"] == 0][:3]}
