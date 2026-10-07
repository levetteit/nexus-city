"""Watchdog: tell your phone when something stops working, instead of finding out later.

Checked every loop in live mode (cheap, no network):
* a symbol that was on the TradingView real-time feed drops off it during market
  hours (alert expired or deleted, wrong secret after an edit) and when it's back
* no new candles at all for a while during market hours (feed and Yahoo both stuck)
* the server restarted with real positions open (they were closed on startup)
* a daily systems check at 08:30 ET on weekdays: all good, or what's wrong

If the whole server is down it can't warn you itself: point a free uptime monitor
(e.g. UptimeRobot) at https://<your-app>/healthz for that.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from .backtest import ET

FEED_GRACE_MIN = 5      # a known real-time symbol missing this long during market hours -> alert
STALL_MIN = 25          # no candle at all this long during market hours -> alert (Yahoo alone runs ~11 min late)
CHECK_AT = (8, 30)      # daily systems check, ET, weekdays


def market_open(now_et: datetime) -> bool:
    """CME equity futures: Sunday 18:00 to Friday 17:00 ET, closed 17:00-18:00 each weekday.
    (Exchange holidays aren't modelled: expect a false 'no candles' alert on those days.)"""
    wd, hm = now_et.weekday(), (now_et.hour, now_et.minute)
    if wd == 5:                                   # Saturday
        return False
    if wd == 6:                                   # Sunday: opens at 18:00
        return hm >= (18, 0)
    if wd == 4 and hm >= (17, 0):                 # Friday close
        return False
    return not ((17, 0) <= hm < (18, 0))          # daily maintenance break


class Watchdog:
    def __init__(self, data_dir: str) -> None:
        self.path = os.path.join(data_dir, "watchdog.json")
        self.expected: list[str] = []        # symbols seen on the real-time feed: they should stay there
        self.active: dict[str, str] = {}     # problem key -> message, while it lasts
        self.checked_on = ""
        if os.path.exists(self.path):
            with open(self.path) as f:
                saved = json.load(f)
            self.expected = saved.get("expected", [])
            self.checked_on = saved.get("checked_on", "")
        self._open_since: datetime | None = None

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"expected": self.expected, "checked_on": self.checked_on}, f)

    def forget_feed(self) -> None:
        """Stop expecting the TradingView feed (you removed it on purpose)."""
        self.expected = []
        self._save()

    # ---------------------------------------------------------------- the checks
    def check(self, market, router=None, desk=None, now: datetime | None = None) -> list[tuple[str, str]]:
        """Returns (title, body) pushes for problems that just started or just cleared."""
        now = now or datetime.now(timezone.utc)
        et = now.astimezone(ET)
        is_open = market_open(et)
        if not is_open:
            self._open_since = None
        elif self._open_since is None:
            self._open_since = now   # give the feed a few minutes after each open / after startup
        settled = self._open_since is not None and now - self._open_since >= timedelta(minutes=FEED_GRACE_MIN)

        live = set(market.realtime_symbols)
        new_expected = sorted(set(self.expected) | live)
        if new_expected != self.expected:
            self.expected = new_expected
            self._save()

        problems: dict[str, str] = {}
        if is_open and settled:
            for sym in self.expected:
                if sym not in live:
                    problems[f"feed:{sym}"] = (f"{sym} is off the TradingView real-time feed: its alert may have expired "
                                               f"or been deleted. The bots fall back to ~10-minute-late data.")
            last = market.timeline[-1][0] if getattr(market, "timeline", None) else None
            if last is not None and now - last.astimezone(timezone.utc) > timedelta(minutes=STALL_MIN):
                problems["stall"] = (f"No new candles since {last.astimezone(ET):%H:%M} ET while the market is open. "
                                     "The bots are blind until data comes back.")

        out: list[tuple[str, str]] = []
        for key, msg in problems.items():
            if key not in self.active:
                out.append(("🚨 Nexus City: data problem", msg))
        for key in list(self.active):
            if key not in problems:
                what = f"{key.split(':')[1]} is back on the real-time feed" if key.startswith("feed:") else "Candles are flowing again"
                out.append(("✅ Nexus City: fixed", what))
        self.active = problems

        if et.weekday() < 5 and (et.hour, et.minute) >= CHECK_AT and self.checked_on != et.date().isoformat():
            self.checked_on = et.date().isoformat()
            self._save()
            out.append(self.daily(market, router, desk, is_open))
        return out

    def daily(self, market, router, desk, is_open: bool) -> tuple[str, str]:
        live = sorted(market.realtime_symbols)
        lines = [f"Price data: {'TradingView real-time (' + ', '.join(live) + ')' if live else 'Yahoo, ~10 min late'}"]
        if self.active:
            lines += list(self.active.values())
        if router is not None:
            lines.append(f"Real orders: {'ARMED' if router.armed else 'off (paper only)'}"
                         + (f" · last error: {router.last_error}" if router.last_error else ""))
        if desk is not None:
            lines.append("Desk: " + ("on" if desk.enabled else "off (no ANTHROPIC_API_KEY)")
                         + (f" · last error: {desk.last_error}" if desk.enabled and desk.last_error else ""))
        lines.append("Renew your TradingView alerts before they expire.")
        ok = not self.active and live and not (router and router.last_error)
        return ("✅ Nexus City systems check: all good" if ok else "⚠️ Nexus City systems check: needs a look", "\n".join(lines))

    def status(self) -> dict:
        return {"expected_feed": self.expected, "problems": list(self.active.values()), "checked_on": self.checked_on}
