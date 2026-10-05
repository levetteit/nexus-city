"""Who lives in the city. Each entry gets its own building.

Tweak risk settings here, or add new workers with a strategy from
`bots/strategies.py`.
"""
import os

from .bots.base import BotConfig
from .bots.strategies import DipBuyer, EmaCrossScalper, FadeTheRip, RangeBreakout, TrendRider

TICK_SECONDS = float(os.getenv("STARNET_TICK_SECONDS", "1.0"))  # real seconds between ticks
SIM_MINUTES_PER_TICK = 0.25   # market minutes that pass each tick (390 min session ~ 26 real min)

WORKERS = [
    (EmaCrossScalper, BotConfig(id="qqq-og", name="QQQ OG", underlying="QQQ", district="0DTE",
                                contracts=5, profit_brake=1800, max_daily_loss=700, color="#ffcc33")),
    (TrendRider, BotConfig(id="qqq-trend", name="QQQ TREND", underlying="QQQ", district="TREND",
                           contracts=3, profit_brake=900, max_daily_loss=450, color="#3dd6ff")),
    (DipBuyer, BotConfig(id="spy-dip", name="SPY DIP", underlying="SPY", district="BUY THE DIP",
                         contracts=4, profit_brake=1200, max_daily_loss=500, color="#43f0a0")),
    (FadeTheRip, BotConfig(id="spy-fade", name="SPY FADE", underlying="SPY", district="FADE THE RIP",
                           contracts=4, profit_brake=1200, max_daily_loss=500, color="#ff5c8a")),
    (RangeBreakout, BotConfig(id="iwm-break", name="IWM BREAK", underlying="IWM", district="BREAKOUT",
                              contracts=6, profit_brake=1000, max_daily_loss=500, color="#b18cff")),
    (EmaCrossScalper, BotConfig(id="nvda-scalp", name="NVDA SCALP", underlying="NVDA", district="CHIPS",
                                contracts=3, profit_brake=1500, max_daily_loss=600, otm_steps=1,
                                color="#76ff3d")),
    (TrendRider, BotConfig(id="tsla-trend", name="TSLA TREND", underlying="TSLA", district="EV ROW",
                           contracts=2, profit_brake=1500, max_daily_loss=700, color="#ff8a3d")),
]
