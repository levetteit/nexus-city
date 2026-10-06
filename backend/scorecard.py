"""Live vs backtest: is paper trading doing what the backtest says it should?

Two checks run in live mode. Both show in the account panel and in the end-of-day
report pushed to your phone (report.py).

1. Replay check. When a day ends, its candles are downloaded again and replayed
   through the same bots, settings, news filter and account state. The paper
   trades and the replay should be the same trades. When they aren't, something
   in the live pipeline changed the outcome (late or missing candles, a
   restart, a bot switched on/off, a TradingView alert), and backtest numbers
   won't carry over to the real account until that's fixed.
2. Edge check. The paper days so far against the backtest: share of green days,
   average day and profit factor. A few days prove little; after 15-20 days a
   big gap means the edge isn't holding up live.

Every check is saved to data/paper_checks.json.
"""
from __future__ import annotations

import copy
import csv
import json
import os
from datetime import datetime, timedelta

from .backtest import ReplayMarket, trading_day
from .engine import Engine

# The 21-day real-data backtest the default settings came from (README, "Optimizing")
BASELINE = {"source": "21 real days, Sep 8 - Oct 5 2026", "profitable_day_pct": 71.4, "avg_day": 630.0,
            "profit_factor": 2.9, "win_rate": 49.3}
MATCH_MINUTES = 3   # a paper trade and a replay trade on the same bot and side this close together are the same trade


class Scorecard:
    def __init__(self, data_dir: str, news=None) -> None:
        self.data_dir = data_dir
        self.news = news
        self.path = os.path.join(data_dir, "paper_checks.json")
        self.checks: list[dict] = []
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.checks = json.load(f)
        self.running = False
        self._day = None

    # ---------------------------------------------------------------- following the live day
    def start_day(self, engine, partial: bool = False) -> None:
        """Remember how the day started so it can be replayed. `partial`: the server came up mid-day."""
        m = engine.market
        self._day = {"day": trading_day(m.now), "account": copy.deepcopy(engine.account),
                     "enabled": {b.cfg.id: b.status != "disabled" for b in engine.bots.values()},
                     "partial": partial, "trades": [], "toggled": False}

    def observe(self, engine, events: list[dict]) -> dict | None:
        """Feed every tick's events. Returns the finished day (to `replay`) when a new day starts."""
        if self._day is None:
            return None
        finished = None
        m = engine.market
        for ev in events:
            if ev["type"] == "new_session":
                finished = self._day
                self.start_day(engine)
            elif ev["type"] == "trade_open":
                side = "long" if ev["contract"].endswith("LONG") else "short"
                self._day["trades"].append({"bot": ev["bot"], "side": side, "at": m.now.isoformat(), "pnl": None})
            elif ev["type"] == "trade_close":
                for t in reversed(self._day["trades"]):
                    if t["bot"] == ev["bot"] and t["pnl"] is None:
                        t["pnl"] = ev.get("trade_pnl", ev["pnl"])
                        break
            elif ev["type"] == "tv_signal":
                self._day["toggled"] = True
            elif ev["type"] == "desk_mode":
                self._day["desk"] = ev["mode"]
        return finished

    def toggled(self) -> None:
        """A bot was switched on/off by hand: the replay starts with the day's original line-up."""
        if self._day:
            self._day["toggled"] = True

    # ---------------------------------------------------------------- the replay
    def replay(self, day: dict, data: dict[str, list] | None = None) -> dict:
        """Replay a finished day on freshly downloaded candles and compare. Blocking; run in a thread."""
        self.running = True
        try:
            return self._replay(day, data)
        finally:
            self.running = False

    def _replay(self, day: dict, data: dict[str, list] | None) -> dict:
        key = day["day"]
        if data is None:
            from .fetch_data import SOURCES, fetch_recent
            from .live import _rows
            data = {s: _rows(fetch_recent(src, "5d")) for s, src in SOURCES.items()}
        # the day itself plus the two days before it, so FFVGs and swings are in place at the open
        data = {s: [r for r in rows if key - timedelta(days=3) <= trading_day(r[0]) <= key]
                for s, rows in data.items()}
        data = {s: rows for s, rows in data.items() if rows}
        market = ReplayMarket(data)
        engine = Engine(market=market, account=copy.deepcopy(day["account"]), news=self.news)
        for bot_id, on in day["enabled"].items():
            if bot_id in engine.bots:
                engine.bots[bot_id].status = "scanning" if on else "disabled"
        nxt = lambda: trading_day(market.timeline[market.i + 1][0])
        while market.has_next() and nxt() < key:
            engine.tick(trade=False)
        market._day_key = key   # the live account already rolled into this day: don't roll it again
        for bot in engine.bots.values():
            bot.new_session()
        replay: list[dict] = []
        while market.has_next() and nxt() == key:
            for ev in engine.tick():
                if ev["type"] == "trade_open":
                    side = "long" if ev["contract"].endswith("LONG") else "short"
                    replay.append({"bot": ev["bot"], "side": side, "at": market.now.isoformat(), "pnl": None})
                elif ev["type"] == "trade_close":
                    for t in reversed(replay):
                        if t["bot"] == ev["bot"] and t["pnl"] is None:
                            t["pnl"] = ev.get("trade_pnl", ev["pnl"])
                            break
        return self._compare(day, replay)

    def _compare(self, day: dict, replay: list[dict]) -> dict:
        live = [t for t in day["trades"] if t["pnl"] is not None]
        replay = [t for t in replay if t["pnl"] is not None]
        unmatched = list(replay)
        matched, only_live = 0, []
        for t in live:
            at = datetime.fromisoformat(t["at"])
            hit = next((r for r in unmatched if r["bot"] == t["bot"] and r["side"] == t["side"]
                        and abs((datetime.fromisoformat(r["at"]) - at).total_seconds()) <= MATCH_MINUTES * 60), None)
            if hit:
                unmatched.remove(hit)
                matched += 1
            else:
                only_live.append(t)
        label = lambda t: f"{t['bot']} {t['side']} {datetime.fromisoformat(t['at']):%H:%M} {'+' if t['pnl'] >= 0 else '-'}${abs(t['pnl']):,.0f}"
        live_pnl = round(sum(t["pnl"] for t in live), 2)
        replay_pnl = round(sum(t["pnl"] for t in replay), 2)
        same = not only_live and not unmatched and abs(live_pnl - replay_pnl) <= max(50.0, 0.1 * abs(replay_pnl))
        why = []
        if day["partial"]:
            why.append("server restarted during the day")
        if day["toggled"]:
            why.append("a bot was switched on/off or a TradingView alert traded")
        if day.get("desk"):
            why.append(f"the desk set {day['desk'].replace('_', ' ')} (the replay trades in normal mode)")
        check = {"day": day["day"].isoformat(), "live_pnl": live_pnl, "replay_pnl": replay_pnl,
                 "live_trades": len(live), "replay_trades": len(replay), "matched": matched,
                 "only_live": [label(t) for t in only_live], "only_replay": [label(t) for t in unmatched],
                 "verdict": "match" if same else "drift", "explained_by": why,
                 "desk": day.get("desk"),   # with a desk mode on, live - replay = what the mode cost (-) or saved (+)
                 "desk_effect": round(live_pnl - replay_pnl, 2) if day.get("desk") else None}
        self.checks = [c for c in self.checks if c["day"] != check["day"]] + [check]
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.checks, f, indent=1)
        return check

    # ---------------------------------------------------------------- the edge check
    def edge(self, account) -> dict:
        days = [pnl for _, pnl in account.day_history]
        traded = [d for d in days if d != 0]
        wins = losses = 0.0
        n = won = 0
        path = os.path.join(self.data_dir, "paper_trades.csv")
        if os.path.exists(path):
            with open(path, newline="") as f:
                for row in csv.DictReader(f):
                    p = float(row["pnl"])
                    if not row["reason"].startswith("trim"):   # a trim is part of the trade after it
                        n += 1
                        won += p > 0
                    wins += max(p, 0)
                    losses += min(p, 0)
        return {"days": len(traded),
                "profitable_day_pct": round(100 * sum(d > 0 for d in traded) / len(traded), 1) if traded else None,
                "avg_day": round(sum(traded) / len(traded), 2) if traded else None,
                "profit_factor": round(wins / -losses, 2) if losses < 0 else None,
                "win_rate": round(100 * won / n, 1) if n else None,
                "trades": n}

    def status(self, account) -> dict:
        real = [c for c in self.checks if not c["explained_by"]]
        trades = sum(c["replay_trades"] for c in real)
        return {"paper": self.edge(account), "backtest": BASELINE,
                "checks": len(self.checks), "clean_days_matched": sum(c["verdict"] == "match" for c in real),
                "clean_days": len(real),
                "trade_match_pct": round(100 * sum(c["matched"] for c in real) / trades, 1) if trades else None,
                "last": self.checks[-1] if self.checks else None, "running": self.running}
