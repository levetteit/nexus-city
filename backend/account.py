"""The prop firm account every bot trades in.

All workers share ONE account, the way a prop evaluation works. This module
enforces the firm's rules plus a safety layer of our own, so the bots can pass
the evaluation and then keep the funded account alive.

Default firm: Lucid Trading, LucidFlex 50K (rules as published in 2026; edit
the presets below if they change or you use another plan):
  * Profit target: $3,000 (evaluation, minimum 2 trading days).
  * Max Loss Limit: end-of-day (EOD) drawdown of $2,000. The MLL is set from
    the highest *closing* balance and only moves at the close, never during
    the day. It locks for good at the starting balance + $100 ($50,100) once
    the account closes at or above $52,100. We treat equity touching the MLL
    during the day as a breach, which is the safe reading.
  * Consistency: in the LucidFlex evaluation the best day must be <= 50% of
    total profit (a bigger best day raises the profit needed to 2x that day).
    LucidFlex funded has none. LucidPro: none in the evaluation, 40% funded.
  * No daily loss limit. Max size 40 micros.
  * Every position must be flat by 16:45 ET; no overnight or weekend holds.

Our safety layer (`Guards`), tighter than the firm so we never touch its lines:
  * daily goal $600: once closed P&L for the day reaches it, no new trades
    (open trades still run until a pointer forms against them)
  * daily cap $1,200: flatten everything at +$1,200 (open + closed); this also
    keeps the best day inside the 50% consistency rule ($1,500 max)
  * daily stop -$600 (open + closed), shrunk on days the account starts close
    to the MLL so a loss can never reach it (we keep a $250 cushion: real
    1-minute candles can move a few hundred dollars against 12 micros)
  * when today's stop is under $500 (little room left), only one 3-contract
    position at a time
  * 3 losing trades in a row -> stop for the day (losing days are chop)
  * less than $150 of room above the MLL -> stop trading, ask for a reset
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
    max_loss: float                     # EOD drawdown size
    mll_lock_offset: float              # MLL stops trailing at start_balance + this
    eval_consistency: Optional[float]   # best day <= this share of profit (evaluation)
    funded_consistency: Optional[float] # same rule in the funded stage (for payouts)
    min_eval_days: int
    max_micros: int
    payout_days: int                    # profitable days needed before a payout request
    payout_buffer: float                # funded balance must exceed start + this to request


LUCIDFLEX_50K = PropRules(
    name="LucidFlex 50K", start_balance=50_000, profit_target=3_000, max_loss=2_000,
    mll_lock_offset=100, eval_consistency=0.5, funded_consistency=None, min_eval_days=2,
    max_micros=40, payout_days=5, payout_buffer=0,
)

LUCIDPRO_50K = PropRules(
    name="LucidPro 50K", start_balance=50_000, profit_target=3_000, max_loss=2_000,
    mll_lock_offset=100, eval_consistency=None, funded_consistency=0.4, min_eval_days=1,
    max_micros=40, payout_days=5, payout_buffer=2_100,
)


@dataclass
class Guards:
    daily_goal: float = 600.0          # no new trades once closed P&L reaches this
    daily_cap: float = 1_200.0         # flatten at this (open + closed); tested best on real data
    daily_stop: float = 600.0          # flatten at -this (open + closed); smaller losing days, tested on real data
    mll_cushion: float = 250.0         # never let a day's loss get closer than this to the MLL
    min_room: float = 150.0            # less room than this above the MLL -> stop trading
    max_loss_streak: int | None = 3      # stop for the day after this many losing trades in a row
    lock_trigger: float | None = None    # once the day has been up this much (open + closed)...
    lock_floor: float = 0.0              # ...flatten and stop if it falls back to this
    thin_room: float = 500.0           # a day stop below this -> only one 3-contract position at a time
    thin_micros: int = 3
    max_open_micros: int = 12          # e.g. two bots at the full 6


@dataclass
class PropAccount:
    rules: PropRules = field(default_factory=lambda: LUCIDFLEX_50K)
    guards: Guards = field(default_factory=Guards)
    phase: str = "evaluation"          # evaluation | funded | failed
    balance: float = 0.0
    eod_high: float = 0.0
    mll: float = 0.0
    mll_locked: bool = False
    day_realized: float = 0.0
    day_open: float = 0.0              # unrealized, refreshed each tick by the engine
    halted: str = ""                   # why trading stopped for the day, if it did
    day_stop: float = 0.0              # today's loss limit (daily_stop, or less near the MLL)
    loss_streak: int = 0
    day_peak: float = 0.0
    best_day: float = 0.0
    days: int = 0
    profitable_days: int = 0
    log: list[str] = field(default_factory=list)
    day_history: list[tuple[str, float]] = field(default_factory=list)   # (phase, closed P&L) per day
    open_micros: dict[str, int] = field(default_factory=dict)   # bot id -> contracts held
    symbol_owner: dict[str, str] = field(default_factory=dict)  # symbol -> bot id holding it

    def __post_init__(self) -> None:
        self.reset("evaluation")

    # ---- lifecycle ----------------------------------------------------------
    def reset(self, phase: str = "evaluation") -> None:
        r = self.rules
        if self.day_realized:   # a day cut short by a reset still counts in the history
            self.day_history.append((self.phase, round(self.day_realized, 2)))
        self.phase = phase
        self.balance = self.eod_high = r.start_balance
        self.mll = r.start_balance - r.max_loss
        self.mll_locked = False
        self.day_realized = self.day_open = self.best_day = 0.0
        self.days = self.profitable_days = 0
        self.open_micros.clear()
        self.symbol_owner.clear()
        self._note(f"{r.name} {phase} started at ${r.start_balance:,.0f}")
        self._start_day()

    def _start_day(self) -> None:
        g = self.guards
        room = self.balance - self.mll - g.mll_cushion
        self.day_stop = min(g.daily_stop, room)
        self.halted = ""
        self.loss_streak = 0
        self.day_peak = 0.0
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
    def consistency(self) -> Optional[float]:
        r = self.rules
        return r.eval_consistency if self.phase == "evaluation" else r.funded_consistency

    @property
    def target_needed(self) -> float:
        """Evaluation profit needed, raised if the best day breaks consistency."""
        c = self.consistency
        return max(self.rules.profit_target, self.best_day / c if c else 0)

    @property
    def max_micros(self) -> int:
        g = self.guards
        cap = g.thin_micros if self.day_stop < g.thin_room else g.max_open_micros   # near the MLL: size down
        return min(self.rules.max_micros, cap)

    @property
    def goal_reached(self) -> bool:
        return self.day_realized >= self.guards.daily_goal

    @property
    def can_trade(self) -> bool:
        return self.phase != "failed" and not self.halted

    @property
    def payout_eligible(self) -> bool:
        r = self.rules
        if self.phase != "funded" or self.profitable_days < r.payout_days or self.profit <= 0:
            return False
        if self.balance < r.start_balance + r.payout_buffer:
            return False
        c = r.funded_consistency
        return not c or self.best_day <= c * self.profit

    # ---- position budget ----------------------------------------------------
    def request(self, bot_id: str, symbol: str, qty: int, adding: bool = False) -> int:
        """How many of `qty` contracts this bot may open now (0 = none)."""
        if not self.can_trade or (self.goal_reached and not adding):
            return 0
        owner = self.symbol_owner.get(symbol)
        if owner and owner != bot_id:
            return 0
        room = self.max_micros - sum(self.open_micros.values())
        return max(0, min(qty, room))

    def filled(self, bot_id: str, symbol: str, qty: int) -> None:
        self.open_micros[bot_id] = self.open_micros.get(bot_id, 0) + qty
        self.symbol_owner[symbol] = bot_id

    def closed(self, bot_id: str, symbol: str, pnl: float, trade_pnl: Optional[float] = None) -> None:
        """`pnl`: this last exit. `trade_pnl`: the whole trade including earlier trims (decides the losing streak)."""
        self.open_micros.pop(bot_id, None)
        if self.symbol_owner.get(symbol) == bot_id:
            del self.symbol_owner[symbol]
        self.balance += pnl
        self.day_realized += pnl
        whole = pnl if trade_pnl is None else trade_pnl
        self.loss_streak = self.loss_streak + 1 if whole <= 0 else 0

    def trimmed(self, bot_id: str, qty: int, pnl: float) -> None:
        """Part of a position was closed for profit (a trim); the rest stays open."""
        self.open_micros[bot_id] = max(0, self.open_micros.get(bot_id, 0) - qty)
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
            return "max loss limit"
        if self.halted:
            return None
        g = self.guards
        self.day_peak = max(self.day_peak, self.day_pnl)
        if self.day_pnl <= -self.day_stop:
            self.halted = f"daily stop -${self.day_stop:,.0f}"
        elif g.lock_trigger and self.day_peak >= g.lock_trigger and self.day_pnl <= g.lock_floor:
            self.halted = f"profit lock: day was up ${self.day_peak:,.0f}, kept +${self.day_pnl:,.0f}"
        elif g.max_loss_streak and self.loss_streak >= g.max_loss_streak:
            self.halted = f"{self.loss_streak} losing trades in a row · stop for the day"
        elif self.day_pnl >= g.daily_cap:
            self.halted = f"daily cap +${g.daily_cap:,.0f} locked in"
        elif self.phase == "evaluation" and self.profit + self.day_open >= self.target_needed \
                and self.days + 1 >= self.rules.min_eval_days:
            self.halted = "profit target reached"
        if self.halted:
            self._note(f"day halted: {self.halted}")
            return self.halted
        return None

    def end_of_day(self) -> None:
        """Roll the day at 16:45: move the EOD drawdown, score consistency, pass."""
        r = self.rules
        if self.phase == "failed":
            return
        day = self.day_realized
        self.day_history.append((self.phase, round(day, 2)))
        self.days += 1
        self.best_day = max(self.best_day, day)
        if day > 0:
            self.profitable_days += 1
        # EOD drawdown: trails the highest close, locks at start + offset
        self.eod_high = max(self.eod_high, self.balance)
        lock = r.start_balance + r.mll_lock_offset
        if not self.mll_locked:
            self.mll = max(self.mll, min(self.eod_high - r.max_loss, lock))
            self.mll_locked = self.mll >= lock
        self._note(f"day {self.days}: {'+' if day >= 0 else '-'}${abs(day):,.0f} · balance ${self.balance:,.0f} · MLL ${self.mll:,.0f}")

        if self.phase == "evaluation" and self.profit >= self.target_needed and self.days >= r.min_eval_days:
            self._note(f"PASSED the evaluation in {self.days} days (+${self.profit:,.0f}) → funded")
            self.reset("funded")
            return
        if self.payout_eligible:
            self._note(f"payout eligible: {self.profitable_days} profitable days, +${self.profit:,.0f}")

        self.day_realized = self.day_open = 0.0
        self._start_day()

    def snapshot(self) -> dict:
        r, g = self.rules, self.guards
        return {
            "firm": r.name, "phase": self.phase, "balance": round(self.balance, 2),
            "equity": round(self.equity, 2), "profit": round(self.profit, 2),
            "target": round(self.target_needed, 2) if self.phase == "evaluation" else None,
            "mll": round(self.mll, 2), "mll_locked": self.mll_locked, "day_pnl": round(self.day_pnl, 2),
            "daily_stop": round(self.day_stop, 2), "goal": g.daily_goal, "cap": g.daily_cap,
            "goal_reached": self.goal_reached, "halted": self.halted,
            "best_day": round(self.best_day, 2), "consistency": self.consistency, "days": self.days,
            "profitable_days": self.profitable_days, "payout_days": r.payout_days,
            "payout_eligible": self.payout_eligible, "open_micros": sum(self.open_micros.values()),
            "max_micros": self.max_micros, "log": self.log[-8:][::-1],
        }
