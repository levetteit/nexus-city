"""The Lookout: watches the big contracts, NQ and ES, and never trades.

Macre reads the full-size charts (NQ / ES: the deep, high-volume books, where the wicks are the "true"
ones) for his setups and confirmations, then executes on the micros. The city does the same:

  * the price data is the full-size contracts: Yahoo's NQ=F / ES=F, or TradingView's NQ1! / ES1! charts
    (`LiveMarket.push` prefers a full-size chart over a micro one of the same market)
  * the Lookout runs the PROC read (FFVGs, taps, pointers, PROCs) on NQ and ES and says whether the two
    agree. It reads the same shared engines the trading bots use (`proc.shared_engine`), so when OG
    Pointer waits for "ES to confirm", it is reading the Lookout's ES read: one read, never a copy.
  * orders still go to MNQ / MES: the Lookout has no position, no contracts and sends nothing.
"""
from __future__ import annotations

from typing import Optional

from ..market import Bar, Market
from .base import Entry
from .proc import ProcBot, ProcEngine

TOGETHER_MIN = 10   # NQ and ES marks this close together (minutes) count as one move
QUIET_MIN = 30      # nothing on either chart for this long: quiet


def last_mark(e: Optional[ProcEngine]) -> Optional[tuple[int, str, str, int]]:
    """The newest pointer or PROC on this chart: (minute, kind, side, tf)."""
    if e is None:
        return None
    return next((r for r in reversed(e.recent) if r[1] in ("pointer", "proc")), None)


def describe(mark, clock=lambda t: "") -> str:
    if not mark:
        return "nothing yet"
    t, kind, side, tf = mark
    return f"{tf}m {'PROC' if kind == 'proc' else 'pointer'} {'↑' if side == 'long' else '↓'} {clock(t)}".rstrip()


class WatcherBot(ProcBot):
    strategy_name = "NQ/ES lookout"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.status != "disabled":
            self.status = "watching"
        self.last_event = "watching NQ and ES"
        self._ref: Optional[tuple[int, float]] = None   # (candle minute, city clock minute): for HH:MM labels

    def _hhmm(self, t: int) -> str:
        if not self._ref:
            return ""
        m = int(self._ref[1] - (self._ref[0] - t)) % (24 * 60)
        return f"{m // 60:02d}:{m % 60:02d}"

    def observe(self, bar: Bar, market: Market) -> None:
        super().observe(bar, market)
        self._ref = (bar.t, market.clock_min)
        a, b = self._chart, self._partner_chart
        for kind, p in self._events:
            if kind == "proc":
                self.last_event = self._call(a, p, self.partner, b)
        if self.partner is not None and self.partner.last_t == self.engine.last_t:
            for kind, p in self.partner._last_events:
                if kind == "proc" and p.tf in self.p["pointer_tfs"]:
                    self.last_event = self._call(b, p, self.engine, a)

    def _call(self, name: str, p, other: Optional[ProcEngine], other_name: str) -> str:
        arrow = "↑" if p.side == "long" else "↓"
        head = f"{name} {p.tf}m PROC {arrow} {self._hhmm(p.time)}"
        if other is None:
            return head
        if other.confirms(p.side, p.time - self.p["confirm_window"], "pointer"):
            return f"{head} · {other_name} is with it"
        return f"{head} · {other_name} not with it yet"

    def read(self) -> str:
        """NQ and ES together, split, or quiet: the one-line read for OG and the owner."""
        a, b = last_mark(self.engine), last_mark(self.partner)
        now = self.engine.last_t if self.engine and self.engine.last_t else 0
        fresh = [m for m in (a, b) if m and now - m[0] <= QUIET_MIN]
        if not fresh:
            return "quiet"
        if len(fresh) == 2 and abs(a[0] - b[0]) <= TOGETHER_MIN:
            if a[2] == b[2]:
                return f"together {'↑ (longs)' if a[2] == 'long' else '↓ (shorts)'}"
            return f"split: {self._chart} and {self._partner_chart} disagree, careful"
        m = fresh[0]
        who = self._chart if m is a else self._partner_chart
        return f"{who} {'↑' if m[2] == 'long' else '↓'} alone"

    # ---- never trades
    def on_bar(self, htf, ltf, market: Market) -> Optional[Entry]:
        return None

    def on_signal(self, sig: dict, market: Market) -> Optional[str]:
        return None

    def halt(self, reason: str, status: str, market: Market) -> None:
        """An account stop sends traders home; the lookout keeps watching."""

    def new_session(self) -> None:
        super().new_session()
        if self.status != "disabled":
            self.status = "watching"

    def set_enabled(self, enabled: bool, market: Market) -> None:
        self.status = "watching" if enabled else "disabled"

    def info(self) -> dict:
        a, b = self._chart, self._partner_chart
        e = self.engine
        return {"setup": self.last_event, "watcher": True, "read": self.read(),
                "marks": {a: describe(last_mark(e), self._hhmm), b: describe(last_mark(self.partner), self._hhmm)},
                "untapped_zones": len([z for z in (e.zones if e else []) if not z.dead and z.tapped_at is None]),
                "pointer_tfs": self.p["pointer_tfs"],
                "proc": (f"{a} {e.proc.tf}m {'bullish' if e.proc.side == 'long' else 'bearish'} "
                         f"{e.proc.low:,.2f}–{e.proc.high:,.2f}") if e and e.proc else None}

    def snapshot(self, market: Market) -> dict:
        out = super().snapshot(market)
        out.update(watcher=True, contracts=0, max_contracts=0, underlying=f"{self._chart}/{self._partner_chart}")
        return out

    def room(self, market: Market) -> dict:
        return {**super().room(market), "symbol": self._chart}

    def chart(self, market: Market, tf: int = 1, count: int = 180) -> dict:
        return {**super().chart(market, tf, count), "symbol": self._chart}
