# Starnet City

A live 3D "trading city": each Python bot is a **worker** living in its own
building and trading one underlying: options on QQQ, SPY, IWM, NVDA and TSLA, or
**MNQ (Micro Nasdaq) futures**. Every worker runs the **Andrew Macre pointer
strategy** on its own candle timeframe. When a worker is in a trade its
building fires a light beam into the sky. When it closes a trade, gold coins (or
red ones) roll down its road to **The Vault** in the middle of town.

![city](docs/city.png)

## Run it

```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
# open http://localhost:8000
```

`STARNET_TICK_SECONDS=0.1 uvicorn backend.main:app` runs the market 10× faster.

- **Click a building** to open that worker's card: strategy, open position, recent trades, and a button to send it home or put it back on shift.
- **Click the vault** for today's payroll.

## How it's built

```
backend/
  market.py      simulated prices + 1-minute OHLC candles, Black-Scholes 0DTE option pricing, MNQ futures
  broker.py      PaperBroker: options (spread + fees) and futures (tick slippage + fees). Implement open/close/mark to go live
  bots/base.py   the worker lifecycle: scanning → in_trade → off_duty / stopped / walked; stops, targets, scale-outs
  bots/pointer.py  the Macre pointer strategy
  config.py      who lives in the city + their risk limits
  engine.py      ticks the market and every bot, builds the snapshot
  main.py        FastAPI: WebSocket /ws, REST /api/state, /api/bots/{id}/{on|off}
frontend/
  city.js        Three.js scene: buildings, beams, halos, roads, coins, bloom, labels
```

### The pointer strategy (`backend/bots/pointer.py`)

Built from Andrew Macre's publicly posted rules. "Pointer" isn't formally
defined anywhere public, so the definitions below are an interpretation; tune
them as you study his videos.

1. **Pointer**: a candle whose wick sweeps the lowest low (or highest high) of the last 10 candles and closes back the other way with a body in that direction.
2. **FFVG**: the *first* fair value gap (3-candle imbalance) after the pointer, in its direction. It "sponsors" the move. No FFVG within 6 candles → reset.
3. **Entry**: price comes back and tests the FFVG → enter (calls / MNQ long for bullish, puts / MNQ short for bearish).
4. **Stop**: just past the pointer's swept wick.
5. **Target**: the next opposing FVG ("every pointer guarantees the move to the next FFVG"), or 2R if there isn't one at least 1R away. Half comes off there and the runner's stop moves to breakeven.
6. **Runner**: stays on until a pointer forms against it.
7. **Inverse**: if a candle closes through the FFVG before the test, it's an IFFVG and the pointer failed. **3 inverses → the bot walks away for the day.**

### Worker rules (every bot)

| Rule | Default | Effect |
|---|---|---|
| Profit brake | per bot, e.g. $1,800 | stops trading for the day once it's up this much ("off duty") |
| Max daily loss | per bot, e.g. $700 | stops trading for the day ("sent home"). It's checked after each trade closes, so one bad trade can overshoot it |
| Premium stop | −50% (options only) | safety net on top of the structure stop |
| Time stop | 90 min | exits stale trades |
| End of day | 5 min before close | flattens everything |

### Add a worker

```python
# backend/config.py
(PointerBot, BotConfig(id="es-5m", name="SPY 5M", underlying="SPY", district="LAB", timeframe=5,
                       params={"lookback": 20, "walk_after": 2}, color="#ff00aa")),
```

For futures, set `instrument="future"` and add the symbol's dollars-per-point to
`FUTURES_MULTIPLIER` in `broker.py` (MNQ is $2 per point).

The city lays itself out automatically for however many workers you register.

## Going live (read this first)

Everything runs on **simulated prices with a paper broker**. To trade for real
you'd swap `Market` for a live data feed and `PaperBroker` for a broker API
(Alpaca, Tradier and IBKR for options; Tradovate, NinjaTrader and IBKR for MNQ). Paper trade for a long time first:
0DTE options lose value fast, and the spread and fees count against every trade.
Simulated prices are a random walk, so they don't prove the strategy works
(or that it doesn't). To judge it, backtest it on real historical candles.
