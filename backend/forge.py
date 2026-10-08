"""The Strategy Forge: new setups are found, tested honestly, shadow-traded on paper, and only go live when you approve.

  1. forge     every Saturday (markets closed), in its own process so trading never slows down: candidate
               settings are built from the strategy's tested filters (never new code), each one a change to
               what the bots trade with now
  2. test      each candidate is backtested on the saved 1m candles (TradingView's own when there are 15+ days,
               otherwise the saved Yahoo history). To pass it must beat the live settings on the first half of
               the training days AND the second half AND on the newest 30% it never saw while being chosen,
               without a worse worst day (by $200+) or more failed evaluations
  3. shadow    the best one that passes becomes the shadow. After every trading day (17:05 ET) that day's real
               candles are replayed with the live settings and with the shadow's: paper only, no orders
  4. vote      after 10 shadow days the desk's rules decide: the shadow must have beaten the live settings by
               $100+, with at least as many green days and a worst day no worse by $200+. If it did, a
               "Promote?" card goes to your approvals; if not, it's retired and next Saturday's forge tries again
  5. promote   only you can promote. The new settings switch in at the next session roll (18:00 ET, bots flat),
               are saved in data/strategy.json and survive restarts. Every promotion is logged

Only settings the bots read at decision time are searched (filters, sessions, confirmation, trims). The PROC
zone settings (pivot length, IFFVGs, proximity) match your TradingView chart and are never changed.
"""
from __future__ import annotations

import copy
import json
import os
import random
import sys
from datetime import date, datetime, timedelta
from typing import Optional

KNOBS = {
    "confirm_mode": ["pointer", "tap", "proc", None],
    "confirm_window": [3, 6, 9],
    "killzones": [["LONDON", "NY AM", "NY PM"], ["LONDON", "NY AM"], ["NY AM", "NY PM"], None],
    "require_liquidity_sweep": [False, True],
    "trim": [False, True],
    "min_range_pts": [0.0, 2.0, 4.0],
    "day_open_bias": [None, "discount", "trend"],
    "range_bias": [None, "discount"],
    "walk_after": [2, 3, 4],
}
CANDIDATES = 40
MIN_DAYS = 15
SHADOW_DAYS = 10
SHADOW_MAX_DAYS = 20
EDGE = 100.0          # the shadow must beat the live settings by at least this over its shadow days
WORST_SLACK = 200.0   # ...without a worst day more than this much worse


# ---------------------------------------------------------------- state (data/forge.json, data/strategy.json)
def _load(path: str, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def _save(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, path)


def state(data_dir: str) -> dict:
    return _load(os.path.join(data_dir, "forge.json"), {"runs": [], "shadow": None, "retired": [], "proposal": None})


def save_state(data_dir: str, doc: dict) -> None:
    _save(os.path.join(data_dir, "forge.json"), doc)


def live_params(data_dir: str) -> dict:
    """The owner-promoted overrides the live bots trade with ({} = the strategy's defaults)."""
    return _load(os.path.join(data_dir, "strategy.json"), {}).get("params", {})


def baseline(data_dir: str) -> dict:
    """The live settings, as a value for every searched knob."""
    from .bots.proc import DEFAULTS
    live = live_params(data_dir)
    return {k: copy.deepcopy(live.get(k, DEFAULTS[k])) for k in KNOBS}


def promote(data_dir: str, params: dict, why: str) -> dict:
    params = {k: v for k, v in params.items() if k in KNOBS}
    doc = _load(os.path.join(data_dir, "strategy.json"), {"params": {}, "history": []})
    doc["params"] = {**doc.get("params", {}), **params}
    doc.setdefault("history", []).append({"at": datetime.now().astimezone().isoformat(timespec="seconds"), "params": params, "why": why})
    _save(os.path.join(data_dir, "strategy.json"), doc)
    st = state(data_dir)
    st["shadow"], st["proposal"] = None, None
    save_state(data_dir, st)
    return doc


# ---------------------------------------------------------------- candidates
def candidates(base: dict, n: int = CANDIDATES, seed: int = 0) -> list[dict]:
    """Every one-setting change from the live settings, then random 2-3 setting changes (seeded, so a run repeats)."""
    out, seen = [], {json.dumps(base, sort_keys=True)}

    def add(c):
        key = json.dumps(c, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(c)
    for k, values in KNOBS.items():
        for v in values:
            add({**base, k: v})
    rng = random.Random(seed)
    tries = 0
    while len(out) < n and tries < 2000:
        tries += 1
        c = dict(base)
        for k in rng.sample(list(KNOBS), rng.choice([2, 3])):
            c[k] = rng.choice(KNOBS[k])
        add(c)
    return out[:n]


def diff(base: dict, cand: dict) -> dict:
    return {k: v for k, v in cand.items() if base.get(k) != v}


# ---------------------------------------------------------------- data
def load_data(data_dir: str) -> tuple[dict, str]:
    """1m candles for MNQ/MES (and M2K when present): TradingView's own once there are 15+ days, else Yahoo's."""
    from .backtest import load_csv, trading_day
    hist = os.path.join(data_dir, "history")
    tv = {s: os.path.join(hist, "tradingview", f"{s}_1m.csv") for s in ("MNQ", "MES")}
    if all(os.path.exists(p) for p in tv.values()):
        data = {s: load_csv(p) for s, p in tv.items()}
        if len({trading_day(r[0]) for r in data["MNQ"]}) >= MIN_DAYS:
            return data, "TradingView"
    data = {s: load_csv(os.path.join(hist, f"{s}_1m.csv")) for s in ("MNQ", "MES", "M2K")
            if os.path.exists(os.path.join(hist, f"{s}_1m.csv"))}
    return data, "Yahoo"


def _days(data: dict) -> list:
    from .backtest import trading_day
    return sorted({trading_day(r[0]) for rows in data.values() for r in rows})


def _slice(data: dict, days: list) -> dict:
    from .backtest import trading_day
    keep = set(days)
    return {s: [r for r in rows if trading_day(r[0]) in keep] for s, rows in data.items()}


# ---------------------------------------------------------------- the weekly forge
def _summary(r: dict) -> dict:
    return {k: r[k] for k in ("total", "days_traded", "profitable_day_pct", "worst_day", "best_day", "trades",
                              "win_rate", "profit_factor", "evals_failed")}


def _beats(c: dict, b: dict) -> bool:
    return (c["total"] > b["total"] and c["worst_day"] >= b["worst_day"] - WORST_SLACK
            and c["evals_failed"] <= b["evals_failed"])


def forge(data: dict, base: dict, seed: int = 0, run=None, n: int = CANDIDATES) -> dict:
    """Search, then check the finalists on both halves of the training days and on the held-out days."""
    from .backtest import run as backtest_run
    run = run or backtest_run
    days = _days(data)
    if len(days) < MIN_DAYS:
        return {"ok": False, "why": f"only {len(days)} days of candles saved; the forge needs {MIN_DAYS}"}
    cut = int(len(days) * 0.7)
    train, test = days[:cut], days[cut:]
    half_a, half_b = train[:len(train) // 2], train[len(train) // 2:]
    sets = {"train": _slice(data, train), "a": _slice(data, half_a), "b": _slice(data, half_b), "test": _slice(data, test)}
    base_res = {k: _summary(run(v, base)) for k, v in sets.items()}
    tried = []
    for c in candidates(base, n, seed):
        r = _summary(run(sets["train"], c))
        tried.append({"params": c, "train": r})
    keep = [t for t in tried if _beats(t["train"], base_res["train"])
            and t["train"]["profitable_day_pct"] >= base_res["train"]["profitable_day_pct"]]
    keep.sort(key=lambda t: (t["train"]["profitable_day_pct"], t["train"]["total"]), reverse=True)
    finalists = []
    for t in keep[:5]:
        for k in ("a", "b", "test"):
            t[k] = _summary(run(sets[k], t["params"]))
        t["passed"] = all(_beats(t[k], base_res[k]) for k in ("a", "b", "test"))
        t["change"] = diff(base, t["params"])
        finalists.append(t)
    passed = sorted((t for t in finalists if t["passed"]), key=lambda t: t["test"]["total"], reverse=True)
    return {"ok": True, "days": len(days), "first": str(days[0]), "last": str(days[-1]), "tried": len(tried),
            "beat_on_training": len(keep), "baseline": base_res, "finalists": finalists,
            "winner": passed[0] if passed else None}


def run_week(data_dir: str, today: Optional[date] = None) -> dict:
    """The Saturday job (run in its own process: python -m backend.forge DATA_DIR)."""
    today = today or date.today()
    data, source = load_data(data_dir)
    base = baseline(data_dir)
    res = forge(data, base, seed=today.toordinal())
    res.update(at=datetime.now().astimezone().isoformat(timespec="seconds"), source=source, week=str(today))
    st = state(data_dir)
    st["runs"] = (st.get("runs", []) + [{k: res.get(k) for k in ("at", "week", "ok", "why", "source", "days", "first", "last",
                                                                  "tried", "beat_on_training", "baseline", "winner")}])[-12:]
    if res.get("winner") and not st.get("shadow") and not st.get("proposal"):
        w = res["winner"]
        st["shadow"] = {"params": w["params"], "change": w["change"], "since": str(today), "backtest": {k: w[k] for k in ("a", "b", "test")},
                        "days": []}
    save_state(data_dir, st)
    return res


# ---------------------------------------------------------------- the shadow (paper only, replayed daily)
def replay_day(data: dict, key: date, params: Optional[dict], account=None) -> float:
    """Closed P&L of one trading day replayed with `params` (the two days before it warm the zones up)."""
    from .account import PropAccount
    from .backtest import ReplayMarket, trading_day
    from .engine import Engine
    window = {s: [r for r in rows if key - timedelta(days=3) <= trading_day(r[0]) <= key] for s, rows in data.items()}
    window = {s: rows for s, rows in window.items() if rows}
    if not window or "MNQ" not in window:
        return 0.0
    market = ReplayMarket(window)
    engine = Engine(market=market, account=copy.deepcopy(account) if account else PropAccount(), params=params or None)
    nxt = lambda: trading_day(market.timeline[market.i + 1][0])
    while market.has_next() and nxt() < key:
        engine.tick(trade=False)
    start = engine.account.balance
    while market.has_next():
        engine.tick()
    return round(engine.account.balance - start, 2)


def score_shadow_day(data_dir: str, key: date, data: Optional[dict] = None, replay=None) -> Optional[dict]:
    """After a trading day: replay it with the live settings and with the shadow's. Paper only."""
    st = state(data_dir)
    sh = st.get("shadow")
    if not sh or str(key) <= sh["since"] or any(d["day"] == str(key) for d in sh["days"]):
        return None
    replay = replay or replay_day
    if data is None:
        data, _ = load_data(data_dir)
    if key not in set(_days(data)):
        return None
    live = live_params(data_dir)
    row = {"day": str(key), "live": replay(data, key, live), "shadow": replay(data, key, {**live, **sh["change"]})}
    sh["days"].append(row)
    verdict = judge(sh)
    if verdict == "promote":
        st["proposal"] = {"params": sh["change"], "shadow": summary(sh), "since": sh["since"]}
    elif verdict == "retire":
        st.setdefault("retired", []).append({**summary(sh), "change": sh["change"], "since": sh["since"], "ended": str(key)})
        st["retired"] = st["retired"][-10:]
        st["shadow"] = None
    save_state(data_dir, st)
    return {"row": row, "verdict": verdict}


def summary(sh: dict) -> dict:
    live = [d["live"] for d in sh["days"]]
    shadow = [d["shadow"] for d in sh["days"]]
    return {"days": len(sh["days"]), "live_total": round(sum(live), 2), "shadow_total": round(sum(shadow), 2),
            "live_green": sum(x > 0 for x in live), "shadow_green": sum(x > 0 for x in shadow),
            "live_worst": min(live, default=0), "shadow_worst": min(shadow, default=0)}


def judge(sh: dict) -> Optional[str]:
    """None = keep watching · 'promote' = ask the owner · 'retire' = it didn't hold up."""
    s = summary(sh)
    if s["days"] < SHADOW_DAYS:
        return None
    good = (s["shadow_total"] >= s["live_total"] + EDGE and s["shadow_green"] >= s["live_green"]
            and s["shadow_worst"] >= s["live_worst"] - WORST_SLACK)
    if good:
        return "promote"
    return "retire" if s["days"] >= SHADOW_MAX_DAYS or s["shadow_total"] < s["live_total"] else None


def status(data_dir: str) -> dict:
    st = state(data_dir)
    sh = st.get("shadow")
    doc = _load(os.path.join(data_dir, "strategy.json"), {"params": {}, "history": []})
    return {"live": doc.get("params", {}), "promotions": doc.get("history", [])[-5:][::-1],
            "last_run": (st.get("runs") or [None])[-1], "shadow": {**sh, "summary": summary(sh)} if sh else None,
            "proposal": st.get("proposal"), "retired": st.get("retired", [])[-3:][::-1],
            "rules": {"min_days": MIN_DAYS, "shadow_days": SHADOW_DAYS, "edge": EDGE, "worst_slack": WORST_SLACK}}


if __name__ == "__main__":   # python -m backend.forge DATA_DIR
    out = run_week(sys.argv[1] if len(sys.argv) > 1 else "data",
                   date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None)
    print(json.dumps({k: out.get(k) for k in ("ok", "why", "source", "days", "tried", "beat_on_training")}))
    w = out.get("winner")
    print("winner:", json.dumps(w["change"]) if w else "none passed")
