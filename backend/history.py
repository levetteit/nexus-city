"""Keep every 1-minute candle: the history that future backtests and re-optimizing need.

Yahoo only serves the last ~30 days of 1-minute candles, so anything older is
gone unless it was saved. In live mode the server:

* backfills the last 29 days on startup (and merges them into what's saved),
* saves the newest few days again at every day roll,

into data/history/MNQ_1m.csv, MES_1m.csv and M2K_1m.csv: the same format the
backtester reads. Download them from the account panel or /api/history/MNQ.csv
and run:  python -m backend.backtest MNQ_1m.csv MES_1m.csv M2K_1m.csv
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone

from .backtest import ET, trading_day
from .fetch_data import SOURCES, fetch, fetch_recent, merge_write


class History:
    def __init__(self, data_dir: str) -> None:
        self.dir = os.path.join(data_dir, "history")
        self.saved_at: str | None = None
        self.last_error = ""
        self._status: dict[str, dict] = {}
        for sym in SOURCES:
            if os.path.exists(self.path(sym)):
                self._status[sym] = self._scan(sym)

    def path(self, symbol: str) -> str:
        return os.path.join(self.dir, f"{symbol}_1m.csv")

    def save(self, backfill: bool = False) -> None:
        """Merge new candles into the saved files. Blocking (network); run in a thread."""
        os.makedirs(self.dir, exist_ok=True)
        errors = []
        for sym, src in SOURCES.items():
            try:
                rows = fetch(src, 29) if backfill or not os.path.exists(self.path(sym)) else fetch_recent(src, "5d")
                if rows:
                    merge_write(self.path(sym), rows)
                self._status[sym] = self._scan(sym)
            except Exception as exc:   # Yahoo hiccup: the next save fills the gap (it re-reads 5 days)
                errors.append(f"{sym}: {exc}")
        self.last_error = "; ".join(errors)[:200]
        self.saved_at = datetime.now(timezone.utc).astimezone(ET).strftime("%Y-%m-%d %H:%M ET")

    def _scan(self, sym: str) -> dict:
        n, first, last, days = 0, None, None, set()
        with open(self.path(sym), newline="") as f:
            for r in csv.DictReader(f):
                t = datetime.fromtimestamp(int(float(r["time"])), tz=timezone.utc).astimezone(ET)
                first = first or t
                last = t
                days.add(trading_day(t))
                n += 1
        return {"candles": n, "days": len(days), "first": first.strftime("%Y-%m-%d") if first else None,
                "last": last.strftime("%Y-%m-%d %H:%M") if last else None}

    def status(self) -> dict:
        return {"symbols": self._status, "days": max((s["days"] for s in self._status.values()), default=0),
                "saved_at": self.saved_at, "error": self.last_error}
