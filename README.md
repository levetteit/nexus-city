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
  bots/proc.py   the Macre PROC strategy (FFVG/IFFVG taps + 3-6m pointers)
  config.py      who lives in the city
  backtest.py    replay real 1m candles through the bots; walk-forward optimizer
  fetch_data.py  download free 1m NQ / ES / RTY futures history (Yahoo, ~30 days)
  engine.py      ticks the market and every bot, builds the snapshot
  main.py        FastAPI: WebSocket /ws, REST /api/state, /api/bots/{id}/{on|off}
frontend/
  city.js        Three.js scene: buildings, beams, halos, roads, coins, bloom, labels
```

### The strategy: PROC (`backend/bots/proc.py`)

A rebuild of the indicators on your TradingView chart (PROC – Pointer Range of
Control, Untapped FFVGs & IFFVGs, Troop Toolkit), computed from 1-minute candles:

1. **FFVG**: the first fair value gap after a confirmed swing high/low on any
   1–6 minute timeframe, within 6 candles of the swing (your "Sweep Proximity 6").
2. **Tap**: the first time any 1-minute wick trades into an untapped FFVG.
3. **IFFVG**: an FFVG that a candle on its own timeframe closes fully through
   flips into an opposite zone that can be tapped the same way.
4. **Pointer**: a 3/4/5/6-minute candle that closes inside the previous
   candle's wick (beyond the body, within the high/low).
5. **PROC = entry**: a pointer whose candle, or the one before it, made the
   first-ever wick into a same-direction untapped FFVG/IFFVG. The bot enters
   with 3 contracts and shows the next opposite zone as the expected move.
6. **Add**: another PROC the same way while the trade is in profit → +3 (6 max).
7. **Exit**: only on a PROC against the trade, i.e. a pointer against you on
   another FFVG/IFFVG. No stop loss.
8. **Walk away**: a PROC is invalidated when an opposite candle on its own
   timeframe closes beyond its box; 3 of those in a day and the bot stops.
9. **MNQ/MES correlation**: an MNQ PROC is only taken (or added to) when MES
   agrees within 6 minutes before or after it, and vice versa. `confirm_mode`
   sets how strict "agrees" is: `proc` (MES printed its own PROC the same way,
   the default), `pointer` (a same-way 3–6m pointer) or `tap` (a wick into a
   same-way FFVG/IFFVG). Exits never wait for confirmation. The bots keep both
   markets' structure up to date even if only one of them is being traded.

Settings (`params` in `config.py`, most tried by the optimizer): `confirm_with`,
`confirm_mode`, `confirm_window`, `pointer_tfs`,
`pivot_len`, `sweep_proximity`, `use_iffvg`, `walk_after`,
`exit_on_invalidation`, `killzones` (Asia 20:00–00:00, London 02:00–05:00,
NY AM 09:30–11:00, NY PM 14:00–16:00 ET), `require_liquidity_sweep` (the PROC
must take one of those sessions' highs/lows, like Troop's liquidity levels).

`backend/bots/pointer.py` is the earlier, simpler pointer bot, kept for reference.

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
(ProcBot, BotConfig(id="mes-ny", name="MES NY", underlying="MES", district="LAB", timeframe=5,
                    params={"pointer_tfs": [5], "killzones": ["NY AM"]}, color="#ff00aa")),
```

To add another micro (e.g. MYM), add it to `Market.underlyings` and its dollars
per point to `FUTURES_MULTIPLIER` in `broker.py` (MNQ $2, MES $5, M2K $5, MYM $0.50).

The city lays itself out automatically for however many workers you register.

## Backtest and optimize on real data (`backend/backtest.py`)

The live city runs on simulated, random prices, so it can't tell you if the
strategy works. The backtester replays **real 1-minute candles** through the
exact same bots, prop account rules and daily goal/cap/stop.

1. **Get data.** Free: `python -m backend.fetch_data` downloads the last ~30
   days of real 1-minute NQ / ES / RTY futures from Yahoo Finance into
   `data/MNQ_1m.csv`, `data/MES_1m.csv`, `data/M2K_1m.csv` (micros track the
   full-size contracts exactly). Run it every few weeks: it merges new candles
   in, so your history keeps growing. A paid TradingView plan can also export
   1-minute charts (chart menu → *Export chart data…*); name the files the same way.
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
   It tries ~190 combinations of the PROC settings (MNQ/MES confirmation off /
   tap / pointer / PROC and its window, swing pivot length, IFFVGs on/off,
   liquidity sweep required, killzones). Export **both MNQ and MES** so the
   confirmation can be tested on the **first 70% of days**,
   then re-runs the top 5 on the **last 30%** they never saw. Pick settings that
   hold up on those unseen days, not the ones with the best tuned numbers.
4. Put the winning settings in `params` in `backend/config.py`.

More history gives more reliable answers; a few weeks of 1-minute data is a
minimum. `--make-sample FOLDER` writes synthetic files if you just want to see
it run.

## TradingView alerts

The PROC, Untapped FFVGs and Troop Toolkit indicators don't publish alert
conditions, so they can't send webhooks. That's why the bots rebuild PROC
themselves from price data. The webhook still accepts direct orders from any
other alert you set up:

1. Start the server with a secret: `STARNET_WEBHOOK_SECRET=<long random string> uvicorn backend.main:app --host 0.0.0.0`
2. Give it a public HTTPS address (`ngrok http 8000`, or a cloud server).
3. In the TradingView alert, tick **Webhook URL** → `https://<address>/api/tradingview`, message:
   ```json
   {"secret": "<your secret>", "ticker": "{{ticker}}", "signal": "long", "price": {{close}}}
   ```
   `signal` is `long`, `short` or `exit`. Alerts go to every bot on that symbol
   (`MNQ1!`, `MES1!`, `M2K1!`), or add `"bot": "mnq-3m"` for one bot.

## Going live (read this first)

Everything runs on **simulated prices with a paper broker**. To trade for real
you'd swap `Market` for a live data feed and `PaperBroker` for the platform your
prop firm account runs on (check which platforms your Lucid plan supports,
e.g. Tradovate, NinjaTrader or Rithmic-based platforms). Check your firm allows automated trading first.
Simulated prices are a random walk, so they don't prove the strategy works
(or that it doesn't). To judge it, backtest it on real historical candles.
