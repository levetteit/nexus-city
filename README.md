# Starnet City

A live 3D "trading city": each Python bot is a **worker** living in its own
building and trading micro futures (**MNQ, MES, M2K**) with the **Andrew Macre
pointer strategy**. All workers share **one prop firm account** whose rules
(Topstep 50K by default) they're built to pass: first the Trading Combine,
then the funded stage. When a worker is in a trade its
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
  market.py      simulated MNQ / MES / M2K prices with 1-minute OHLC candles
  broker.py      PaperBroker: micro futures (tick slippage + fees; options still supported). Implement open/close/mark to go live
  account.py     the shared prop firm account: Topstep 50K rules, daily stop / profit cap, contract budget, payouts
  bots/base.py   the worker lifecycle: scanning → in_trade → off_duty / stopped / walked; 3 → 6 contract sizing
  bots/pointer.py  the Macre pointer strategy
  config.py      who lives in the city
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
4. **Exit**: there is **no stop loss and no take-profit**. The trade stays on until a pointer forms against it. The next opposing FVG ("every pointer guarantees the move to the next FFVG") is shown as the expected move only.
5. **Inverse**: if a candle closes through the FFVG before the test, it's an IFFVG and the pointer failed. **3 inverses → the bot walks away for the day.**

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
| `bullish_pointer` / `bearish_pointer` | starts a setup; if it's in a trade the other way, exits ("pointer against") |
| `bullish_ffvg` / `bearish_ffvg` | marks the pointer's FFVG (send `top` and `bottom` if your alert has them, else uses the bot's own 1m FVG) and waits for the test |
| `bullish_iffvg` / `bearish_iffvg` | the opposite FFVG was closed through → counts an inverse |
| `long` / `short` | enters right away (optional `target`, shown only) |
| `exit` | closes the position |

Alerts go to every bot on that symbol (`MNQ1!`, `CME_MINI:MNQ1!`, `MNQZ2026` → MNQ; same for MES and M2K), or add `"bot": "mnq-3m"` to target one. A bullish pointer while already long adds to the position (3 → 6). Each bot's `signals` param picks `builtin`, `tradingview` or `both` (default). A building's halo flashes and shows "TV · …" when an alert lands.

**Note:** the city still runs on simulated prices. Each alert's `price` snaps that symbol to the real price, but P&L between alerts is simulated until a live data feed and broker are connected.

### Position size

Every trade **starts at 3 contracts**. When another pointer forms in the trade's
direction and the trade is in profit, the bot **adds 3 more, up to 6, never
more**. The whole account holds at most **12 micros** at once (two bots at full
size), and only one bot can hold a given symbol at a time, so they never take
opposite sides of the same contract.

### Prop firm account (`backend/account.py`)

All bots trade one shared account with Topstep 50K rules:

| Rule | Topstep 50K | What the bots do |
|---|---|---|
| Profit target (Combine) | $3,000 | stop for the day once it's in hand; pass at end of day |
| Maximum Loss Limit | $2,000 below the highest end-of-day balance, locks at $50,000, counts open P&L | never let a day's loss reach it (keep a $100 cushion) |
| Daily loss limit (optional) | $1,000 | **daily stop at −$800** (open + closed): flatten everything, done for the day |
| Consistency | best day ≤ 50% of profit | **daily profit cap at +$1,400** (open + closed): flatten, done for the day |
| Max size | 50 micros (Combine); funded: 20 → 30 at +$1,500 → 50 at +$2,000 | at most 12 micros open, and never above the firm's limit |
| Payouts (funded) | 5 days of ≥ $150, then 50% of profit up to $2,000 | requested automatically; locks the MLL at $50,000 |

After passing, the account switches to the funded stage. If it fails, or ends
up with under $150 of room above the MLL, the bots stop and the panel shows
**Reset Combine**. Change the numbers in `TOPSTEP_50K` / `Guards` for another
firm or account size.

The account's limits are the only exits besides a pointer against the trade:
there are still **no per-trade stops**. They exist because breaking a firm rule
fails the account.

| Bot rule | Effect |
|---|---|
| End of day | flattens everything 5 minutes before the close |
| Walk away | 3 pointer inverses in a day and that bot stops for the day |

### Add a worker

```python
# backend/config.py
(PointerBot, BotConfig(id="mes-5m", name="MES 5M", underlying="MES", district="LAB", timeframe=5,
                       params={"signals": "tradingview", "walk_after": 2}, color="#ff00aa")),
```

To add another micro (e.g. MYM), add it to `Market.underlyings` and its dollars
per point to `FUTURES_MULTIPLIER` in `broker.py` (MNQ $2, MES $5, M2K $5, MYM $0.50).

The city lays itself out automatically for however many workers you register.

## Going live (read this first)

Everything runs on **simulated prices with a paper broker**. To trade for real
you'd swap `Market` for a live data feed and `PaperBroker` for the platform your
prop firm uses (Topstep runs on TopstepX / ProjectX; Tradovate and NinjaTrader
are common elsewhere). Check your firm allows automated trading first.
Simulated prices are a random walk, so they don't prove the strategy works
(or that it doesn't). To judge it, backtest it on real historical candles.
