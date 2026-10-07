"""Keep every 1-minute candle: the history that future backtests and re-optimizing need.

Yahoo only serves the last ~30 days of 1-minute candles, so anything older is
gone unless it was saved. In live mode the server:

* backfills the last 29 days on startup (and merges them into what's saved),
* saves the newest few days again at every day roll,

into data/history/MNQ_1m.csv, MES_1m.csv and M2K_1m.csv: the same format the
backtester reads. Download them from the account panel or /api/history/MNQ.csv
and run:  python -m backend.backtest MNQ_1m.csv MES_1m.csv M2K_1m.csv

It also keeps the TradingView candles themselves (the real-time feed the bots trade on, which differs from
Yahoo's copy) as they arrive, with volume when the feed script sends it: data/history/tradingview/MNQ_1m.csv
and MES_1m.csv, same format, downloadable from the account panel or /api/history/tradingview/MNQ.csv.
Only candles from the day this started: TradingView's own export needs a Premium plan.
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
        self.tv_dir = os.path.join(self.dir, "tradingview")
        self._tv: dict[str, dict] = {}   # symbol -> {"candles", "days" (set), "first", "last", "last_t", "volume"}
        if os.path.isdir(self.tv_dir):
            for name in sorted(os.listdir(self.tv_dir)):
                if name.endswith("_1m.csv"):
                    self._tv[name[:-7]] = self._scan_tv(os.path.join(self.tv_dir, name))

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

    # ---------------------------------------------------------------- the TradingView feed's own candles
    def tv_path(self, symbol: str) -> str:
        return os.path.join(self.tv_dir, f"{symbol}_1m.csv")

    def record_feed(self, symbol: str, t: int, o: float, h: float, low: float, c: float, volume=None) -> bool:
        """Append one closed TradingView candle (once: a repeat or an older candle is skipped). Cheap: one line."""
        st = self._tv.get(symbol)
        if st is not None and t <= st["last_t"]:
            return False
        os.makedirs(self.tv_dir, exist_ok=True)
        path = self.tv_path(symbol)
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "open", "high", "low", "close", "volume"])
            w.writerow([int(t), o, h, low, c, "" if volume is None else volume])
        if st is None:
            st = self._tv[symbol] = {"candles": 0, "days": set(), "first": None, "last": None, "last_t": 0, "volume": False}
        self._note(st, int(t), volume is not None)
        return True

    @staticmethod
    def _note(st: dict, t: int, has_volume: bool) -> None:
        when = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(ET)
        st["candles"] += 1
        st["days"].add(trading_day(when))
        st["first"] = st["first"] or when.strftime("%Y-%m-%d")
        st["last"] = when.strftime("%Y-%m-%d %H:%M")
        st["last_t"] = t
        st["volume"] = st["volume"] or has_volume

    def _scan_tv(self, path: str) -> dict:
        st = {"candles": 0, "days": set(), "first": None, "last": None, "last_t": 0, "volume": False}
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                try:
                    self._note(st, int(float(r["time"])), bool(r.get("volume")))
                except (ValueError, TypeError, KeyError):
                    continue
        return st

    def status(self) -> dict:
        tv = {sym: {"candles": st["candles"], "days": len(st["days"]), "first": st["first"], "last": st["last"],
                    "volume": st["volume"]} for sym, st in self._tv.items()}
        return {"symbols": self._status, "days": max((s["days"] for s in self._status.values()), default=0),
                "saved_at": self.saved_at, "error": self.last_error,
                "tradingview": tv, "tv_days": max((x["days"] for x in tv.values()), default=0)}
