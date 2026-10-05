"""Who lives in the city. Each entry gets its own building.

Every worker trades micro futures (MNQ, MES, M2K) with the Macre PROC strategy
(`bots/proc.py`), a rebuild of the PROC / Untapped FFVGs indicators on your
chart: a 3-6 minute pointer reacting to the first wick into an untapped
1-6 minute FFVG/IFFVG. `pointer_tfs` picks which pointer timeframes a bot uses.
MNQ and MES bots only take a PROC when the other market agrees (`confirm_with`). By default
each takes both its built-in signals and TradingView alerts for its symbol;
set params={"signals": "tradingview"} to trade only your indicator's alerts.

Account-level risk (prop firm rules, daily stop, contract budget) lives in
`account.py`. Pass strategy settings through `params` (see `proc.DEFAULTS`).
"""
import os

from .bots.base import BotConfig
from .bots.proc import ProcBot

TICK_SECONDS = float(os.getenv("STARNET_TICK_SECONDS", "1.0"))  # real seconds between ticks
SIM_MINUTES_PER_TICK = 0.25   # market minutes per tick (an 18:00-16:45 day ~ 91 real minutes)

# All bots trade micro futures in ONE prop firm account (see account.py).
# Each trade starts at 3 contracts and can grow to 6, never more.
# On 21 days of real data MNQ made the money while MES and M2K were breakeven,
# so only the MNQ bots trade by default. MES still confirms every MNQ entry;
# the MES and M2K bots start switched off (turn them on from their building).
WORKERS = [
    (ProcBot, BotConfig(id="mnq-3m", name="MNQ OG", underlying="MNQ", district="NASDAQ", timeframe=3,
                        params={"pointer_tfs": [3, 4], "confirm_with": "MES"}, color="#ffcc33",
                        persona={"handle": "OG_Pointer", "vibe": "gold-chain hype streamer", "props": ["trophy", "lava", "cat"],
                                 "win": ["LET'S GOOO", "PROC printed, money printed", "that's why they call me OG", "paid in full"],
                                 "loss": ["nah that's crazy", "chat it's fine", "pointer against... respect it", "we go again"],
                                 "idle": ["MES confirm or no trade", "patience = profit", "waiting on that tap"]})),
    (ProcBot, BotConfig(id="mnq-6m", name="MNQ 6M", underlying="MNQ", district="6M POINTERS", timeframe=6,
                        params={"pointer_tfs": [5, 6], "confirm_with": "MES"}, color="#ff3df2",
                        persona={"handle": "SixMinuteSage", "vibe": "lo-fi zen trader", "props": ["plant", "plant", "candle"],
                                 "win": ["calm money", "the 6m never lies", "breathe in profit", "as foretold"],
                                 "loss": ["the market teaches", "acceptance", "one trade, nothing more", "sip tea, reset"],
                                 "idle": ["slow candles, fast money", "let the 6m close", "no rush"]})),
    (ProcBot, BotConfig(id="mes-3m", name="MES 3M", underlying="MES", district="S&P ST", timeframe=3,
                        params={"pointer_tfs": [3, 4], "confirm_with": "MNQ"}, color="#43f0a0", enabled=False,
                        persona={"handle": "SPX_Scout", "vibe": "data nerd", "props": ["books", "plant"],
                                 "win": ["statistically inevitable", "edge confirmed", "spreadsheet goes up"],
                                 "loss": ["sample size, chat", "variance", "logging this one"],
                                 "idle": ["MNQ leading?", "checking correlation"]})),
    (ProcBot, BotConfig(id="mes-6m", name="MES 6M", underlying="MES", district="SWEEP ALLEY", timeframe=6,
                        params={"pointer_tfs": [5, 6], "confirm_with": "MNQ"}, color="#3dd6ff", enabled=False,
                        persona={"handle": "SweepQueen", "vibe": "neon night-owl", "props": ["lava", "cat"],
                                 "win": ["swept & kept", "liquidity collected", "ez clap"],
                                 "loss": ["they swept ME", "ok that hurt", "rematch"],
                                 "idle": ["where's the liquidity", "eyes on the highs"]})),
    (ProcBot, BotConfig(id="m2k", name="M2K PROC", underlying="M2K", district="SMALL CAPS", timeframe=3,
                        params={"pointer_tfs": [3, 4, 5, 6]}, color="#b18cff", enabled=False,
                        persona={"handle": "SmallCapKid", "vibe": "chaotic gremlin", "props": ["trophy", "books", "candle"],
                                 "win": ["SMALL CAPS BIG GAINS", "russell said yes", "i'm built different"],
                                 "loss": ["russell why", "i'm calm i'm calm", "rage-quit loading..."],
                                 "idle": ["any setup is a setup? no.", "hands off the button"]})),
]
