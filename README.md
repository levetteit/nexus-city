# Starnet City

A live 3D "trading city": each Python bot is a **worker** living in its own
building and trading micro futures (**MNQ, MES, M2K**) with the **Andrew Macre
pointer strategy**. All workers share **one prop firm account** whose rules
(Lucid Trading, LucidFlex 50K by default) they're built to pass: first the
evaluation, then the funded stage. They trade **every session** (Asia, London,
New York) from the 18:00 ET open to the 16:45 ET flat deadline, aiming for
**$600–$1,000 a day**. When a worker is in a trade its
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
  account.py     the shared prop firm account: LucidFlex / LucidPro 50K rules, EOD drawdown, daily goal / cap / stop, contract budget
  bots/base.py   the worker lifecycle: scanning → in_trade → off_duty / stopped / walked; 3 → 6 contract sizing
  bots/pointer.py  the Macre pointer strategy
  config.py      who lives in the city
  backtest.py    replay real 1m candles through the bots; walk-forward optimizer
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

## Backtest and optimize on real data (`backend/backtest.py`)

The live city runs on simulated, random prices, so it can't tell you if the
strategy works. The backtester replays **real 1-minute candles** through the
exact same bots, prop account rules and daily goal/cap/stop.

1. **Export data from TradingView:** open a 1-minute chart (MNQ1!, MES1!, M2K1!),
   scroll back as far as your plan loads, then chart menu → *Export chart data…*.
   Put the symbol in each file name: `data/MNQ_1m.csv`, `data/MES_1m.csv`, `data/M2K_1m.csv`.
2. **Backtest the current settings:**
   ```bash
   python -m backend.backtest data/*.csv
   ```
   You get days traded, **% profitable days**, days that reached the $600 goal,
   win rate, average win/loss, profit factor, best/worst day, evaluations passed
   and failed, and P&L by session.
3. **Optimize:**
   ```bash
   python -m backend.backtest data/*.csv --optimize --out results.json
   ```
   It tries ~190 combinations of strategy settings (pointer sweep rule, liquidity
   sweep of the previous session's high/low, which sessions to trade, FFVG and
   test windows, walk-away count, minimum FFVG size) on the **first 70% of days**,
   then re-runs the top 5 on the **last 30%** they never saw. Pick settings that
   hold up on those unseen days, not the ones with the best tuned numbers.
4. Put the winning settings in `params` in `backend/config.py`.

More history gives more reliable answers; a few weeks of 1-minute data is a
minimum. `--make-sample FOLDER` writes synthetic files if you just want to see
it run.

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

### Trading day and sessions

The simulated day matches the futures day under Lucid's flat rule: **18:00 ET
open → Asia → London (03:00) → New York (09:30) → flat by 16:45 ET**. Bots trade
whenever the market is open, in every session, and flatten at 16:40. Volatility
is lowest in Asia, higher in London, and highest at the New York open.

### Daily goal

| | Default | What happens |
|---|---|---|
| Daily goal | **$600** closed profit | no new trades; open trades keep running until a pointer forms against them |
| Daily cap | **$1,000** open + closed | flatten everything, done for the day |
| Daily stop | **−$800** open + closed | flatten everything, done for the day (smaller when the account is near its drawdown) |

### Prop firm account (`backend/account.py`)

All bots trade one shared account with LucidFlex 50K rules:

| Rule | LucidFlex 50K | What the bots do |
|---|---|---|
| Profit target | $3,000, at least 2 trading days | stop for the day once it's in hand; pass at the 16:45 close |
| Drawdown | **End-of-day**: $2,000 below the highest *closing* balance, only moves at the close, locks at $50,100 once the account closes at $52,100 | never let a day's loss reach it (keep a $100 cushion). Equity touching it during the day is treated as a breach (the safe reading) |
| Consistency | evaluation: best day ≤ 50% of profit; funded: none | the $1,000 cap keeps the best day well under half the $3,000 target |
| Daily loss limit | none | our own −$800 daily stop |
| Max size | 40 micros | at most 12 micros open, 3–6 per trade |
| Flat rule | flat by 16:45 ET, no overnight/weekend holds | flatten at 16:40 |

`LUCIDPRO_50K` is also included (no evaluation consistency rule; 40% funded
consistency and a $2,100 payout buffer). Use it with
`PropAccount(rules=LUCIDPRO_50K)` in `engine.py`. After passing, the account
switches to the funded stage and the panel shows when a payout is eligible. If
it fails, or ends up with under $150 of room above the drawdown, the bots stop
and the panel shows **Reset evaluation**. Change `Guards` in `account.py` to
adjust the goal, cap, stop or contract budget.

The account's limits are the only exits besides a pointer against the trade:
there are still **no per-trade stops**.

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
prop firm account runs on (check which platforms your Lucid plan supports,
e.g. Tradovate, NinjaTrader or Rithmic-based platforms). Check your firm allows automated trading first.
Simulated prices are a random walk, so they don't prove the strategy works
(or that it doesn't). To judge it, backtest it on real historical candles.
