"""The Finance team's books. Plain code, no model calls: numbers shouldn't be written by a language model.

  Treasurer (Finance Agent)  the pool, bills, runway, AI budget, funding goals (economy.py)
  Accountant                 statements per month for the city, the station and each venture, with a
                             tax set-aside estimate (STARNET_TAX_RATE, default 25%: an estimate, not tax
                             advice; check it with a tax professional)
  Auditor                    daily: the ledger's hash chain is intact; every Stripe payment is booked
                             (missed webhooks get booked from Stripe's own records); every agent's cost
                             against what it delivered; outbound actions that failed
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from . import connectors
from .economy import Treasury
from .store import Store

TAX_RATE = float(os.getenv("STARNET_TAX_RATE", "0.25"))
COSTLY_AGENT = 5.0   # $ of AI spend with nothing delivered → flagged


def statement(treasury: Treasury, month: Optional[str] = None) -> dict:
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    rows = [e for e in treasury.entries if e["at"].startswith(month)]
    by = lambda key: defaultdict(lambda: {"income": 0.0, "expenses": 0.0, "ai": 0.0})
    units, ventures = by("unit"), by("venture")
    for e in rows:
        for bucket, k in ((units, e["unit"]), (ventures, e.get("venture") or "unassigned")):
            if e["kind"] in ("income", "lucid_payout"):
                bucket[k]["income"] += e["amount"]
            elif e["kind"] == "ai_usage":
                bucket[k]["ai"] += e["amount"]
            else:
                bucket[k]["expenses"] += e["amount"]
    fin = lambda d: {k: {**{x: round(y, 2) for x, y in v.items()}, "net": round(v["income"] - v["expenses"] - v["ai"], 2)} for k, v in d.items()}
    u = fin(units)
    net = round(sum(x["net"] for x in u.values()), 2)
    return {"month": month, "units": u, "ventures": fin(ventures), "net": net,
            "tax_set_aside": round(max(0.0, net) * TAX_RATE, 2), "tax_rate": TAX_RATE, "entries": len(rows),
            "note": "Tax set-aside is an estimate, not tax advice."}


def audit(store: Store, treasury: Treasury) -> dict:
    findings = []
    chain = treasury.verify_chain()
    if not chain["intact"]:
        findings.append({"severity": "CRITICAL", "finding": f"Ledger entries changed after they were written: {chain['broken_at']}"})
    booked = 0
    if connectors.stripe_configured():
        try:
            for s in connectors.stripe_paid_sessions():
                if treasury.book_stripe_sale(s):
                    booked += 1
            if booked:
                findings.append({"severity": "WARNING", "finding": f"{booked} Stripe payment(s) weren't booked by the webhook; booked from Stripe's records"})
        except connectors.ConnectorError as exc:
            findings.append({"severity": "WARNING", "finding": f"Couldn't reconcile with Stripe: {exc}"})
    for a in store.all("agents"):
        if a.get("kind") != "ai":
            continue
        cost = treasury.pnl("agent", a["id"])["ai_costs"]
        if cost >= COSTLY_AGENT and not a.get("tasks_done") and a["id"] not in ("A-002", "A-011", "A-012"):
            findings.append({"severity": "WARNING", "finding": f"{a['name']} has cost ${cost:.2f} and delivered nothing"})
    failed = [x for x in store.all("actions") if x["status"] == "failed"]
    if failed:
        findings.append({"severity": "ACTION NEEDED", "finding": f"{len(failed)} outbound action(s) failed to send",
                         "refs": [x["id"] for x in failed[:10]]})
    doc = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "chain": chain, "stripe_booked": booked,
           "findings": findings, "clean": not findings}
    store.save_doc(f"audit-{doc['at'][:10]}.json", doc)
    store.event("finance.audit", "A-009", "audit clean" if not findings else f"audit: {len(findings)} finding(s): {findings[0]['finding'][:120]}",
                severity="INFO" if not findings else max((f["severity"] for f in findings), key=["INFO", "WARNING", "ACTION NEEDED", "CRITICAL"].index))
    return doc
