"""The city's heartbeat: steps the market, runs every bot, collects events."""
from __future__ import annotations

from .account import PropAccount
from .bots.base import Bot
from .broker import Broker, PaperBroker
from .config import SIM_MINUTES_PER_TICK, WORKERS
from .market import SESSION_OPEN_MIN, Market


class Engine:
    def __init__(self, broker: Broker | None = None) -> None:
        self.market = Market(SIM_MINUTES_PER_TICK)
        self.broker = broker or PaperBroker()
        self.events: list[dict] = []
        self.account = PropAccount()
        self.bots: dict[str, Bot] = {}
        for cls, cfg in WORKERS:
            self.bots[cfg.id] = cls(cfg, self.broker, self.events.append, self.account)
        # warm up ~2.5 hours of candles so every timeframe has history from the first tick
        for _ in range(600):
            for u in self.market.underlyings.values():
                u.step(SIM_MINUTES_PER_TICK)
        for u in self.market.underlyings.values():
            u.open_price = u.price

    def tick(self) -> list[dict]:
        before = self.market.clock_min
        self.market.step()
        if self.market.clock_min == SESSION_OPEN_MIN and before != SESSION_OPEN_MIN:
            phase = self.account.phase
            self.account.end_of_day()
            for bot in self.bots.values():
                bot.new_session()
            self.events.append({"type": "new_session", "phase_change": phase != self.account.phase})
        if not self.account.can_trade:
            self._halt_all("account failed" if self.account.phase == "failed" else self.account.halted)
        for bot in self.bots.values():
            bot.on_tick(self.market)
        self._risk_check()
        out, self.events[:] = list(self.events), []
        return out

    def _unrealized(self) -> float:
        return sum(b.position.pnl(self.broker.mark(b.position, self.market))
                   for b in self.bots.values() if b.position)

    def _risk_check(self) -> None:
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

    def reset_account(self) -> None:
        for bot in self.bots.values():
            if bot.position:
                bot._close("account reset", self.market)
        self.account.reset("combine")
        for bot in self.bots.values():
            bot.new_session()

    def signal(self, payload: dict) -> list[dict]:
        """Route a TradingView alert to the bot(s) it's for. Returns what each bot did."""
        targets = [self.bots[payload["bot"]]] if payload.get("bot") in self.bots else [
            b for b in self.bots.values() if b.cfg.underlying == payload.get("symbol")]
        if not targets:
            return []
        if payload.get("price") is not None:
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
            "vault": round(sum(b["realized"] for b in bots), 2),
            "account": self.account.snapshot(),
            "on_shift": sum(1 for b in bots if b["status"] in ("scanning", "in_trade")),
            "tickers": {s: {"price": round(u.price, 2), "change_pct": round(u.change_pct, 2)}
                        for s, u in self.market.underlyings.items()},
            "bots": bots,
        }
