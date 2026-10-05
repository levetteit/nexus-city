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

Built from Andrew Macre's public rules, with the definitions used by the Flux
Charts indicators made from his concepts (Pointer Closure Detection,
Untapped FFVGs & IFFVGs, Troop Toolkit).

1. **Pointer** (on the bot's 3–6 minute candles): a candle that closes back inside the previous candle's wick. Bullish = green, close above the previous body but at or below the previous high; bearish is the mirror. By default its wick must also sweep the previous candle's low/high.
2. **FFVG** (on 1-minute candles): the first fair value gap after the pointer, in its direction. It "sponsors" the move. No FFVG within 15 minutes → reset.
3. **Entry**: price comes back and tests the FFVG without closing through it → enter (calls / MNQ long for bullish, puts / MNQ short for bearish).
4. **Stop**: just past the pointer's wick.
5. **Target**: the next opposing FVG ("every pointer guarantees the move to the next FFVG"), or 2R if there isn't one at least 1R away. Half comes off there and the runner's stop moves to breakeven.
6. **Runner**: stays on until a pointer forms against it.
7. **Inverse**: if a candle closes through the FFVG before the test, it's an IFFVG and the pointer failed. **3 inverses → the bot walks away for the day.**

## TradingView alerts (use your real indicators)

Your TradingView indicators can drive the bots through webhook alerts.

1. **Start the server with a secret** (anyone who knows it can send signals):
   ```bash
   STARNET_WEBHOOK_SECRET=pick-a-long-random-string uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```
2. **Give it a public HTTPS address.** TradingView only sends to ports 80/443. Either run it on a small cloud server, or tunnel your laptop: `ngrok http 8000` gives you `https://xxxx.ngrok.app`.
3. **In TradingView** (paid plan needed for webhooks): on your chart, open *Create alert*, set *Condition* to your indicator and the event (e.g. a bullish pointer on Pointer Closure Detection, or an FFVG/IFFVG from Untapped FFVGs & IFFVGs). Under *Notifications* tick **Webhook URL** and enter `https://xxxx.ngrok.app/api/tradingview`.
4. **Message**: paste JSON like this, changing `signal` per alert:
   ```json
   {"secret": "pick-a-long-random-string", "ticker": "{{ticker}}", "signal": "bullish_pointer",
    "price": {{close}}, "high": {{high}}, "low": {{low}}, "tf": "{{interval}}"}
   ```

| `signal` | What the bot does |
|---|---|
| `bullish_pointer` / `bearish_pointer` | starts a setup (wick = `low` / `high`); if it's in a trade the other way, exits ("pointer against") |
| `bullish_ffvg` / `bearish_ffvg` | marks the pointer's FFVG (send `top` and `bottom` if your alert has them, else uses the bot's own 1m FVG) and waits for the test |
| `bullish_iffvg` / `bearish_iffvg` | the opposite FFVG was closed through → counts an inverse |
| `long` / `short` | enters right away (optional `stop`, `target`) |
| `exit` | closes the position |

Alerts go to every bot on that symbol (`MNQ1!`, `CME_MINI:MNQ1!`, `MNQZ2026` → MNQ), or add `"bot": "mnq-3m"` to target one. Each bot's `signals` param picks `builtin`, `tradingview` or `both` (default). A building's halo flashes and shows "TV · …" when an alert lands.

**Note:** the city still runs on simulated prices. Each alert's `price` snaps that symbol to the real price, but P&L between alerts is simulated until a live data feed and broker are connected.

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
(PointerBot, BotConfig(id="spy-5m", name="SPY 5M", underlying="SPY", district="LAB", timeframe=5,
                       params={"signals": "tradingview", "walk_after": 2}, color="#ff00aa")),
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
