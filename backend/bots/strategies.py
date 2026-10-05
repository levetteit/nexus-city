"""The workers. Each strategy is a few lines on top of `Bot`.

Add your own: subclass Bot, implement `signal()`, register it in
`backend/config.py`.
"""
from __future__ import annotations

from typing import Optional

from ..broker import Position
from ..market import Market, Underlying
from .base import Bot


def ema(values: list[float], period: int) -> float:
    k = 2 / (period + 1)
    out = values[0]
    for v in values[1:]:
        out = v * k + out * (1 - k)
    return out


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains = losses = 0.0
    for a, b in zip(values[-period - 1:-1], values[-period:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - 100 / (1 + rs)


def vwap(prices: list[float], volumes: list[float]) -> float:
    return sum(p * v for p, v in zip(prices, volumes)) / sum(volumes)


class EmaCrossScalper(Bot):
    """Buys calls when the fast EMA crosses above the slow EMA, puts on the reverse."""
    strategy_name = "EMA cross scalper"
    fast, slow = 8, 21

    def signal(self, u: Underlying, market: Market) -> Optional[str]:
        h = u.history[-60:]
        if len(h) < self.slow + 2:
            return None
        f_now, s_now = ema(h, self.fast), ema(h, self.slow)
        f_prev, s_prev = ema(h[:-1], self.fast), ema(h[:-1], self.slow)
        if f_prev <= s_prev and f_now > s_now:
            return "call"
        if f_prev >= s_prev and f_now < s_now:
            return "put"
        return None

    def exit_signal(self, u: Underlying, market: Market, pos: Position) -> bool:
        h = u.history[-60:]
        f, s = ema(h, self.fast), ema(h, self.slow)
        return (pos.kind == "call" and f < s) or (pos.kind == "put" and f > s)


class TrendRider(Bot):
    """Only trades with the day's trend: price on the right side of VWAP and a rising slope."""
    strategy_name = "VWAP trend rider"
    lookback = 30

    def signal(self, u: Underlying, market: Market) -> Optional[str]:
        if len(u.history) < self.lookback + 1:
            return None
        v = vwap(u.history[-120:], u.volumes[-120:])
        slope = (u.history[-1] - u.history[-self.lookback]) / u.history[-self.lookback]
        if u.price > v and slope > 0.0015:
            return "call"
        if u.price < v and slope < -0.0015:
            return "put"
        return None


class DipBuyer(Bot):
    """Buys calls when RSI is oversold and price starts to bounce."""
    strategy_name = "RSI dip buyer"

    def signal(self, u: Underlying, market: Market) -> Optional[str]:
        h = u.history
        if len(h) < 20:
            return None
        r_prev, r_now = rsi(h[:-1]), rsi(h)
        if r_prev < 28 and r_now > r_prev and h[-1] > h[-2]:
            return "call"
        return None


class FadeTheRip(Bot):
    """Mirror of DipBuyer: buys puts when RSI is overbought and rolls over."""
    strategy_name = "RSI rip fader"

    def signal(self, u: Underlying, market: Market) -> Optional[str]:
        h = u.history
        if len(h) < 20:
            return None
        r_prev, r_now = rsi(h[:-1]), rsi(h)
        if r_prev > 72 and r_now < r_prev and h[-1] < h[-2]:
            return "put"
        return None


class RangeBreakout(Bot):
    """Trades a break of the recent N-bar range."""
    strategy_name = "range breakout"
    bars = 40

    def signal(self, u: Underlying, market: Market) -> Optional[str]:
        h = u.history
        if len(h) < self.bars + 1:
            return None
        window = h[-self.bars - 1:-1]
        hi, lo = max(window), min(window)
        if h[-1] > hi and (hi - lo) / lo > 0.002:
            return "call"
        if h[-1] < lo and (hi - lo) / lo > 0.002:
            return "put"
        return None
