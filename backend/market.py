"""Simulated market: intraday underlying prices + 0DTE option pricing.

Prices follow geometric Brownian motion with a drift "regime" that switches
between trending up, trending down and chop, so the bots have something real
to react to. Swap this module for a live data feed when you're ready.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

SESSION_OPEN_MIN = 9 * 60 + 30   # 09:30
SESSION_CLOSE_MIN = 16 * 60      # 16:00
MINUTES_PER_YEAR = 252 * 390     # trading minutes


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
class Underlying:
    symbol: str
    price: float
    iv: float                 # implied vol used for option pricing
    vol: float                # realized annualized vol of the simulation
    strike_step: float = 1.0
    history: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)
    open_price: float = 0.0
    _drift: float = 0.0
    _regime_left: int = 0

    def __post_init__(self) -> None:
        self.open_price = self.price
        self.history.append(self.price)
        self.volumes.append(1.0)

    def step(self, minutes: float) -> None:
        if self._regime_left <= 0:
            # new regime: strong up, strong down, or chop
            # drift is a fraction per sim-minute, scaled to the symbol's vol
            self._drift = random.choice([1, -1, 0, 0]) * random.uniform(0.5, 1.5) * self.vol * 1e-3
            self._regime_left = random.randint(40, 160)
        self._regime_left -= 1
        dt = minutes / MINUTES_PER_YEAR
        shock = random.gauss(0, 1)
        self.price *= math.exp(self._drift * minutes + self.vol * math.sqrt(dt) * shock)
        self.history.append(self.price)
        self.volumes.append(random.uniform(0.5, 1.5) * (1 + abs(shock)))
        if len(self.history) > 500:
            self.history = self.history[-500:]
            self.volumes = self.volumes[-500:]

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
        self.underlyings: dict[str, Underlying] = {
            "QQQ": Underlying("QQQ", 512.0, iv=0.19, vol=0.22),
            "SPY": Underlying("SPY", 578.0, iv=0.15, vol=0.17),
            "IWM": Underlying("IWM", 221.0, iv=0.24, vol=0.27),
            "NVDA": Underlying("NVDA", 138.0, iv=0.48, vol=0.50),
            "TSLA": Underlying("TSLA", 251.0, iv=0.55, vol=0.58, strike_step=2.5),
        }

    def step(self) -> None:
        self.clock_min += self.sim_minutes_per_tick
        if self.clock_min >= SESSION_CLOSE_MIN:
            self.new_session()
        for u in self.underlyings.values():
            u.step(self.sim_minutes_per_tick)

    def new_session(self) -> None:
        self.clock_min = float(SESSION_OPEN_MIN)
        for u in self.underlyings.values():
            u.open_price = u.price

    @property
    def minutes_to_close(self) -> float:
        return SESSION_CLOSE_MIN - self.clock_min

    @property
    def clock_str(self) -> str:
        m = int(self.clock_min)
        return f"{m // 60:02d}:{m % 60:02d}"

    def option_price(self, symbol: str, strike: float, kind: str) -> float:
        u = self.underlyings[symbol]
        return black_scholes(u.price, strike, self.minutes_to_close, u.iv, kind)
