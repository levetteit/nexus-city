# Live trading: paper, data feeds and real orders

Running the bots on real market data: paper trading, the news filter, the AI trading desk, reports, and the guarded path to real orders.

## Live paper trading (`backend/live.py`)

Run the city on real markets with paper money:

```bash
NEXUS_MODE=live uvicorn backend.main:app
```

- Real MNQ / MES / M2K candles (via NQ=F / ES=F / RTY=F on Yahoo) step the
  bots minute by minute. The header shows **● LIVE PAPER** and how far behind
  the data is: Yahoo's free CME feed is **~10 minutes delayed**, so this is a
  forward test, not something to mirror trades from.
- On startup the bots read the last 2 days of candles without trading, so
  their FFVG / PROC structure is ready before the first live candle.
- Every closed trade goes to `data/paper_trades.csv`, every finished day to
  `data/paper_days.csv`, and the prop account to `data/paper_account.json`, so
  a restart resumes the same evaluation (open positions aren't carried over).
- Leave it running on a small server or always-on computer for a few weeks:
  forward-test results can't be overfit, unlike backtests.

Going from paper to a real Lucid account needs a real-time data feed and order
routing through the platform your account uses (see *Going live* below).

## News filter (`backend/news.py`)

These bots trade without a stop loss, so a CPI, FOMC or NFP candle is the
quickest way to lose a prop account. For every high-impact USD release on the
ForexFactory calendar:

- **No new trades** from 10 minutes before the release until 15 minutes after it, or 45 minutes after for FOMC.
- **Open trades are closed** 2 minutes before the release.

The account panel lists the next releases, the activity feed shows each pause,
and your phone gets an alert. The calendar refreshes every 6 hours and is saved
to `data/news_calendar.json`. Add your own events in `data/news_extra.json`.

Settings (environment variables):

| Variable | Default | What it does |
| --- | --- | --- |
| `NEXUS_NEWS_BEFORE` | 10 | Minutes before a release with no new trades |
| `NEXUS_NEWS_AFTER` | 15 | Minutes after a release with no new trades |
| `NEXUS_NEWS_AFTER_FOMC` | 45 | Minutes after an FOMC release with no new trades |
| `NEXUS_NEWS_FLATTEN` | 2 | Minutes before a release to close open trades; `0` holds them instead |

To backtest with a calendar: `--news data/news_calendar.json`.

## Trading desk: journals, news and a daily plan (`backend/desk.py`)

The bots hold two meetings a day on Claude (`claude-opus-5-5`):

- **🌙 Evening meeting**, after each day's report:
  - Every bot writes a journal entry in its own voice about its actual trades (why in, why out, what it learned).
  - The desk updates its **standing lessons**, which are fed back into every later meeting. That's how they learn.
  - The desk sets the risk mode for the overnight and London session.
- **☀️ Morning briefing**, 08:40 ET on weekdays:
  - A web search for what is moving NQ/ES today (the 8:30 data, Fed, megacap news, geopolitics).
  - A plan, a one-line note for each bot, and the risk mode for New York.

The desk is built to compete and never quit, and to treat discipline as the weapon.
**It can only take risk off**:

- `normal`: trade as usual (the default)
- `cautious`: no adds, positions stay at 3 contracts
- `sit_out`: no new trades until the next meeting

It can't touch the strategy, the stops, or the goal and cap. The replay check trades
every day in normal mode, so each non-normal mode's cost or savings is measured, and
the desk sees that history. You can make the desk advisory-only from its panel.

**Turn it on:** add `ANTHROPIC_API_KEY` in Render → Environment. Without a key the desk
stays off and nothing else changes. Expect about 4 Claude calls and up to 10 web
searches a day: roughly $0.30–0.70 a day, or $10–20 a month.

**Where to see it:**

- 🧠 Desk notes in the account panel: briefings, meetings, lessons, and "hold a meeting now"
- **JOURNAL** in each bot's room
- The desk section of each daily report
- A push after each meeting

Everything is saved in `data/desk/`.

## Candle history (`backend/history.py`)

Yahoo only keeps about 30 days of 1-minute candles, so live mode saves them as they come in:

- **On startup:** it backfills the last 29 days.
- **At every day roll:** it saves the newest days again.

Everything goes to `data/history/{MNQ,MES,M2K}_1m.csv` on the Render disk. The
account panel shows how many days are saved, with download links (also at
`/api/history/MNQ.csv`). Feed the files to the backtester to re-test and
re-optimize on more data as it builds up:

    python -m backend.backtest MNQ_1m.csv MES_1m.csv M2K_1m.csv --optimize

**TradingView's own candles.** Yahoo's copy differs from what TradingView sends (missing minutes, different
closes), and TradingView's export needs a Premium plan. So every candle the feed script delivers is also
saved, once, to `data/history/tradingview/{MNQ,MES}_1m.csv`, with volume when the script sends it. The
account panel shows the days collected and download links (`/api/history/tradingview/MNQ.csv`); the
backtester reads them as is. It starts with the first candle after this was deployed.

## Paper vs backtest check (`backend/scorecard.py`)

When each trading day ends, live mode downloads that day's candles again and
replays them through the same bots, settings and account state. It then checks
that paper trading took the same trades. A mismatch means the live pipeline
changed the result (late or missing candles, a restart, a bot switched on or
off), so backtest numbers won't carry over to real money yet.

The account panel also compares the paper days so far with the backtest: green
days, average day and profit factor. After each day you get a push such as
"📊 Day done +$640 · replay +$640 ✅". The full history is at `/api/scorecard`
and in `data/paper_checks.json`.

Before you connect real money, look for:

- **Replay match:** close to 100% on days without a restart.
- **Green days and average day:** near the backtest after 15–20 days.

## Daily report (`backend/report.py`)

When each trading day ends (around 6pm ET in live mode), the app saves a report
of the day. Once the paper-vs-backtest replay has checked the day, it pushes a
summary to your phone, for example:

> 📊 Tue Oct 6 · +$640 · 3 trades
> 2W 1L · goal ✓
> Eval +$1,840 / $3,000 (61%) · $2,450 room
> Replay ✅ 3/3 trades matched
> Best: OG_Pointer +$520 (3m PROC + MES)

Tap the push, or 📒 Daily reports in the account panel, to see each trade's
entry reason, adds, exit reason and prices. The panel also shows news pauses and
daily stops. Reports are saved in `data/reports/` and served at `/api/reports`.
For ntfy, set `NEXUS_PUBLIC_URL` (Render sets `RENDER_EXTERNAL_URL` for you)
so that tapping the notification opens the report.

## Real orders on your Lucid accounts (`backend/execution.py`)

Lucid allows automated trading (not high-frequency trading or sub-5-second
scalping, which these bots don't do). Real orders go **bot → TradersPost →
Tradovate → your Lucid account(s)**. Two pieces, both one-time setup:

**1. Real-time prices (required).** The free Yahoo data is ~10 minutes late, and
real orders are blocked whenever prices are more than 2.5 minutes old. The
`tradingview/nexus_city_feed.pine` script streams each 1-minute candle the moment
it closes (needs a paid TradingView plan with webhooks and CME real-time data):

1. In Render → your service → **Environment**, copy `NEXUS_FEED_SECRET`.
2. TradingView → open **NQ1!** on the **1-minute** chart → Pine Editor → paste
   the script → **Add to chart** → settings → paste the secret.
3. **Create Alert** → Condition **Nexus City feed → Any alert() function call** →
   Notifications: **Webhook URL** `https://<your-render-url>/api/feed` → Create.
4. Repeat 2–3 on **ES1!** (ES confirms every entry).

Like Macre, the bots read the **full-size** charts and execute on the micros: NQ1!'s candles feed the MNQ
bots, ES1!'s the MES side, and orders still go to MNQ / MES. NQ and MNQ trade at the same price, but NQ's
book is far deeper, so its wicks (and so its FFVGs, taps and pointers) are the clean ones; Yahoo's NQ=F /
ES=F, which every backtest here used, are the full-size contracts too. MNQ1! / MES1! alerts still work on
their own, but while an NQ1! / ES1! alert is feeding, a micro alert for the same market is ignored (the feed
log says so: delete it). The account panel shows which chart feeds which symbol (`NQ → MNQ`).

The account panel shows **Price data: TradingView · real-time** once it's flowing.
After updating the script (it now also sends volume), re-create both alerts: TradingView keeps the old
version in an existing alert.

**2. Order routing.**

1. Buy your Lucid account(s) and choose **Tradovate** as the platform.
2. Sign up at **traderspost.io** → **Brokers → Tradovate** → log in with your
   Lucid Tradovate credentials (repeat for each Lucid account).
3. **Strategies → New strategy** (futures). Copy its **webhook URL**.
4. **Subscribe** each Lucid account to the strategy. In the subscription
   settings: allow **shorting**, allow **add to position**, use the **signal's
   quantity**, market orders. No stop loss or take profit (the bots manage exits).
5. Render → **Environment** → set `NEXUS_TRADERSPOST_WEBHOOKS` to that URL →
   Save (it redeploys).
6. In the city, the account panel shows **Real orders: off**. Tap
   **ARM REAL ORDERS** and type `ARM`. The header turns to **● REAL ORDERS**.

What gets sent: entry `buy`/`sell` with the bot's quantity (3), `add` (3 more,
6 max) and `exit`, on the front-month contract (e.g. `MNQZ2026`, rolling 8
days before expiry). Every order is logged in `data/orders.csv`.

Safety built in:
- Off until you arm it; **FLATTEN ALL** exits everything on your accounts and disarms.
- Disarming stops new entries and adds. A position already open for real keeps getting its trims and exit until
  it's flat; the account panel shows it as still managed.
- New entries are blocked when price data is over 2.5 minutes old; exits always go through.
- No new entries from 15:50 ET by the real clock, even if the candles are late. From 15:55 ET by the clock, and
  inside a news-flatten window, open real positions are exited without waiting for a candle.
- Adds and exits are only sent for positions the router opened itself.
- After a restart, any position left open is closed immediately (the bots restart flat).
- Your Lucid account still enforces its own rules (drawdown, position limits,
  4:45 PM ET flat); the bots' daily goal / cap / stop and 15:55 flatten sit inside those.

The city's account panel still tracks paper P&L from the bots' fills. Your real
fills (slippage, commissions) are in TradersPost and Tradovate. Run paper for a
while, then start with **one** evaluation account before connecting more.

## Signal check against Macre's indicator (`backend/signals.py`)

The PROC engine is a rebuild of the TradingView indicators, and the backtest is
only as good as that rebuild. **🎯 Signal check** in the account panel lists
every PROC the bots traded each day, with a mini chart of:

- the candles around it
- the FFVG/IFFVG it reacted to
- the pointer candle
- the entry

Each signal is labeled by its candle's open time, as TradingView does. Mark each one
**✅ on my chart** or **❌ not on my chart** (with a note), and add PROCs your
indicator printed that the bots missed. A per-killzone table shows how many PROCs
the engine saw on each timeframe. On the 21 days that's about 40 per day inside
the killzones; if your indicator shows far fewer, the rebuild is too loose. The
agreement score and the mismatches show exactly what to fix. Saved in
`data/signals/`.

## TradingView alerts

The PROC, Untapped FFVGs and Troop Toolkit indicators don't publish alert
conditions, so they can't send webhooks. That's why the bots rebuild PROC
themselves from price data. The webhook still accepts direct orders from any
other alert you set up:

1. Start the server with a secret: `NEXUS_WEBHOOK_SECRET=<long random string> uvicorn backend.main:app --host 0.0.0.0`
2. Give it a public HTTPS address (`ngrok http 8000`, or a cloud server).
3. In the TradingView alert, tick **Webhook URL** → `https://<address>/api/tradingview`, message:
   ```json
   {"secret": "<your secret>", "ticker": "{{ticker}}", "signal": "long", "price": {{close}}}
   ```
   `signal` is `long`, `short` or `exit`. Alerts go to every bot on that symbol
   (`MNQ1!`, `MES1!`), or add `"bot": "mnq-3m"` for one bot.

## Going live (read this first)

The default mode (`NEXUS_MODE=sim`) runs on **simulated prices with a paper broker**. Simulated prices are a
random walk, so they don't prove the strategy works (or that it doesn't); backtest it on real candles to judge it.

`NEXUS_MODE=live` runs the bots on real candles with **paper** money. Real orders are a separate, deliberate
step: they go through TradersPost to Tradovate only after you configure the webhooks, stream real-time
candles from TradingView and **arm** execution in the app (typing `ARM`); see *Real orders on your Lucid
accounts* above. Check that your prop firm allows automated trading first (Lucid does, within its rules).
