"""Andrew Macre's "pointer" strategy, as a bot.

Rules (from his public posts):

  * Every implied move starts and ends at a pointer / FFVG / IFFVG reaction.
  * A pointer needs an FFVG to sponsor the move.
  * A pointer with a swept wick in the direction of the close must be tested
    on the lower timeframe - you must enter.
  * Every pointer guarantees the move to the next FFVG. That's all it guarantees.
  * If in a trade, never fully exit until a pointer forms against you.
  * 3 or more pointer inverses -> walk away from the market.

Definitions, matching the Flux Charts indicators built on his concepts
(Pointer Closure Detection, Untapped FFVGs & IFFVGs, Troop Toolkit):

  pointer   An "efficient break of structure": a candle that closes back
            inside the previous candle's wick.
              bullish: green candle, close > previous body top, close <= previous high
              bearish: red candle,   close < previous body bottom, close >= previous low
            Watched on the bot's higher timeframe (3-6 minute candles).
            With `require_sweep`, the pointer's wick must also take out the
            previous candle's low (bullish) or high (bearish).
  FVG       A 3-candle imbalance: candle 1's high < candle 3's low (bullish)
            or candle 1's low > candle 3's high (bearish).
  FFVG      The *first* FVG after the swing the pointer made, in its
            direction, on the lower timeframe (1-minute candles here). It
            "sponsors" the move.
  IFFVG     An FFVG that a candle closes straight through. Order flow flipped:
            the pointer failed. That is a "pointer inverse".

Trade plan:

  1. Pointer closes on the bot's timeframe -> wait for its FFVG on 1m candles.
  2. Price comes back and tests the FFVG without closing through it -> enter
     (calls / long for bullish, puts / short for bearish).
  3. Size: enter with 3 contracts. Each new pointer in the trade's direction
     while the trade is in profit adds 3 more, up to 6. The prop account
     (`account.py`) can refuse or cap any of this.
  4. No stop loss. The only exit is a pointer forming against the trade
     (plus flattening before the close, and the account's own risk limits).
  5. The next opposing FVG (the "next FFVG" the pointer guarantees) is shown
     as the expected move; it doesn't close the trade.
  6. If the FFVG gets closed through before the test, that's an inverse.
     After `walk_after` inverses in a day, the bot walks away.

Signals can come from this file's own detection ("builtin"), from your
TradingView indicators via webhook ("tradingview"), or both. See `on_signal`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..market import Bar, Market
from .base import DONE_FOR_DAY, Bot, Entry


@dataclass
class Pointer:
    side: str        # 'long' (bullish) | 'short' (bearish)
    n: int           # 1m candle number it was seen on
    time: str
    source: str = "builtin"


@dataclass
class Gap:
    side: str        # 'long' (bullish FVG) | 'short' (bearish FVG)
    top: float
    bottom: float
    n: int           # 1m candle number of the 3rd candle


DEFAULTS = {
    "signals": "both",      # 'builtin' | 'tradingview' | 'both'
    "require_sweep": True,  # pointer wick must take the previous candle's low/high
    "ffvg_window": 15,      # 1m candles after the pointer to find its FFVG
    "test_window": 20,      # 1m candles after the FFVG to get the test
    "walk_after": 3,        # pointer inverses before walking away
    # confluence filters (off by default; the optimizer in backtest.py tries them)
    "sessions": None,           # e.g. ["LONDON", "NEW YORK"]: only enter in these sessions
    "liquidity_sweep": False,   # pointer must sweep a previous session's high/low and close back
    "min_gap_ticks": 0,         # ignore FFVGs smaller than this many ticks
}

SIGNALS = {
    "bullish_pointer", "bearish_pointer", "bullish_ffvg", "bearish_ffvg",
    "bullish_iffvg", "bearish_iffvg", "long", "short", "exit",
}


def is_pointer(prev: Bar, cur: Bar, require_sweep: bool) -> Optional[str]:
    """'long' / 'short' if `cur` is a pointer off `prev`, else None."""
    body_top, body_bottom = max(prev.open, prev.close), min(prev.open, prev.close)
    if cur.bullish and body_top < cur.close <= prev.high and (not require_sweep or cur.low < prev.low):
        return "long"
    if cur.bearish and prev.low <= cur.close < body_bottom and (not require_sweep or cur.high > prev.high):
        return "short"
    return None


class PointerBot(Bot):
    strategy_name = "Macre pointer"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.p = {**DEFAULTS, **self.cfg.params}
        self.gaps: list[Gap] = []
        self.levels: list[tuple[str, float, float]] = []   # finished sessions: (label, high, low)
        self._session: Optional[list] = None               # [label, high, low] of the current one
        self._n = 0
        self.last_signal = ""
        self.reset_day()

    def reset_day(self) -> None:
        self.pointer: Optional[Pointer] = None
        self.ffvg: Optional[Gap] = None
        self.inverses = 0
        self.last_event = "waiting for a pointer"

    @property
    def builtin(self) -> bool:
        return self.p["signals"] in ("builtin", "both")

    # ---- candle reading ---------------------------------------------------
    def _advance(self, ltf: list[Bar], market: Market) -> Optional[Gap]:
        """Process the newest 1m candle: retire filled gaps, return a new FVG if one formed."""
        self._n += 1
        bar = ltf[-1]
        # session highs/lows = the liquidity a pointer can sweep
        if self._session is None or self._session[0] != market.session:
            if self._session:
                self.levels = (self.levels + [tuple(self._session)])[-4:]
            self._session = [market.session, bar.high, bar.low]
        else:
            self._session[1] = max(self._session[1], bar.high)
            self._session[2] = min(self._session[2], bar.low)
        self.gaps = [g for g in self.gaps if not self._filled(g, bar)][-60:]
        if len(ltf) >= 3:
            c1, c3 = ltf[-3], ltf[-1]
            if c1.high < c3.low:
                self.gaps.append(Gap("long", c3.low, c1.high, self._n))
                return self.gaps[-1]
            if c1.low > c3.high:
                self.gaps.append(Gap("short", c1.low, c3.high, self._n))
                return self.gaps[-1]
        return None

    @staticmethod
    def _filled(g: Gap, bar: Bar) -> bool:
        return bar.low <= g.bottom if g.side == "long" else bar.high >= g.top

    def _htf_pointer(self, htf: Optional[list[Bar]]) -> Optional[Pointer]:
        if not self.builtin or not htf or len(htf) < 2:
            return None
        cur = htf[-1]
        side = is_pointer(htf[-2], cur, self.p["require_sweep"])
        if not side:
            return None
        if self.p["liquidity_sweep"]:
            if side == "long" and not any(cur.low < lo < cur.close for _, _, lo in self.levels):
                return None
            if side == "short" and not any(cur.close < hi < cur.high for _, hi, _ in self.levels):
                return None
        return Pointer(side, self._n, htf[-1].time)

    def _target(self, side: str, price: float) -> Optional[float]:
        """The nearest opposing FVG in the trade's direction, if any."""
        if side == "long":
            levels = [g.bottom for g in self.gaps if g.side == "short" and g.bottom > price]
            return min(levels) if levels else None
        levels = [g.top for g in self.gaps if g.side == "long" and g.top < price]
        return max(levels) if levels else None

    def _set_pointer(self, ptr: Pointer) -> None:
        self.pointer, self.ffvg = ptr, None
        arrow = "↑" if ptr.side == "long" else "↓"
        src = " (TradingView)" if ptr.source == "tradingview" else ""
        self.last_event = f"pointer {arrow}{src} at {ptr.time} · waiting for 1m FFVG"

    def _set_ffvg(self, gap: Gap) -> None:
        self.ffvg = gap
        self.last_event = f"FFVG {gap.bottom:,.2f}–{gap.top:,.2f} sponsors the {gap.side} pointer · waiting for test"

    def _inverse(self) -> None:
        self.inverses += 1
        self.last_event = f"FFVG inverted ({self.inverses}/{self.p['walk_after']} inverses)"
        self.pointer = self.ffvg = None
        if self.inverses >= self.p["walk_after"]:
            self.status = "walked"
            self.last_event = f"{self.inverses} pointer inverses · walked away"

    # ---- bot hooks ----------------------------------------------------------
    def on_bar(self, htf: Optional[list[Bar]], ltf: list[Bar], market: Market) -> Optional[Entry]:
        new_gap = self._advance(ltf, market)
        bar, n = ltf[-1], self._n
        allowed = not self.p["sessions"] or market.session in self.p["sessions"]

        if self.ffvg:  # waiting for the FFVG test on 1m
            g, long = self.ffvg, self.ffvg.side == "long"
            if (long and bar.close < g.bottom) or (not long and bar.close > g.top):
                self._inverse()
                return None
            if n > g.n and ((long and bar.low <= g.top) or (not long and bar.high >= g.bottom)):
                if allowed:
                    return self._enter(market)
                self.last_event = f"FFVG tested in {market.session} · outside allowed sessions"
                self.pointer = self.ffvg = None
            if n - g.n > self.p["test_window"]:
                self.last_event = "FFVG never got tested · reset"
                self.pointer = self.ffvg = None

        elif self.pointer:  # waiting for the pointer's FFVG on 1m
            tick = market.underlyings[self.cfg.underlying].tick_size
            if new_gap and new_gap.side == self.pointer.side and new_gap.n > self.pointer.n \
                    and new_gap.top - new_gap.bottom >= self.p["min_gap_ticks"] * tick:
                self._set_ffvg(new_gap)
            elif n - self.pointer.n > self.p["ffvg_window"]:
                self.last_event = "pointer had no FFVG · reset"
                self.pointer = None

        ptr = self._htf_pointer(htf)
        if ptr and not self.ffvg:
            self._set_pointer(ptr)
        return None

    def _enter(self, market: Market) -> Entry:
        ptr, g = self.pointer, self.ffvg
        self.pointer = self.ffvg = None
        self.last_event = f"FFVG tested · entered {ptr.side}"
        return self._plan(ptr.side, market, f"pointer {ptr.time} · FFVG {g.bottom:,.2f}–{g.top:,.2f}")

    def _plan(self, side: str, market: Market, note: str, target: Optional[float] = None) -> Entry:
        if target is None:
            target = self._target(side, market.underlyings[self.cfg.underlying].price)
        return Entry(side, target, note=note)

    def exit_on_bar(self, htf: Optional[list[Bar]], ltf: list[Bar], market: Market) -> Optional[str]:
        self._advance(ltf, market)
        ptr = self._htf_pointer(htf)
        if ptr and ptr.side != self.plan.side:
            self.last_event = f"pointer formed against the trade at {ptr.time}"
            return "pointer against"
        if ptr:
            self._maybe_add(market, f"pointer with the trade at {ptr.time}")
        return None

    def _maybe_add(self, market: Market, why: str) -> None:
        """A new pointer in the trade's direction: size up (3 -> 6) if the trade is working."""
        pos = self.position
        if pos.pnl(self.broker.mark(pos, market)) > 0:
            if self.add(market, why):
                self.last_event = f"added to {pos.qty} contracts · {why}"

    def on_position_closed(self, pnl: float) -> None:
        self.last_event = f"trade closed {'+' if pnl >= 0 else '-'}${abs(pnl):,.0f} · waiting for a pointer"

    # ---- TradingView ---------------------------------------------------------
    def on_signal(self, sig: dict, market: Market) -> Optional[str]:
        """Handle one webhook alert. Returns a short description for the city, or None if ignored.

        `sig` has `signal` (one of SIGNALS) and optionally `price`, `target`,
        `top`, `bottom`.
        """
        if self.p["signals"] == "builtin" or self.status in DONE_FOR_DAY:
            return None
        kind = sig["signal"]
        u = market.underlyings[self.cfg.underlying]
        self.last_signal = f"{kind.replace('_', ' ')} @ {market.clock_str}"

        if kind == "exit":
            if self.position:
                self._close("TradingView exit", market)
                return "exit"
            return None

        side = "long" if kind.startswith("bullish") or kind == "long" else "short"

        if kind.endswith("pointer"):
            if self.position:
                if side != self.plan.side:
                    self._close("pointer against (TradingView)", market)
                    return f"{kind.replace('_', ' ')} · exited"
                before = self.position.qty
                self._maybe_add(market, "TradingView pointer with the trade")
                return f"{kind.replace('_', ' ')} · added" if self.position.qty > before else None
            self._set_pointer(Pointer(side, self._n, market.clock_str, "tradingview"))
            return kind.replace("_", " ")

        if kind.endswith("_ffvg"):
            if self.position or not self.pointer or self.pointer.side != side:
                return None
            if "top" in sig and "bottom" in sig:
                gap = Gap(side, float(sig["top"]), float(sig["bottom"]), self._n - 1)
            else:
                same = [g for g in self.gaps if g.side == side and g.n > self.pointer.n]
                if not same:
                    return None
                gap = same[0]
            self._set_ffvg(gap)
            return kind.replace("_", " ")

        if kind.endswith("_iffvg"):
            # a bearish IFFVG is a bullish FFVG that got closed through (and vice versa)
            if not self.position and self.ffvg and self.ffvg.side != side:
                self._inverse()
                return f"{kind.replace('_', ' ')} · inverse {self.inverses}"
            return None

        # direct 'long' / 'short' orders
        if self.position or market.minutes_to_flat <= 10:
            return None
        target = float(sig["target"]) if sig.get("target") is not None else None
        entry = self._plan(side, market, "TradingView alert", target)
        self._open(entry, u, market)
        return f"{kind} order"

    def info(self) -> dict:
        return {"setup": self.last_event, "inverses": self.inverses, "walk_after": self.p["walk_after"],
                "signals": self.p["signals"], "last_signal": self.last_signal}
