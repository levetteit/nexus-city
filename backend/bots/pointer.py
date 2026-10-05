"""Andrew Macre's "pointer" strategy, as a bot.

My reading of his publicly posted rules (tune it as you study the method):

  * Every implied move starts and ends at a pointer / FFVG / IFFVG reaction.
  * A pointer needs an FFVG to sponsor the move.
  * A pointer with a swept wick in the direction of the close must be tested
    on the lower timeframe - you must enter.
  * Every pointer guarantees the move to the next FFVG. That's all it guarantees.
  * If in a trade, never fully exit until a pointer forms against you on
    another FFVG / IFFVG.
  * 3 or more pointer inverses -> walk away from the market.

Definitions used here:

  pointer   A candle whose wick sweeps liquidity (takes out the lowest low /
            highest high of the last `lookback` candles) and then closes back
            the other way with a body in that direction. A bullish pointer
            sweeps lows and closes green; a bearish pointer sweeps highs and
            closes red.
  FVG       A 3-candle imbalance: candle 1's high < candle 3's low (bullish)
            or candle 1's low > candle 3's high (bearish).
  FFVG      The *first* FVG that forms after the pointer, in its direction.
            It "sponsors" the move.
  IFFVG     An FFVG that price closes straight through. Order flow flipped:
            the pointer failed. That is a "pointer inverse".

Trade plan:

  1. Pointer prints -> wait for its FFVG (within `ffvg_window` candles).
  2. Price comes back and tests the FFVG and the candle closes back out of it
     in the pointer's direction -> enter (calls / long for bullish,
     puts / short for bearish).
  3. Stop goes just past the pointer's swept wick.
  4. Target = the next opposing FVG (the "next FFVG" the pointer guarantees).
     If there is none, or it's closer than `min_rr` x risk, aim for 2R.
  5. At the target, scale out half; the runner's stop moves to breakeven.
  6. The runner stays on until a pointer forms against it.
  7. If an FFVG gets closed through before the test, that's an inverse.
     After `walk_after` inverses in a day, the bot walks away.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..market import Bar, Market
from .base import Bot, Entry


@dataclass
class Pointer:
    side: str        # 'long' (bullish) | 'short' (bearish)
    sweep: float     # the swept wick extreme -> invalidation
    n: int           # candle number it printed on
    time: str


@dataclass
class Gap:
    side: str        # 'long' (bullish FVG) | 'short' (bearish FVG)
    top: float
    bottom: float
    n: int           # candle number of the 3rd candle


DEFAULTS = {
    "lookback": 10,       # candles of liquidity a pointer must sweep
    "ffvg_window": 6,     # candles after the pointer to find its FFVG
    "test_window": 10,    # candles after the FFVG to get the test
    "min_rr": 1.0,        # an FVG target closer than this x risk is ignored (2R used instead)
    "walk_after": 3,      # pointer inverses before walking away
    "stop_ticks": 2,      # stop buffer past the swept wick, in ticks
}


class PointerBot(Bot):
    strategy_name = "Macre pointer"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.p = {**DEFAULTS, **self.cfg.params}
        self.reset_day()
        self._n = 0
        self.gaps: list[Gap] = []

    def reset_day(self) -> None:
        self.pointer: Optional[Pointer] = None
        self.ffvg: Optional[Gap] = None
        self.inverses = 0
        self.last_event = "waiting for a pointer"

    # ---- candle reading ---------------------------------------------------
    def _advance(self, bars: list[Bar]) -> Optional[Pointer]:
        """Process the newest closed candle: update FVGs, return a pointer if one printed."""
        self._n += 1
        n, bar = self._n, bars[-1]

        # fill / invalidate tracked gaps, then add a new one if candles 1-3 left an imbalance
        self.gaps = [g for g in self.gaps if not self._filled(g, bar)][-40:]
        if len(bars) >= 3:
            c1, c3 = bars[-3], bars[-1]
            if c1.high < c3.low:
                self.gaps.append(Gap("long", c3.low, c1.high, n))
            elif c1.low > c3.high:
                self.gaps.append(Gap("short", c1.low, c3.high, n))

        lb = self.p["lookback"]
        if len(bars) < lb + 1:
            return None
        prior = bars[-lb - 1:-1]
        low, high = min(b.low for b in prior), max(b.high for b in prior)
        if bar.low < low and bar.bullish and bar.close > low:
            return Pointer("long", bar.low, n, bar.time)
        if bar.high > high and bar.bearish and bar.close < high:
            return Pointer("short", bar.high, n, bar.time)
        return None

    @staticmethod
    def _filled(g: Gap, bar: Bar) -> bool:
        return bar.low <= g.bottom if g.side == "long" else bar.high >= g.top

    def _target(self, side: str, price: float) -> Optional[float]:
        """The nearest opposing FVG in the trade's direction, if any."""
        if side == "long":
            levels = [g.bottom for g in self.gaps if g.side == "short" and g.bottom > price]
            return min(levels) if levels else None
        levels = [g.top for g in self.gaps if g.side == "long" and g.top < price]
        return max(levels) if levels else None

    # ---- bot hooks ----------------------------------------------------------
    def on_bar(self, bars: list[Bar], market: Market) -> Optional[Entry]:
        new_pointer = self._advance(bars)
        bar, n = bars[-1], self._n
        tick = market.underlyings[self.cfg.underlying].tick_size

        if self.ffvg:  # waiting for the FFVG test
            g, ptr = self.ffvg, self.pointer
            long = g.side == "long"
            if (long and bar.close < g.bottom) or (not long and bar.close > g.top):
                self.inverses += 1
                self.last_event = f"FFVG inverted ({self.inverses}/{self.p['walk_after']} inverses)"
                self.pointer = self.ffvg = None
                if self.inverses >= self.p["walk_after"]:
                    self.status = "walked"
                    self.last_event = f"{self.inverses} pointer inverses · walked away"
                    return None
            elif (long and bar.low <= g.top) or (not long and bar.high >= g.bottom):
                self.pointer = self.ffvg = None
                entry = self._plan(ptr, g, bar.close, tick)
                if entry:
                    return entry
            elif n - g.n > self.p["test_window"]:
                self.last_event = "FFVG never got tested · reset"
                self.pointer = self.ffvg = None

        elif self.pointer:  # waiting for the pointer's FFVG
            ptr = self.pointer
            gap = self.gaps[-1] if self.gaps and self.gaps[-1].n == n else None
            if gap and gap.side == ptr.side and n - 2 >= ptr.n:
                self.ffvg = gap
                self.last_event = f"FFVG {gap.bottom:,.2f}–{gap.top:,.2f} sponsors the {ptr.side} pointer · waiting for test"
            elif n - ptr.n > self.p["ffvg_window"]:
                self.last_event = "pointer had no FFVG · reset"
                self.pointer = None

        if new_pointer and not self.ffvg:
            self.pointer = new_pointer
            arrow = "↑" if new_pointer.side == "long" else "↓"
            self.last_event = f"pointer {arrow} swept {new_pointer.sweep:,.2f} at {new_pointer.time} · waiting for FFVG"
        return None

    def _plan(self, ptr: Pointer, g: Gap, price: float, tick: float) -> Optional[Entry]:
        buf = self.p["stop_ticks"] * tick
        stop = ptr.sweep - buf if ptr.side == "long" else ptr.sweep + buf
        risk = abs(price - stop)
        if risk <= 0 or (ptr.side == "long" and price <= stop) or (ptr.side == "short" and price >= stop):
            self.last_event = "test came too deep · skipped"
            return None
        target = self._target(ptr.side, price)
        if target is None or abs(target - price) < self.p["min_rr"] * risk:
            target = price + 2 * risk if ptr.side == "long" else price - 2 * risk
        self.last_event = f"FFVG tested · entered {ptr.side}"
        return Entry(ptr.side, stop, target, note=f"pointer {ptr.time} · FFVG {g.bottom:,.2f}–{g.top:,.2f}")

    def exit_on_bar(self, bars: list[Bar], market: Market) -> Optional[str]:
        ptr = self._advance(bars)
        if ptr and ptr.side != self.plan.side:
            self.last_event = f"pointer formed against the trade at {ptr.time}"
            return "pointer against"
        return None

    def on_position_closed(self, pnl: float) -> None:
        self.last_event = f"trade closed {'+' if pnl >= 0 else '-'}${abs(pnl):,.0f} · waiting for a pointer"

    def info(self) -> dict:
        return {"setup": self.last_event, "inverses": self.inverses, "walk_after": self.p["walk_after"]}
