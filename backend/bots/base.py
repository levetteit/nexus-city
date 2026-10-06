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
    t_open: int = 0     # candle minute the trade opened / closed (chart markers)
    t_close: int = 0
    trim: bool = False  # a partial exit; the rest of the position stayed open


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
    persona: dict = field(default_factory=dict)   # streamer-room personality: handle, vibe, props, lines
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
        self.career = 0.0        # lifetime P&L, never reset: buys gadgets for the bot's room
        self.career_best = 0.0   # high-water mark, so gadgets are never taken back
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

    _t_open = 0
    _trade_pnl = 0.0

    def _last_t(self, market: Market) -> int:
        bars = market.underlyings[self.cfg.underlying].bars
        return bars[-1].t if bars else 0

    def chart(self, market: Market, tf: int = 1, count: int = 180) -> dict:
        """Clock-aligned candles on `tf` minutes plus today's trades, for the full-screen chart."""
        u = market.underlyings[self.cfg.underlying]
        candles: list[list] = []
        for b in u.bars[-(count + 1) * tf:]:
            start = b.t - b.t % tf
            if candles and candles[-1][0] == start:
                c = candles[-1]
                c[2], c[3], c[4] = max(c[2], b.high), min(c[3], b.low), b.close
            else:
                candles.append([start, b.open, b.high, b.low, b.close, b.time])
        candles = candles[-count:]
        trades = [{"side": "long" if t.contract.endswith("LONG") else "short", "qty": t.qty, "entry": t.entry,
                   "exit": t.exit, "pnl": t.pnl, "t_open": t.t_open - t.t_open % tf,
                   "t_close": t.t_close - t.t_close % tf, "reason": t.reason, "opened": t.opened_at,
                   "closed": t.closed_at} for t in self.trades]
        pos = None
        if self.position:
            mark = self.broker.mark(self.position, market)
            pos = {"side": self.plan.side, "qty": self.position.qty, "entry": self.position.entry,
                   "pnl": round(self.position.pnl(mark), 2), "t_open": self._t_open - self._t_open % tf,
                   "why": self.plan.note}
        return {"symbol": self.cfg.underlying, "name": self.cfg.name, "color": self.cfg.color, "tf": tf,
                "clock": market.clock_str, "price": u.price, "candles": candles, "trades": trades,
                "position": pos, "zones": [], "procs": [], "partner": None, "status": self.status}

    news_hold = None   # a NewsEvent while the engine's news filter blocks new trades (see news.py)

    desk_mode = None   # the trading desk's active risk mode, if not normal (see desk.py)

    def _news_blocked(self, what: str, adding: bool = False) -> bool:
        """News pause, or the desk taking risk off: sit_out blocks entries, cautious blocks adds."""
        why = None
        if self.news_hold is not None:
            why = f"{self.news_hold.label} news"
        elif self.desk_mode and (self.desk_mode["mode"] == "sit_out" or (adding and self.desk_mode["mode"] == "cautious")):
            why = f"desk: {self.desk_mode['mode'].replace('_', ' ')}"
        if why is None:
            return False
        if hasattr(self, "last_event"):
            self.last_event = f"{what} skipped · {why}"
        return True

    def _open(self, entry: Entry, u: Underlying, market: Market) -> None:
        if self._news_blocked(f"{entry.side} entry"):
            return
        qty = self.account.request(self.cfg.id, self.cfg.underlying, self.cfg.contracts)
        if qty < self.cfg.contracts:   # never open undersized; wait for room in the budget
            return
        self.position = self._buy(entry.side, qty, u, market)
        self._t_open = self._last_t(market)
        self._trade_pnl = 0.0   # P&L already banked by trims on this trade
        self.account.filled(self.cfg.id, self.cfg.underlying, qty)
        self.plan = entry
        self.status = "in_trade"
        self.emit({"type": "trade_open", "bot": self.cfg.id, "contract": self.position.label,
                   "qty": self.position.qty, "entry": round(self.position.entry, 2), "note": entry.note})

    def add(self, market: Market, why: str) -> bool:
        """Size up the open position by `contracts`, up to `max_contracts`."""
        pos = self.position
        if self._news_blocked("add", adding=True):
            return False
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
        self.career += pnl
        self.career_best = max(self.career_best, self.career)
        rec = TradeRecord(next(_trade_ids), self.cfg.id, pos.label, qty, round(pos.entry, 2),
                          round(exit_px, 2), round(pnl, 2), reason, pos.opened_at, market.clock_str,
                          t_open=self._t_open, t_close=self._last_t(market))
        self.trades.append(rec)
        return rec

    def trim(self, qty: int, why: str, market: Market, price: Optional[float] = None) -> bool:
        """Take partial profit: close `qty` contracts (at `price` for a resting limit), keep the rest."""
        pos = self.position
        qty = min(qty, pos.qty - 1)   # never trims the last contract: that's the runner
        if qty <= 0:
            return False
        rec = self._record(qty, self.broker.close(pos, market, price), f"trim: {why}", market)
        rec.trim = True
        pos.qty -= qty
        self._trade_pnl += rec.pnl
        self.account.trimmed(self.cfg.id, qty, rec.pnl)
        self.emit({"type": "trade_trim", "bot": self.cfg.id, "qty": qty, "left": pos.qty, "pnl": rec.pnl,
                   "price": rec.exit, "why": why})
        return True

    def _close(self, reason: str, market: Market) -> None:
        pos = self.position
        rec = self._record(pos.qty, self.broker.close(pos, market), reason, market)
        whole = round(self._trade_pnl + rec.pnl, 2)
        self.account.closed(self.cfg.id, self.cfg.underlying, rec.pnl, whole)
        self.position = None
        self.plan = None
        if self.status not in DONE_FOR_DAY:
            self.status = "scanning"
        self._trade_pnl = 0.0
        self.on_position_closed(whole)
        self.emit({"type": "trade_close", "bot": self.cfg.id, "pnl": rec.pnl, "trade_pnl": whole, "reason": reason,
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

    def room(self, market: Market) -> dict:
        """What the bot's monitors show: recent candles, its zones, PROC and position."""
        u = market.underlyings[self.cfg.underlying]
        out = {
            "symbol": self.cfg.underlying, "clock": market.clock_str, "price": u.price,
            "candles": [[b.t, b.open, b.high, b.low, b.close] for b in u.bars[-90:]],
            "zones": [], "proc": None, "position": None,
            "trades": [t.__dict__ for t in self.trades[-12:]],
        }
        if self.position:
            mark = self.broker.mark(self.position, market)
            out["position"] = {"side": self.plan.side, "qty": self.position.qty, "entry": self.position.entry,
                               "pnl": round(self.position.pnl(mark), 2), "target": self.plan.target}
        return out

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
        whole = [t for t in self.trades if not t.trim]   # trims are part of a trade, not trades of their own
        wins = sum(1 for t in whole if t.pnl > 0)
        return {
            "id": self.cfg.id, "name": self.cfg.name, "underlying": self.cfg.underlying,
            "district": self.cfg.district, "strategy": self.strategy_name, "color": self.cfg.color,
            "instrument": self.cfg.instrument, "timeframe": self.cfg.timeframe,
            "status": self.status, "realized": round(self.realized, 2), "unrealized": round(unreal, 2),
            "trades": len(whole), "wins": wins, "position": pos,
            "contracts": self.cfg.contracts, "max_contracts": self.cfg.max_contracts,
            "info": self.info(),
            "persona": self.cfg.persona,
            "career": round(self.career, 2), "career_best": round(self.career_best, 2),
            "recent": [t.__dict__ for t in self.trades[-8:]][::-1],
        }
