# Trading: strategy, prop account and research

How the bots trade, the prop firm rules they trade under, the results on real data, and the tools for testing changes before they go live.

## How the trading side is built

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
  live.py        live paper trading on real candles (Yahoo, or real-time via TradingView), with trade logs
  scale.py       the Lucid scale plan: accounts by stage, next payouts, when to buy the next evaluation
  execution.py   real orders to your Lucid accounts via TradersPost (armed from the city, with safety checks)
  notify.py      phone notifications for every trade (web push to the home-screen app, or ntfy)
station/       the Space Station: ULTRON, the Research Station, ventures, approvals, the shared treasury
frontend/station3d.html  the 3D orbital station: ULTRON's core, every module, the crew at work, pets, ventures as planets
frontend/station.html  the station's Command Board (Command, Approvals, Ventures, Research, Treasury, Crew, Log)
frontend/room.js  the bots' streamer rooms: robot, monitors, emotions, gadgets
Dockerfile, render.yaml   one-click hosting (password-protected) so you can watch from your phone
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
open → Asia → London (03:00) → New York (09:30) → flat by 16:45 ET**. Bots track
market structure the whole time but only open trades in the killzones London
02:00–05:00, NY AM 09:30–11:00 and NY PM 14:00–16:00 ET (open trades run on
until a PROC against them). **Tradovate's session for the micros ends at 16:00 ET**, so no new entries or adds
after 15:50 and every trade is flattened at 15:55 (`market.FLAT_BY_MIN`); the real-order router also refuses a
new entry after 15:50. The day still rolls at 16:45. On the 22 days of history this changed nothing: no trade
was ever open past 15:55.

### Real-data results (Sep 8 – Oct 5 2026, 21 days of 1m NQ/ES/RTY)

| Settings | Profitable days | Total | Profit factor | Evaluations |
|---|---|---|---|---|
| **Defaults**: MNQ only (MES confirms), killzones London + NY AM + NY PM, pointer confirmation, swing length 6, stop after 3 losers in a row, $1,200 daily cap, −$600 daily stop | **71%** | **+$13,224** | **2.9** | 1 passed, 0 failed |
| Same with a −$800 daily stop | 76% | +$11,847 | 2.73 | 1 passed, 0 failed |
| Same with a $1,000 daily cap | 76% | +$10,173 | 2.63 | 1 passed, 0 failed |
| Same, with MES and M2K bots also trading | 71% | +$10,321 | 1.86 | 1 passed, 0 failed |
| Same, but entering in every session | 45% | −$515 | 0.97 | 0 passed, 2 failed |
| Original settings (all sessions, PROC confirmation, swing length 2) | 48% | −$127 | 0.97 | 1 passed, 2 failed |

On the last 7 days, which were never used for tuning, MNQ-only had 86%
profitable days and +$4,252. Win rate is ~48%: winners average ~2.9× losers
because trades only close on a PROC against them (or the daily cap).

What the trade-level breakdown showed, and what was tried:

- MNQ made +$9,645 while MES (−$197) and M2K (−$154) were breakeven → MNQ only.
- Trades that grew to 6 contracts made +$11,047; trades that stayed at 3 lost
  −$1,752. The edge is in adding to winners.
- Trades closed within 15 minutes lost (chop); trades held 60+ minutes won 72%.
- Losing days went straight to the −$800 stop without ever being up much →
  stop after 3 losing trades in a row.
- The daily cap does most of the profit-taking. $1,200 beat $1,000 (+16%, same
  consistency); $1,500 made more but fewer profitable days and a best day over
  Lucid's $1,500 consistency limit.
- Tested and rejected (worse when re-run): dropping 5m pointers, exiting only
  on an opposite PROC of the same or higher timeframe, a 2-loss streak stop,
  adding on MNQ's own pointers, an $800 goal or no goal, a profit lock that
  stops a green day from giving back (`lock_trigger` / `lock_floor`), 3 or 10
  minute confirmation windows, FFVGs only (IFFVGs carry a lot of the edge),
  and requiring a liquidity sweep (cut profit by ~90%).
- Robustness: with 2-3 ticks of slippage per side instead of 1 the results
  barely change, so the edge isn't living on perfect fills.
- Daily stops of −$600 and −$1,000 both beat −$800 on total profit, which
  shows how much of the difference between settings is noise on 21 days.
  Adding on an MES pointer (`add_on:
  "partner_pointer"`) made more money but fewer profitable days and a best day
  over $1,500: worth re-testing as more data comes in. 21 days is a small sample:
keep fetching data and re-running the backtest as history grows.

### Trims and the 5-minute chart (tested Oct 2026)

**Trims (partial profits).** Setting `params={"trim": True}` makes a bot close part of the
position each time price reaches the next untapped opposite FFVG/IFFVG in the
trade's direction. The last contract always runs until a pointer against, and
PROCs with the trade can add back up to 6. These settings tune it:

| Setting | What it does |
| --- | --- |
| `trim_frac` | Share of open contracts closed at each zone |
| `trim_min_tf` | Only zones of this timeframe or higher count |
| `trim_min_pts` | Only zones at least this many points from entry count |
| `trim_max` | Most trims per trade |
| `trim_fill` | `limit` at the zone edge, or `close` (market order after the candle) |

On real accounts each trim is sent to TradersPost as a `resize` to the remaining size.

On the 21 real days, **no trim setting made more money than no trims**:

| Setting | Total | Change |
| --- | --- | --- |
| No trims (default) | $13,224 | — |
| Best trim: 3m+ zones, 30+ pts away, 1/3 each | $12,899 | −$325 |
| Median of 36 trim settings | $11,886 | −$1,338 |
| Trim at every next zone | $6,896 | about half |

Every setting kept 71.4% green days. Trims shrink the size on the runners that
make the money (average win $540 vs average loss $181), and the daily $600 goal
and $1,200 cap already bank profits. So trims stay off by default.

**The 5-minute chart.** The **MNQ 5/6M** bot already trades 5m pointers (`pointer_tfs: [5, 6]`).
Results by entry timeframe:

| Entry | Trades | P&L | Win rate |
| --- | --- | --- | --- |
| 3m PROC | 25 | +$6,521 | |
| 4m PROC | 10 | +$2,322 | |
| 5m PROC | 16 | −$755 | 31% |
| 6m PROC | 18 | +$3,950 | |

Removing 5m entries still made less overall ($11,362). Other ways of using the 5m, tested:

| Setup | Total |
| --- | --- |
| Current: [3,4] + [5,6] | $13,224 |
| Dedicated 5m bot | $12,474 |
| 5m only | $3,417 |
| 5m PROC/pointer as a direction filter (`bias_tf: 5`) | $17 – $4,119 |

So the current setup stays.

### Context filters: RSI, ICT day open, premium/discount, chop (tested Oct 6 2026)

Optional entry filters in `bots/proc.py`, all **off by default**. Each one only removes PROCs; it never adds trades:

| Setting | What it does |
| --- | --- |
| `rsi_filter` | `{"tf": 5, "period": 14, "ob": 70, "os": 30}`: no longs when RSI is overbought, no shorts when oversold. `"mode": "momentum"`: longs only with RSI above 50, shorts below |
| `day_open_bias` | ICT true day open (00:00 ET): `"discount"` = longs below it, shorts above; `"trend"` = the reverse |
| `range_bias` | Premium/discount of the previous trading day's range: `"discount"` = longs in its lower half, shorts in the upper; `"trend"` = the reverse |
| `min_range_pts` | Chop filter: the average 1-minute high-low over the last 30 minutes must be at least this many points |

Walk-forward on Yahoo's 1-minute data, Sep 8 – Oct 6: each filter judged on the first 15 days, then checked on the last 7.

| Setting | First 15 days | Last 7 days |
| --- | --- | --- |
| **Current (no filter)** | **+$5,621** | **+$5,044** |
| RSI 5m exhaustion 70/30 | +$5,261 | +$4,611 |
| RSI 5m exhaustion 80/20 | +$6,601 | +$2,601 |
| RSI 5m momentum | +$4,650 | −$1,433 |
| RSI 15m momentum | +$2,390 | +$518 |
| ICT day open, discount | −$912 | +$3,796 |
| ICT day open, trend | +$2,287 | −$1,384 |
| Previous-day range, discount | +$3,546 | +$3,526 |
| Previous-day range, trend | +$2,542 | −$1,360 |
| Chop filter 6 / 9 / 12 pts | +$5,541 / +$3,775 / +$1,482 | +$3,808 / +$3,028 / +$5,495 |

None beat the current setup on both halves, so all stay off. The PROC already is an ICT-style structure entry
(fair value gaps, inversions, killzones, SMT-like MES confirmation); the filters mostly removed good trades.
Volume can't be tested yet: Yahoo's data has none. The feed script now sends volume and the server saves TradingView's candles (see Candle history), so it can be tested once a few weeks are collected.

### Daily goal

| | Default | What happens |
|---|---|---|
| Daily goal | **$600** closed profit | no new trades; open trades keep running until a pointer forms against them |
| Daily cap | **$1,200** open + closed | flatten everything, done for the day |
| Daily stop | **−$600** open + closed | flatten everything, done for the day (smaller when the account is near its drawdown) |

### Prop firm account (`backend/account.py`)

All bots trade one shared account with LucidFlex 50K rules:

| Rule | LucidFlex 50K | What the bots do |
|---|---|---|
| Profit target | $3,000, at least 2 trading days | stop for the day once it's in hand; pass at the 16:45 close |
| Drawdown | **End-of-day**: $2,000 below the highest *closing* balance, only moves at the close, locks at $50,100 once the account closes at $52,100 | never let a day's loss reach it (keep a $100 cushion). Equity touching it during the day is treated as a breach (the safe reading) |
| Consistency | evaluation: best day ≤ 50% of profit; funded: none | the $1,200 cap keeps the best day under half the $3,000 target |
| Daily loss limit | none | our own −$600 daily stop |
| Max size | 40 micros | at most 12 micros open, 3–6 per trade |
| Flat rule | flat by 16:45 ET, no overnight/weekend holds (Tradovate's micro session ends 16:00) | no entries after 15:50, flatten at 15:55 |

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

### Funded account and payouts (LucidFlex 50K, rules as of Oct 2026)

When the evaluation passes, the account switches to the funded rules with its own
guards (`funded_guards()`: the same goal, cap and stop by default, with overrides
through `NEXUS_FUNDED_DAILY_GOAL` / `_CAP` / `_STOP` / `_KEEP_ROOM`).

**Lucid's funded rules, built in:**

- No consistency rule and no buffer; 90/10 split.
- A payout cycle needs **5 days of at least $150 profit** and a **net-positive cycle**.
- Payouts are **$500 minimum, up to 50% of profit or $2,000**, and 5 payouts per account before it moves to a live account.
- After a payout the MLL locks at **$50,100**.
- Scaling plan: 20, 30 or 40 micros at $0, $1k or $2k of profit, set each session. It never binds, because we use 12 at most.

**In the app:**

- The account panel shows the cycle progress, the largest payout allowed, and a
  **suggested payout** that keeps `$1,500` above the locked MLL afterwards.
- You get a 💸 push when a payout opens up.
- **Record a payout** mirrors one you requested at Lucid.
- **Sync with my Lucid account** sets the phase, balance, MLL, payouts taken and cycle days from your dashboard.

**What the 21 real days say:**

- The evaluation passed on day 6 (Sep 15).
- The funded account made about $6,400 over the next 14 days.
- Taking every suggested payout gave one payout of $1,950 (you keep $1,755) on Sep 28, with the second due on Oct 6.

Lucid's payout limits, not the bots, cap the take-home: about $2,000 per account
per cycle of 5+ days. The way to scale is more accounts and fast, steady $150+
days, not bigger days.

    python -m backend.backtest data/*_1m.csv --payouts

### Scale plan (`backend/scale.py`)

**📈 SCALE PLAN** in the account panel shows every account by stage (in evaluation, funded, payout ready,
moved to live, failed), the next milestone for each with an estimated date, the payouts coming (your 90%),
and when the treasury can buy the next evaluation. Estimates use $400/day (the latest 22-day backtest on real
candles) until there are 10 traded paper days, then your own average, with ~55% of days making $150+.

Set what Lucid charges you for an evaluation and your account limit with the button in the panel
(`POST /api/scale`). From then on the next evaluation is a one-time treasury goal: once the pool covers it on
top of a month of bills, ULTRON puts **Buy: Lucid evaluation #N** in your approvals. Nothing is bought for you:
you buy it at Lucid and add it under 👥. In the simulation the plan reads the simulated account and never
asks for money.

### Your Lucid accounts (`backend/accounts.py`)

Open **👥 My Lucid accounts** in the account panel and add each account you buy:
a name, its phase, and the balance, MLL and payout progress from your Lucid
dashboard. Every bot trade is applied to every account, so each card shows:

- the balance and today's P&L
- the room above its MLL
- evaluation progress, or the payout cycle and the suggested payout

The top of the panel totals what's **ready to pay out right now** across all
accounts. You get pushes when an account passes, fails, has a payout ready, or
has to stop while the bots keep trading.

**Routing with one TradersPost strategy per account (recommended).** Give each
account its own TradersPost strategy and paste that strategy's webhook into
**Add webhook**. The router then manages every account separately:

- An account only joins a new trade if it may trade (not stopped for the day,
  not at its evaluation target) and has room in its contract budget.
- An account close to its MLL stays at 3 contracts while the others add to 6.
- Trims resize each account to its own size, and exits go to every account in
  the trade.

Accounts without their own webhook copy everything sent to
`NEXUS_TRADERSPOST_WEBHOOKS`. For those the app can only tell you to pause the
subscription. Webhook URLs stay in `data/accounts.json` on the server and are
never sent to the app.

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

## Strategy Forge (`backend/forge.py`)

New setups are found, tested honestly, shadow-traded on paper, and go live only when you approve. Open it with
**⚒️ STRATEGY FORGE** in the account panel.

1. **Forge, every Saturday.** It runs in its own low-priority process, so trading never slows down. It builds 40
   setups from the strategy's tested filters: confirmation mode and window, killzones, sweep requirement, trims,
   chop and bias filters, and walk-away count. It writes no new code, and it never touches the PROC zone settings
   (pivot length, IFFVGs, proximity), which match your TradingView chart.
2. **Test.** Each setup is backtested on the saved 1-minute candles: TradingView's own once 15+ days are saved,
   otherwise the Yahoo history. To pass, a setup must beat the live settings on the first half of the training
   days, the second half, and the newest 30% it never saw while being chosen. Its worst day can be no worse by more
   than $200, and it can't fail more evaluations.
3. **Shadow.** The best setup that passes is replayed with each real trading day after the close, next to the live
   settings. This is paper only: no orders.
4. **Vote.** After 10 shadow days, the desk's rules decide. If the shadow beat the live settings by $100+, with at
   least as many green days and a comparable worst day, a "Promote?" card goes to your approvals. If not, it's
   retired.
5. **Promote.** Only you can promote. The new settings switch in at the next session roll (18:00 ET, bots flat).
   They're saved in `data/strategy.json` and survive restarts, and every promotion is logged. The daily
   paper-vs-replay scorecard uses the same settings.

The first run on 22 real days (Sep 8 – Oct 7 2026) tried 40 setups. One beat the live settings on the training
days, none passed every check, and the live settings stayed. You can also run the forge from the panel while the
market is shut.

## The Lookout (`backend/bots/watcher.py`)

The M2K bot is gone: the Russell added nothing to a strategy that trades NQ and ES. Its building is now
**TheLookout** (NQ/ES LOOKOUT, district BIG BOARD), who watches the big contracts and **never trades**:

- runs the PROC read (FFVGs, taps, 3-6m pointers, PROCs) on NQ and ES and calls each PROC with whether the
  other market is with it ("NQ 4m PROC ↑ 10:32 · ES is with it"); those calls show in the city feed
- keeps one read on his board: **together ↑ / together ↓** (both charts agree), **split** (they disagree:
  careful), a market moving **alone**, or **quiet**
- OG Pointer and SixMinuteSage only enter when ES agrees: that confirmation reads the **same shared engine**
  as the Lookout's ES read (`proc.shared_engine`), so there is one read, never a copy
- has no contracts and no position, sends no orders, and keeps watching through an account stop

Nothing about the trading changed: same entries, same exits, same numbers in the backtests.
