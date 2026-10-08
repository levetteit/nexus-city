"""Signal check: do the bots' PROCs match Andrew Macre's indicator on your chart?

The PROC engine (bots/proc.py) is a rebuild of the TradingView indicators, so the
backtest is only as good as that rebuild. Every day this logs:

* each PROC a bot actually traded: timeframe, side, the FFVG/IFFVG it reacted to,
  the pointer candle, the entry, plus the candles around it for a mini chart;
* how many PROCs the engine saw per killzone and timeframe (traded or not).

In the app (🎯 Signal check) you mark each traded PROC ✅ "my indicator shows it"
or ❌ "not on my chart", and add PROCs your indicator printed that the bots
missed. Agreement stats and the mismatches show where the rebuild differs.
Saved per day in data/signals/YYYY-MM-DD.json.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

from .persist import write_json_atomic
from .backtest import ET, trading_day

SESSIONS = {"LONDON": (2 * 60, 5 * 60), "NY AM": (9 * 60 + 30, 11 * 60), "NY PM": (14 * 60, 16 * 60)}
BEFORE, AFTER = 40, 12   # candles of the PROC's timeframe kept around it for the mini chart


def _clock(minute: int) -> str:
    return datetime.fromtimestamp(minute * 60, tz=timezone.utc).astimezone(ET).strftime("%H:%M")


def _session(minute: int) -> str | None:
    t = datetime.fromtimestamp(minute * 60, tz=timezone.utc).astimezone(ET)
    mod = t.hour * 60 + t.minute
    return next((name for name, (a, b) in SESSIONS.items() if a <= mod < b), None)


class SignalLog:
    def __init__(self, data_dir: str, symbol: str = "MNQ") -> None:
        self.dir = os.path.join(data_dir, "signals")
        self.symbol = symbol
        self.day: dict | None = None
        self._seen: set = set()

    # ---------------------------------------------------------------- recording
    def start_day(self, engine) -> None:
        self.day = {"day": trading_day(engine.market.now).isoformat(), "signals": [], "counts": {}, "votes": {}, "missed": []}
        self._seen = set()

    def observe(self, engine, events: list[dict]) -> None:
        if self.day is None:
            return
        for bot in engine.bots.values():   # every PROC the engine saw, for the per-session counts
            if bot.cfg.underlying != self.symbol or not getattr(bot, "_events", None):
                continue
            for kind, p in bot._events:
                key = (p.tf, p.time, p.side)
                if kind == "proc" and key not in self._seen:
                    self._seen.add(key)
                    session = _session(p.time)
                    if session:
                        c = self.day["counts"].setdefault(session, {})
                        c[f"{p.tf}m"] = c.get(f"{p.tf}m", 0) + 1
        for ev in events:
            if ev["type"] == "new_session":
                self.finish(engine)
                self.start_day(engine)
            elif ev["type"] == "trade_open":
                bot = engine.bots.get(ev["bot"])
                p = getattr(bot, "my_proc", None)
                if bot is None or bot.cfg.underlying != self.symbol or p is None:
                    continue
                z = p.zone
                persona = bot.cfg.persona or {}
                self.day["signals"].append({
                    "id": f"{p.tf}-{p.time}-{p.side}", "bot": bot.cfg.id, "handle": persona.get("handle", bot.cfg.name),
                    # p.time is the pointer candle's last minute; TradingView labels candles by their open
                    "tf": p.tf, "side": p.side, "t": p.time, "clock": _clock(p.time - p.time % p.tf),
                    "closed": _clock(p.time + 1), "session": _session(p.time),
                    "box": {"high": p.high, "low": p.low},
                    "zone": {"kind": z.kind, "tf": z.tf, "side": z.side, "top": z.top, "bottom": z.bottom, "created": z.created},
                    "entry": ev["entry"], "entry_t": engine.market.underlyings[self.symbol].bars[-1].t,
                    "note": ev.get("note", ""), "candles": []})
                self.save()

    def finish(self, engine) -> None:
        """At the day roll: attach the candles around each signal (including the ones after it) and save."""
        if self.day is None:
            return
        rows = []
        for t, bars in getattr(engine.market, "timeline", []):
            row = bars.get(self.symbol)
            if row:
                rows.append((int(t.timestamp() // 60), row[1], row[2], row[3], row[4]))
        for s in self.day["signals"]:
            lo, hi = s["t"] - BEFORE * s["tf"], s["t"] + AFTER * s["tf"]
            s["candles"] = [list(r) for r in rows if lo <= r[0] <= hi]
        self.save()

    # ---------------------------------------------------------------- storage + review
    def _path(self, day: str) -> str:
        date.fromisoformat(day)   # also keeps the path inside data/signals
        return os.path.join(self.dir, f"{day}.json")

    def save(self) -> None:
        if self.day:
            os.makedirs(self.dir, exist_ok=True)
            write_json_atomic(self._path(self.day["day"]), self.day)

    def get(self, day: str) -> dict | None:
        if self.day and self.day["day"] == day:
            return self.day
        try:
            path = self._path(day)
        except ValueError:
            return None
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def _write(self, doc: dict) -> None:
        if self.day and self.day["day"] == doc["day"]:
            self.day = doc
        os.makedirs(self.dir, exist_ok=True)
        write_json_atomic(self._path(doc["day"]), doc)

    def vote(self, day: str, sig_id: str, vote: str, note: str = "") -> dict:
        doc = self.get(day)
        if doc is None or not any(s["id"] == sig_id for s in doc["signals"]):
            raise KeyError("no such signal")
        if vote not in ("yes", "no", ""):
            raise ValueError("vote must be yes or no")
        if vote:
            doc["votes"][sig_id] = {"vote": vote, "note": note[:200]}
        else:
            doc["votes"].pop(sig_id, None)
        self._write(doc)
        return doc

    def add_missed(self, day: str, clock: str, tf: int, side: str, note: str = "") -> dict:
        doc = self.get(day)
        if doc is None:
            raise KeyError("no such day")
        datetime.strptime(clock, "%H:%M")
        if tf not in (1, 2, 3, 4, 5, 6) or side not in ("long", "short"):
            raise ValueError("timeframe 1-6 and side long/short")
        doc["missed"].append({"clock": clock, "tf": tf, "side": side, "note": note[:200]})
        self._write(doc)
        return doc

    def days(self, limit: int = 30) -> list[dict]:
        names = sorted((n for n in os.listdir(self.dir) if n.endswith(".json")), reverse=True)[:limit] \
            if os.path.isdir(self.dir) else []
        out = []
        for n in names:
            d = self.get(n[:-5])
            if d:
                votes = [v["vote"] for v in d["votes"].values()]
                out.append({"day": d["day"], "signals": len(d["signals"]), "reviewed": len(votes),
                            "yes": votes.count("yes"), "no": votes.count("no"), "missed": len(d["missed"]),
                            "procs_seen": sum(sum(c.values()) for c in d["counts"].values())})
        return out

    def stats(self) -> dict:
        days = self.days(365)
        yes, no = sum(d["yes"] for d in days), sum(d["no"] for d in days)
        return {"reviewed": yes + no, "match_pct": round(100 * yes / (yes + no), 1) if yes + no else None,
                "missed": sum(d["missed"] for d in days), "days": len(days)}
