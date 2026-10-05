"""Live paper trading: the city runs on real MNQ / MES / M2K candles as they print.

Start it with:  STARNET_MODE=live uvicorn backend.main:app

* Candles come from Yahoo Finance (NQ=F / ES=F / RTY=F stand in for the micros).
  Yahoo's CME futures feed runs about 10 minutes behind, so the bots act on
  real prices, just 10 minutes late. That's fine for forward testing and not
  for real money: a live account needs a real-time feed from your broker.
* On startup the bots read the last 2 days of candles without trading, so
  their FFVG / PROC structure is in place before the first live candle.
* Every closed paper trade goes to data/paper_trades.csv and every finished day
  to data/paper_days.csv. The prop account is saved to data/paper_account.json
  after each trade and day, and each bot's lifetime earnings (which unlock
  gadgets in its room) to data/paper_bots.json, so a restart picks up where it
  left off (open positions are not carried over a restart).
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone

from .account import PropAccount
from .backtest import ET, ReplayMarket
from .fetch_data import SOURCES, fetch_recent

DATA_DIR = os.getenv("STARNET_DATA_DIR", "data")
ACCOUNT_FIELDS = ("phase", "balance", "eod_high", "mll", "mll_locked", "best_day", "days",
                  "profitable_days", "day_realized", "day_history")


def _rows(raw: dict[int, tuple]) -> list[tuple]:
    return [(datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET), *ohlc) for ts, ohlc in sorted(raw.items())]


class LiveMarket(ReplayMarket):
    """A ReplayMarket whose timeline keeps growing as new candles are fetched."""

    def __init__(self, symbols: list[str] | None = None, warmup: str = "2d") -> None:
        self.symbols = symbols or list(SOURCES)
        data = {s: _rows(fetch_recent(SOURCES[s], warmup)) for s in self.symbols}
        data = {s: rows for s, rows in data.items() if rows}
        if not data:
            raise RuntimeError("no candles from Yahoo; check the network")
        super().__init__(data)
        self.last_seen = self.timeline[-1][0]
        self.warm_until = len(self.timeline)   # candles before this index are history, not traded
        self._pending: dict[datetime, dict[str, tuple]] = {}
        self._prev_day = 0
        self.last_push: datetime | None = None   # last candle from the real-time TradingView feed
        self._pushed: dict[str, datetime] = {}

    def poll(self) -> int:
        """Fetch the newest candles. Returns how many new timestamps are ready to step through."""
        for sym in self.symbols:
            for row in _rows(fetch_recent(SOURCES[sym], "1d")):
                if row[0] > self.last_seen:
                    self._pending.setdefault(row[0], {})[sym] = row
        return self._release()

    def _release(self) -> int:
        added = 0
        if not self._pending:
            return 0
        newest = max(self._pending)
        for t in sorted(self._pending):
            bars = self._pending[t]
            # release a minute once every symbol we expect has it, or once it's 2 minutes old (a symbol had
            # no trade). With the real-time feed on, only its symbols count: the rest come 10 minutes late.
            need = self.realtime_symbols or set(self.underlyings)
            if need <= set(bars) or (newest - t).total_seconds() >= 120:
                self.timeline.append((t, bars))
                self.last_seen = t
                del self._pending[t]
                added += 1
            else:
                break
        return added

    def push(self, symbol: str, ts: int, o: float, h: float, l: float, c: float) -> None:
        """A closed 1m candle pushed in real time (TradingView feed). Newer than Yahoo, so it wins."""
        if symbol not in self.underlyings:
            return
        row = (datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET), o, h, l, c)
        if row[0] > self.last_seen:
            self._pending.setdefault(row[0], {})[symbol] = row
        self.last_push = self._pushed[symbol] = datetime.now(timezone.utc)

    def release(self) -> int:
        """Move pushed/polled candles that are complete onto the timeline."""
        return self._release()

    def step(self) -> None:
        super().step()
        if self.day != self._prev_day:
            self._prev_day = self.day
            for u in self.underlyings.values():
                u.open_price = u.price

    @property
    def realtime_symbols(self) -> set[str]:
        now = datetime.now(timezone.utc)
        return {s for s, t in self._pushed.items() if (now - t).total_seconds() < 180}

    @property
    def feed(self) -> str:
        live = self.last_push and (datetime.now(timezone.utc) - self.last_push).total_seconds() < 180
        return "tradingview" if live else "yahoo"

    @property
    def delay_minutes(self) -> float:
        if not self.now:
            return 0.0
        return (datetime.now(timezone.utc) - self.now.astimezone(timezone.utc)).total_seconds() / 60


# ---------------------------------------------------------------- paper records
def load_account() -> PropAccount:
    acct = PropAccount()
    path = os.path.join(DATA_DIR, "paper_account.json")
    if os.path.exists(path):
        with open(path) as f:
            saved = json.load(f)
        for k in ACCOUNT_FIELDS:
            if k in saved:
                setattr(acct, k, [tuple(x) for x in saved[k]] if k == "day_history" else saved[k])
        acct._note(f"resumed paper account: balance ${acct.balance:,.0f}, day {acct.days}")
        acct._start_day()
    return acct


def save_account(acct: PropAccount) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "paper_account.json"), "w") as f:
        json.dump({k: getattr(acct, k) for k in ACCOUNT_FIELDS}, f, indent=1)


def load_careers(engine) -> None:
    """Restore each bot's lifetime earnings (and so its room gadgets)."""
    path = os.path.join(DATA_DIR, "paper_bots.json")
    if os.path.exists(path):
        with open(path) as f:
            saved = json.load(f)
        for bot_id, c in saved.items():
            if bot_id in engine.bots:
                engine.bots[bot_id].career, engine.bots[bot_id].career_best = c["career"], c["career_best"]


def save_careers(engine) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(os.path.join(DATA_DIR, "paper_bots.json"), "w") as f:
        json.dump({b.cfg.id: {"career": b.career, "career_best": b.career_best} for b in engine.bots.values()}, f, indent=1)


def _append(name: str, header: list[str], row: list) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, name)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(header)
        w.writerow(row)


def record(engine, events: list[dict]) -> None:
    """Write closed trades and finished days to the paper-trading logs."""
    market, acct = engine.market, engine.account
    changed = False
    for ev in events:
        if ev["type"] == "trade_close":
            t = engine.bots[ev["bot"]].trades[-1]
            _append("paper_trades.csv",
                    ["closed_at_et", "bot", "contract", "qty", "entry", "exit", "pnl", "reason", "opened_at"],
                    [market.now.strftime("%Y-%m-%d %H:%M"), t.bot_id, t.contract, t.qty, t.entry, t.exit,
                     t.pnl, t.reason, t.opened_at])
            changed = True
        elif ev["type"] == "new_session" and acct.day_history:
            phase, pnl = acct.day_history[-1]
            _append("paper_days.csv", ["day_ended_et", "phase", "pnl", "balance", "mll"],
                    [market.now.strftime("%Y-%m-%d"), phase, pnl, round(acct.balance, 2), round(acct.mll, 2)])
            changed = True
    if changed:
        save_account(acct)
        save_careers(engine)
