"""The Lucid scale plan: where every account is, when its next payout lands, and when the treasury can buy
the next evaluation.

Scaling at Lucid means more accounts, not bigger size: each LucidFlex 50K pays out at most $2,000 per
cycle of 5+ days with $150+ profit. The plan reads your accounts (the 👥 book, or the main account when
the book is empty) and projects each one forward at a conservative pace:

  * AVG_DAY        dollars per trading day: your paper average once there are 10+ traded days, otherwise
                   the latest 22-day backtest on real candles ($404/day), rounded down
  * QUALIFY_RATE   share of trading days that make $150+ and count toward a payout cycle (backtest: ~55%)

Projections are estimates, labelled as such. Nothing here buys anything: when the treasury can cover
the next evaluation on top of a month of bills, ULTRON asks you to approve it (a treasury goal, one-time).
The evaluation price and your firm's account limit are yours to set (POST /api/scale); until the price
is set there is no goal.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

AVG_DAY = 400.0
QUALIFY_RATE = 0.55
MIN_PAPER_DAYS = 10
GOAL_PREFIX = "lucid-eval-"


def trading_days_ahead(start: date, n: int) -> date:
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def pace(edge: Optional[dict]) -> tuple[float, str]:
    """Dollars per day to project with, and where it came from."""
    if edge and (edge.get("days") or 0) >= MIN_PAPER_DAYS and edge.get("avg_day") is not None:
        return max(0.0, float(edge["avg_day"])), f"your paper average over {edge['days']} days"
    return AVG_DAY, "the 22-day backtest on real candles"


def account_step(a: dict, avg: float, today: date) -> dict:
    """One account's stage and next milestone."""
    phase = a.get("phase", "evaluation")
    out = {"id": a.get("id", "main"), "name": a.get("name", "Main account"), "phase": phase,
           "balance": a.get("balance"), "profit": a.get("profit"), "paid_out": a.get("paid_out", 0),
           "payouts": a.get("payouts", 0), "max_payouts": a.get("max_payouts")}
    if phase == "failed":
        return {**out, "stage": "failed", "next": "Failed: reset it at Lucid or retire it", "eta_days": None, "eta": None}
    if phase == "evaluation":
        left = max(0.0, (a.get("target") or 0) - (a.get("profit") or 0))
        if left <= 0:
            return {**out, "stage": "passing", "next": "Target reached: Lucid moves it to funded", "eta_days": 0,
                    "eta": today.isoformat()}
        n = math.ceil(left / avg) if avg > 0 else None
        return {**out, "stage": "evaluation", "left": round(left, 2),
                "next": f"${left:,.0f} to pass" + (f" · about {n} trading day{'s' if n != 1 else ''}" if n else ""),
                "eta_days": n, "eta": trading_days_ahead(today, n).isoformat() if n else None}
    if a.get("max_payouts") and (a.get("payouts") or 0) >= a["max_payouts"]:
        return {**out, "stage": "live", "next": "All payouts taken: moving to a live account", "eta_days": None, "eta": None}
    if a.get("payout_eligible"):
        amt = a.get("safe_payout") or a.get("payout_limit") or 0
        return {**out, "stage": "payout ready", "payout": round(amt, 2),
                "next": f"Payout ready: request ${amt:,.0f}" if amt else "Payout ready: wait for more cushion",
                "eta_days": 0, "eta": today.isoformat()}
    need = max(0, (a.get("payout_days") or 5) - (a.get("cycle_days") or 0))
    n = math.ceil(need / QUALIFY_RATE) if need else 1
    est = min(2000.0, max(0.0, 0.5 * ((a.get("profit") or 0) + n * avg)))   # LucidFlex: up to 50% of profit, $2,000 max
    return {**out, "stage": "funded", "payout": round(est, 2),
            "next": f"{need} more $150+ day{'s' if need != 1 else ''} to payout #{(a.get('payouts') or 0) + 1} (est. ${est:,.0f})",
            "eta_days": n, "eta": trading_days_ahead(today, n).isoformat()}


def plan(accounts: list[dict], treasury: Optional[dict], cfg: dict, edge: Optional[dict], today: date,
         split: float = 0.9) -> dict:
    avg, source = pace(edge)
    rows = [account_step(a, avg, today) for a in accounts]
    active = [r for r in rows if r["stage"] not in ("failed", "live")]
    price = cfg.get("eval_price")
    limit = int(cfg.get("max_accounts") or 5)
    pool = (treasury or {}).get("pool", 0.0)
    reserve = (treasury or {}).get("reserve", 0.0)
    free = round(max(0.0, pool - reserve), 2)
    # money coming: each funded account's next payout, at the trader split, in date order
    coming = sorted(((r["eta"], round(r["payout"] * split, 2), r["name"]) for r in rows
                     if r["stage"] in ("funded", "payout ready") and r.get("payout")), key=lambda x: x[0])
    nxt = {"room": len(active) < limit, "price": price, "free": free}
    if not price:
        nxt.update(can_fund=False, eta=None, text="Set the evaluation price to plan the next account")
    elif len(active) >= limit:
        nxt.update(can_fund=False, eta=None, text=f"At your limit of {limit} active accounts: scale by taking payouts")
    elif free >= price:
        nxt.update(can_fund=True, eta=today.isoformat(), text=f"The treasury can fund evaluation #{len(rows) + 1} now (${price:,.0f})")
    else:
        need, eta = price - free, None
        for when, amount, _ in coming:
            need -= amount
            if need <= 0:
                eta = when
                break
        nxt.update(can_fund=False, eta=eta, short=round(price - free, 2),
                   text=f"${price - free:,.0f} more in the treasury for evaluation #{len(rows) + 1}"
                        + (f" · expected by {eta} from payouts" if eta else " · no payout scheduled yet to cover it"))
    funded = sum(r["stage"] in ("funded", "payout ready") for r in rows)
    return {"accounts": rows, "pace": {"avg_day": round(avg, 2), "source": source, "qualify_rate": QUALIFY_RATE},
            "counts": {s: sum(r["stage"] == s for r in rows) for s in ("evaluation", "passing", "funded", "payout ready", "live", "failed")},
            "limit": limit, "eval_price": price, "next_eval": nxt, "coming": [{"eta": e, "amount": a, "account": n} for e, a, n in coming],
            "paid_out": round(sum(r.get("paid_out") or 0 for r in rows), 2),
            # a rough ceiling: every funded account paying its max each cycle (5 qualifying days)
            "monthly_ceiling": round(funded * 2000 * split * (21 * QUALIFY_RATE / 5), 0) if funded else 0}


def eval_goal(cfg: dict, plan_: dict) -> Optional[dict]:
    """The treasury goal for the next evaluation (None when there is no price or no room)."""
    price, nxt = cfg.get("eval_price"), plan_["next_eval"]
    if not price or not nxt["room"]:
        return None
    n = len(plan_["accounts"]) + 1
    return {"id": f"{GOAL_PREFIX}{n}", "name": f"Lucid evaluation #{n}", "monthly": float(price), "months": 1,
            "unit": "city", "one_time": True,
            "why": "Scale plan: another LucidFlex 50K trading the same bots. You buy it at Lucid and add it under 👥."}
