"""Who lives in the city. Each entry gets its own building.

Every worker trades micro futures (MNQ, MES) with the Macre PROC strategy
(`bots/proc.py`), a rebuild of the PROC / Untapped FFVGs indicators on your
chart: a 3-6 minute pointer reacting to the first wick into an untapped
1-6 minute FFVG/IFFVG. `pointer_tfs` picks which pointer timeframes a bot uses.
MNQ and MES bots only take a PROC when the other market agrees (`confirm_with`).
Like Macre, the city reads the full-size charts (NQ / ES) and executes on the micros: the candles
behind MNQ / MES are NQ's / ES's (Yahoo NQ=F / ES=F, or TradingView's NQ1! / ES1! charts).
The Lookout (`bots/watcher.py`) watches NQ and ES and never trades; the traders' ES confirmation
reads the same shared engine as the Lookout's ES read. By default
each takes both its built-in signals and TradingView alerts for its symbol;
set params={"signals": "tradingview"} to trade only your indicator's alerts.

Account-level risk (prop firm rules, daily stop, contract budget) lives in
`account.py`. Pass strategy settings through `params` (see `proc.DEFAULTS`).
"""

from .env import env
from .bots.base import BotConfig
from .bots.proc import ProcBot
from .bots.watcher import WatcherBot

TICK_SECONDS = float(env("TICK_SECONDS", "1.0"))  # real seconds between ticks
SIM_MINUTES_PER_TICK = 0.25   # market minutes per tick (an 18:00-16:45 day ~ 91 real minutes)

# All bots trade micro futures in ONE prop firm account (see account.py).
# Each trade starts at 3 contracts and can grow to 6, never more.
# On 21 days of real data MNQ made the money while MES and M2K were breakeven,
# so only the MNQ bots trade by default. ES still confirms every MNQ entry;
# the MES bots start switched off (turn them on from their building).
# M2K (Russell) added nothing to an NQ/ES strategy: its building is the Lookout's now.
WORKERS = [
    (ProcBot, BotConfig(id="mnq-3m", name="MNQ OG", underlying="MNQ", district="NASDAQ", timeframe=3,
                        params={"pointer_tfs": [3, 4], "confirm_with": "MES"}, color="#ffcc33",
                        persona={"handle": "OG_Pointer", "vibe": "gold-chain hype streamer", "props": ["trophy", "lava", "cat"],
                                 "win": ["LET'S GOOO", "PROC printed, money printed", "that's why they call me OG", "paid in full"],
                                 "loss": ["nah that's crazy", "chat it's fine", "pointer against... respect it", "we go again"],
                                 "idle": ["MES confirm or no trade", "patience = profit", "waiting on that tap"]})),
    (ProcBot, BotConfig(id="mnq-6m", name="MNQ 5/6M", underlying="MNQ", district="5M & 6M", timeframe=6,
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
    (WatcherBot, BotConfig(id="watch", name="NQ/ES LOOKOUT", underlying="MNQ", district="BIG BOARD", timeframe=3,
                           contracts=0, max_contracts=0,
                           params={"pointer_tfs": [3, 4, 5, 6], "confirm_with": "MES", "killzones": None},
                           color="#b18cff",
                           persona={"handle": "TheLookout", "vibe": "rooftop spotter with binoculars",
                                    "props": ["books", "candle", "plant"],
                                    "win": ["called it from the roof", "NQ and ES both said go", "big boys moved first"],
                                    "loss": ["the big board lied once", "noted, recalibrating the binoculars"],
                                    "idle": ["eyes on NQ and ES", "micros follow the big boys", "no read, no trade",
                                             "split tape, stay out", "waiting for both to agree"]})),
]
