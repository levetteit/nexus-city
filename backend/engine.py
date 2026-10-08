"""The city's heartbeat: steps the market, runs every bot, collects events."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .account import PropAccount
from .bots.base import Bot
from .broker import Broker, PaperBroker
from .config import SIM_MINUTES_PER_TICK, WORKERS
from .market import Market


class Engine:
    """Runs the bots against a market: the live simulation by default, or a
    `ReplayMarket` of real candles (see backtest.py)."""

    def __init__(self, broker: Broker | None = None, market=None, account: PropAccount | None = None,
                 workers=None, params: dict | None = None, news=None) -> None:
        self.news = news                # NewsCalendar: no trades around high-impact releases (news.py)
        self.pending_params: dict | None = None   # owner-promoted Forge settings, switched in at the next session roll
        self.desk = None                # TradingDesk: may take risk off for a session (desk.py)
        self._desk_seen = None
        self._news_seen: set = set()
        self.broker = broker or PaperBroker()
        self.events: list[dict] = []
        self.account = account or PropAccount()
        simulated = market is None
        self.market = market or Market(SIM_MINUTES_PER_TICK)
        self.bots: dict[str, Bot] = {}
        for cls, cfg in workers or WORKERS:
            if cfg.underlying not in self.market.underlyings:
                continue
            if params:
                cfg = replace(cfg, params={**cfg.params, **params})
            self.bots[cfg.id] = cls(cfg, self.broker, self.events.append, self.account)
        if simulated:
            # warm up ~2.5 hours of candles so every timeframe has history from the first tick
            for _ in range(600):
                for u in self.market.underlyings.values():
                    u.step(SIM_MINUTES_PER_TICK)
            for u in self.market.underlyings.values():
                u.open_price = u.price

    def tick(self, trade: bool = True) -> list[dict]:
        """Advance one step. `trade=False` replays history into the bots without trading."""
        before = self.market.day
        self.market.step()
        if not trade:
            for bot in self.bots.values():
                bot.on_tick(self.market, trade=False)
            self.events.clear()
            return []
        if self.market.day != before:
            if self.pending_params:
                self.apply_params(self.pending_params)
                self.pending_params = None
            phase, could_pay = self.account.phase, self.account.payout_eligible
            self.account.end_of_day()
            for bot in self.bots.values():
                bot.new_session()
            self.events.append({"type": "new_session", "phase_change": phase != self.account.phase})
            if phase == "evaluation" and self.account.phase == "funded":
                self.events.append({"type": "account_passed"})
            if self.account.payout_eligible and not could_pay:
                a = self.account
                self.events.append({"type": "payout_ready", "limit": a.payout_limit, "safe": a.safe_payout,
                                    "balance": round(a.balance, 2), "number": len(a.payouts) + 1})
        if not self.account.can_trade:
            self._halt_all("account failed" if self.account.phase == "failed" else self.account.halted)
        self._news_check()
        for bot in self.bots.values():
            bot.on_tick(self.market)
        self._risk_check()
        out, self.events[:] = list(self.events), []
        return out

    def _news_check(self) -> None:
        now = getattr(self.market, "now", None)
        if now is None:
            return
        if self.desk is not None:
            mode = self.desk.mode_now(now)
            for bot in self.bots.values():
                bot.desk_mode = mode
            key = mode and (mode["mode"], mode["until"])
            if key and key != self._desk_seen:
                self.events.append({"type": "desk_mode", "mode": mode["mode"], "why": mode["why"],
                                    "until": datetime.fromisoformat(mode["until"]).strftime("%a %H:%M")})
            self._desk_seen = key
        if self.news is None:
            return
        hold = self.news.blackout(now)
        for bot in self.bots.values():
            bot.news_hold = hold
        if hold and hold not in self._news_seen:
            self._news_seen.add(hold)
            until = self.news.window(hold)[1].strftime("%H:%M")
            self.events.append({"type": "news_hold", "title": hold.title, "at": hold.time.strftime("%H:%M"),
                                "until": until})
        flat = self.news.flatten_for(now)
        if flat:
            for bot in self.bots.values():
                if bot.position:
                    bot._close(f"news: {flat.label}", self.market)

    def _unrealized(self) -> float:
        return sum(b.position.pnl(self.broker.mark(b.position, self.market))
                   for b in self.bots.values() if b.position)

    def _risk_check(self) -> None:
        if self.account.goal_reached:  # daily goal hit: flat bots clock out, open trades run on
            for bot in self.bots.values():
                if not bot.position and bot.status == "scanning":
                    bot.status = "off_duty"
        reason = self.account.check(self._unrealized())
        if reason:
            self._halt_all(reason)
            self.events.append({"type": "account_halt", "reason": reason, "phase": self.account.phase})

    def _halt_all(self, reason: str) -> None:
        loss = self.account.phase == "failed" or "stop" in reason or "MLL" in reason
        for bot in self.bots.values():
            if bot.status not in ("disabled", "stopped", "off_duty", "walked"):
                bot.halt(reason, "stopped" if loss else "off_duty", self.market)
        self.account.check(self._unrealized())

    def apply_params(self, params: dict) -> None:
        """Switch in promoted Strategy Forge settings (forge.py). Only settings the bots read at decision time
        are allowed, so this is safe between sessions; the PROC zone settings never change here."""
        from .forge import KNOBS
        params = {k: v for k, v in params.items() if k in KNOBS}
        for bot in self.bots.values():
            bot.cfg = replace(bot.cfg, params={**bot.cfg.params, **params})
            if hasattr(bot, "p"):
                bot.p.update(params)
        self.events.append({"type": "strategy_promoted", "params": params})

    def resume_after_sync(self) -> list[str]:
        """After the owner syncs with the real account: if it may trade again, bots the account sent home come back.
        A bot that walked away on its own signal, or that the owner switched off, stays as it is."""
        a, back = self.account, []
        if not a.can_trade:
            return back
        for bot in self.bots.values():
            if bot.status == "stopped" or (bot.status == "off_duty" and not a.goal_reached):
                bot.status = "scanning"
                back.append(bot.cfg.id)
        if back:
            self.events.append({"type": "account_resumed", "bots": back, "day_pnl": round(a.day_pnl, 2)})
        return back

    def reset_account(self) -> None:
        for bot in self.bots.values():
            if bot.position:
                bot._close("account reset", self.market)
        self.account.reset("evaluation")
        for bot in self.bots.values():
            bot.new_session()

    def signal(self, payload: dict) -> list[dict]:
        """Route a TradingView alert to the bot(s) it's for. Returns what each bot did."""
        targets = [self.bots[payload["bot"]]] if payload.get("bot") in self.bots else [
            b for b in self.bots.values() if b.cfg.underlying == payload.get("symbol")]
        if not targets:
            return []
        # The simulation snaps to an alert's price; on real candles the candles are the price, and an alert's
        # value (late, mistyped or bogus) must not move the mark that stops and the drawdown are measured on (M-3).
        if payload.get("price") is not None and getattr(self.market, "anchor_signals", True):
            self.market.underlyings[targets[0].cfg.underlying].anchor(float(payload["price"]))
        results = []
        for bot in targets:
            did = bot.on_signal(payload, self.market)
            if did:
                ev = {"type": "tv_signal", "bot": bot.cfg.id, "signal": payload["signal"], "action": did}
                self.events.append(ev)
                results.append(ev)
        return results

    def set_enabled(self, bot_id: str, enabled: bool) -> None:
        self.bots[bot_id].set_enabled(enabled, self.market)

    def snapshot(self) -> dict:
        bots = [b.snapshot(self.market) for b in self.bots.values()]
        return {
            "clock": self.market.clock_str,
            "session": self.market.session,
            "vault": round(sum(b["realized"] for b in bots), 2),
            "account": self.account.snapshot(),
            "on_shift": sum(1 for b in bots if b["status"] in ("scanning", "in_trade")),
            "tickers": {s: {"price": round(u.price, 2), "change_pct": round(u.change_pct, 2)}
                        for s, u in self.market.underlyings.items()},
            "bots": bots,
            "news": self.news.status(getattr(self.market, "now", None)) if self.news else None,
            "weather": self.weather(),
        }

    def weather(self) -> dict:
        """The city's weather follows the market: how busy the last 30 minutes were next to the last day.
        clear (normal) · rain (busy) · storm (very busy, or a news blackout) · fog (dead quiet)."""
        u = self.market.underlyings.get("MNQ") or next(iter(self.market.underlyings.values()), None)
        bars = list(getattr(u, "bars", []) or [])
        ratio = None
        if len(bars) >= 60:
            recent = bars[-30:]
            base = bars[-390:]
            avg = lambda bs: sum(b.high - b.low for b in bs) / len(bs)
            ratio = round(avg(recent) / avg(base), 2) if avg(base) > 0 else None
        news = bool(self.news and self.news.status(getattr(self.market, "now", None)).get("hold"))
        kind = ("storm" if news or (ratio or 1) >= 1.8 else "rain" if (ratio or 1) >= 1.25
                else "fog" if (ratio or 1) <= 0.55 else "clear")
        return {"kind": kind, "vol_ratio": ratio, "news": news}
