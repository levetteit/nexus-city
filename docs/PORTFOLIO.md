# Nexus City: what this project demonstrates

This page is for reviewers, recruiters and interviewers. Every technology and number below can be checked in this
repository. For the system design, see [ARCHITECTURE.md](ARCHITECTURE.md).

**How it was built.** Jerai Padilla built Nexus City using Claude Code as an AI pair programmer, and the git history
shows both authors. The owner:
- set the product direction, the trading rules and the safety policy;
- reviewed and merged every change;
- operates the system day to day.

In an interview, describe it that way: designing, directing, reviewing and operating an AI-assisted codebase, not
writing every line by hand.

## At a glance

| | |
|---|---|
| Backend | about 12,600 lines of Python 3.12 (FastAPI, asyncio) |
| Frontend | about 6,200 lines of vanilla JavaScript, HTML and CSS, with Three.js for the 3D world |
| Tests | 186 pytest cases (unit and integration), 76% line coverage of `backend/`, network blocked during tests |
| CI | GitHub Actions: lint, tests with coverage, secret scan over the full history, dependency audit, Docker build and smoke test |
| Deployment | Docker image on Render with a persistent disk and a password gate |
| External services | Claude API, TradersPost, TradingView, Yahoo Finance, Stripe, Etsy, Printify, Meta Graph API (Facebook/Instagram), Pinterest, SMTP/IMAP, ntfy, Web Push |

## What it demonstrates

### AI engineering
- **Structured outputs everywhere.** Every agent call asks Claude for a JSON schema (`station/brain.py`, `structured()`). Refusals, cut-off answers (retried once), empty answers and invalid JSON become clear errors that the scheduler handles.
- **Web research with citations.** It uses Claude's server-side web search tool (`Brain.research`), resuming paused turns.
- **Cost controls.**
  - A monthly AI budget is checked *before* each call, and each call is charged to a treasury afterwards.
  - Credit-balance tracking can reconcile with Anthropic's cost report.
  - After authentication or credit errors, the scheduler backs off.
- **Feedback loop.** A "War Room" review (weekly, or sooner when enough results arrive) records lessons, and agents receive those lessons in their prompts on later tasks (`crew.lessons_text`).
- **Evaluation of a strategy change before adoption.** Strategy Forge runs a walk-forward backtest, then a shadow paper bot, then an AI desk recommendation, and the owner approves last.

### Backend development
- **One process.** A FastAPI app runs three long-lived asyncio loops (trading, station, forge). Blocking work is moved to threads with `asyncio.to_thread`, so the event loop stays responsive.
- **Clear domain modules.** The prop firm rules (`account.py`), the strategy (`bots/proc.py`), the order router (`execution.py`), the scheduler (`station/ultron.py`) and the outbox (`station/actions.py`).
- **Input handling.** One JSON body reader returns 400 for malformed input instead of a 500 (`main.json_body`), and domain errors map to 404 or 409.

### API integration
- **One adapter per service** (`station/connectors.py`). Each failure becomes a `ConnectorError` with secrets masked.
- **OAuth 2.0.** Authorization-code flows with state, expiry and one-time use, plus PKCE for Etsy, and token refresh.
- **Webhooks in.**
  - Stripe, verified with an HMAC signature and timestamp tolerance.
  - TradingView candle and signal feeds, verified with a shared secret.
  - A token-protected operations API for Jarvis, the owner's outside AI assistant.
- **Idempotency.** Stripe idempotency keys, and income booked once per payment reference.

### Automation
- **ULTRON's scheduler.** It picks one job at a time from an explicit priority list, then:
  - retries or escalates stalled tasks;
  - recovers work interrupted by a restart;
  - reads replies, metrics and orders on a schedule.
- **Trading automation.** Candles go through the strategy and the prop account rules to an order router. The router enforces arming, data freshness, session cutoffs and position ownership.

### Software architecture
- **AI output is a draft; code decides.** Agents create actions with status `qa`. A QA verdict, a per-kind send policy, daily caps and an emergency stop all run in Python before a connector is called. Prompts are not the security boundary.
- **Explicit state machine** for outbound actions (qa → ready / waiting_owner → sending → sent / failed / manual). The `sending` status is claimed before the external call, so a crash cannot cause a duplicate send.
- **Separated domains.** The station can read the trading account but has no path to the order router.
- **Documented design decisions with their costs** ([ARCHITECTURE.md](ARCHITECTURE.md#7-design-decisions)).

### Testing
- **No real side effects.** A pytest fixture blocks every non-local socket connection and DNS lookup and clears proxy variables, so a missed fake fails loudly instead of trading, posting or charging.
- **Fakes** for every connector, Claude included, with the failure paths tested: refusals, HTTP errors, OAuth state attacks, duplicate webhooks, crashes mid-send.
- **Regression on real data.** Five days of recorded 1-minute candles run through the real strategy and account rules.
- **Markers.** `integration` tests the app through its HTTP API in process. `live` tests are skipped unless explicitly enabled.

### Security
- **Threat model and trust boundaries** are written down in [SECURITY.md](SECURITY.md).
- **Password gate** (`backend/security.py`):
  - an HMAC session cookie;
  - throttling: 10 failures per 15 minutes, then 429;
  - cross-site POST and WebSocket requests refused, checked with `Origin`/`Sec-Fetch-Site`;
  - live mode refuses to serve without a password;
  - security headers.
- **Secret redaction** across errors, logs, feeds and stored task errors (`backend/redact.py`).
- **Bounded agency.** The Jarvis API has an allowlist and refuses anything touching money, trading or accounts with a 403.
- **Tamper evidence.** A hash-chained money ledger and an append-only audit log.

### DevOps
- **Reproducible builds.** A lockfile generated with `uv pip compile` is installed by Docker and by CI, so what is tested is what ships.
- **CI:** gitleaks over the full git history, pip-audit on the lockfile, and a container smoke test that checks `/healthz`, the page and the API.
- **Durability.** Atomic file writes, crash-tolerant JSONL (a torn last line is moved aside), and restart recovery for actions and positions.
- **Backward-compatible rename.** `NEXUS_*` settings take priority over `STARNET_*`, with deprecation logging (names only) and a migration guide.

### Frontend development
- **A 3D world in Three.js** with no build step: buildings per bot, weather driven by market volatility, animated agents and a station.
- **Live updates over a WebSocket.** It can be installed on a phone (manifest, service worker, Web Push).
- **A hand-written canvas chart** with zoom and scroll, showing the strategy's zones and signals.

### Business-process automation
- **Venture pipeline.** Ventures move through research → validate → build → launch → operate → measure, with owner approvals, auto-launch limits (score, one a day, at most 3 live) and an automatic close after 21 days with no sale.
- **Digital products end to end.** The crew writes a product, renders it as a PDF, runs QA, then publishes it with a Stripe link, a storefront page and an Etsy listing. Downloads are served only after payment is verified.
- **Treasury.** Per-venture P&L. Only real money counts: income the owner records or a signed Stripe event, recorded payouts, and AI usage.

## Resume bullet suggestions

Pick the ones that fit the role. Each is backed by code in this repository.

1. Designed and shipped a FastAPI and asyncio platform that runs rule-based futures trading bots and a Claude-powered multi-agent operations scheduler in one process, with a Three.js 3D interface. Deployed with Docker on Render.
2. Built human-in-the-loop safeguards for LLM agents: a schema-validated output → QA → send-policy → daily-cap → emergency-stop pipeline that agents cannot bypass, plus an allowlisted operations API that refuses money, trading and account actions.
3. Integrated about 10 external APIs: Stripe (signed webhooks, idempotent writes), Etsy and Pinterest (OAuth 2.0 with PKCE and refresh), Meta Graph, Printify, TradersPost, TradingView webhooks and SMTP/IMAP. Each adapter has typed errors and secret redaction.
4. Built a pre-trade risk layer for automated order routing: explicit arming, stale-data blocks, session cutoffs, position-ownership checks, and flatten-on-restart. Strategy changes are tested walk-forward on recorded market data before shadow trading and owner approval.
5. Raised test coverage from 72% to 76% across 186 pytest cases, with a network-blocking fixture that guarantees tests have no real side effects. Set up CI with a secret scan over the full history, a dependency vulnerability audit and a container smoke test.

Bullet 5's numbers describe this project as it stands: Phase 7 raised coverage from 72% to 76%, and the full
suite now runs 186 cases (pytest, October 2026). Re-check them before using the bullet. Avoid "fully autonomous",
"production-grade" or claims of trading profit. The trading results are a 21-day backtest and ongoing paper trading.

## Technical interview talking points

**What problem does Nexus City solve?**
It is one owner's operations console for two things that need watching all the time:
- **Intraday futures trading** for a prop firm account, where breaking a rule ends the account.
- **Small online ventures run by AI agents.** The hard part isn't calling an LLM. It is keeping automated actions inside the rules (prop firm rules, platform policies, a budget) and making every action visible and reversible where possible.

**How is the agent architecture structured?**
- **One orchestrator.** ULTRON is a deterministic Python scheduler, not an LLM. Every 15 seconds it does housekeeping, then picks at most one job from a fixed priority list.
- **Agents are roles, not processes.** Each one is a system prompt plus a JSON schema that `Brain` calls.
- **Work is tracked as records:** ventures, tasks with dependencies, actions and approvals, all in a store with an audit log.
- **A recurring review.** The War Room meets weekly, or sooner once enough new results arrive. It evaluates ventures and writes lessons that later prompts include.

**What role does the LLM actually play?**
It researches, plans, drafts copy and products, reviews compliance, and recommends. It never decides on its own
that something leaves the system, and it never moves money. Code makes those decisions: the QA verdict's effect,
the policy, the caps, the emergency stop and the allowlists. LLM output is always schema-validated before it
changes state.

**How do you prevent unsafe autonomous actions?**
- **Defense in depth.** Drafts only, then QA, then a per-kind policy (`auto` or `owner`), then daily caps, then the emergency stop, then connector-level checks. Spending, killing ventures, arming orders and promoting strategies are owner-only in code.
- **An honest caveat:** the default policy is `auto` for outbound posts, a deliberate owner choice, documented in SECURITY.md along with how to require approval.

**How does state persistence work?**
- **Records:** JSON documents per collection, written atomically (temp file, fsync, rename).
- **Append-only JSONL** for the audit log and the hash-chained ledger. A torn last line from a crash is moved aside at startup.
- **One lock** guards the store. Everything lives on one mounted disk.

**How are integrations implemented?**
- **Small, dependency-free HTTP adapters** in `connectors.py`. Each normalizes errors into `ConnectorError`, with secrets masked.
- **OAuth flows** store pending state with an expiry and allow one use.
- **Webhooks in** are verified: Stripe with an HMAC signature, TradingView with a shared secret, Jarvis with a bearer token.
- **Writes that could duplicate** carry idempotency keys.

**How is external execution protected?**
- **Trading:** orders go out only when every check passes: armed with an explicit `ARM`, prices under 2.5 minutes old, before 15:50 ET, and for positions this router opened. Exits can only reduce a position, and a restart flattens anything left open.
- **Station:** the `sending` claim before each call, plus recovery after a restart, prevents duplicate posts and charges.

**How do tests avoid real external side effects?**
- **A network guard.** An autouse fixture replaces `socket.connect` and `getaddrinfo` to refuse non-local hosts, and clears proxy variables. It caught a real gap: a local proxy had been letting traffic through.
- **Fakes.** Connectors and Claude are faked per test.
- **Isolated data.** Data directories are temporary.
- **Explicit opt-in** for live tests (`NEXUS_LIVE_TESTS=1`); CI never sets it.

**What would you change to scale the system?**
1. Move the store to PostgreSQL; the schema is already designed in PERSISTENCE.md.
2. Supervise the trading loop and make health checks detect a stall (audit item C-1).
3. Split the station worker from the web process, behind a job queue, so several agent jobs can run at once.
4. Add structured logging and metrics.
5. Move the frontend to TypeScript for type checking.

**Why JSON persistence now instead of PostgreSQL?**
One owner, one process, and data small enough to scan. Files on one disk mean no extra service to run, pay for or
secure, and they are easy to inspect and back up. The costs are understood: one writer, scan queries, no
transactions across files. The migration path is written down, so the change can happen when it's needed.

**What engineering tradeoffs were made?**
- **One agent job at a time:** predictable cost and a readable audit log, but limited throughput.
- **One process:** simple operations, but no isolation between the trading and AI loops.
- **Vanilla JavaScript:** no build step, but no type safety.
- **Auto-send by default:** the ventures actually move, but more weight falls on QA and caps.
- **Strategy work that resists overfitting:** walk-forward tests and shadow trading slow down changes, but that's the point.
