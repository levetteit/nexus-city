"""Base class for every worker that lives in the city.

A bot owns one building, trades one symbol, and shares a single prop firm
account (`backend/account.py`) with every other bot. It follows the same
shift rules:

* scanning  - on shift, waiting for its strategy to fire a setup
* in_trade  - holding a position (the building's light beam turns on)
* off_duty  - the account reached its daily goal / cap / profit target, clocked out
* stopped   - the account hit its daily stop (or failed), sent home
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

from ..account import PropAccount
from ..broker import Broker, Position
from ..market import Bar, Market, Underlying, aggregate

Event = dict
_trade_ids = itertools.count(1)
DONE_FOR_DAY = ("off_duty", "stopped", "walked", "disabled")


@dataclass
class Entry:
    """A trade plan. There is no stop: the strategy decides when to get out."""
    side: str                 # 'long' | 'short'
    target: Optional[float]   # where the move is expected to go (shown in the UI only)
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
    instrument: str = "future"     # 'future' | 'option'
    timeframe: int = 3             # candle size in minutes for the bot's main signal
    contracts: int = 3             # size of the first entry and of each add
    max_contracts: int = 6         # never hold more than this
    otm_steps: int = 0             # 0 = ATM strikes
    enabled: bool = True           # False: the building stands, the bot starts switched off
    color: str = "#7c5cff"
    params: dict = field(default_factory=dict)   # strategy-specific settings


class Bot:
    strategy_name = "base"

    def __init__(self, cfg: BotConfig, broker: Broker, emit: Callable[[Event], None], account: PropAccount) -> None:
        self.cfg = cfg
        self.broker = broker
        self.emit = emit
        self.account = account
        self.status = "scanning" if cfg.enabled else "disabled"
        self.position: Optional[Position] = None
        self.plan: Optional[Entry] = None
        self.realized = 0.0
        self.trades: list[TradeRecord] = []
        self._last_bar_count = -1

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
    def observe(self, bar: Bar, market: Market) -> None:
        """Called on every closed 1m candle, even when the bot is done for the day,
        so strategies that track market structure never miss a candle."""

    uses_htf = True   # build the bot's own-timeframe candles for on_bar/exit_on_bar

    def on_tick(self, market: Market, trade: bool = True) -> None:
        """`trade=False` only reads the candle (used to warm up on history before going live)."""
        u = market.underlyings[self.cfg.underlying]
        new_bar = bool(u.bars) and u.bar_count != self._last_bar_count
        if new_bar:
            self._last_bar_count = u.bar_count
            self.observe(u.bars[-1], market)
        if not trade or self.status in DONE_FOR_DAY:
            return
        if self.position:
            self._manage_tick(u, market)
        if not new_bar or self.status in DONE_FOR_DAY:
            return
        htf = self._candles(u) if self.uses_htf and u.bar_count % self.cfg.timeframe == 0 else None
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

    def _buy(self, side: str, qty: int, u: Underlying, market: Market) -> Position:
        if self.cfg.instrument == "future":
            return self.broker.open(self.cfg.underlying, side, qty, market)
        kind = "call" if side == "long" else "put"
        return self.broker.open(self.cfg.underlying, kind, qty, market, u.atm_strike(kind, self.cfg.otm_steps))

    def _open(self, entry: Entry, u: Underlying, market: Market) -> None:
        qty = self.account.request(self.cfg.id, self.cfg.underlying, self.cfg.contracts)
        if qty < self.cfg.contracts:   # never open undersized; wait for room in the budget
            return
        self.position = self._buy(entry.side, qty, u, market)
        self.account.filled(self.cfg.id, self.cfg.underlying, qty)
        self.plan = entry
        self.status = "in_trade"
        self.emit({"type": "trade_open", "bot": self.cfg.id, "contract": self.position.label,
                   "qty": self.position.qty, "entry": round(self.position.entry, 2), "note": entry.note})

    def add(self, market: Market, why: str) -> bool:
        """Size up the open position by `contracts`, up to `max_contracts`."""
        pos = self.position
        want = min(self.cfg.contracts, self.cfg.max_contracts - pos.qty)
        qty = self.account.request(self.cfg.id, self.cfg.underlying, want, adding=True) if want > 0 else 0
        if qty <= 0:
            return False
        extra = self._buy(self.plan.side, qty, market.underlyings[self.cfg.underlying], market)
        pos.entry = (pos.entry * pos.qty + extra.entry * qty) / (pos.qty + qty)
        pos.qty += qty
        self.account.filled(self.cfg.id, self.cfg.underlying, qty)
        self.emit({"type": "trade_add", "bot": self.cfg.id, "qty": qty, "total": pos.qty, "why": why})
        return True

    def _manage_tick(self, u: Underlying, market: Market) -> None:
        # No stop loss, target or time stop: exits come from the strategy
        # (exit_on_bar / on_signal). The one forced exit is just before the
        # 16:45 ET flat deadline: prop firms don't allow overnight holds.
        if market.minutes_to_close <= 5:
            self._close("end of day", market)

    def _record(self, qty: int, exit_px: float, reason: str, market: Market) -> TradeRecord:
        pos = self.position
        pnl = pos.pnl(exit_px, qty)
        self.realized += pnl
        rec = TradeRecord(next(_trade_ids), self.cfg.id, pos.label, qty, round(pos.entry, 2),
                          round(exit_px, 2), round(pnl, 2), reason, pos.opened_at, market.clock_str)
        self.trades.append(rec)
        return rec

    def _close(self, reason: str, market: Market) -> None:
        pos = self.position
        rec = self._record(pos.qty, self.broker.close(pos, market), reason, market)
        self.account.closed(self.cfg.id, self.cfg.underlying, rec.pnl)
        self.position = None
        self.plan = None
        if self.status not in DONE_FOR_DAY:
            self.status = "scanning"
        self.on_position_closed(rec.pnl)
        self.emit({"type": "trade_close", "bot": self.cfg.id, "pnl": rec.pnl, "reason": reason,
                   "contract": rec.contract, "status": self.status})

    def halt(self, reason: str, status: str, market: Market) -> None:
        """The account stopped trading: flatten and clock out."""
        if self.status == "disabled":
            return
        self.status = status
        if self.position:
            self._close(f"account: {reason}", market)

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
                   "target": round(self.plan.target, 2) if self.plan.target is not None else None,
                   "note": self.plan.note}
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return {
            "id": self.cfg.id, "name": self.cfg.name, "underlying": self.cfg.underlying,
            "district": self.cfg.district, "strategy": self.strategy_name, "color": self.cfg.color,
            "instrument": self.cfg.instrument, "timeframe": self.cfg.timeframe,
            "status": self.status, "realized": round(self.realized, 2), "unrealized": round(unreal, 2),
            "trades": len(self.trades), "wins": wins, "position": pos,
            "contracts": self.cfg.contracts, "max_contracts": self.cfg.max_contracts,
            "info": self.info(),
            "recent": [t.__dict__ for t in self.trades[-8:]][::-1],
        }
