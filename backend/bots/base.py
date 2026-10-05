"""Base class for every worker that lives in the city.

A bot owns one building, trades one underlying (options or futures), and
follows the same shift rules:

* scanning  - on shift, waiting for its strategy to fire a setup
* in_trade  - holding a position (the building's light beam turns on)
* off_duty  - hit its daily profit brake, clocked out with the money
* stopped   - hit its daily max loss, sent home
* walked    - the strategy told it to walk away from the market for the day
* disabled  - turned off by you

Strategies see every closed 1-minute candle, plus the bot's own timeframe
candles whenever one closes. They implement `on_bar()` (return an `Entry` to
open a trade) and optionally `exit_on_bar()` and `on_signal()` (webhooks).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..broker import Broker, Position
from ..market import Bar, Market, Underlying, aggregate

Event = dict
_trade_ids = itertools.count(1)
DONE_FOR_DAY = ("off_duty", "stopped", "walked", "disabled")


@dataclass
class Entry:
    """A trade plan, in underlying prices."""
    side: str                 # 'long' | 'short'
    stop: float               # invalidation level
    target: Optional[float]   # first target (scale out half here)
    note: str = ""


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
    district: str                  # label for the street sign / UI
    instrument: str = "option"     # 'option' | 'future'
    timeframe: int = 3             # candle size in minutes for the bot's main signal
    contracts: int = 2
    profit_brake: float = 1500.0   # stop for the day once realized P&L >= this
    max_daily_loss: float = 600.0
    option_stop_pct: Optional[float] = 0.5   # hard stop on option premium (safety net)
    max_hold_min: float = 90.0     # time stop, in sim minutes
    otm_steps: int = 0             # 0 = ATM strikes
    color: str = "#7c5cff"
    params: dict = field(default_factory=dict)   # strategy-specific settings


class Bot:
    strategy_name = "base"

    def __init__(self, cfg: BotConfig, broker: Broker, emit: Callable[[Event], None]) -> None:
        self.cfg = cfg
        self.broker = broker
        self.emit = emit
        self.status = "scanning"
        self.position: Optional[Position] = None
        self.plan: Optional[Entry] = None
        self.scaled = False
        self.realized = 0.0
        self.trades: list[TradeRecord] = []
        self._opened_clock = 0.0
        self._last_bar_count = -1
        self._entry_underlying = 0.0

    # ---- strategy hooks -------------------------------------------------
    def on_bar(self, htf: Optional[list[Bar]], ltf: list[Bar], market: Market) -> Optional[Entry]:
        """Called on every closed 1m candle while flat. `htf` holds the bot's
        timeframe candles when one just closed, else None. Return an Entry to trade."""
        raise NotImplementedError

    def exit_on_bar(self, htf: Optional[list[Bar]], ltf: list[Bar], market: Market) -> Optional[str]:
        """Called on every closed 1m candle while in a trade. Return a reason to exit."""
        return None

    def on_signal(self, sig: dict, market: Market) -> Optional[str]:
        """An external alert (TradingView webhook). Return a description if acted on."""
        return None

    def on_position_closed(self, pnl: float) -> None:
        pass

    def reset_day(self) -> None:
        pass

    def info(self) -> dict:
        """Extra strategy details for the UI."""
        return {}

    # ---- lifecycle ------------------------------------------------------
    def on_tick(self, market: Market) -> None:
        if self.status in DONE_FOR_DAY:
            return
        u = market.underlyings[self.cfg.underlying]
        if self.position:
            self._manage_tick(u, market)

        if u.bar_count == self._last_bar_count or not u.bars or self.status in DONE_FOR_DAY:
            return
        self._last_bar_count = u.bar_count
        htf = self._candles(u) if u.bar_count % self.cfg.timeframe == 0 else None
        if self.position:
            reason = self.exit_on_bar(htf, u.bars, market)
            if reason:
                self._close(reason, market)
        elif market.minutes_to_close > 10:
            entry = self.on_bar(htf, u.bars, market)
            if entry and self.status not in DONE_FOR_DAY:
                self._open(entry, u, market)

    def _candles(self, u: Underlying) -> list[Bar]:
        tf = self.cfg.timeframe
        n = (len(u.bars) // tf) * tf
        return aggregate(u.bars[len(u.bars) - n:], tf)

    def _open(self, entry: Entry, u: Underlying, market: Market) -> None:
        if self.cfg.instrument == "future":
            self.position = self.broker.open(self.cfg.underlying, entry.side, self.cfg.contracts, market)
        else:
            kind = "call" if entry.side == "long" else "put"
            strike = u.atm_strike(kind, self.cfg.otm_steps)
            self.position = self.broker.open(self.cfg.underlying, kind, self.cfg.contracts, market, strike)
        self.plan = entry
        self.scaled = False
        self._entry_underlying = u.price
        self._opened_clock = market.clock_min
        self.status = "in_trade"
        self.emit({"type": "trade_open", "bot": self.cfg.id, "contract": self.position.label,
                   "qty": self.position.qty, "entry": round(self.position.entry, 2), "note": entry.note})

    def _manage_tick(self, u: Underlying, market: Market) -> None:
        pos, plan = self.position, self.plan
        long = plan.side == "long"
        price = u.price
        if (long and price <= plan.stop) or (not long and price >= plan.stop):
            return self._close("stop hit" if not self.scaled else "runner stopped", market)
        if plan.target is not None and not self.scaled and ((long and price >= plan.target) or (not long and price <= plan.target)):
            if pos.qty > 1:
                self._scale_out(pos.qty // 2, market)
            else:
                return self._close("target hit", market)
        if not pos.is_future and self.cfg.option_stop_pct is not None:
            if self.broker.mark(pos, market) / pos.entry - 1 <= -self.cfg.option_stop_pct:
                return self._close("premium stop", market)
        if market.clock_min - self._opened_clock >= self.cfg.max_hold_min:
            return self._close("time stop", market)
        if market.minutes_to_close <= 5:
            return self._close("end of day", market)

    def _record(self, qty: int, exit_px: float, reason: str, market: Market) -> TradeRecord:
        pos = self.position
        pnl = pos.pnl(exit_px, qty)
        self.realized += pnl
        rec = TradeRecord(next(_trade_ids), self.cfg.id, pos.label, qty, round(pos.entry, 2),
                          round(exit_px, 2), round(pnl, 2), reason, pos.opened_at, market.clock_str)
        self.trades.append(rec)
        return rec

    def _scale_out(self, qty: int, market: Market) -> None:
        """Take part of the position off at the first target and move the runner's stop to breakeven."""
        rec = self._record(qty, self.broker.close(self.position, market), "target · scaled out", market)
        self.position.qty -= qty
        self.scaled = True
        self.plan.stop = self._entry_underlying
        self.emit({"type": "trade_close", "bot": self.cfg.id, "pnl": rec.pnl, "reason": rec.reason,
                   "contract": rec.contract, "status": self.status, "partial": True})

    def _close(self, reason: str, market: Market) -> None:
        pos = self.position
        rec = self._record(pos.qty, self.broker.close(pos, market), reason, market)
        total = sum(t.pnl for t in self.trades if t.opened_at == pos.opened_at and t.contract == pos.label)
        self.position = None
        self.plan = None
        self.status = "scanning"
        self.on_position_closed(total)
        if self.status not in DONE_FOR_DAY:
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
        self.reset_day()
        if self.status != "disabled":
            self.status = "scanning"

    # ---- reporting ------------------------------------------------------
    def snapshot(self, market: Market) -> dict:
        unreal = 0.0
        pos = None
        if self.position:
            mark = self.broker.mark(self.position, market)
            unreal = self.position.pnl(mark)
            pos = {"contract": self.position.label, "qty": self.position.qty,
                   "entry": round(self.position.entry, 2), "mark": round(mark, 2),
                   "stop": round(self.plan.stop, 2),
                   "target": round(self.plan.target, 2) if self.plan.target is not None else None,
                   "note": self.plan.note}
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return {
            "id": self.cfg.id, "name": self.cfg.name, "underlying": self.cfg.underlying,
            "district": self.cfg.district, "strategy": self.strategy_name, "color": self.cfg.color,
            "instrument": self.cfg.instrument, "timeframe": self.cfg.timeframe,
            "status": self.status, "realized": round(self.realized, 2), "unrealized": round(unreal, 2),
            "trades": len(self.trades), "wins": wins, "position": pos,
            "profit_brake": self.cfg.profit_brake, "max_daily_loss": self.cfg.max_daily_loss,
            "info": self.info(),
            "recent": [t.__dict__ for t in self.trades[-8:]][::-1],
        }
