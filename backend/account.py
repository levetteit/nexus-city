"""The prop firm account every bot trades in.

All workers share ONE account, the way a Topstep evaluation works. This module
enforces the firm's rules plus a safety layer of our own, so the bots can pass
the Trading Combine and then keep the Express Funded Account (XFA) alive.

Firm rules (Topstep 50K, as published in 2026; edit `TOPSTEP_50K` if they change):
  * Profit target: $3,000 (Combine).
  * Maximum Loss Limit: $2,000 below the highest end-of-day balance, checked in
    real time including open P&L. It stops trailing once it reaches the
    starting balance. Touching it fails the account.
  * Consistency: best day should be <= 50% of total profit. A bigger best day
    raises the profit needed to pass (2x the best day).
  * Position size: 50 micros in the Combine. The XFA scaling plan allows
    20 micros until +$1,500, 30 until +$2,000, then 50.
  * XFA payouts: after 5 winning days of >= $150, request 50% of profit, capped
    at $2,000. A payout locks the MLL at the starting balance.

Our safety layer (`Guards`), tighter than the firm so we never touch its lines:
  * daily stop: flatten everything and stop for the day at -$800 (open + closed),
    shrunk on days the account starts close to the MLL so a loss can never
    reach it (we keep a $100 cushion)
  * if there's less than $150 of room left above the MLL, the bots stop trading
    and the account asks for a reset
  * daily profit cap: flatten and stop at +$1,400 (open + closed) so one day
    never breaks the 50% consistency rule; same once the profit target is in hand
  * contract budget: at most 12 micros open across all bots (each trade is 3-6)
  * one bot per symbol at a time, so bots never hold opposite sides of the same contract
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PropRules:
    name: str
    start_balance: float
    profit_target: float
    max_loss: float
    consistency_pct: float
    combine_max_micros: int
    xfa_scaling: list[tuple[float, int]]        # (profit reached, micros allowed)
    payout_winning_days: int
    payout_min_day: float
    payout_pct: float
    payout_cap: float


TOPSTEP_50K = PropRules(
    name="Topstep 50K", start_balance=50_000, profit_target=3_000, max_loss=2_000,
    consistency_pct=0.5, combine_max_micros=50,
    xfa_scaling=[(0, 20), (1_500, 30), (2_000, 50)],
    payout_winning_days=5, payout_min_day=150, payout_pct=0.5, payout_cap=2_000,
)


@dataclass
class Guards:
    daily_stop: float = 800.0          # below Topstep's optional $1,000 daily loss limit
    mll_cushion: float = 100.0         # never let a day's loss get closer than this to the MLL
    min_room: float = 150.0            # less room than this above the MLL -> stop trading
    daily_profit_cap: float = 1_400.0  # below 50% of the $3,000 target
    max_open_micros: int = 12          # e.g. two bots at the full 6


@dataclass
class PropAccount:
    rules: PropRules = field(default_factory=lambda: TOPSTEP_50K)
    guards: Guards = field(default_factory=Guards)
    phase: str = "combine"             # combine | funded | failed
    balance: float = 0.0
    eod_high: float = 0.0
    mll: float = 0.0
    day_realized: float = 0.0
    day_open: float = 0.0              # unrealized, refreshed each tick by the engine
    halted: str = ""                   # why trading stopped for the day, if it did
    day_stop: float = 0.0              # today's loss limit (daily_stop, or less near the MLL)
    best_day: float = 0.0
    days: int = 0
    winning_days: int = 0
    payouts: list[float] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    open_micros: dict[str, int] = field(default_factory=dict)   # bot id -> contracts held
    symbol_owner: dict[str, str] = field(default_factory=dict)  # symbol -> bot id holding it

    def __post_init__(self) -> None:
        self.reset("combine")

    # ---- lifecycle ----------------------------------------------------------
    def reset(self, phase: str = "combine") -> None:
        r = self.rules
        self.phase = phase
        self.balance = self.eod_high = r.start_balance
        self.mll = r.start_balance - r.max_loss
        self.day_realized = self.day_open = self.best_day = 0.0
        self.days = self.winning_days = 0
        self.open_micros.clear()
        self._start_day()
        self.symbol_owner.clear()
        self._note(f"{'Trading Combine' if phase == 'combine' else 'Express Funded Account'} started at ${r.start_balance:,.0f}")

    def _start_day(self) -> None:
        g = self.guards
        room = self.balance - self.mll - g.mll_cushion
        self.day_stop = min(g.daily_stop, room)
        self.halted = ""
        if room < g.min_room:
            self.halted = f"only ${self.balance - self.mll:,.0f} above the MLL · reset recommended"
            self._note(self.halted)

    def _note(self, msg: str) -> None:
        self.log.append(msg)
        self.log[:] = self.log[-20:]

    @property
    def profit(self) -> float:
        return self.balance - self.rules.start_balance

    @property
    def equity(self) -> float:
        return self.balance + self.day_open

    @property
    def day_pnl(self) -> float:
        return self.day_realized + self.day_open

    @property
    def target_needed(self) -> float:
        """Combine profit needed, raised if the best day breaks consistency."""
        return max(self.rules.profit_target, self.best_day / self.rules.consistency_pct)

    @property
    def max_micros(self) -> int:
        """Contracts allowed right now: the firm's limit, then our tighter budget."""
        if self.phase == "combine":
            firm = self.rules.combine_max_micros
        else:
            scaling = self.rules.xfa_scaling
            firm = max((m for p, m in scaling if self.profit >= p), default=scaling[0][1])
        return min(firm, self.guards.max_open_micros)

    @property
    def can_trade(self) -> bool:
        return self.phase != "failed" and not self.halted

    # ---- position budget ----------------------------------------------------
    def request(self, bot_id: str, symbol: str, qty: int) -> int:
        """How many of `qty` contracts this bot may add now (0 = none)."""
        if not self.can_trade:
            return 0
        owner = self.symbol_owner.get(symbol)
        if owner and owner != bot_id:
            return 0
        room = self.max_micros - sum(self.open_micros.values())
        return max(0, min(qty, room))

    def filled(self, bot_id: str, symbol: str, qty: int) -> None:
        self.open_micros[bot_id] = self.open_micros.get(bot_id, 0) + qty
        self.symbol_owner[symbol] = bot_id

    def closed(self, bot_id: str, symbol: str, pnl: float) -> None:
        self.open_micros.pop(bot_id, None)
        if self.symbol_owner.get(symbol) == bot_id:
            del self.symbol_owner[symbol]
        self.balance += pnl
        self.day_realized += pnl

    # ---- risk checks (engine calls this every tick) --------------------------
    def check(self, unrealized: float) -> Optional[str]:
        """Update open P&L. Returns a reason if every position must be flattened now."""
        self.day_open = unrealized
        if self.phase == "failed":
            return None
        if self.equity <= self.mll:
            self.phase = "failed"
            self._note(f"FAILED: equity ${self.equity:,.0f} touched the MLL ${self.mll:,.0f}")
            return "maximum loss limit"
        if self.halted:
            return None
        g = self.guards
        if self.day_pnl <= -self.day_stop:
            self.halted = f"daily stop -${self.day_stop:,.0f}"
        elif self.day_pnl >= g.daily_profit_cap:
            self.halted = f"daily profit cap +${g.daily_profit_cap:,.0f}"
        elif self.phase == "combine" and self.profit + self.day_open >= self.target_needed:
            self.halted = "profit target reached"
        if self.halted:
            self._note(f"day halted: {self.halted}")
            return self.halted
        return None

    def end_of_day(self) -> None:
        """Roll the day: trail the MLL, score consistency, pass / pay out."""
        r = self.rules
        if self.phase == "failed":
            return
        day = self.day_realized
        self.days += 1
        self.best_day = max(self.best_day, day)
        if day >= r.payout_min_day:
            self.winning_days += 1
        self.eod_high = max(self.eod_high, self.balance)
        self.mll = max(self.mll, min(self.eod_high - r.max_loss, r.start_balance))
        self._note(f"day {self.days}: {'+' if day >= 0 else '-'}${abs(day):,.0f} · balance ${self.balance:,.0f} · MLL ${self.mll:,.0f}")

        if self.phase == "combine" and self.profit >= self.target_needed:
            self._note(f"PASSED the Combine in {self.days} days (+${self.profit:,.0f}) → Express Funded Account")
            self.reset("funded")
        elif self.phase == "funded" and self.winning_days >= r.payout_winning_days and self.profit > 0:
            amount = min(self.profit * r.payout_pct, r.payout_cap)
            self.balance -= amount
            self.payouts.append(round(amount, 2))
            self.winning_days = 0
            self.mll = r.start_balance
            self._note(f"PAYOUT ${amount:,.0f} requested · MLL locked at ${self.mll:,.0f}")

        self.day_realized = self.day_open = 0.0
        self._start_day()

    def snapshot(self) -> dict:
        r = self.rules
        return {
            "firm": r.name, "phase": self.phase, "balance": round(self.balance, 2),
            "equity": round(self.equity, 2), "profit": round(self.profit, 2),
            "target": round(self.target_needed, 2) if self.phase == "combine" else None,
            "mll": round(self.mll, 2), "day_pnl": round(self.day_pnl, 2),
            "daily_stop": round(self.day_stop, 2), "profit_cap": self.guards.daily_profit_cap,
            "halted": self.halted, "best_day": round(self.best_day, 2), "days": self.days,
            "winning_days": self.winning_days, "payout_days_needed": r.payout_winning_days,
            "payouts": self.payouts, "open_micros": sum(self.open_micros.values()),
            "max_micros": self.max_micros, "log": self.log[-8:][::-1],
        }
