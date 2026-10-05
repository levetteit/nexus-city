"""Base class for every worker that lives in the city.

A bot owns one building, trades options on one underlying, and follows the
same shift rules:

* scanning  - on shift, waiting for its strategy to fire a signal
* in_trade  - holding a position (the building's light beam turns on)
* off_duty  - hit its daily profit brake, clocked out with the money
* stopped   - hit its daily max loss, sent home
* disabled  - turned off by you

Subclasses only implement `signal()` (and optionally `exit_signal()`).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..broker import Broker, Position
from ..market import Market, Underlying

Event = dict
_trade_ids = itertools.count(1)


@dataclass
class TradeRecord:
    id: int
    bot_id: str
    contract: str
    qty: int
    entry: float
    exit: float
    pnl: float
    reason: str
    opened_at: str
    closed_at: str


@dataclass
class BotConfig:
    id: str
    name: str
    underlying: str
    district: str                 # label for the street sign / UI
    contracts: int = 2
    profit_brake: float = 1500.0  # stop for the day once realized P&L >= this
    max_daily_loss: float = 600.0
    take_profit_pct: float = 0.35 # +35% on the option premium
    stop_loss_pct: float = 0.20   # -20% on the option premium
    max_hold_min: float = 25.0    # time stop, in sim minutes
    cooldown_min: float = 3.0     # wait after a trade closes
    otm_steps: int = 0            # 0 = ATM strikes
    color: str = "#7c5cff"


class Bot:
    strategy_name = "base"

    def __init__(self, cfg: BotConfig, broker: Broker, emit: Callable[[Event], None]) -> None:
        self.cfg = cfg
        self.broker = broker
        self.emit = emit
        self.status = "scanning"
        self.position: Optional[Position] = None
        self.realized = 0.0
        self.trades: list[TradeRecord] = []
        self._cooldown_until = 0.0
        self._opened_clock = 0.0

    # ---- strategy hooks -------------------------------------------------
    def signal(self, u: Underlying, market: Market) -> Optional[str]:
        """Return 'call', 'put' or None."""
        raise NotImplementedError

    def exit_signal(self, u: Underlying, market: Market, pos: Position) -> bool:
        return False

    # ---- lifecycle ------------------------------------------------------
    def on_tick(self, market: Market) -> None:
        if self.status in ("off_duty", "stopped", "disabled"):
            return
        u = market.underlyings[self.cfg.underlying]
        if self.position:
            self._manage(u, market)
        elif market.clock_min >= self._cooldown_until and market.minutes_to_close > 10:
            kind = self.signal(u, market)
            if kind:
                self._open(kind, u, market)

    def _open(self, kind: str, u: Underlying, market: Market) -> None:
        strike = u.atm_strike(kind, self.cfg.otm_steps)
        self.position = self.broker.buy(self.cfg.underlying, strike, kind, self.cfg.contracts, market)
        self._opened_clock = market.clock_min
        self.status = "in_trade"
        self.emit({"type": "trade_open", "bot": self.cfg.id, "contract": self.position.label,
                   "qty": self.position.qty, "entry": round(self.position.entry, 2)})

    def _manage(self, u: Underlying, market: Market) -> None:
        pos = self.position
        mark = self.broker.mark(pos, market)
        change = mark / pos.entry - 1
        held = market.clock_min - self._opened_clock
        reason = None
        if change >= self.cfg.take_profit_pct:
            reason = "take profit"
        elif change <= -self.cfg.stop_loss_pct:
            reason = "stop loss"
        elif held >= self.cfg.max_hold_min:
            reason = "time stop"
        elif market.minutes_to_close <= 5:
            reason = "end of day"
        elif self.exit_signal(u, market, pos):
            reason = "signal exit"
        if reason:
            self._close(reason, market)

    def _close(self, reason: str, market: Market) -> None:
        pos = self.position
        exit_px = self.broker.sell(pos, market)
        pnl = (exit_px - pos.entry) * pos.qty * 100
        self.realized += pnl
        rec = TradeRecord(next(_trade_ids), self.cfg.id, pos.label, pos.qty, round(pos.entry, 2),
                          round(exit_px, 2), round(pnl, 2), reason, pos.opened_at, market.clock_str)
        self.trades.append(rec)
        self.position = None
        self._cooldown_until = market.clock_min + self.cfg.cooldown_min
        self.status = "scanning"
        if self.realized >= self.cfg.profit_brake:
            self.status = "off_duty"
        elif self.realized <= -self.cfg.max_daily_loss:
            self.status = "stopped"
        self.emit({"type": "trade_close", "bot": self.cfg.id, "pnl": rec.pnl, "reason": reason,
                   "contract": rec.contract, "status": self.status})

    def set_enabled(self, enabled: bool, market: Market) -> None:
        if not enabled:
            if self.position:
                self._close("turned off", market)
            self.status = "disabled"
        elif self.status == "disabled":
            self.status = "scanning"

    def new_session(self) -> None:
        self.realized = 0.0
        self.trades.clear()
        if self.status != "disabled":
            self.status = "scanning"

    # ---- reporting ------------------------------------------------------
    def snapshot(self, market: Market) -> dict:
        unreal = 0.0
        pos = None
        if self.position:
            mark = self.broker.mark(self.position, market)
            unreal = (mark - self.position.entry) * self.position.qty * 100
            pos = {"contract": self.position.label, "qty": self.position.qty,
                   "entry": round(self.position.entry, 2), "mark": round(mark, 2)}
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return {
            "id": self.cfg.id, "name": self.cfg.name, "underlying": self.cfg.underlying,
            "district": self.cfg.district, "strategy": self.strategy_name, "color": self.cfg.color,
            "status": self.status, "realized": round(self.realized, 2), "unrealized": round(unreal, 2),
            "trades": len(self.trades), "wins": wins, "position": pos,
            "profit_brake": self.cfg.profit_brake, "max_daily_loss": self.cfg.max_daily_loss,
            "recent": [t.__dict__ for t in self.trades[-8:]][::-1],
        }
