"""Who lives in the city. Each entry gets its own building.

Every worker trades micro futures (MNQ, MES, M2K) with the Macre pointer
strategy (`bots/pointer.py`): pointers on
its own 3-6 minute candles, FFVG and entry on 1-minute candles. By default
each takes both its built-in signals and TradingView alerts for its symbol;
set params={"signals": "tradingview"} to trade only your indicator's alerts.

Account-level risk (prop firm rules, daily stop, contract budget) lives in
`account.py`. Pass strategy settings through `params` (see `pointer.DEFAULTS`).
"""
import os

from .bots.base import BotConfig
from .bots.pointer import PointerBot

TICK_SECONDS = float(os.getenv("STARNET_TICK_SECONDS", "1.0"))  # real seconds between ticks
SIM_MINUTES_PER_TICK = 0.25   # market minutes that pass each tick (390 min session ~ 26 real min)

# All bots trade micro futures in ONE prop firm account (see account.py).
# Each trade starts at 3 contracts and can grow to 6, never more.
WORKERS = [
    (PointerBot, BotConfig(id="mnq-3m", name="MNQ OG", underlying="MNQ", district="NASDAQ", timeframe=3,
                           color="#ffcc33")),
    (PointerBot, BotConfig(id="mnq-6m", name="MNQ 6M", underlying="MNQ", district="6M POINTERS", timeframe=6,
                           color="#ff3df2")),
    (PointerBot, BotConfig(id="mes-3m", name="MES 3M", underlying="MES", district="S&P ST", timeframe=3,
                           color="#43f0a0")),
    (PointerBot, BotConfig(id="mes-6m", name="MES 6M", underlying="MES", district="SWEEP ALLEY", timeframe=6,
                           color="#3dd6ff")),
    (PointerBot, BotConfig(id="m2k-4m", name="M2K 4M", underlying="M2K", district="SMALL CAPS", timeframe=4,
                           color="#b18cff")),
]
