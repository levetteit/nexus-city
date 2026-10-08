"""The treasury: one shared pool for the city and the station.

Everyone has to earn their keep. The trading city and the station both pay into the same pool and
both draw their bills from it, so whichever side is earning keeps the other running. Each side (and
each venture) still has its own P&L, so ULTRON can see who carries whom.

What counts as real money, and who can record it:
  * income/expense   only the owner (the API marks these source="owner"); agents can never book revenue
  * lucid_payout     payouts you record in the city's account panel, at the firm's trader split
  * ai_usage         what the station's Claude calls cost, computed from each response's token usage
Paper trading profit is shown next to the pool but never counts toward it.

Nothing here moves money. A funding goal that the pool can cover becomes an approval for the owner.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

from ..env import env
from ..persist import read_jsonl, repair_jsonl_tail, write_json_atomic
from .store import Store, now_iso

# Claude Opus 5.5 list prices (USD per million tokens) and web search ($ per search)
PRICES = {"input": 4.00, "output": 20.00, "cache_read": 0.20, "cache_write": 5.00, "search": 0.01}
AI_BUDGET = float(env("STATION_AI_BUDGET", "50"))        # $/month cap on the station's Claude usage
PAYOUT_SPLIT = float(env("PAYOUT_SPLIT", "0.9"))         # the trader's share of a Lucid payout
RESERVE_MONTHS = 1.0   # the pool keeps one month of bills before it funds anything new

DEFAULT_BILLS = [
    {"id": "render", "unit": "city", "name": "Render Starter plan + 1 GB disk", "monthly": 7.25},
    {"id": "station-ai", "unit": "station", "name": "Station AI usage (cap)", "monthly": AI_BUDGET},
]
DEFAULT_GOALS = [
    {"id": "printify-premium", "name": "Printify Premium", "monthly": 29.0, "months": 2, "unit": "station",
     "why": "Up to 20% off every Etsy product's cost: worth it once the shop sells steadily."},
]


def usage_cost(usage) -> float:
    """Dollar cost of one Claude response, from its usage block."""
    g = lambda k: getattr(usage, k, 0) or 0
    tools = getattr(usage, "server_tool_use", None)
    searches = (getattr(tools, "web_search_requests", 0) or 0) if tools else 0
    return round(g("input_tokens") * PRICES["input"] / 1e6 + g("output_tokens") * PRICES["output"] / 1e6
                 + g("cache_read_input_tokens") * PRICES["cache_read"] / 1e6
                 + g("cache_creation_input_tokens") * PRICES["cache_write"] / 1e6
                 + searches * PRICES["search"], 4)


def entry_hash(e: dict) -> str:
    body = {k: v for k, v in e.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


class Treasury:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.path = os.path.join(store.dir, "ledger.jsonl")
        self.cfg_path = os.path.join(store.dir, "treasury.json")
        self.cfg = {"bills": DEFAULT_BILLS, "goals": DEFAULT_GOALS, "payouts_synced": 0}
        if os.path.exists(self.cfg_path):
            with open(self.cfg_path) as f:
                self.cfg.update(json.load(f))
        if any(g["id"] == "etsy-launch" for g in self.cfg["goals"]):   # the owner already runs the Etsy shop
            self.cfg["goals"] = [g for g in self.cfg["goals"] if g["id"] != "etsy-launch"] + DEFAULT_GOALS
        torn = repair_jsonl_tail(self.path)   # a crash mid-append: the fragment is set aside, the chain stays readable
        self.entries, self.bad_lines = read_jsonl(self.path)
        if torn or self.bad_lines:
            store.event("storage.repaired", "A-008", f"ledger: {'a line cut off by a crash was moved to ' + os.path.basename(torn) if torn else ''}"
                        f"{'; ' if torn and self.bad_lines else ''}{f'{self.bad_lines} unreadable line(s) skipped' if self.bad_lines else ''}",
                        severity="WARNING")

    # ---------------------------------------------------------------- booking
    def book(self, kind: str, amount: float, unit: str, source: str, note: str, venture: Optional[str] = None,
             agent: Optional[str] = None, ref: Optional[str] = None) -> dict:
        if kind not in ("income", "expense", "ai_usage", "lucid_payout"):
            raise ValueError("kind must be income, expense, ai_usage or lucid_payout")
        if unit not in ("city", "station"):
            raise ValueError("unit must be city or station")
        if kind in ("income", "expense") and source not in ("owner", "stripe"):
            raise ValueError("only the owner (or a verified Stripe payment) can record income or expenses")
        amount = round(float(amount), 4)
        if amount <= 0:
            raise ValueError("amount must be positive")
        e = {"at": now_iso(), "kind": kind, "amount": amount, "unit": unit, "source": source, "note": note[:300]}
        if venture:
            e["venture"] = venture
        if agent:
            e["agent"] = agent
        if ref:
            e["ref"] = ref
        with self.store.lock, open(self.path, "a") as f:
            e["prev"] = self.entries[-1].get("hash", "") if self.entries else ""
            e["hash"] = entry_hash(e)
            f.write(json.dumps(e) + "\n")
            self.entries.append(e)
        if kind != "ai_usage":   # AI usage is logged per call in the ledger; the event log would drown in it
            self.store.event(f"money.{kind}", source, f"{'+' if kind in ('income', 'lucid_payout') else '-'}${amount:,.2f} {unit}: {note[:120]}",
                             ref=venture, severity="OPPORTUNITY" if kind != "expense" else "INFO")
        return e

    def has_ref(self, ref: str) -> bool:
        return any(e.get("ref") == ref for e in self.entries)

    def book_stripe_sale(self, session: dict) -> Optional[dict]:
        """A paid Stripe checkout, once: the sale, and Stripe's estimated fee as an expense."""
        from .connectors import stripe_fee
        sid = session.get("id", "")
        amount = (session.get("amount_total") or 0) / 100
        if not sid or session.get("payment_status") != "paid" or amount <= 0:
            return None
        meta = session.get("metadata") or {}   # links made before the rename carry starnet_* keys
        venture = (meta.get("nexus_venture") or meta.get("starnet_venture")
                   or ((session.get("payment_link") and self.venture_for_link(session["payment_link"])) or None))
        with self.store.lock:   # the webhook and the Auditor's reconciliation can race: book each sale once
            if self.has_ref(sid):
                return None
            product = meta.get("nexus_product") or meta.get("starnet_product")
            sale = self.book("income", amount, "station", "stripe", f"Stripe sale {sid[-8:]}" + (f" · {product}" if product else ""),
                             venture=venture, ref=sid)
            self.book("expense", stripe_fee(amount), "station", "stripe", f"Stripe fee (est.) {sid[-8:]}", venture=venture,
                      ref=sid + ":fee")
        return sale

    def venture_for_link(self, link_id: str) -> Optional[str]:
        for a in self.store.find("actions", kind="stripe.payment_link"):
            if (a.get("result") or {}).get("payment_link") == link_id:
                return a.get("venture")
        return None

    def verify_chain(self) -> dict:
        """The Auditor's check: every entry still hashes to what was written, in order."""
        prev, bad = "", []
        for i, e in enumerate(self.entries):
            if "hash" not in e:   # written before the chain existed
                continue
            if e.get("prev", "") != prev or entry_hash(e) != e["hash"]:
                bad.append(i)
            prev = e["hash"]
        return {"entries": len(self.entries), "intact": not bad, "broken_at": bad[:10]}

    def charge_ai(self, usage, agent: str, venture: Optional[str], note: str, unit: str = "station") -> float:
        cost = usage_cost(usage)
        if cost > 0:
            self.book("ai_usage", cost, unit, "api_usage", note, venture=venture, agent=agent)
        return cost

    def sync_payouts(self, account) -> int:
        """Credit the city with Lucid payouts recorded in the account panel (each once)."""
        payouts = list(getattr(account, "payouts", []) or [])
        n = self.cfg.get("payouts_synced", 0)
        for i, (day, amount) in enumerate(payouts[n:], start=n):
            ref = f"lucid-payout-{i + 1}"
            if self.has_ref(ref):   # booked before a crash stopped the counter being saved: never twice
                continue
            self.book("lucid_payout", amount * PAYOUT_SPLIT, "city", "lucid_payout",
                      f"Lucid payout ${amount:,.0f} (day {day}) at the {PAYOUT_SPLIT:.0%} trader split", venture="V-001", ref=ref)
        if len(payouts) > n:
            self.cfg["payouts_synced"] = len(payouts)
            self._save_cfg()
        return len(payouts) - n

    def set_eval_goal(self, goal: Optional[dict]) -> None:
        """The scale plan's one-time goal for the next Lucid evaluation (backend/scale.py): one at a time."""
        keep = [g for g in self.cfg["goals"] if not g["id"].startswith("lucid-eval-") or (goal and g["id"] == goal["id"])]
        if goal and not any(g["id"] == goal["id"] for g in keep):
            keep.append(goal)
        elif goal:
            keep = [goal if g["id"] == goal["id"] else g for g in keep]   # the price may have changed
        if keep != self.cfg["goals"]:
            self.cfg["goals"] = keep
            self._save_cfg()

    def set_scale(self, eval_price: Optional[float], max_accounts: Optional[int]) -> dict:
        sc = self.cfg.setdefault("scale", {})
        if eval_price is not None:
            if eval_price < 0 or eval_price > 5000:
                raise ValueError("evaluation price must be $0-$5,000")
            sc["eval_price"] = round(float(eval_price), 2) or None
        if max_accounts is not None:
            if not 1 <= int(max_accounts) <= 20:
                raise ValueError("account limit must be 1-20")
            sc["max_accounts"] = int(max_accounts)
        self._save_cfg()
        return sc

    # ---------------------------------------------------------------- reading
    def flights(self, n: int = 6) -> list[dict]:
        """The latest real money in, as shuttle flights: a Lucid payout flies from the city's vault up to the
        station's treasury, a store sale docks at the treasury from the marketplace. Newest first."""
        key = (len(self.entries), n)
        if getattr(self, "_flights", (None,))[0] == key:   # the city asks every tick; the ledger rarely changes
            return self._flights[1]
        out = []
        for e in reversed(self.entries):
            if e["kind"] == "lucid_payout" or (e["kind"] == "income" and e.get("source") in ("stripe", "owner")):
                out.append({"id": (e.get("hash") or e["at"])[:12], "at": e["at"], "amount": round(e["amount"], 2),
                            "kind": "payout" if e["kind"] == "lucid_payout" else "sale", "unit": e["unit"],
                            "note": e["note"][:80]})
                if len(out) >= n:
                    break
        self._flights = (key, out)
        return out

    def ai_spent(self, month: Optional[str] = None) -> float:
        month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        return round(sum(e["amount"] for e in self.entries if e["kind"] == "ai_usage" and e["at"].startswith(month)
                         and e.get("unit", "station") == "station"), 2)   # the station's cap; the desk's calls are the city's

    def ai_allowed(self, estimate: float = 1.0) -> bool:
        return self.ai_spent() + estimate <= AI_BUDGET

    def pnl(self, key: str, value: str) -> dict:
        """Real income and costs for one unit, venture or agent."""
        rows = [e for e in self.entries if e.get(key) == value]
        income = sum(e["amount"] for e in rows if e["kind"] in ("income", "lucid_payout"))
        cost = sum(e["amount"] for e in rows if e["kind"] in ("expense", "ai_usage"))
        ai = sum(e["amount"] for e in rows if e["kind"] == "ai_usage")
        return {"income": round(income, 2), "costs": round(cost, 2), "ai_costs": round(ai, 2), "net": round(income - cost, 2)}

    def summary(self, paper_pnl: Optional[float] = None) -> dict:
        city, station = self.pnl("unit", "city"), self.pnl("unit", "station")
        pool = round(city["net"] + station["net"], 2)
        monthly = round(sum(b["monthly"] for b in self.cfg["bills"]), 2)
        reserve = monthly * RESERVE_MONTHS
        goals = []
        for g in self.cfg["goals"]:
            need = round(g["monthly"] * g.get("months", 1), 2)
            free = max(0.0, pool - reserve)
            goals.append({**g, "need": need, "progress": round(min(1.0, free / need), 3) if need else 1.0,
                          "funded": free >= need})
        carry = "city" if city["net"] > station["net"] else "station" if station["net"] > city["net"] else None
        return {
            "pool": pool, "monthly_bills": monthly, "reserve": round(reserve, 2),
            "runway_months": round(pool / monthly, 1) if monthly else None,
            "city": city, "station": station, "carrying": carry,
            "ai": {"spent_month": self.ai_spent(), "budget": AI_BUDGET},
            "bills": self.cfg["bills"], "goals": goals,
            "paper_pnl": paper_pnl, "recent": self.entries[-15:][::-1],
        }

    def _save_cfg(self) -> None:
        write_json_atomic(self.cfg_path, self.cfg, indent=1)
