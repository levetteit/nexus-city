"""Download free 1-minute futures candles from Yahoo Finance for the backtester.

Yahoo keeps 1-minute history for about the last 30 days, served in chunks of
up to 8 days. Micro contracts track the full-size ones tick for tick (same
index, smaller multiplier), so NQ=F stands in for MNQ, ES=F for MES and
RTY=F for M2K.

  python -m backend.fetch_data --out data          # writes data/MNQ_1m.csv, MES_1m.csv, M2K_1m.csv

Run it every few weeks and it merges new candles into the existing files, so
your history keeps growing past Yahoo's 30-day window.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.request

SOURCES = {"MNQ": "NQ=F", "MES": "ES=F", "M2K": "RTY=F"}
URL = "https://query2.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&period1={p1}&period2={p2}&includePrePost=true"


def fetch(yahoo_symbol: str, days: int) -> dict[int, tuple]:
    now = int(time.time())
    start = now - days * 86_400 + 3_600
    rows: dict[int, tuple] = {}
    p1 = start
    while p1 < now:
        p2 = min(p1 + 7 * 86_400, now)
        req = urllib.request.Request(URL.format(sym=yahoo_symbol, p1=p1, p2=p2), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        result = (data.get("chart", {}).get("result") or [None])[0]
        if result and result.get("timestamp"):
            q = result["indicators"]["quote"][0]
            for i, ts in enumerate(result["timestamp"]):
                o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                if None not in (o, h, l, c) and ts % 60 == 0:   # skip the still-forming candle
                    rows[ts] = (o, h, l, c)
        p1 = p2
        time.sleep(0.5)
    return rows


def fetch_recent(yahoo_symbol: str, rng: str = "1d") -> dict[int, tuple]:
    """Latest closed 1m candles (Yahoo's CME futures data runs ~10 minutes behind)."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1m&range={rng}&includePrePost=true"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    result = (data.get("chart", {}).get("result") or [None])[0]
    rows: dict[int, tuple] = {}
    if result and result.get("timestamp"):
        q = result["indicators"]["quote"][0]
        for i, ts in enumerate(result["timestamp"]):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None not in (o, h, l, c) and ts % 60 == 0:
                rows[ts] = (o, h, l, c)
    if rows:
        rows.pop(max(rows))   # the newest candle may still be forming
    return rows


def merge_write(path: str, rows: dict[int, tuple]) -> int:
    if os.path.exists(path):
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                rows.setdefault(int(float(r["time"])), (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close"])
        for ts in sorted(rows):
            w.writerow([ts, *(round(v, 2) for v in rows[ts])])
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data")
    ap.add_argument("--days", type=int, default=29, help="how far back (Yahoo allows ~30 days of 1m data)")
    ap.add_argument("--symbols", nargs="*", default=list(SOURCES))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for sym in a.symbols:
        rows = fetch(SOURCES[sym], a.days)
        fetched = len(rows)
        total = merge_write(os.path.join(a.out, f"{sym}_1m.csv"), rows)
        print(f"{sym} ({SOURCES[sym]}): {fetched:,} candles fetched, {total:,} in {a.out}/{sym}_1m.csv", file=sys.stderr)


if __name__ == "__main__":
    main()
