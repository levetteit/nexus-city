"""PROC (Pointer Range of Control): the Macre pointer strategy as the indicators
on your chart define it, rebuilt from 1-minute candles.

Spec (from the "PROC - Pointer Range of Control" publication, with FFVG rules
from Flux Charts' "Untapped FFVGs & IFFVGs" / "Troop Toolkit"):

  * Synthetic 1-6 minute candles are built from 1-minute data, aligned to the clock.
  * FFVG: the first fair value gap (3-candle imbalance) that forms after a
    confirmed swing low (bullish) or swing high (bearish) on any of the 1-6
    minute timeframes, within `sweep_proximity` candles of the swing.
    A swing low is a low below the `pivot_len` candles on each side.
  * Tapped: an FFVG is tapped the first time any 1-minute *wick* trades into
    it (closes don't matter). Once tapped it can't start a PROC again.
  * IFFVG: an FFVG that a candle on its own timeframe closes fully through
    flips into an opposite-direction IFFVG, untapped from that close. Its
    first wick can start a PROC like an FFVG. IFFVGs never re-invert.
  * Pointer: on the 3, 4, 5 and 6 minute candles, a candle that closes inside
    the previous candle's wick: above the previous body but at or below its
    high (bullish), or below the body but at or above its low (bearish).
  * PROC: a pointer whose candle - or the candle right before it - delivered
    the first-ever wick into a same-direction untapped FFVG/IFFVG. The pointer
    candle's range is the PROC box. Only one PROC exists at a time.
  * PROC invalidation: on the PROC's own timeframe, an opposite candle closes
    fully beyond the box (bearish close below a bullish box, and vice versa).

How the bot trades it (Macre's rules):
  * Enter on a PROC in its direction (3 contracts).
  * Another PROC in the same direction while in profit -> add 3 (6 max).
  * Exit only when a PROC forms against the trade: "a pointer against you on
    another FFVG/IFFVG". No stop loss.
  * An invalidated PROC the bot could have traded counts as a pointer inverse;
    `walk_after` of them in a session (Asia / London / New York) and the bot
    walks away until the next session.

MNQ/MES correlation (`confirm_with`): a PROC only becomes an entry (or an add)
when the partner market shows the same direction within `confirm_window`
minutes before or after it. `confirm_mode` sets how strict that is:
  "proc"     the partner printed its own PROC the same way (strictest)
  "pointer"  the partner printed a pointer the same way on 3-6m
  "tap"      the partner's wick tapped a same-direction FFVG/IFFVG
Exits never wait for confirmation.
"""
from __future__ import annotations

import weakref
from dataclasses import dataclass, field
from typing import Optional

from ..market import Bar, Market, aggregate
from .base import DONE_FOR_DAY, Bot, Entry

TIMEFRAMES = (1, 2, 3, 4, 5, 6)

# Troop Toolkit liquidity sessions (ET, minutes of day), used by the liquidity-sweep filter
KILLZONES = {
    "ASIA": (20 * 60, 24 * 60),
    "LONDON": (2 * 60, 5 * 60),
    "NY AM": (9 * 60 + 30, 11 * 60),
    "NY PM": (14 * 60, 16 * 60),
}


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    start: int          # first minute
    end: int            # last minute

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open


@dataclass
class Zone:
    side: str           # 'long' (bullish) | 'short' (bearish)
    top: float
    bottom: float
    tf: int
    kind: str           # 'FFVG' | 'IFFVG'
    created: int        # minute it became active
    tapped_at: Optional[int] = None
    dead: bool = False  # inverted (FFVG) or closed through (IFFVG)

    def label(self) -> str:
        return f"{self.tf}m {self.kind} {self.bottom:,.2f}–{self.top:,.2f}"


@dataclass
class Proc:
    side: str
    tf: int
    high: float
    low: float
    zone: Zone
    time: int
    swept: bool = False   # pointer candle (or the one before) took a killzone high/low


@dataclass
class _Frame:
    tf: int
    candles: list[Candle] = field(default_factory=list)
    building: Optional[Candle] = None
    fvgs: list[tuple[str, float, float, int]] = field(default_factory=list)   # side, top, bottom, candle idx
    swings: list[tuple[str, int]] = field(default_factory=list)               # pending: side, candle idx
    n: int = 0          # candles closed so far (absolute index)


def is_pointer(prev: Candle, cur: Candle) -> Optional[str]:
    if max(prev.open, prev.close) < cur.close <= prev.high:
        return "long"
    if prev.low <= cur.close < min(prev.open, prev.close):
        return "short"
    return None


class ProcEngine:
    """Feeds on 1-minute bars, emits ('proc', Proc) and ('invalidated', Proc) events."""

    def __init__(self, pointer_tfs=(3, 4, 5, 6), pivot_len: int = 2, sweep_proximity: int = 6,
                 use_iffvg: bool = True, min_gap: float = 0.0) -> None:
        self.pointer_tfs = tuple(pointer_tfs)
        self.pivot_len = pivot_len
        self.prox = sweep_proximity
        self.use_iffvg = use_iffvg
        self.min_gap = min_gap
        self.frames = {tf: _Frame(tf) for tf in TIMEFRAMES}
        self.zones: list[Zone] = []
        self.proc: Optional[Proc] = None
        self.levels: dict[str, tuple[float, float, bool, bool]] = {}   # killzone -> (hi, lo, hi swept, lo swept)
        self._kz: Optional[list] = None
        self.recent: list[tuple[int, str, str, int]] = []   # (minute, 'tap'|'pointer'|'proc', side, tf)
        self.last_t: Optional[int] = None
        self._last_events: list[tuple[str, Proc]] = []

    # ---------------------------------------------------------------- feed
    def update(self, bar: Bar, minute_of_day: int) -> list[tuple[str, Proc]]:
        """Feed one 1m bar. Engines are shared, so a bar already fed returns the same events."""
        if self.last_t is not None and bar.t <= self.last_t:
            return self._last_events if bar.t == self.last_t else []
        events: list[tuple[str, Proc]] = []
        t = bar.t
        # 1. first wick into an untapped zone
        for z in self.zones:
            if z.tapped_at is None and not z.dead and t > z.created:
                if (z.side == "long" and bar.low <= z.top) or (z.side == "short" and bar.high >= z.bottom):
                    z.tapped_at = t
                    self.recent.append((t, "tap", z.side, z.tf))
        self._track_liquidity(bar, minute_of_day)
        # 2. synthetic candles
        for tf in TIMEFRAMES:
            for done in self._build(self.frames[tf], bar):
                events += self._on_close(self.frames[tf], done)
        cutoff = t - 3 * 24 * 60
        self.zones = [z for z in self.zones if z.created > cutoff and not (z.dead and z.tapped_at)][-400:]
        self.recent = [r for r in self.recent if r[0] > t - 120]
        self.last_t, self._last_events = t, events
        return events

    def confirms(self, side: str, since: int, mode: str) -> bool:
        """Did this market show `side` since minute `since`? (for MNQ/MES correlation)"""
        kinds = {"proc": ("proc",), "pointer": ("pointer", "proc"), "tap": ("tap", "proc")}[mode]
        return any(t >= since and k in kinds and sd == side for t, k, sd, _ in self.recent)

    def _build(self, f: _Frame, bar: Bar) -> list[Candle]:
        """Add a 1m bar to this timeframe's candle; return any candles that closed."""
        closed = []
        if f.building and f.building.start // f.tf != bar.t // f.tf:   # missing minutes: close what we had
            closed.append(f.building)
            f.building = None
        if f.building is None:
            f.building = Candle(bar.open, bar.high, bar.low, bar.close, bar.t, bar.t)
        else:
            c = f.building
            c.high, c.low, c.close, c.end = max(c.high, bar.high), min(c.low, bar.low), bar.close, bar.t
        if (bar.t + 1) % f.tf == 0:   # its last minute just finished
            closed.append(f.building)
            f.building = None
        return closed

    def _on_close(self, f: _Frame, c: Candle) -> list[tuple[str, Proc]]:
        events: list[tuple[str, Proc]] = []
        f.candles.append(c)
        f.n += 1
        f.candles = f.candles[-60:]
        idx = f.n - 1

        # inversions on this timeframe
        for z in self.zones:
            if z.tf != f.tf or z.dead or z.created >= c.end:
                continue
            through = (z.side == "long" and c.close < z.bottom) or (z.side == "short" and c.close > z.top)
            if through:
                z.dead = True
                if self.use_iffvg and z.kind == "FFVG":
                    flip = "short" if z.side == "long" else "long"
                    self.zones.append(Zone(flip, z.top, z.bottom, f.tf, "IFFVG", c.end))

        # new FVG on this timeframe
        if len(f.candles) >= 3:
            c1, c3 = f.candles[-3], f.candles[-1]
            if c1.high < c3.low and c3.low - c1.high >= self.min_gap:
                f.fvgs.append(("long", c3.low, c1.high, idx))
            elif c1.low > c3.high and c1.low - c3.high >= self.min_gap:
                f.fvgs.append(("short", c1.low, c3.high, idx))
            f.fvgs = f.fvgs[-30:]

        # confirm a swing pivot_len candles back
        L = self.pivot_len
        if len(f.candles) >= 2 * L + 1:
            mid = f.candles[-L - 1]
            left, right = f.candles[-2 * L - 1:-L - 1], f.candles[-L:]
            if all(mid.low < x.low for x in left + right):
                f.swings.append(("long", idx - L))
            if all(mid.high > x.high for x in left + right):
                f.swings.append(("short", idx - L))
        # first FVG after each pending swing, within the sweep proximity
        keep = []
        for side, k in f.swings:
            first = next((g for g in f.fvgs if g[0] == side and k < g[3] <= k + self.prox), None)
            if first:
                _, top, bottom, gidx = first
                if not any(z.tf == f.tf and z.kind == "FFVG" and z.top == top and z.bottom == bottom for z in self.zones):
                    self.zones.append(Zone(side, top, bottom, f.tf, "FFVG", c.end))
            elif idx < k + self.prox:
                keep.append((side, k))
        f.swings = keep

        # pointer -> PROC
        if f.tf in self.pointer_tfs and len(f.candles) >= 2:
            prev = f.candles[-2]
            side = is_pointer(prev, c)
            if side:
                self.recent.append((c.end, "pointer", side, f.tf))
                hit = [z for z in self.zones if z.side == side and z.tapped_at is not None
                       and prev.start <= z.tapped_at <= c.end and z.created < z.tapped_at]
                if hit:
                    z = max(hit, key=lambda z: z.tapped_at)
                    swept = self._swept(side, prev, c)
                    self.proc = Proc(side, f.tf, c.high, c.low, z, c.end, swept)
                    self.recent.append((c.end, "proc", side, f.tf))
                    events.append(("proc", self.proc))

        # PROC invalidation on its own timeframe
        p = self.proc
        if p and p.tf == f.tf and p.time < c.end:
            if (p.side == "long" and c.bearish and c.close < p.low) or (p.side == "short" and c.bullish and c.close > p.high):
                events.append(("invalidated", p))
                self.proc = None
        return events

    # ---------------------------------------------------------------- liquidity
    def _track_liquidity(self, bar: Bar, mod: int) -> None:
        kz = next((k for k, (a, b) in KILLZONES.items() if a <= mod < b), None)
        if self._kz and self._kz[0] != kz:      # a killzone just finished: its high/low is liquidity
            name, hi, lo = self._kz
            self.levels[name] = (hi, lo, False, False)
            self._kz = None
        if kz:
            if self._kz is None:
                self._kz = [kz, bar.high, bar.low]
            else:
                self._kz[1], self._kz[2] = max(self._kz[1], bar.high), min(self._kz[2], bar.low)

    def _swept(self, side: str, prev: Candle, c: Candle) -> bool:
        lo, hi = min(prev.low, c.low), max(prev.high, c.high)
        for name, (h, l, hs, ls) in self.levels.items():
            if side == "long" and lo < l and not ls:
                self.levels[name] = (h, l, hs, True)
                return True
            if side == "short" and hi > h and not hs:
                self.levels[name] = (h, l, True, ls)
                return True
        return False

    def next_zone(self, side: str, price: float) -> Optional[float]:
        """Nearest opposite untapped zone in the trade's direction: where the move should run to."""
        if side == "long":
            lv = [z.bottom for z in self.zones if z.side == "short" and not z.dead and z.tapped_at is None and z.bottom > price]
            return min(lv) if lv else None
        lv = [z.top for z in self.zones if z.side == "long" and not z.dead and z.tapped_at is None and z.top < price]
        return max(lv) if lv else None


DEFAULTS = {
    "pointer_tfs": [3, 4, 5, 6],
    "pivot_len": 6,             # swing = low/high beyond this many candles each side (your chart: 6)
    "sweep_proximity": 6,       # your chart's setting: FFVG within 6 candles of the swing
    "use_iffvg": True,          # your chart has Untapped IFFVGs on
    "min_gap_ticks": 0,
    "walk_after": 3,            # invalidated PROCs (pointer inverses) in one session before walking away
    "exit_on_invalidation": False,   # Macre: exit only on a pointer against
    "add_on": "proc",           # when to add 3 contracts to a winner: 'proc' | 'pointer' (MNQ's own
                                # 3-6m pointer) | 'partner_pointer' (a pointer on the confirming market)
    "exit_min_tf": False,       # only a PROC against on the entry's timeframe or higher closes the trade
    # Entries only in these killzones (None = any time). On 21 days of real data
    # (Sep 8 - Oct 5 2026) this beat trading every session: Asia entries lost money.
    "killzones": ["LONDON", "NY AM", "NY PM"],
    "require_liquidity_sweep": False,  # PROC must take an Asia/London/NY high or low
    "confirm_with": None,       # partner symbol, e.g. "MES" for an MNQ bot
    "confirm_mode": "pointer",  # 'proc' | 'pointer' | 'tap' | None (off); 'pointer' tested best
    "confirm_window": 6,        # minutes before/after the PROC for the partner to agree
    "signals": "both",          # TradingView webhook orders still accepted
    # Higher-timeframe bias: only take a PROC that agrees with the latest `bias_kind`
    # ('proc' | 'pointer') on the `bias_tf` chart within `bias_window` minutes. None = off.
    "bias_tf": None,
    "bias_kind": "proc",
    "bias_window": 60,
    # Trims (partial profits): when price reaches the next untapped opposite FFVG/IFFVG
    # in the trade's direction, close part of the position and aim for the zone after it.
    # The last contract always runs until a pointer against.
    "trim": False,
    "trim_frac": 1 / 3,         # share of the open contracts to close at each zone (at least 1)
    "trim_fill": "limit",       # 'limit': resting order at the zone edge | 'close': market order after the candle
    "trim_min_tf": 1,           # only zones of this timeframe or higher count as trim levels
    "trim_min_pts": 0.0,        # ...and only once they're at least this many points from the entry
    "trim_max": None,           # most trims per trade (None = no limit)
    # Context filters (experiments, all off by default; see README "Context filters"):
    "rsi_filter": None,         # {"tf": 5, "period": 14, "ob": 70, "os": 30, "mode": "exhaustion"|"momentum"}
    "day_open_bias": None,      # ICT true day open (00:00 ET): "discount" = longs below it, shorts above; "trend" = the reverse
    "range_bias": None,         # previous trading day's range: "discount" = longs in its lower half, shorts upper; "trend" = reverse
    "min_range_pts": 0.0,       # chop filter: average 1m high-low over the last 30 minutes must be at least this
}

# One engine per (market, symbol, settings), shared by every bot that needs it
_ENGINES: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def shared_engine(market: Market, symbol: str, p: dict) -> ProcEngine:
    engines = _ENGINES.setdefault(market, {})
    tick = market.underlyings[symbol].tick_size
    key = (symbol, p["pivot_len"], p["sweep_proximity"], p["use_iffvg"], p["min_gap_ticks"])
    if key not in engines:
        engines[key] = ProcEngine((3, 4, 5, 6), p["pivot_len"], p["sweep_proximity"],
                                  p["use_iffvg"], p["min_gap_ticks"] * tick)
    return engines[key]


class ProcBot(Bot):
    strategy_name = "Macre PROC"
    uses_htf = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.p = {**DEFAULTS, **self.cfg.params}
        self.engine: Optional[ProcEngine] = None
        self.partner: Optional[ProcEngine] = None
        self._events: list[tuple[str, Proc]] = []
        self.pending: list[Proc] = []    # PROCs waiting for the partner market to confirm
        self.candidates: list[Proc] = [] # PROCs that passed this bot's filters (for counting inverses)
        self.my_proc: Optional[Proc] = None
        self.trim_target: Optional[float] = None
        self.trims_done = 0
        self.trim_last: Optional[float] = None
        self._session = ""
        self.last_signal = ""
        self._day_open: Optional[float] = None       # 00:00 ET open
        self._day_hi = self._day_lo = None             # this trading day so far (from 18:00 ET)
        self._prev_range: Optional[tuple[float, float]] = None
        self.reset_day()

    def reset_day(self) -> None:
        self.inverses = 0
        self.pending = []
        self.last_event = "waiting for a PROC"

    @property
    def _confirming(self) -> bool:
        return bool(self.p["confirm_with"] and self.p["confirm_mode"])

    def observe(self, bar: Bar, market: Market) -> None:
        mod = int(market.clock_min) % (24 * 60)
        self._track_day(bar, mod)
        self.engine = shared_engine(market, self.cfg.underlying, self.p)
        tfs = self.p["pointer_tfs"]
        self._events = [(k, p) for k, p in self.engine.update(bar, mod) if p.tf in tfs]
        partner = self.p["confirm_with"]
        if self._confirming and partner in market.underlyings and market.underlyings[partner].bars:
            self.partner = shared_engine(market, partner, self.p)
            self.partner.update(market.underlyings[partner].bars[-1], mod)
        if market.session != self._session:   # each session starts with a clean walk-away count
            self._session = market.session
            self.inverses = 0
            if self.status == "walked":
                self.status = "scanning"
                self.last_event = f"{market.session} open · back on shift"
        for kind, p in self._events:
            if kind == "invalidated" and p in self.candidates:
                self.candidates.remove(p)
                self.inverses += 1
                if self.status not in DONE_FOR_DAY:
                    self.last_event = f"{p.tf}m PROC invalidated ({self.inverses}/{self.p['walk_after']})"
                if self.inverses >= self.p["walk_after"] and self.status == "scanning":
                    self.status = "walked"
                    self.last_event = f"{self.inverses} pointer inverses · walked away until next session"

    def _bias_ok(self, p: Proc) -> bool:
        tf = self.p["bias_tf"]
        if not tf:
            return True
        kinds = ("proc",) if self.p["bias_kind"] == "proc" else ("proc", "pointer")
        for t, k, side, ptf in reversed(self.engine.recent):
            if ptf == tf and k in kinds and p.time - self.p["bias_window"] <= t <= p.time:
                return side == p.side
        return False

    def _track_day(self, bar: Bar, mod: int) -> None:
        if mod == 18 * 60 and self._day_hi is not None:   # the futures day opens at 18:00 ET
            self._prev_range, self._day_hi, self._day_lo = (self._day_lo, self._day_hi), None, None
        self._day_hi = bar.high if self._day_hi is None else max(self._day_hi, bar.high)
        self._day_lo = bar.low if self._day_lo is None else min(self._day_lo, bar.low)
        if mod == 0:
            self._day_open = bar.open

    def _rsi(self, market: Market, tf: int, period: int) -> Optional[float]:
        closes = [b.close for b in aggregate(market.underlyings[self.cfg.underlying].bars[-(period * 4 * tf):], tf)]
        if len(closes) < period + 1:
            return None
        gains = losses = 0.0
        for a, b in zip(closes[-period - 1:-1], closes[-period:]):
            gains += max(0.0, b - a)
            losses += max(0.0, a - b)
        return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)

    def _context_ok(self, p: Proc, market: Market) -> bool:
        """Optional context filters. Each one is off unless its setting is given."""
        price = market.underlyings[self.cfg.underlying].price
        long = p.side == "long"
        rf = self.p["rsi_filter"]
        if rf:
            r = self._rsi(market, rf.get("tf", 5), rf.get("period", 14))
            if r is not None:
                if rf.get("mode", "exhaustion") == "momentum":
                    if (long and r < 50) or (not long and r > 50):
                        return False
                elif (long and r >= rf.get("ob", 70)) or (not long and r <= rf.get("os", 30)):
                    return False
        for key, level in (("day_open_bias", self._day_open),
                           ("range_bias", sum(self._prev_range) / 2 if self._prev_range else None)):
            mode = self.p[key]
            if mode and level is not None:
                below = price < level
                if mode == "discount" and below != long:
                    return False
                if mode == "trend" and below == long:
                    return False
        if self.p["min_range_pts"]:
            recent = market.underlyings[self.cfg.underlying].bars[-30:]
            if recent and sum(b.high - b.low for b in recent) / len(recent) < self.p["min_range_pts"]:
                return False
        return True

    def _usable(self, p: Proc, market: Market) -> bool:
        if not self._bias_ok(p) or not self._context_ok(p, market):
            return False
        kz = self.p["killzones"]
        if kz:
            mod = int(market.clock_min) % (24 * 60)
            if not any(KILLZONES[k][0] <= mod < KILLZONES[k][1] for k in kz):
                return False
        return p.swept or not self.p["require_liquidity_sweep"]

    def _confirmed(self, p: Proc) -> bool:
        if not self._confirming:
            return True
        if self.partner is None:      # no partner data (e.g. a backtest with one symbol): can't filter
            return True
        return self.partner.confirms(p.side, p.time - self.p["confirm_window"], self.p["confirm_mode"])

    def _new_procs(self, market: Market) -> list[Proc]:
        """PROCs ready to act on: new confirmed ones, plus pending ones the partner just confirmed."""
        now = self.engine.last_t or 0
        ready = []
        for kind, p in self._events:
            if kind != "proc":
                continue
            arrow = "↑" if p.side == "long" else "↓"
            if not self._usable(p, market):
                self.last_event = f"{p.tf}m PROC {arrow} at {market.clock_str} · filtered out"
                continue
            self.candidates = (self.candidates + [p])[-10:]
            self.pending = [q for q in self.pending if q.side == p.side]   # an opposite PROC cancels waiting ones
            if self._confirmed(p):
                ready.append(p)
            else:
                self.pending.append(p)
                self.last_event = (f"{p.tf}m PROC {arrow} at {market.clock_str} · waiting for "
                                   f"{self.p['confirm_with']} to confirm ({self.p['confirm_mode']})")
        still = []
        for q in self.pending:
            if q in ready:
                continue
            if self._confirmed(q):
                ready.append(q)
            elif now - q.time < self.p["confirm_window"]:
                still.append(q)
            else:
                self.last_event = f"{q.tf}m PROC not confirmed by {self.p['confirm_with']} · skipped"
        self.pending = still
        return ready

    def on_bar(self, htf, ltf: list[Bar], market: Market) -> Optional[Entry]:
        for p in self._new_procs(market):
            self.pending = []
            self.my_proc = p
            arrow = "↑" if p.side == "long" else "↓"
            both = f" + {self.p['confirm_with']}" if self._confirming and self.partner else ""
            self.last_event = f"{p.tf}m PROC {arrow}{both} off {p.zone.label()} · entered {p.side}"
            price = market.underlyings[self.cfg.underlying].price
            self.trims_done, self.trim_last = 0, None
            self.trim_target = self._trim_level(p.side, price, price)
            return Entry(p.side, self.trim_target,
                         note=f"{p.tf}m PROC off {p.zone.label()}{both}")
        return None

    def _trim_level(self, side: str, price: float, entry: float) -> Optional[float]:
        """Next untapped opposite FFVG/IFFVG in the trade's direction that qualifies as a trim level."""
        tf, pts = self.p["trim_min_tf"], self.p["trim_min_pts"]
        if side == "long":
            lv = [z.bottom for z in self.engine.zones if z.side == "short" and not z.dead and z.tapped_at is None
                  and z.tf >= tf and z.bottom > price and z.bottom >= entry + pts]
            return min(lv) if lv else None
        lv = [z.top for z in self.engine.zones if z.side == "long" and not z.dead and z.tapped_at is None
              and z.tf >= tf and z.top < price and z.top <= entry - pts]
        return max(lv) if lv else None

    def _trim_check(self, bar: Bar, market: Market) -> None:
        side, t = self.plan.side, self.trim_target
        cap = self.p["trim_max"]
        if t is not None and (bar.high >= t if side == "long" else bar.low <= t) and (cap is None or self.trims_done < cap):
            qty = max(1, round(self.position.qty * self.p["trim_frac"]))
            price = t if self.p["trim_fill"] == "limit" else None
            if self.trim(qty, f"next zone {t:,.2f}", market, price):
                self.trims_done += 1
                self.last_event = f"trimmed {qty} at the next zone {t:,.2f} · {self.position.qty} left"
        if t is not None and (bar.high >= t if side == "long" else bar.low <= t):
            self.trim_last = t   # reached: a zone only touched at its edge stays "untapped", so remember it
        # aim for the next qualifying zone beyond price and beyond the last level reached
        ref = bar.close if self.trim_last is None else (
            max(bar.close, self.trim_last) if side == "long" else min(bar.close, self.trim_last))
        self.trim_target = self._trim_level(side, ref, self.position.entry)
        self.plan.target = self.trim_target

    def exit_on_bar(self, htf, ltf: list[Bar], market: Market) -> Optional[str]:
        if self.p["trim"] and ltf:
            self._trim_check(ltf[-1], market)
        for kind, p in self._events:
            if kind == "proc" and p.side != self.plan.side:
                if self.p["exit_min_tf"] and self.my_proc and p.tf < self.my_proc.tf:
                    self.last_event = f"{p.tf}m PROC against, below the {self.my_proc.tf}m entry · held"
                    continue
                self.last_event = f"{p.tf}m PROC against the trade at {market.clock_str}"
                return "pointer against (PROC)"
            if kind == "invalidated" and p is self.my_proc and self.p["exit_on_invalidation"]:
                return "PROC invalidated"
        pos, side = self.position, self.plan.side
        triggers = [f"{p.tf}m PROC with the trade" for p in self._new_procs(market) if p.side == side]
        mode = self.p["add_on"]
        if mode in ("pointer", "partner_pointer"):
            eng = self.engine if mode == "pointer" else self.partner
            if eng is not None:
                triggers += [f"{tf}m {'MES ' if mode == 'partner_pointer' else ''}pointer with the trade"
                             for t, k, sd, tf in eng.recent if t == eng.last_t and k == "pointer" and sd == side]
        if triggers and pos.pnl(self.broker.mark(pos, market)) > 0 and self.add(market, triggers[0]):
            self.last_event = f"added to {pos.qty} contracts · {triggers[0]}"
        return None

    def on_position_closed(self, pnl: float) -> None:
        self.my_proc = None
        self.last_event = f"trade closed {'+' if pnl >= 0 else '-'}${abs(pnl):,.0f} · waiting for a PROC"

    # TradingView: these indicators don't publish alert conditions, so only direct orders apply
    def on_signal(self, sig: dict, market: Market) -> Optional[str]:
        if self.p["signals"] == "builtin" or self.status in DONE_FOR_DAY:
            return None
        kind = sig["signal"]
        self.last_signal = f"{kind.replace('_', ' ')} @ {market.clock_str}"
        if kind == "exit" and self.position:
            self._close("TradingView exit", market)
            return "exit"
        if kind in ("long", "short") and not self.position and market.minutes_to_close > 10:
            u = market.underlyings[self.cfg.underlying]
            self._open(Entry(kind, None, "TradingView alert"), u, market)
            return f"{kind} order" if self.position else None
        return None

    def room(self, market: Market) -> dict:
        out = super().room(market)
        e = self.engine
        if e:
            first = out["candles"][0][0] if out["candles"] else 0
            out["zones"] = [{"side": z.side, "top": z.top, "bottom": z.bottom, "kind": z.kind, "tf": z.tf,
                             "from": max(z.created, first)}
                            for z in e.zones if not z.dead and z.tapped_at is None][-24:]
            if e.proc:
                p = e.proc
                out["proc"] = {"side": p.side, "tf": p.tf, "high": p.high, "low": p.low, "t": p.time,
                               "zone": p.zone.label()}
        out["waiting"] = len(self.pending)
        out["confirm_with"] = self.p["confirm_with"] if self._confirming else None
        return out

    def chart(self, market: Market, tf: int = 1, count: int = 180) -> dict:
        out = super().chart(market, tf, count)
        e = self.engine
        if not e or not out["candles"]:
            return out
        first = out["candles"][0][0]
        out["zones"] = [{"side": z.side, "top": z.top, "bottom": z.bottom, "kind": z.kind, "tf": z.tf,
                         "from": max(z.created, first), "tapped": z.tapped_at is not None}
                        for z in e.zones if not z.dead and (z.tapped_at is None or z.tapped_at >= first)][-40:]
        mine = set(self.p["pointer_tfs"])
        out["procs"] = [{"t": t - t % tf, "kind": k, "side": sd, "tf": ptf}
                        for t, k, sd, ptf in e.recent if k in ("proc", "pointer") and ptf in mine and t >= first]
        if e.proc:
            p = e.proc
            out["proc"] = {"side": p.side, "tf": p.tf, "high": p.high, "low": p.low, "t": p.time - p.time % tf,
                           "zone": p.zone.label()}
        if self._confirming and self.partner:
            out["partner"] = {"symbol": self.p["confirm_with"], "mode": self.p["confirm_mode"],
                              "marks": [{"t": t - t % tf, "kind": k, "side": sd, "tf": ptf}
                                        for t, k, sd, ptf in self.partner.recent
                                        if k in ("proc", "pointer") and t >= first]}
        out["setup"] = self.last_event
        return out

    def info(self) -> dict:
        e = self.engine
        live = [z for z in (e.zones if e else []) if not z.dead and z.tapped_at is None]
        return {"setup": self.last_event, "inverses": self.inverses, "walk_after": self.p["walk_after"],
                "signals": self.p["signals"], "last_signal": self.last_signal,
                "untapped_zones": len(live), "pointer_tfs": self.p["pointer_tfs"],
                "confirm": (f"{self.p['confirm_with']} {self.p['confirm_mode']} within {self.p['confirm_window']}m"
                            if self._confirming else None),
                "waiting": len(self.pending),
                "proc": (f"{e.proc.tf}m {'bullish' if e.proc.side == 'long' else 'bearish'} "
                         f"{e.proc.low:,.2f}–{e.proc.high:,.2f}") if e and e.proc else None}
