"""Backtest and optimize the bots on real 1-minute candles.

The same bot code, prop account rules and daily goal/cap/stop as the live city
are replayed over historical data, so the numbers you get here are what the
city would have done.

Get data: open a 1-minute chart in TradingView (e.g. MNQ1!), scroll back as
far as your plan allows, then chart menu → "Export chart data…". Save one CSV
per symbol with the symbol in the file name (MNQ_1m.csv, MES_1m.csv, M2K_1m.csv).
Any CSV with time/open/high/low/close columns works (unix seconds or ISO times).

  python -m backend.backtest data/MNQ_1m.csv data/MES_1m.csv          # one run, current settings
  python -m backend.backtest data/*.csv --optimize                    # try setting combinations
  python -m backend.backtest --make-sample data/sample                # synthetic files to test the pipeline

The optimizer tunes on the first 70% of trading days and then reports how the
best settings did on the last 30%, which they never saw. Trust the second
number: settings that only shine on the days they were tuned on are fitted to
noise and won't hold up live.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .account import PropAccount
from .engine import Engine
from .market import FLAT_BY_MIN, SESSION_CLOSE_MIN, Bar, Market, Underlying, session_at

ET = ZoneInfo("America/New_York")
SYMBOLS = {"MNQ": 0.25, "MES": 0.25, "M2K": 0.10, "MYM": 1.0}   # tick sizes


# ---------------------------------------------------------------- data
def symbol_from_path(path: str) -> str:
    name = os.path.basename(path).upper()
    for sym in SYMBOLS:
        if sym in name:
            return sym
    raise SystemExit(f"can't tell the symbol from {path}; put MNQ / MES / M2K in the file name")


def _parse_time(value: str, naive_tz) -> datetime:
    value = value.strip()
    if re.fullmatch(r"\d+(\.\d+)?", value):
        ts = float(value)
        return datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc).astimezone(ET)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=naive_tz)).astimezone(ET)


def load_csv(path: str, naive_tz=ET) -> list[tuple[datetime, float, float, float, float]]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.lower().strip(): c for c in reader.fieldnames or []}
        tcol = cols.get("time") or cols.get("datetime") or cols.get("date") or cols.get("timestamp")
        if not tcol or not all(k in cols for k in ("open", "high", "low", "close")):
            raise SystemExit(f"{path}: need time, open, high, low, close columns (got {reader.fieldnames})")
        for r in reader:
            try:
                rows.append((_parse_time(r[tcol], naive_tz), float(r[cols["open"]]), float(r[cols["high"]]),
                             float(r[cols["low"]]), float(r[cols["close"]])))
            except (ValueError, TypeError):
                continue
    rows.sort(key=lambda x: x[0])
    return rows


def trading_day(t: datetime) -> date:
    """Futures trading day: anything from 18:00 ET belongs to the next day."""
    return t.date() + timedelta(days=1) if t.hour >= 18 else t.date()


def clock_min(t: datetime) -> int:
    """Minutes on the same scale as market.py: 18:00 = 1080, next day 16:45 = 2445."""
    m = t.hour * 60 + t.minute
    return m if t.hour >= 18 else m + 24 * 60


# ---------------------------------------------------------------- replay market
class ReplayMarket:
    """Plays recorded 1-minute candles through the same interface as `Market`."""

    anchor_signals = False   # real candles set the price; an alert's price never moves it

    def __init__(self, data: dict[str, list]) -> None:
        self.underlyings = {s: Underlying(s, rows[0][4], iv=0.2, vol=0.2, tick_size=SYMBOLS[s])
                            for s, rows in data.items() if rows}
        by_time: dict[datetime, dict[str, tuple]] = defaultdict(dict)
        for sym, rows in data.items():
            for row in rows:
                by_time[row[0]][sym] = row
        self.timeline = sorted(by_time.items())
        self.i = -1
        self.clock_min = 0
        self.clock_str = ""
        self.day = 0
        self._day_key = None
        self.now: datetime | None = None

    def has_next(self) -> bool:
        return self.i + 1 < len(self.timeline)

    def step(self) -> None:
        self.i += 1
        t, bars = self.timeline[self.i]
        self.now = t
        key = trading_day(t)
        if self._day_key is not None and key != self._day_key:
            self.day += 1
        self._day_key = key
        self.clock_min = clock_min(t)
        self.clock_str = t.strftime("%H:%M")
        for sym, rows in bars.items():
            u = self.underlyings[sym]
            # usually one candle; a live symbol catching up after a late delivery brings several, oldest first
            for rt, o, h, l, c in (rows if isinstance(rows, list) else [rows]):
                u.bars.append(Bar(o, h, l, c, rt.strftime("%H:%M"), int(rt.timestamp() // 60)))
                if len(u.bars) > 1200:
                    u.bars = u.bars[-1200:]
                u.bar_count += 1
                u.price = c
                u.history.append(c)
                if len(u.history) > 500:
                    u.history = u.history[-500:]

    @property
    def minutes_to_close(self) -> float:
        return SESSION_CLOSE_MIN - self.clock_min

    @property
    def minutes_to_flat(self) -> float:
        return FLAT_BY_MIN - self.clock_min

    @property
    def session(self) -> str:
        return session_at(self.clock_min)[1]


# ---------------------------------------------------------------- one run
def run(data: dict[str, list], params: dict | None = None, news=None, workers=None, payouts: bool = False) -> dict:
    """Replay `data` once. Failed or stuck evaluations are reset and counted, like buying a new one.
    `news` is an optional NewsCalendar (news.py): no trades around high-impact releases."""
    market = ReplayMarket(data)
    engine = Engine(market=market, account=PropAccount(), params=params, news=news, workers=workers)
    acct = engine.account
    trades, by_session, reasons = [], Counter(), Counter()
    open_session: dict[str, str] = {}
    passes = fails = funded_days = trims = 0
    paid: list[tuple[str, float]] = []
    last_day = 0
    while market.has_next():
        for ev in engine.tick():
            if ev["type"] == "trade_open":
                open_session[ev["bot"]] = market.session
            elif ev["type"] == "trade_close":
                whole = ev.get("trade_pnl", ev["pnl"])   # including any trims
                trades.append(whole)
                by_session[open_session.get(ev["bot"], "?")] += whole
                reasons[ev["reason"].split(":")[0]] += 1
            elif ev["type"] == "trade_trim":
                trims += 1
            elif ev["type"] == "new_session" and ev.get("phase_change"):
                passes += 1
        if market.day != last_day:
            last_day = market.day
            if acct.phase == "funded":
                funded_days += 1
            if payouts and acct.safe_payout:   # take the suggested payout as soon as it's there
                paid.append((str(trading_day(market.now)), acct.safe_payout))
                acct.take_payout(acct.safe_payout)
            if acct.phase == "failed" or "reset" in acct.halted:
                fails += 1
                engine.reset_account()   # keeps day_history
    days = [pnl for _, pnl in acct.day_history] + ([round(acct.day_realized, 2)] if acct.day_realized else [])
    traded = [d for d in days if d != 0]
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    return {
        "params": params or {},
        "days": len(days), "days_traded": len(traded),
        "profitable_day_pct": round(100 * sum(d > 0 for d in traded) / len(traded), 1) if traded else 0.0,
        "goal_days": sum(d >= acct.guards.daily_goal for d in traded),
        "total": round(sum(days), 2), "avg_day": round(sum(traded) / len(traded), 2) if traded else 0.0,
        "best_day": max(days, default=0), "worst_day": min(days, default=0),
        "trades": len(trades), "win_rate": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "evals_passed": passes, "evals_failed": fails,
        "pnl_by_session": {k: round(v, 2) for k, v in by_session.items()},
        "exits": dict(reasons), "trims": trims, "funded_days": funded_days,
        "payouts": paid, "take_home": round(0.9 * sum(a for _, a in paid), 2),
    }


# ---------------------------------------------------------------- optimizer
GRID = {
    "confirm_mode": [None, "tap", "pointer", "proc"],   # MNQ/MES correlation (None = off)
    "confirm_window": [3, 6],
    "pivot_len": [2, 6],
    "use_iffvg": [True, False],
    "require_liquidity_sweep": [False, True],
    "killzones": [None, ["LONDON", "NY AM"], ["NY AM", "NY PM"]],
}


def split_days(data: dict[str, list], frac: float) -> tuple[dict, dict]:
    keys = sorted({trading_day(r[0]) for rows in data.values() for r in rows})
    cut = keys[max(1, int(len(keys) * frac)) - 1]
    train = {s: [r for r in rows if trading_day(r[0]) <= cut] for s, rows in data.items()}
    test = {s: [r for r in rows if trading_day(r[0]) > cut] for s, rows in data.items()}
    return train, test


def score(res: dict) -> tuple:
    """Rank by share of profitable days, then total profit; runs that lose money rank last."""
    return (res["total"] > 0, res["days_traded"] >= 3, res["profitable_day_pct"], res["total"])


def _run_args(args):
    return run(*args)


def optimize(data: dict[str, list], jobs: int, top: int = 5) -> list[dict]:
    train, test = split_days(data, 0.7)
    combos = [dict(zip(GRID, values)) for values in itertools.product(*GRID.values())]
    print(f"trying {len(combos)} setting combinations on {len(_days(train))} training days "
          f"({len(_days(test))} held-out days for the check)…", file=sys.stderr)
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(_run_args, [(train, c) for c in combos], chunksize=4))
    results.sort(key=score, reverse=True)
    best = results[:top]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        checks = list(pool.map(_run_args, [(test, r["params"]) for r in best]))
    return [{"params": r["params"], "train": r, "test": t} for r, t in zip(best, checks)]


def _days(data: dict[str, list]) -> set:
    return {trading_day(r[0]) for rows in data.values() for r in rows}


# ---------------------------------------------------------------- sample data
def make_sample(folder: str, days: int = 15, seed: int = 7) -> None:
    """Write synthetic 1m CSVs (TradingView export format) to test the pipeline. Not real prices."""
    random.seed(seed)
    os.makedirs(folder, exist_ok=True)
    market = Market(sim_minutes_per_tick=0.25)
    writers, files, seen = {}, [], {s: 0 for s in market.underlyings}
    for s in market.underlyings:
        f = open(os.path.join(folder, f"{s}_1m_SAMPLE.csv"), "w", newline="")
        files.append(f)
        writers[s] = csv.writer(f)
        writers[s].writerow(["time", "open", "high", "low", "close"])
    start = datetime(2026, 9, 6, 18, 0, tzinfo=ET)   # a Sunday evening open
    while market.day < days:
        market.step()
        base = start + timedelta(days=market.day + 2 * (market.day // 5))   # skip weekends
        for s, u in market.underlyings.items():
            while seen[s] < u.bar_count:
                b = u.bars[-(u.bar_count - seen[s])]
                seen[s] += 1
                t = base + timedelta(minutes=market.clock_min - 18 * 60)
                writers[s].writerow([int(t.timestamp()), b.open, b.high, b.low, b.close])
    for f in files:
        f.close()
    print(f"wrote synthetic 1m files for {', '.join(market.underlyings)} to {folder}/ ({days} days)")


# ---------------------------------------------------------------- CLI
def _print_result(title: str, r: dict) -> None:
    print(f"\n{title}")
    print(f"  days traded {r['days_traded']}/{r['days']} · profitable days {r['profitable_day_pct']}% · "
          f"goal days (≥$600) {r['goal_days']}")
    print(f"  total ${r['total']:,.0f} · avg day ${r['avg_day']:,.0f} · best ${r['best_day']:,.0f} · worst ${r['worst_day']:,.0f}")
    print(f"  trades {r['trades']} · win rate {r['win_rate']}% · avg win ${r['avg_win']:,.0f} · "
          f"avg loss ${r['avg_loss']:,.0f} · profit factor {r['profit_factor']}")
    print(f"  evaluations passed {r['evals_passed']} · failed/reset {r['evals_failed']}")
    print(f"  P&L by session {r['pnl_by_session']} · exits {r['exits']}")
    if r.get("payouts"):
        print(f"  payouts {r['payouts']} · you keep (90%) ${r['take_home']:,.0f} over {r['funded_days']} funded days")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="1-minute CSVs, symbol in the file name")
    ap.add_argument("--optimize", action="store_true", help="search setting combinations (walk-forward)")
    ap.add_argument("--params", help='JSON of strategy settings for a single run, e.g. \'{"sessions": ["NEW YORK"]}\'')
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", help="write results as JSON here")
    ap.add_argument("--payouts", action="store_true", help="take the suggested payout whenever the funded account allows one")
    ap.add_argument("--news", metavar="JSON", help="news calendar (data/news_calendar.json format): skip trades around releases")
    ap.add_argument("--make-sample", metavar="FOLDER", help="write synthetic test files and exit")
    a = ap.parse_args()

    if a.make_sample:
        return make_sample(a.make_sample)
    if not a.files:
        ap.error("give at least one CSV (or --make-sample FOLDER)")
    data = {symbol_from_path(p): load_csv(p) for p in a.files}
    for s, rows in data.items():
        print(f"{s}: {len(rows):,} candles, {rows[0][0]:%Y-%m-%d %H:%M} → {rows[-1][0]:%Y-%m-%d %H:%M} ET", file=sys.stderr)

    if a.optimize:
        out = optimize(data, a.jobs)
        for i, r in enumerate(out, 1):
            print(f"\n#{i} settings: {json.dumps(r['params'])}")
            _print_result("  tuned on (first 70% of days):", r["train"])
            _print_result("  CHECK on unseen days (last 30%):", r["test"])
    else:
        cal = None
        if a.news:
            from .news import NewsCalendar
            with open(a.news) as f:
                cal = NewsCalendar(NewsCalendar.parse(json.load(f), high_only=False))
        out = run(data, json.loads(a.params) if a.params else None, cal, payouts=a.payouts)
        _print_result("backtest:", out)
    if a.out:
        with open(a.out, "w") as f:
            json.dump(out, f, indent=2, default=str)


if __name__ == "__main__":
    main()
