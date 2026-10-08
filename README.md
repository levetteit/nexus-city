<div align="center">

# Nexus City

**A 3D operations dashboard where trading bots and AI agents work under rules that code enforces, and a person approves.**

[![CI](https://github.com/levetteit/nexus-city/actions/workflows/ci.yml/badge.svg)](https://github.com/levetteit/nexus-city/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-asyncio-009688?logo=fastapi&logoColor=white)
![Three.js](https://img.shields.io/badge/Three.js-3D-000000?logo=threedotjs&logoColor=white)
![Claude API](https://img.shields.io/badge/Claude_API-structured_outputs-D97757)
![Tests](https://img.shields.io/badge/pytest-186_tests-2ea44f?logo=pytest&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Render-2496ED?logo=docker&logoColor=white)

[Screenshots](#screenshots) · [Architecture](docs/ARCHITECTURE.md) · [Safety model](#safety-and-human-in-the-loop-model) · [What it demonstrates](docs/PORTFOLIO.md) · [Run it](#local-setup) · [Docs](#documentation)

![Nexus City: trading bots in the center, the AI station's departments around them](docs/screenshots/city-world.jpg)

</div>

## At a glance

| | |
|---|---|
| **What it is** | One FastAPI app with two sides. **The City**: Python bots trade micro futures for a prop firm account, each in its own 3D building. **The Space Station**: ULTRON, a scheduler built on the Claude API, runs a crew of AI agents that research, draft and operate small online ventures |
| **Why it's interesting** | LLM agents that can't act on their own. Every outbound action is a draft that passes code-enforced QA, a send policy, daily caps and an emergency stop. Real orders need an explicit arm, fresh data and session cutoffs. Every change is written to an audit log |
| **Stack** | Python 3.12 · FastAPI · asyncio · Claude API · Three.js · Docker · GitHub Actions · Stripe, Etsy, Meta, Pinterest, TradersPost integrations |
| **Quality** | 186 pytest cases with the network blocked, 76% backend coverage. CI runs lint, tests, a secret scan over the full history, a dependency audit and a Docker smoke test |
| **Who built it** | Jerai Padilla: design, domain rules and operation, with Claude Code as an AI pair programmer ([details](docs/PORTFOLIO.md)) |
| **Try it** | `uvicorn backend.main:app` runs a simulated market. It needs no keys or accounts ([setup](#local-setup)) |

Old `STARNET_*` settings still work; see [docs/MIGRATION_FROM_STARNET.md](docs/MIGRATION_FROM_STARNET.md).

## Screenshots

| The Space Station (3D) | The Command Board |
|---|---|
| ![ULTRON's command core with the station's departments around it](docs/screenshots/station-3d.jpg) | ![Mission, emergency stop, AI credits, treasury and portfolio](docs/screenshots/command-board.jpg) |
| **A bot's streamer room** | **Title screen** |
| ![A bot's room: live chart, P&L and stream chat](docs/room.png) | ![Nexus: trading city and space station](docs/screenshots/title-screen.jpg) |

The screenshots come from the local simulation with seed data; no real accounts or money are involved.

## Architecture overview

```mermaid
flowchart LR
    TV[TradingView 1m candles] --> API
    Y[Yahoo delayed candles] --> API
    subgraph App[FastAPI app]
        API[REST + WebSocket + password gate] --> Engine[Trading engine: bots + prop account rules]
        Engine --> Router[Order router: armed by the owner]
        API --> Ultron[ULTRON scheduler]
        Ultron --> Crew[AI agents via Claude API]
        Crew --> Outbox[Outbox: QA, policy, caps, E-STOP]
        Engine --> Store[(JSON / JSONL store + audit log)]
        Ultron --> Store
    end
    Router --> TP[TradersPost → Tradovate]
    Outbox --> Ext[Stripe · Etsy · Meta · Pinterest · email]
    API --> UI[Browser: 3D city, station, boards]
```

- **One process.** The trading loop, the station scheduler and the web server are asyncio tasks in one process.
- **No database.** State lives in JSON and JSONL files on a mounted disk, written atomically. See [docs/PERSISTENCE.md](docs/PERSISTENCE.md).

The full design, with the AI workflow, the trading flow and the order safety checks, is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Key capabilities

**Trading (City)**
- **The strategy:** a rules-based intraday strategy (PROC: fair-value-gap taps plus multi-timeframe pointers), read on NQ/ES and executed on the micros.
- **Account rules:** prop firm rules are modelled in code: drawdown, daily goal, cap and stop, consistency limits and payouts.
- **Backtesting:** a backtester and walk-forward optimizer that replay real 1-minute candles. Strategy Forge tests candidate changes, runs the survivors as shadow paper bots, and leaves promotion to the owner.
- **Live paper trading:** runs on real candles, with a news blackout filter, daily reports and a check of live trading against a replay.
- **Real orders (optional):** sent through TradersPost, guarded by an explicit `ARM`, stale-data blocks, session cutoffs and a flatten-and-disarm.

**AI operations (Space Station)**
- **The crew:** ULTRON schedules a crew of agents: research, validation, marketing, content, outreach, QA and an auditor. Every agent call uses structured outputs.
- **The board:** ventures move through stages on a Command Board, with approvals, tasks, a War Room review and lessons the agents carry forward.
- **The outbox:** every outbound action (post, email, listing, payment link) is a draft first. It passes a compliance check, a per-kind send policy and daily caps, and it stops at an emergency stop.
- **Money:** one treasury with per-venture P&L, AI spend caps and a hash-chained ledger. Only real, verified money counts.
- **Jarvis API:** a token-protected endpoint lets an outside operator act on the board within a fixed allowlist. It is refused for anything that touches money, trading or accounts.

## Technology stack

| Area | Tools |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn, asyncio, WebSockets |
| AI | Anthropic Claude API (structured outputs, web search tool) |
| Frontend | Vanilla ES modules, Three.js, a hand-written canvas chart; installable as a phone app (manifest and service worker) |
| Integrations | TradersPost, TradingView (Pine script webhook), Yahoo Finance, Stripe, Etsy, Printify, Meta Graph API, Pinterest, SMTP/IMAP, ntfy and Web Push |
| Storage | JSON and JSONL files with atomic writes and a hash-chained ledger |
| Delivery | Docker, Render (blueprint in `render.yaml`), GitHub Actions |
| Quality | pytest (unit and integration), coverage, pyflakes, gitleaks, pip-audit |

## Safety and human-in-the-loop model

| Area | What a human must do | What code enforces regardless |
|---|---|---|
| Real orders | Arm execution with an explicit `ARM`; promote any strategy change | Stale-data blocks, 15:50 ET entry cutoff, 15:55 ET flatten, account loss limits, exits that can only reduce a position |
| Money | Approve spending, funding and goals; record payouts | No code path moves money; income is booked only from the owner or signed Stripe events; AI budget caps |
| Outbound actions | Optionally require approval per kind (`NEXUS_POLICY_*=owner`) | Compliance check, daily caps, emergency stop, connector checks, idempotent Stripe calls |
| Ventures | Kill a venture; open accounts | Auto-launch limits (score, one a day, 3 live) and an automatic close after 21 days with no sale |
| Everything | | An append-only audit log of who changed what and why |

> By default, outbound actions that pass the compliance check are sent automatically
> (`NEXUS_POLICY_*=auto`). Set the policy to `owner` for any kind that should wait for a person.

Full details: [docs/SECURITY.md](docs/SECURITY.md), including its threat model and known limitations.

## Project structure

```text
backend/            FastAPI app (main.py), trading engine, bots, prop account, order router, backtester, Strategy Forge
backend/station/    ULTRON, agents, connectors, outbox, store, treasury
frontend/           the 3D city and station, the Command Board, rooms and charts
tests/              pytest suite (fixtures/ holds 5 days of real 1-minute candles)
kits/               finished products the station can publish
tradingview/        Pine script that streams 1-minute candles to the app
docs/               the deep documentation (index below)
```

## Local setup

```bash
git clone https://github.com/levetteit/nexus-city.git && cd nexus-city
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock -r requirements-dev.txt
uvicorn backend.main:app --reload        # http://localhost:8000, simulated market, no keys needed
```

`NEXUS_TICK_SECONDS=0.1` runs the simulated market 10× faster. More detail is in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Environment configuration

Every setting is listed in [`.env.example`](.env.example), grouped by area and with placeholders only. Copy it to `.env`, which git ignores, and run with `--env-file .env`.

| Setting | Purpose |
|---|---|
| `NEXUS_MODE` | `sim` (default: random-walk market) or `live` (real candles, paper trading) |
| `NEXUS_PASSWORD` | The app's password; in live mode the app answers 503 until one is set |
| `ANTHROPIC_API_KEY` | Turns on the AI trading desk and the station's agents |
| `NEXUS_POLICY_*` | Per-kind send policy for outbound actions: `auto` or `owner` |

Secrets come only from the environment and are masked in logs and errors.

## Testing

```bash
python -m pytest -q                  # 186 tests, ~30 s; the network is blocked during tests
python -m pytest -q -m "not integration"
python -m pyflakes backend tests
```

CI runs four jobs on every pull request:
- **lint**
- **pytest** with coverage
- **security**: gitleaks over the full history, and pip-audit on the lockfile
- **docker**: builds the image and smoke-tests it

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Deployment

- **Docker:** the `Dockerfile` builds a single image.
- **Render:** `render.yaml` deploys it to Render with a password and a persistent disk, and every push to `main` redeploys.
- **Anywhere else:** the same image runs on any Docker host. Set `NEXUS_PASSWORD`, mount a volume at `/app/data` and expose port 8000.

A deploy restarts the app, and on startup it closes any positions the order router had open. Deploy while the bots are flat.

Step-by-step hosting, phone alerts and monitoring are in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Project status

- **Single-owner project.** It is in daily use by its owner: hosted on Render in live paper mode, with real-order routing wired to one prop firm account.
- **Trading results:**
  - Backtest: 21 days of real 1-minute data (Sep–Oct 2026). That is a small sample and not evidence of future performance.
  - Forward test: paper trading is ongoing.
  - Details: [docs/TRADING.md](docs/TRADING.md).
- **Station:** live. Some outbound channels wait on third-party approvals or tokens.
- **Trading reliability:** every approved finding from the audit's trading review is fixed with regression tests (C-1, T-H1 to T-H7, M-4, M-11; see [docs/ENGINEERING_AUDIT.md](docs/ENGINEERING_AUDIT.md)). The remaining open items are medium and low findings listed there.

## Roadmap

1. **Trading:** the open medium findings (M-3 signal price anchoring, M-12 serial order posting) and Render build filters so docs-only changes don't restart the bots.
2. **Persistence:** move from JSON files to PostgreSQL along the schema already designed in [docs/PERSISTENCE.md](docs/PERSISTENCE.md), once the data outgrows one disk.
3. **Station:** reconnect the expired social tokens, finish the Pinterest app review, and test channels with real traffic.

## Documentation

| Document | Contents |
|---|---|
| [docs/PORTFOLIO.md](docs/PORTFOLIO.md) | What the project demonstrates, resume bullets, interview talking points |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, runtime model, the AI workflow, the trading flow, persistence, design decisions |
| [docs/CITY.md](docs/CITY.md) | The 3D city: weather, streamer rooms, skins, shuttles, the shared world |
| [docs/TRADING.md](docs/TRADING.md) | The strategy, sizing, sessions, prop account rules, real-data results, backtesting, Strategy Forge |
| [docs/LIVE_TRADING.md](docs/LIVE_TRADING.md) | Live paper trading, the news filter, the AI trading desk, reports, real orders, TradingView setup |
| [docs/STATION.md](docs/STATION.md) | ULTRON, the agents, ventures, the outbox, treasury, connectors, Jarvis |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Hosting on Render, phone alerts, the watchdog |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model, authentication, secrets, agent boundaries, safeguards |
| [docs/PERSISTENCE.md](docs/PERSISTENCE.md) | Storage, durability, recovery, the PostgreSQL design |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, tests, CI, dependencies |
| [docs/MODERNIZATION_REPORT.md](docs/MODERNIZATION_REPORT.md) | The 14-phase modernization: before and after, validation, remaining debt |
| [docs/ENGINEERING_AUDIT.md](docs/ENGINEERING_AUDIT.md) | The engineering audit: findings and their status |
| [docs/MIGRATION_FROM_STARNET.md](docs/MIGRATION_FROM_STARNET.md) | The StarNet → Nexus City rename |

## Author

Built by **Jerai Padilla** ([@levetteit](https://github.com/levetteit)), with AI pair-programming from Claude Code.
