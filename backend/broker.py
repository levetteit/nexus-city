"""Brokers execute the bots' orders.

`PaperBroker` fills against the simulated market with a bid/ask spread, so
nothing touches real money. To go live, implement the same three methods
(`buy`, `sell`, `mark`) against your broker's API (Alpaca, Tradier, IBKR...)
and pass it to the Engine instead. Paper trade for weeks before you do.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .market import Market


@dataclass
class Position:
    symbol: str
    strike: float
    kind: str         # 'call' | 'put'
    qty: int
    entry: float      # premium paid per share
    opened_at: str

    @property
    def label(self) -> str:
        strike = f"{self.strike:g}"
        return f"{self.symbol} {strike}{'C' if self.kind == 'call' else 'P'}"


class Broker(Protocol):
    def buy(self, symbol: str, strike: float, kind: str, qty: int, market: Market) -> Position: ...
    def sell(self, pos: Position, market: Market) -> float: ...
    def mark(self, pos: Position, market: Market) -> float: ...


class PaperBroker:
    def __init__(self, spread_pct: float = 0.02, fee_per_contract: float = 0.65) -> None:
        self.spread_pct = spread_pct
        self.fee = fee_per_contract

    def _fee_per_share(self) -> float:
        return self.fee / 100

    def buy(self, symbol: str, strike: float, kind: str, qty: int, market: Market) -> Position:
        mid = market.option_price(symbol, strike, kind)
        fill = mid * (1 + self.spread_pct / 2) + self._fee_per_share()
        return Position(symbol, strike, kind, qty, fill, market.clock_str)

    def sell(self, pos: Position, market: Market) -> float:
        mid = market.option_price(pos.symbol, pos.strike, pos.kind)
        return max(mid * (1 - self.spread_pct / 2) - self._fee_per_share(), 0.0)

    def mark(self, pos: Position, market: Market) -> float:
        return market.option_price(pos.symbol, pos.strike, pos.kind)
