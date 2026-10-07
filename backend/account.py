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
    payout_day_min: float = 0.0         # a day counts toward payout_days only with at least this profit
    payout_min: float = 0.0             # smallest payout request
    payout_max: float = 0.0             # largest payout request ($)
    payout_share: float = 1.0           # ...and at most this share of the profit
    max_payouts: Optional[int] = None   # payouts per account before it moves to a live account
    funded_scaling: tuple = ()          # ((profit from, max micros), ...): funded size limit by profit, set each session


LUCIDFLEX_50K = PropRules(
    name="LucidFlex 50K", start_balance=50_000, profit_target=3_000, max_loss=2_000,
    mll_lock_offset=100, eval_consistency=0.5, funded_consistency=None, min_eval_days=2,
    max_micros=40, payout_days=5, payout_buffer=0,
    # LucidFlex funded (support.lucidtrading.com, Oct 2026): 5 days of $150+ per payout cycle and a
    # positive cycle, payouts $500 up to 50% of profit / $2,000, 5 payouts then live, 90/10 split,
    # the MLL locks at $50,100 after the first payout, scaling plan 20/30/40 micros at $0/$1k/$2k profit.
    payout_day_min=150, payout_min=500, payout_max=2_000, payout_share=0.5, max_payouts=5,
    funded_scaling=((0, 20), (1_000, 30), (2_000, 40)),
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
    payout_keep_room: float = 1_500.0  # funded: suggested payouts leave at least this much above the MLL


def funded_guards() -> Guards:
    """Funded-stage guards. Same as the evaluation unless overridden: LucidFlex funded has no
    consistency rule, so the $1,200 cap is no longer required there, but on our 21 real days a
    higher cap only helped in one half of the data. Override with NEXUS_FUNDED_* env vars."""
    from .env import env
    g = Guards()
    for name, attr in (("FUNDED_DAILY_GOAL", "daily_goal"), ("FUNDED_DAILY_CAP", "daily_cap"),
                       ("FUNDED_DAILY_STOP", "daily_stop"), ("FUNDED_KEEP_ROOM", "payout_keep_room")):
        if env(name):
            setattr(g, attr, float(env(name)))
    return g


@dataclass
class PropAccount:
    rules: PropRules = field(default_factory=lambda: LUCIDFLEX_50K)
    eval_guards: Guards = field(default_factory=Guards)
    funded_guards: Guards = field(default_factory=funded_guards)
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
    # funded payout cycle
    cycle_days: int = 0                # days in this payout cycle with at least payout_day_min profit
    cycle_start: float = 0.0           # balance when this payout cycle began
    payouts: list[list] = field(default_factory=list)   # [day number, amount] per payout taken
    scale_micros: int = 0              # funded scaling-plan limit for this session (0 = none)

    def __post_init__(self) -> None:
        self.reset("evaluation")

    @property
    def guards(self) -> Guards:
        return self.funded_guards if self.phase == "funded" else self.eval_guards

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
        self.cycle_days, self.cycle_start, self.payouts = 0, r.start_balance, []
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
        self.scale_micros = 0
        if self.phase == "funded" and self.rules.funded_scaling:   # the scaling plan updates once per session
            self.scale_micros = max(m for p, m in self.rules.funded_scaling if self.profit >= p) \
                if self.profit >= self.rules.funded_scaling[0][0] else self.rules.funded_scaling[0][1]
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
        return min(self.rules.max_micros, cap, self.scale_micros or cap)

    @property
    def goal_reached(self) -> bool:
        return self.day_realized >= self.guards.daily_goal

    @property
    def can_trade(self) -> bool:
        return self.phase != "failed" and not self.halted

    @property
    def payout_eligible(self) -> bool:
        r = self.rules
        if self.phase != "funded" or self.cycle_days < r.payout_days or self.profit <= 0:
            return False
        if self.balance <= self.cycle_start or self.balance < r.start_balance + r.payout_buffer:
            return False   # the cycle must be net positive
        if r.max_payouts is not None and len(self.payouts) >= r.max_payouts:
            return False
        if self.payout_limit < r.payout_min:
            return False
        c = r.funded_consistency
        return not c or self.best_day <= c * self.profit

    @property
    def payout_limit(self) -> float:
        """The largest payout the firm allows right now."""
        r = self.rules
        cap = min(self.profit * r.payout_share, r.payout_max or float("inf"))
        return max(0.0, float(int(cap)))

    @property
    def locked_mll(self) -> float:
        return self.rules.start_balance + self.rules.mll_lock_offset

    @property
    def safe_payout(self) -> float:
        """Our suggestion: the most we can take while keeping `payout_keep_room` above the
        MLL afterwards (it locks at start + $100 after a payout). 0 = wait and build more profit."""
        if not self.payout_eligible:
            return 0.0
        room_after = self.balance - self.locked_mll - self.guards.payout_keep_room
        amount = float(int(min(self.payout_limit, room_after) // 50 * 50))
        return amount if amount >= self.rules.payout_min else 0.0

    def take_payout(self, amount: float) -> None:
        """Record a payout taken at the firm: balance down, MLL locked, new payout cycle."""
        if not self.payout_eligible:
            raise ValueError("not eligible for a payout yet")
        if not self.rules.payout_min <= amount <= self.payout_limit:
            raise ValueError(f"payout must be ${self.rules.payout_min:,.0f}-${self.payout_limit:,.0f}")
        if self.balance - amount <= self.locked_mll:
            raise ValueError("that payout would put the balance at or below the MLL")
        self.balance -= amount
        self.eod_high = self.balance
        self.mll, self.mll_locked = self.locked_mll, True
        self.payouts.append([self.days, round(amount, 2)])
        self.cycle_days, self.cycle_start = 0, self.balance
        self._note(f"payout #{len(self.payouts)}: ${amount:,.0f} (you keep ${amount * 0.9:,.0f}) · MLL locked at ${self.mll:,.0f}")
        self._start_day_limits()

    def _start_day_limits(self) -> None:
        """Re-derive today's stop and size after the balance or MLL changed mid-day."""
        g = self.guards
        self.day_stop = min(g.daily_stop, self.balance - self.mll - g.mll_cushion)

    def sync(self, phase: str, balance: float, mll: float, payouts_taken: int = 0, cycle_days: int = 0,
             day_pnl: Optional[float] = None) -> None:
        """Match the paper account to the real one (from the Lucid dashboard). `day_pnl`: today's closed P&L on the
        real account. Given, it replaces the paper day, so trades that never reached the account (sent before
        real orders worked, say) stop counting toward today's goal, cap and stop."""
        if phase not in ("evaluation", "funded"):
            raise ValueError("phase must be evaluation or funded")
        if not mll < balance:
            raise ValueError("the MLL must be below the balance")
        self.phase, self.balance, self.mll = phase, float(balance), float(mll)
        self.eod_high = max(self.balance, self.mll + self.rules.max_loss)
        self.mll_locked = self.mll >= self.locked_mll
        self.payouts = [[self.days, 0.0] for _ in range(int(payouts_taken))]
        # before the first payout the cycle runs from the funded start; after one, from now (unknown)
        self.cycle_days = int(cycle_days)
        self.cycle_start = self.rules.start_balance if not self.payouts else self.balance
        if day_pnl is not None:
            self.day_realized = round(float(day_pnl), 2)
        self._note(f"synced with the firm: {phase}, balance ${balance:,.0f}, MLL ${mll:,.0f}"
                   + (f", today {'+' if self.day_realized >= 0 else '-'}${abs(self.day_realized):,.0f}" if day_pnl is not None else ""))
        self._start_day()

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
        if self.phase == "funded" and day >= self.rules.payout_day_min:
            self.cycle_days += 1
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
            self._note(f"payout eligible: up to ${self.payout_limit:,.0f} (suggested ${self.safe_payout:,.0f})")

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
            "cycle_days": self.cycle_days, "payout_day_min": r.payout_day_min,
            "cycle_net": round(self.balance - self.cycle_start, 2), "payout_limit": self.payout_limit,
            "safe_payout": self.safe_payout, "keep_room": g.payout_keep_room,
            "payouts": len(self.payouts), "max_payouts": r.max_payouts,
            "paid_out": round(sum(a for _, a in self.payouts), 2), "scale_micros": self.scale_micros,
            "max_micros": self.max_micros, "log": self.log[-8:][::-1],
        }
