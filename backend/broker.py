"""Brokers execute the bots' orders.

`PaperBroker` fills against the simulated market with realistic costs, so
nothing touches real money. It handles two instruments:

* options  - long calls / puts, $100 multiplier, bid/ask spread + fees
* futures  - long or short (e.g. MNQ, $2 per point), 1 tick slippage + fees

To go live, implement the same methods (`open`, `close`, `mark`) against your
broker's API (Alpaca/Tradier for options, Tradovate/NinjaTrader/IBKR for
futures) and pass it to the Engine instead. Paper trade for weeks before you do.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from .market import Market

FUTURES_MULTIPLIER = {"MNQ": 2.0, "MES": 5.0, "M2K": 5.0, "MYM": 0.5}   # dollars per index point


@dataclass
class Position:
    symbol: str
    kind: str                 # options: 'call' | 'put'   futures: 'long' | 'short'
    qty: int
    entry: float              # premium per share (options) or price (futures)
    opened_at: str
    strike: Optional[float] = None
    multiplier: float = 100.0

    @property
    def is_future(self) -> bool:
        return self.strike is None

    def pnl(self, price: float, qty: Optional[int] = None) -> float:
        qty = self.qty if qty is None else qty
        sign = -1 if self.kind == "short" else 1   # long options and long futures profit when price > entry
        return (price - self.entry) * sign * qty * self.multiplier

    @property
    def label(self) -> str:
        if self.is_future:
            return f"{self.symbol} {self.kind.upper()}"
        return f"{self.symbol} {self.strike:g}{'C' if self.kind == 'call' else 'P'}"


class Broker(Protocol):
    def open(self, symbol: str, kind: str, qty: int, market: Market, strike: Optional[float] = None) -> Position: ...
    def close(self, pos: Position, market: Market, price: Optional[float] = None) -> float: ...
    def mark(self, pos: Position, market: Market) -> float: ...


class PaperBroker:
    def __init__(self, spread_pct: float = 0.02, option_fee: float = 0.65, futures_fee: float = 0.62,
                 slippage_ticks: float = 1.0) -> None:
        self.spread_pct = spread_pct
        self.slippage_ticks = slippage_ticks
        self.option_fee = option_fee      # per contract, per side
        self.futures_fee = futures_fee    # per contract, per side

    def open(self, symbol: str, kind: str, qty: int, market: Market, strike: Optional[float] = None) -> Position:
        if strike is None:  # futures
            u = market.underlyings[symbol]
            mult = FUTURES_MULTIPLIER[symbol]
            slip = self.slippage_ticks * u.tick_size * (1 if kind == "long" else -1)
            fee = self.futures_fee / mult if kind == "long" else -self.futures_fee / mult
            return Position(symbol, kind, qty, u.price + slip + fee, market.clock_str, None, mult)
        mid = market.option_price(symbol, strike, kind)
        fill = mid * (1 + self.spread_pct / 2) + self.option_fee / 100
        return Position(symbol, kind, qty, fill, market.clock_str, strike, 100.0)

    def close(self, pos: Position, market: Market, price: Optional[float] = None) -> float:
        """Exit price, net of costs, for `pos` (the caller decides how many contracts).
        `price`: a resting limit order's price (futures only, no slippage) instead of the market."""
        if pos.is_future:
            u = market.underlyings[pos.symbol]
            cost = (0 if price is not None else self.slippage_ticks * u.tick_size) + self.futures_fee / pos.multiplier
            px = u.price if price is None else price
            return px - cost if pos.kind == "long" else px + cost
        mid = market.option_price(pos.symbol, pos.strike, pos.kind)
        return max(mid * (1 - self.spread_pct / 2) - self.option_fee / 100, 0.0)

    def mark(self, pos: Position, market: Market) -> float:
        if pos.is_future:
            return market.underlyings[pos.symbol].price
        return market.option_price(pos.symbol, pos.strike, pos.kind)
