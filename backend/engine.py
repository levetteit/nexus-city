"""The city's heartbeat: steps the market, runs every bot, collects events."""
from __future__ import annotations

from .bots.base import Bot
from .broker import Broker, PaperBroker
from .config import SIM_MINUTES_PER_TICK, WORKERS
from .market import SESSION_OPEN_MIN, Market


class Engine:
    def __init__(self, broker: Broker | None = None) -> None:
        self.market = Market(SIM_MINUTES_PER_TICK)
        self.broker = broker or PaperBroker()
        self.events: list[dict] = []
        self.bots: dict[str, Bot] = {}
        for cls, cfg in WORKERS:
            self.bots[cfg.id] = cls(cfg, self.broker, self.events.append)
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
            for bot in self.bots.values():
                bot.new_session()
            self.events.append({"type": "new_session"})
        for bot in self.bots.values():
            bot.on_tick(self.market)
        out, self.events[:] = list(self.events), []
        return out

    def set_enabled(self, bot_id: str, enabled: bool) -> None:
        self.bots[bot_id].set_enabled(enabled, self.market)

    def snapshot(self) -> dict:
        bots = [b.snapshot(self.market) for b in self.bots.values()]
        return {
            "clock": self.market.clock_str,
            "vault": round(sum(b["realized"] for b in bots), 2),
            "on_shift": sum(1 for b in bots if b["status"] in ("scanning", "in_trade")),
            "tickers": {s: {"price": round(u.price, 2), "change_pct": round(u.change_pct, 2)}
                        for s, u in self.market.underlyings.items()},
            "bots": bots,
        }
