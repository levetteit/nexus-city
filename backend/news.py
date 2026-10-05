"""High-impact news filter: no new trades around CPI, FOMC, NFP and the like.

These bots trade without a stop loss and exit only on a pointer against, so a
release that moves NQ 100+ points in a minute is the fastest way to blow a prop
account. Around every high-impact USD event the bots:

* take no new entries from `before` minutes ahead until `after` minutes after it
  (FOMC rate decisions and press conferences get `after_fomc`), and
* close open trades `flatten` minutes before it (STARNET_NEWS_FLATTEN=0 to hold instead).

The calendar is the free ForexFactory weekly feed (this week's events, refreshed
every few hours and cached in data/news_calendar.json, so past weeks pile up for
backtests). Add your own events in data/news_extra.json:
    [{"date": "2026-10-14T08:30:00-04:00", "title": "CPI m/m"}]
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
REFRESH_SECONDS = 6 * 3600   # the feed asks for few downloads; the week's events rarely change

BEFORE = int(os.getenv("STARNET_NEWS_BEFORE", "10"))
AFTER = int(os.getenv("STARNET_NEWS_AFTER", "15"))
AFTER_FOMC = int(os.getenv("STARNET_NEWS_AFTER_FOMC", "45"))
FLATTEN = int(os.getenv("STARNET_NEWS_FLATTEN", "2"))   # minutes before; 0 = keep open trades


@dataclass(frozen=True)
class NewsEvent:
    time: datetime    # ET
    title: str

    @property
    def fomc(self) -> bool:
        t = self.title.lower()
        return "fomc" in t or "federal funds" in t or "fed chair" in t

    @property
    def label(self) -> str:
        return f"{self.title} {self.time:%H:%M}"


class NewsCalendar:
    def __init__(self, events: list[NewsEvent] | None = None, data_dir: str | None = None,
                 before: int = BEFORE, after: int = AFTER, after_fomc: int = AFTER_FOMC, flatten: int = FLATTEN) -> None:
        self.before, self.after, self.after_fomc, self.flatten = before, after, after_fomc, flatten
        self.data_dir = data_dir
        self.events: list[NewsEvent] = sorted(set(events or []), key=lambda e: e.time)
        self.fetched_at = 0.0
        self.last_error = ""
        if data_dir:
            self._load_cache()

    # ---------------------------------------------------------------- queries
    def window(self, e: NewsEvent) -> tuple[datetime, datetime]:
        return (e.time - timedelta(minutes=self.before),
                e.time + timedelta(minutes=self.after_fomc if e.fomc else self.after))

    def blackout(self, now: datetime) -> Optional[NewsEvent]:
        """The event whose no-new-trades window `now` is in, if any."""
        for e in self.events:
            start, end = self.window(e)
            if start <= now < end:
                return e
            if start > now:
                break
        return None

    def flatten_for(self, now: datetime) -> Optional[NewsEvent]:
        """The event open trades should be closed for, if one is `flatten` minutes away or less."""
        if self.flatten <= 0:
            return None
        for e in self.events:
            if e.time - timedelta(minutes=self.flatten) <= now < e.time:
                return e
            if e.time > now:
                break
        return None

    def upcoming(self, now: datetime, hours: float = 24) -> list[NewsEvent]:
        end = now + timedelta(hours=hours)
        return [e for e in self.events if now - timedelta(minutes=self.after_fomc) <= e.time <= end]

    # ---------------------------------------------------------------- loading
    @staticmethod
    def parse(raw: list[dict], high_only: bool = True) -> list[NewsEvent]:
        out = []
        for r in raw:
            if high_only and (r.get("country") != "USD" or r.get("impact") != "High"):
                continue
            try:
                t = datetime.fromisoformat(r["date"]).astimezone(ET)
            except (KeyError, ValueError):
                continue
            out.append(NewsEvent(t, r.get("title", "news")))
        return out

    def _cache_path(self) -> str:
        return os.path.join(self.data_dir, "news_calendar.json")

    def _load_cache(self) -> None:
        events = list(self.events)
        for name, high_only in (("news_calendar.json", False), ("news_extra.json", False)):
            path = os.path.join(self.data_dir, name)
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        events += self.parse(json.load(f), high_only)
                except (OSError, ValueError) as exc:
                    self.last_error = f"{name}: {exc}"
        self.events = sorted(set(events), key=lambda e: e.time)

    def _save_cache(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        extra = set()
        path = os.path.join(self.data_dir, "news_extra.json")
        if os.path.exists(path):
            with open(path) as f:
                extra = set(self.parse(json.load(f), False))
        rows = [{"date": e.time.isoformat(), "title": e.title} for e in self.events if e not in extra]
        with open(self._cache_path(), "w") as f:
            json.dump(rows, f, indent=1)

    def refresh(self, force: bool = False) -> bool:
        """Download this week's calendar if the cached one is stale. Blocking; run in a thread."""
        if not force and time.time() - self.fetched_at < REFRESH_SECONDS:
            return False
        self.fetched_at = time.time()
        try:
            req = urllib.request.Request(FEED_URL, headers={"User-Agent": "starnet-city"})
            with urllib.request.urlopen(req, timeout=15) as r:
                fresh = self.parse(json.load(r))
        except Exception as exc:   # keep trading on the cached calendar
            self.last_error = f"calendar download failed: {exc}"[:200]
            return False
        self.last_error = ""
        self.events = sorted(set(self.events) | set(fresh), key=lambda e: e.time)
        if self.data_dir:
            self._save_cache()
        return True

    def status(self, now: Optional[datetime]) -> dict:
        hold = self.blackout(now) if now else None
        nxt = [e for e in self.upcoming(now, 72) if e.time >= now] if now else []
        return {"hold": hold.label if hold else None,
                "hold_until": self.window(hold)[1].strftime("%H:%M") if hold else None,
                "next": [{"time": e.time.strftime("%a %H:%M"), "title": e.title} for e in nxt[:5]],
                "error": self.last_error}
