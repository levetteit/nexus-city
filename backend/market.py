"""Simulated futures market over the full trading day, every session.

The trading day runs like CME equity futures under a prop firm's flat rule:
it opens at 18:00 ET (Asia), runs through London and New York, and rolls at
16:45 ET. The bots are flat by 15:55 ET: Tradovate's session for the micros ends at 16:00. All times are US Eastern.

Prices follow geometric Brownian motion with a drift "regime" that switches
between trending up, trending down and chop, and volatility that changes by
session (quiet Asia, busier London, busiest New York open). Swap this module
for a live data feed when you're ready.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Optional

# Minutes are counted from midnight of the day the session opens, so the
# 18:00 open is 1080 and the next afternoon's 16:45 close is 1440 + 1005.
SESSION_OPEN_MIN = 18 * 60              # 18:00 ET, Asia opens
SESSION_CLOSE_MIN = 24 * 60 + 16 * 60 + 45   # 16:45 ET next day: the trading day rolls (prop firm EOD)
# Tradovate's session for the micros ends at 16:00 ET: an order after that never reaches the account. So the
# bots stop opening (and adding) 10 minutes before and are flat 5 minutes before, whatever the day's close.
FLAT_BY_MIN = 24 * 60 + 16 * 60              # 16:00 ET

# (start, label, volatility multiplier), by minutes since midnight of the open day
SESSIONS = [
    (18 * 60, "ASIA", 0.45),
    (24 * 60 + 3 * 60, "LONDON", 0.75),
    (24 * 60 + 9 * 60 + 30, "NEW YORK", 1.0),
]
MINUTES_PER_YEAR = 252 * 390     # trading minutes


def session_at(clock_min: float) -> tuple:
    """(start, label, vol multiplier) of the session at `clock_min`."""
    return [s for s in SESSIONS if clock_min >= s[0]][-1]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes(spot: float, strike: float, minutes_left: float, iv: float, kind: str, r: float = 0.04) -> float:
    """Price a European option. `kind` is 'call' or 'put'."""
    t = max(minutes_left, 0.5) / MINUTES_PER_YEAR
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    if kind == "call":
        price = spot * _norm_cdf(d1) - strike * math.exp(-r * t) * _norm_cdf(d2)
    else:
        price = strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return max(price, 0.01)


@dataclass
class Bar:
    """One OHLC candle."""
    open: float
    high: float
    low: float
    close: float
    time: str = ""
    t: int = 0          # absolute minute the candle opened (keeps higher timeframes clock-aligned)

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open


def aggregate(bars: list[Bar], minutes: int) -> list[Bar]:
    """Merge 1-minute bars into `minutes`-minute bars (only complete ones)."""
    if minutes <= 1:
        return list(bars)
    out = []
    for i in range(len(bars) % minutes, len(bars), minutes):
        chunk = bars[i:i + minutes]
        out.append(Bar(chunk[0].open, max(b.high for b in chunk), min(b.low for b in chunk),
                       chunk[-1].close, chunk[-1].time))
    return out


@dataclass
class Underlying:
    symbol: str
    price: float
    iv: float                 # implied vol used for option pricing
    vol: float                # realized annualized vol of the simulation
    strike_step: float = 1.0
    tick_size: float = 0.01
    history: list[float] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)   # closed 1-minute candles
    open_price: float = 0.0
    _drift: float = 0.0
    _regime_left: int = 0
    bar_count: int = 0       # total 1-minute bars ever closed (keeps higher timeframes aligned)
    _bar: Optional[Bar] = None
    _bar_elapsed: float = 0.0

    def __post_init__(self) -> None:
        self.open_price = self.price
        self.history.append(self.price)

    def step(self, minutes: float, clock: str = "", vol_mult: float = 1.0) -> None:
        if self._regime_left <= 0:
            # new regime: strong up, strong down, or chop
            # drift is a fraction per sim-minute, scaled to the symbol's vol
            self._drift = random.choice([1, -1, 0, 0]) * random.uniform(0.5, 1.5) * self.vol * 1e-3
            self._regime_left = random.randint(40, 160)
        self._regime_left -= 1
        dt = minutes / MINUTES_PER_YEAR
        shock = random.gauss(0, 1)
        prev = self.price
        vol = self.vol * vol_mult
        new = prev * math.exp(self._drift * vol_mult * minutes + vol * math.sqrt(dt) * shock)
        # wicks: price pokes past where it ends up within each tick
        poke = abs(new - prev) * random.uniform(0, 0.8) + prev * vol * math.sqrt(dt) * random.uniform(0, 0.5)
        hi, lo = max(prev, new) + poke * random.random(), min(prev, new) - poke * random.random()
        self.price = round(new / self.tick_size) * self.tick_size
        self.history.append(self.price)
        if len(self.history) > 500:
            self.history = self.history[-500:]

        if self._bar is None:
            self._bar = Bar(prev, prev, prev, prev)
        self._bar.high = max(self._bar.high, hi, self.price)
        self._bar.low = min(self._bar.low, lo, self.price)
        self._bar.close = self.price
        self._bar_elapsed += minutes
        if self._bar_elapsed >= 1.0 - 1e-9:
            self._bar.time = clock
            self._bar.t = self.bar_count
            self.bars.append(self._bar)
            self.bar_count += 1
            self._bar, self._bar_elapsed = None, 0.0
            if len(self.bars) > 1200:
                self.bars = self.bars[-1200:]

    def anchor(self, price: float) -> None:
        """Snap the simulation to a real price (e.g. the close sent in a TradingView alert)."""
        self.price = round(price / self.tick_size) * self.tick_size
        self.history.append(self.price)
        if self._bar:
            self._bar.high = max(self._bar.high, self.price)
            self._bar.low = min(self._bar.low, self.price)
            self._bar.close = self.price

    def atm_strike(self, kind: str, otm_steps: int = 0) -> float:
        base = round(self.price / self.strike_step) * self.strike_step
        offset = otm_steps * self.strike_step
        return base + offset if kind == "call" else base - offset

    @property
    def change_pct(self) -> float:
        return (self.price / self.open_price - 1) * 100


class Market:
    """Holds every underlying plus a simulated session clock."""

    def __init__(self, sim_minutes_per_tick: float = 0.25) -> None:
        self.sim_minutes_per_tick = sim_minutes_per_tick
        self.clock_min = float(SESSION_OPEN_MIN)
        self.day = 0
        self.underlyings: dict[str, Underlying] = {
            "MNQ": Underlying("MNQ", 24500.0, iv=0.20, vol=0.22, tick_size=0.25),  # Micro Nasdaq-100
            "MES": Underlying("MES", 6850.0, iv=0.15, vol=0.17, tick_size=0.25),   # Micro S&P 500
        }

    def step(self) -> None:
        self.clock_min += self.sim_minutes_per_tick
        if self.clock_min >= SESSION_CLOSE_MIN:
            self.new_session()
        _, _, mult = self._session
        if 0 <= self.clock_min - SESSIONS[2][0] < 30:
            mult *= 1.4   # New York open
        for u in self.underlyings.values():
            u.step(self.sim_minutes_per_tick, self.clock_str, mult)

    @property
    def _session(self) -> tuple:
        return session_at(self.clock_min)

    @property
    def session(self) -> str:
        return self._session[1]

    def new_session(self) -> None:
        self.clock_min = float(SESSION_OPEN_MIN)
        self.day += 1
        for u in self.underlyings.values():
            u.open_price = u.price

    @property
    def minutes_to_close(self) -> float:
        return SESSION_CLOSE_MIN - self.clock_min

    @property
    def minutes_to_flat(self) -> float:
        """Minutes until 16:00 ET, when the broker's session ends: no entries in the last 10, flat by the last 5."""
        return FLAT_BY_MIN - self.clock_min

    @property
    def clock_str(self) -> str:
        m = int(self.clock_min) % (24 * 60)
        return f"{m // 60:02d}:{m % 60:02d}"

    def option_price(self, symbol: str, strike: float, kind: str) -> float:
        u = self.underlyings[symbol]
        return black_scholes(u.price, strike, self.minutes_to_close, u.iv, kind)
