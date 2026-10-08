# Operations: hosting, alerts and monitoring

Running Nexus City day to day: hosting on Render, phone alerts, the watchdog and the tests that guard the money paths.

## Watch it from your phone, 24/7 (deploy to Render)

The repo is ready to host: `Dockerfile` + `render.yaml` run the city in live
paper mode with a password and a disk for the paper-trading logs.

1. Push to `main` on GitHub (Render deploys the default branch).
2. Sign up at **render.com** with your GitHub account.
3. Dashboard → **New → Blueprint** → pick `levetteit/nexus-city` → **Apply**.
4. When asked for **`NEXUS_PASSWORD`**, pick a strong password. That's what
   you'll type on your phone. (`NEXUS_WEBHOOK_SECRET` is generated for you.)
5. It uses the **Starter plan (~$7/month) + a 1 GB disk (~$0.25/month)**. The free
   plan sleeps after 15 minutes without visitors, which would stop the bots.
6. When the deploy is green, open the `https://starnet-city-….onrender.com` URL (the Render service keeps its original name, so the address doesn't change: see [MIGRATION_FROM_STARNET.md](MIGRATION_FROM_STARNET.md))
   on your phone, log in with any username + your password, then
   **Share → Add to Home Screen** (iPhone) or **⋮ → Add to Home screen /
   Install app** (Android). It opens full screen like an app.

On the phone you get a compact account bar (tap it for the full panel), the
city, and an **activity feed** of what every bot is doing: PROCs seen, waiting
for MES, entries, adds, exits, account stops. Tap a building for its card.

Every push to `main` redeploys automatically. Paper results stay on the disk
(`/app/data/paper_trades.csv`, `paper_days.csv`); download them from Render's
Shell tab. The same Docker image runs on Fly.io, Railway or any VPS: set
`NEXUS_PASSWORD`, mount a volume at `/app/data`, expose port 8000.

## Trade alerts on your phone (`backend/notify.py`)

Get a notification every time a bot enters, adds to or exits a trade (with the
P&L), when the account stops for the day, and if a real order ever fails.

**iPhone / Android (no extra app):** open Nexus City from its **home-screen icon**
(on iPhone, web push only works from there), tap the account bar to expand it →
**🔔 TURN ON ALERTS** → **Allow**. You'll get a confirmation buzz; **SEND TEST**
sends another. Turn it on separately on each device you want alerts on.

**Backup: ntfy.** Install the free **ntfy** app, subscribe to a long random topic
name (e.g. `nexus-7f3k9q2x`), and set `NEXUS_NTFY_TOPIC` to the same name in
Render → Environment.

Alerts only fire in live mode. Real-order alerts are marked **· REAL**.

## Tests and the watchdog

**Tests.** `python -m pytest tests` checks the things that cost money when they break:

- Lucid's rules: drawdown, consistency, payouts and scaling.
- The real-order router: per-account sizing, stale data, restarts.
- The account book and the news filter.
- The desk's risk-off-only modes.
- The password gate.
- A regression on 5 real trading days (`tests/fixtures`). The 21-day baseline also runs when `data/` is present.

GitHub runs the tests on every pull request.

**Watchdog (`backend/watchdog.py`).** It pushes to your phone when, during market hours:

- MNQ or MES drops off the TradingView real-time feed (usually an expired alert), and again when it's back;
- no candles arrive at all for 25 minutes;
- the server restarts with real positions open.

Every weekday at 08:30 ET it also sends a short systems check. If the whole server
is down it can't warn you itself, so point a free uptime monitor (e.g. UptimeRobot)
at `https://<your-app>/healthz`.
