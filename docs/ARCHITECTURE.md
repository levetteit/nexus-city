# Architecture

Nexus City is one Python 3.12 process: a FastAPI application. It runs two long-lived asyncio loops beside the web server:
- **the trading loop**, which steps the bots and the prop account through market data;
- **the station loop**, in which ULTRON schedules work for the AI agents.

Both loops write to files on one mounted disk, and both are observed through the same REST/WebSocket API by a
browser frontend. This document describes the layers, the runtime model, and the main flows. Each claim names
the module that implements it.

## 1. System layers

```mermaid
flowchart TB
    FE["Frontend<br/>vanilla ES modules + Three.js<br/>city · station · Command Board · rooms"]
    API["FastAPI application · backend/main.py<br/>REST · WebSocket /ws · webhooks<br/>PasswordGate middleware · backend/security.py"]
    CORE["Core services<br/>config (env.py) · redaction (redact.py) · persistence (persist.py) · notifications (notify.py)"]
    subgraph DOMAINS[" "]
        direction LR
        TRADE["Trading system<br/>engine · bots · prop account<br/>order router · desk · forge"]
        STATION["AI operations station<br/>ULTRON · agents · outbox<br/>treasury · connectors"]
    end
    EXT["External integrations<br/>TradingView · Yahoo · TradersPost<br/>Claude API · Stripe · Etsy · Printify · Meta · Pinterest · SMTP/IMAP · ntfy/Web Push"]
    STATE[("Persistent state and audit log<br/>JSON documents · append-only JSONL · CSV trade logs<br/>hash-chained money ledger")]

    FE <--> API
    API --> CORE
    CORE --> TRADE
    CORE --> STATION
    TRADE --> EXT
    STATION --> EXT
    TRADE --> STATE
    STATION --> STATE
    TRADE -. "payouts, paper P&L, AI desk cost" .-> STATION
```

| Layer | Responsibility | Main modules |
|---|---|---|
| Frontend | Renders state, sends owner commands. Holds no business logic | `frontend/city.js`, `world.js`, `room.js`, `station3d.js`, `station.js` |
| API | Routing, request validation, authentication, cross-site protection, security headers, webhook verification | `backend/main.py`, `backend/security.py` |
| Core services | Settings with the `NEXUS_*`/`STARNET_*` fallback, secret masking, atomic file writes, phone notifications | `env.py`, `redact.py`, `persist.py`, `notify.py` |
| Trading system | Market data, strategy, prop account rules, real-order routing, research tools | `engine.py`, `bots/`, `account.py`, `accounts.py`, `execution.py`, `live.py`, `backtest.py`, `forge.py`, `desk.py` |
| AI operations station | Scheduling, agent work, outbound actions, money accounting | `backend/station/` |
| External integrations | One adapter per service. Each failure becomes a `ConnectorError` with secrets masked | `station/connectors.py`, `execution.py`, `live.py`, `news.py`, `notify.py` |
| Persistent state | Station records, audit log, ledger, trading logs and account state | `station/store.py`, `station/economy.py`, `persist.py`; files under `NEXUS_DATA_DIR` |

**Boundaries between the two domains.** The station reads the trading side but never drives it. It reads the
account (payouts, paper P&L) to keep the treasury current, and it books the trading desk's Claude cost to the City.
It cannot place, size or arm orders. That boundary is in code: ULTRON has no reference to the order router, and
Jarvis refuses the trading venture (`backend/jarvis.py`).

## 2. Runtime model

```mermaid
flowchart LR
    subgraph Process["uvicorn process · one asyncio event loop"]
        WEB["HTTP + WebSocket handlers"]
        TL["Trading loop<br/>run_city (sim) or run_live (live)"]
        SL["Station loop<br/>run_station · every 15 s"]
        FL["Forge loop<br/>run_forge (live)"]
        TP["Worker threads<br/>asyncio.to_thread<br/>Claude calls · HTTP polls · file-heavy work"]
        OQ["Order worker<br/>asyncio.Queue → TradersPost"]
    end
    TL --> TP
    SL --> TP
    FL --> TP
    TL --> OQ
    TL -- "broadcast state" --> WEB
```

- **Startup** (`lifespan` in `main.py`):
  - logs any deprecated setting names (names only);
  - builds ULTRON, then starts the trading loop and the station loop.
  - **Live mode only:** downloads recent candles, warms the bots on history without trading, restores the prop account, and starts the order router. That router step closes any positions left open by the previous process.
- **Blocking work is kept off the event loop.** Claude calls, HTTP polls, replays and file writes run in worker threads with `asyncio.to_thread`. The station runs **one agent job at a time**, so its spend and side effects are easy to reason about.
- **Failure isolation.**
  - The station loop catches every exception from a tick and records it on `station.last_error`, so the station cannot stop the City.
  - Each ULTRON job has its own recovery path (`Ultron._job_failed`). When Claude is unreachable, the job waits for a back-off; any other failure skips it.
  - Known gap (audit **C-1**): nothing supervises the trading loop yet.
- **Shared state.** The station store serialises access with one re-entrant lock. The trading engine is owned by the trading loop.

## 3. AI operations workflow

### 3.1 From schedule to audit event

```mermaid
flowchart TD
    A["Scheduler tick · every 15 s<br/>run_station → Ultron.tick"] --> B["ULTRON orchestrator<br/>housekeeping: roster, treasury, stalled tasks,<br/>credit watch, proposals, daily report"]
    B --> C{"Job selection<br/>Ultron.next_job<br/>(fixed priority order)"}
    C -- "no job / AI blocked" --> Z["wait for next tick"]
    C -- "dispatch job<br/>(a QA-passed action)" --> G
    C -- "other non-AI jobs<br/>metrics · shop orders · mail · pins" --> H
    C -- "daily audit<br/>(no outside call)" --> J
    C -- "AI job<br/>routine · plan · QA · War Room · marketing · task" --> D["Agent + Brain · station/brain.py<br/>budget check before every call"]
    D --> E["Structured LLM output<br/>JSON schema per job · refusal / cut-off / bad JSON → error"]
    E --> F["Validation / QA<br/>code checks + Compliance & QA agent<br/>pass → ready · fail → one revision → rejected"]
    F --> G{"Approval or automation policy<br/>E-STOP · NEXUS_POLICY_* · daily caps"}
    G -- "policy = owner" --> W["waiting_owner<br/>owner or Jarvis OKs it"]
    W --> G
    G -- "allowed" --> H["Connector · station/connectors.py<br/>status claimed as 'sending' first<br/>idempotency key for Stripe"]
    H --> I["External service<br/>Stripe · Etsy · Printify · Meta · Pinterest · SMTP"]
    I --> J["Audit event<br/>events.jsonl (who, what, why)<br/>ledger.jsonl for money"]
    H -- "no connector" --> M["manual: owner queue with a Copy button"]
    M --> J
```

1. **Scheduler.** `run_station` calls `Ultron.tick` every 15 seconds. The tick keeps the roster and the treasury current. It catches stalled or failed tasks, watches the Claude credit balance, proposes ventures and goals, and writes the daily report.
2. **Job selection.** `Ultron.next_job` is an explicit priority list:
   1. Jobs that don't call Claude come first. Sending QA-passed actions comes first among them, then the daily audit, engagement metrics, shop orders, credit reconciliation, the outreach inbox and kit pins.
   2. AI jobs follow, and only if the Claude client exists, the monthly AI budget allows it, credits aren't exhausted and no back-off is active. In order: venture planning, QA, revisions, the War Room, Jarvis-requested routines, marketing plans, daily content, outreach, scheduled research routines, Etsy shop research, product creation and queued agent tasks. Tasks are capped per day.
3. **Agent and Brain.**
   - `Brain` wraps the Claude API: `structured()` for JSON-schema outputs, and `research()` for web search with citations.
   - Every call is checked against the budget first and charged to the treasury afterwards.
   - The agent's role, standing rules and the lessons the War Room recorded (`crew.lessons_text`) go into the system prompt.
4. **Structured output.**
   - Each job asks for a fixed JSON schema.
   - A refusal, a cut-off answer (retried once), missing text or invalid JSON raises a clear error. The job's recovery path then handles it.
5. **Validation and QA.**
   - Agents can only create *drafts*. `actions.create` stores every outbound action with status `qa`.
   - The Compliance & QA agent returns a verdict. A pass becomes `ready`; a fail becomes `revise` (once), then `rejected`.
   - Code-level rules run regardless. For outreach: no repeat contacts, no opted-out addresses, and a public inquiry page is required.
6. **Policy.** `actions.dispatch` sends only QA-passed actions, and only when all of these hold:
   - The outbound E-STOP is off.
   - The kind's policy is `auto`, or the owner has OK'd it.
   - The day's cap for that kind is not reached.
7. **Connector.**
   - The action is marked `sending` *before* the external call, so a crash can't make the loop send it twice.
   - A known connector error marks it `failed`. An unexpected error marks it `failed` with `check_before_resending`, because the side effect may have happened.
   - Stripe calls carry an idempotency key derived from the action id.
8. **Audit.**
   - Every state change goes through `Store.update`/`Store.event`, which appends to `events.jsonl` with the actor, the reason and a timestamp.
   - Money goes to `ledger.jsonl`, where each entry hashes the previous one.

### 3.2 Outbound action lifecycle

```mermaid
stateDiagram-v2
    [*] --> qa: agent drafts (actions.create)
    qa --> ready: QA pass
    qa --> revise: QA fail (first time)
    revise --> qa: author revises
    qa --> rejected: QA fail after a revision
    ready --> waiting_owner: policy = owner
    waiting_owner --> ready: owner / Jarvis OK
    ready --> sending: dispatch claims it
    sending --> sent: connector succeeded
    sending --> failed: connector error
    sending --> manual: no connector configured
    manual --> sent: owner marks it done
    failed --> qa: requeue (owner / Jarvis)
    rejected --> qa: requeue (owner / Jarvis)
    qa --> cancelled
    ready --> cancelled
    waiting_owner --> cancelled
    sent --> [*]
```

An action that is `sending` cannot be cancelled. After a restart, ULTRON recovers any action left in `sending`
and marks it for a check before it is resent.

### 3.3 Who can do what

| Actor | Can | Cannot |
|---|---|---|
| Agents (via ULTRON) | Research, plan, draft, revise, analyse; create tasks and drafts | Send anything without QA and policy; spend; book income; touch trading |
| ULTRON | Schedule jobs, retry or escalate tasks, propose ventures and funding goals, auto-launch within limits | Approve spending, move money, act on outside accounts, change orders or risk |
| Jarvis (`POST /api/jarvis/act`, token) | Run allowlisted board operations: retry or cancel tasks, edit or requeue drafts, OK social posts, run routines, convene the War Room, decide no-cost approvals | Anything about money, Stripe links, the trading desk, killing a venture, or anything needing an account (403) |
| Owner (password session) | Everything above, plus spending approvals, killing ventures, arming real orders, promoting strategies | — |

## 4. Trading flow

### 4.1 Market data to orders

```mermaid
flowchart TD
    TV["TradingView Pine alert<br/>closed 1m candle → POST /api/feed<br/>(shared secret)"] --> M
    Y["Yahoo poll · every 20 s<br/>~10 min delayed"] --> M
    M["LiveMarket · backend/live.py<br/>merges feeds, releases closed candles"] --> E
    E["Engine.tick · backend/engine.py<br/>new session · halts · news blackout"] --> B
    B["Bots · backend/bots/<br/>PROC strategy on NQ/ES structure<br/>emit trade events"] --> R
    R["Prop account rules · backend/account.py<br/>goal · cap · stop · drawdown · contracts"] --> EV["Trade events<br/>open · add · trim · close"]
    EV --> L["Paper logs<br/>paper_trades.csv · paper_days.csv"]
    EV --> AB["Account book · accounts.py<br/>each real Lucid account follows its trades"]
    EV --> N["Notifier · phone alerts"]
    EV --> S["Signals · reports · scorecard"]
    EV --> OR{"Order router · execution.py<br/>armed? fresh data? before 15:50 ET?<br/>position opened by this router?"}
    OR -- "blocked" --> BL["counted as blocked<br/>never queued"]
    OR -- "allowed" --> Q["asyncio.Queue → order worker"]
    Q --> TPW["TradersPost webhook<br/>per-account URL"]
    TPW --> TDV["Tradovate · Lucid account"]
    Q --> OL["orders.csv<br/>every order and response (redacted)"]
```

1. **Data.**
   - With a paid plan, a TradingView Pine script pushes each closed 1-minute candle to `/api/feed`. The request is authenticated with a shared secret.
   - Yahoo is polled every 20 seconds as a delayed fallback.
   - The bots read NQ/ES structure and trade the micros (MNQ/MES).
2. **Engine.** Each candle advances `Engine.tick`. A new trading day rolls the account through `end_of_day`. Account halts and news blackouts stop the bots before they act.
3. **Strategy and risk.** The bots (`bots/proc.py`) emit open, add, trim and close events. The prop account (`account.py`) enforces the firm's rules: daily goal, cap and stop, end-of-day drawdown, consistency and contract limits.
4. **Fan-out.** The same events feed:
   - the paper trade log;
   - every configured real account (`accounts.py`);
   - phone notifications;
   - the signal log, the daily report and the live-vs-replay scorecard;
   - the order router.
5. **Order router** (`TradersPostRouter.handle`). Orders go out only when every check passes:

   | Check | Rule |
   |---|---|
   | Armed | Off until the owner sends `ARM`; flatten-all also disarms |
   | Data freshness | Entries and adds are refused when prices are more than 2.5 minutes old; exits always go |
   | Session cutoff | No entries from 15:50 ET; the bots flatten by 15:55 (Tradovate's micro session ends at 16:00) |
   | Ownership | Adds and exits only for positions this router opened |

   Allowed orders go onto a queue. A worker posts them to TradersPost, retries failures and logs every attempt to `orders.csv` with the URLs masked.
6. **Restart.** `router.start()` sends exits for any position the previous process left open, because the bots restart flat.

Known gaps in this flow (audit **T-H1 to T-H7**, fixes approved) are listed in [SECURITY.md](SECURITY.md#7-trading-safeguards).

### 4.2 Changing the strategy safely

```mermaid
flowchart LR
    C["Candidate change<br/>Strategy Forge"] --> WF["Walk-forward backtest<br/>on saved real candles"]
    WF -- "beats baseline out of sample" --> SH["Shadow paper bot<br/>trades live data, no orders"]
    WF -- "fails" --> X["retired"]
    SH --> D["Trading desk (Claude)<br/>recommends"]
    D --> O{"Owner approves?"}
    O -- "yes" --> P["promoted params<br/>applied at the next session"]
    O -- "no" --> X
```

`Engine.apply_params` changes parameters only at a session boundary (`pending_params`), never in the middle of a trade.

## 5. Request path and security

```mermaid
sequenceDiagram
    participant B as Browser / caller
    participant G as PasswordGate (ASGI)
    participant H as Route handler
    participant S as Store / Engine
    B->>G: request
    G->>G: live mode without a password? → 503
    G->>G: cross-site POST or WebSocket (Origin / Sec-Fetch-Site)? → 403
    G->>G: open path (webhook, healthz, /media, /shop)? → pass (route checks its own secret)
    G->>G: session cookie (HMAC) or Basic auth? throttle 10 failures / 15 min → 429
    G->>H: authorised
    H->>H: json_body(): non-object → 400
    H->>S: domain call
    S-->>H: result or ValueError / KeyError
    H-->>B: 200 / 400 / 404 / 409, plus security headers
```

Webhooks authenticate themselves:
- **TradingView feed and signal:** a shared secret in the body.
- **Stripe:** a signature checked against the webhook secret.
- **Jarvis:** a bearer token.

Details: [SECURITY.md](SECURITY.md).

## 6. Persistence

| Data | Format | Writer | Notes |
|---|---|---|---|
| Station records (ventures, tasks, actions, approvals, agents, routines, opportunities…) | `<collection>.json` | `station/store.py` | Whole-file atomic replace (temp file, fsync, rename) |
| Audit log | `events.jsonl` | `Store.event` | Append-only; a line torn by a crash is moved aside at startup |
| Money ledger | `ledger.jsonl` | `station/economy.py` | Append-only, hash-chained; each sale booked once by reference |
| Prop account and router state | `paper_account.json`, router state | `live.py`, `execution.py` | Atomic writes |
| Trading logs | `paper_trades.csv`, `paper_days.csv`, `orders.csv` | `live.py`, `execution.py` | Append; secrets redacted |
| Candle history | `history/<SYMBOL>_1m.csv` (Yahoo and TradingView copies) | `history.py` | Merged as candles arrive; feeds the backtester and Strategy Forge |

In production all of this lives on one Render disk mounted at `/app/data`. The trade-offs and a PostgreSQL schema
for later are in [PERSISTENCE.md](PERSISTENCE.md).

## 7. Design decisions

| Decision | Why | Cost |
|---|---|---|
| One process, asyncio loops | One deploy unit, shared in-memory state, nothing else to operate | No horizontal scaling; a trading-loop crash isn't supervised yet (C-1) |
| Files, not a database | Survives restarts on one disk, easy to inspect and back up, no extra service | One writer only; queries are scans; the PostgreSQL design is ready when needed |
| LLM output is a draft, code decides | Prompts aren't a security boundary: QA, policy, caps, the E-STOP and allowlists are enforced in Python | More states to manage (section 3.2) |
| One agent job at a time | Predictable spend, simple concurrency, readable audit log | Throughput bounded by one Claude call at a time |
| Structured outputs everywhere | Every agent result is machine-checkable before it changes state | Schemas must evolve with the prompts |
| Vanilla JS frontend | No build step; the server serves files directly | Less tooling (no type checking in the browser code) |
