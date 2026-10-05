"""Who lives in the city. Each entry gets its own building.

Every worker runs the Macre pointer strategy (`bots/pointer.py`): pointers on
its own 3-6 minute candles, FFVG and entry on 1-minute candles. By default
each takes both its built-in signals and TradingView alerts for its symbol;
set params={"signals": "tradingview"} to trade only your indicator's alerts.

Tweak risk settings here, or pass strategy settings through `params`
(see `pointer.DEFAULTS`).
"""
import os

from .bots.base import BotConfig
from .bots.pointer import PointerBot

TICK_SECONDS = float(os.getenv("STARNET_TICK_SECONDS", "1.0"))  # real seconds between ticks
SIM_MINUTES_PER_TICK = 0.25   # market minutes that pass each tick (390 min session ~ 26 real min)

WORKERS = [
    (PointerBot, BotConfig(id="qqq-og", name="QQQ OG", underlying="QQQ", district="0DTE", timeframe=3,
                           contracts=5, profit_brake=1800, max_daily_loss=700, color="#ffcc33")),
    (PointerBot, BotConfig(id="qqq-5m", name="QQQ 5M", underlying="QQQ", district="5M POINTERS", timeframe=5,
                           contracts=3, profit_brake=900, max_daily_loss=450, color="#3dd6ff")),
    (PointerBot, BotConfig(id="spy-3m", name="SPY 3M", underlying="SPY", district="SPY ST", timeframe=3,
                           contracts=4, profit_brake=1200, max_daily_loss=500, color="#43f0a0")),
    (PointerBot, BotConfig(id="spy-6m", name="SPY 6M", underlying="SPY", district="SWEEP ALLEY", timeframe=6,
                           contracts=4, profit_brake=1200, max_daily_loss=500, color="#ff5c8a")),
    (PointerBot, BotConfig(id="iwm-4m", name="IWM 4M", underlying="IWM", district="SMALL CAPS", timeframe=4,
                           contracts=6, profit_brake=1000, max_daily_loss=500, color="#b18cff")),
    (PointerBot, BotConfig(id="nvda-3m", name="NVDA 3M", underlying="NVDA", district="CHIPS", timeframe=3,
                           contracts=3, profit_brake=1500, max_daily_loss=600, otm_steps=1, color="#76ff3d")),
    (PointerBot, BotConfig(id="tsla-4m", name="TSLA 4M", underlying="TSLA", district="EV ROW", timeframe=4,
                           contracts=2, profit_brake=1500, max_daily_loss=700, color="#ff8a3d")),
    (PointerBot, BotConfig(id="mnq-3m", name="MNQ 3M", underlying="MNQ", district="FUTURES", instrument="future",
                           timeframe=3, contracts=4, profit_brake=1500, max_daily_loss=600, color="#ff3df2")),
]
