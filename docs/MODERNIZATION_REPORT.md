# Modernization report

The record of the 14-phase modernization of Nexus City (formerly StarNet), 7–8 October 2026.

- **Baseline:** commit `794c5b3`, the last commit before Phase 1.
- **Final state:** `main` after Phase 13 (`deb1e77`) plus this report.

Each phase was one reviewed pull request (#47 to #59 and this one), merged by the owner.

## 1. Baseline state

| Area | Baseline (`794c5b3`) |
|---|---|
| Tests | 117 passed, 1 skipped (118 collected, 13 files); **69%** line coverage of `backend/` (measured on the baseline commit for this report) |
| Network isolation in tests | None. A test that missed a mock could reach a real host |
| CI | One workflow: install `requirements.txt` (unpinned), run pytest |
| Dependencies | No lockfile; versions resolved at build time |
| Security | The password gate had no cross-site protection; live mode ran open without a password; the cookie was an unsalted hash of the password; no login throttle |
| Secrets | No redaction in errors, logs or feeds; no `.env.example` |
| Persistence | Plain truncating writes for treasury, counters and trading state; a torn last JSONL line broke reads; read-modify-write of contacts without a lock |
| Outbound safety | An action that failed with an unexpected error stayed `ready` and was retried every tick (possible duplicate sends); kit pins bypassed the E-STOP |
| Naming | StarNet and Nexus City mixed in code, settings and UI |
| Documentation | One 1,069-line README (an operator manual); no architecture, security or persistence documentation |

The full baseline audit, with every finding, is in [ENGINEERING_AUDIT.md](ENGINEERING_AUDIT.md).

## 2. Modifications by phase

| Phase | PR | What changed |
|---|---|---|
| 1. Audit | #47 | `docs/ENGINEERING_AUDIT.md`: baseline, findings C-1 … L-14, technical debt, and the owner's decisions |
| 2. Naming | #48 | StarNet → Nexus City. `NEXUS_*` settings take priority and `STARNET_*` still works; deprecated names are logged at startup (names only); `docs/MIGRATION_FROM_STARNET.md` |
| 3. Configuration and secrets | #49 | `backend/env.py` (one settings reader), `backend/redact.py` (secret masking in errors, logs, feed and router), `.env.example` |
| 4. Security | #50 | Cross-site POST/WebSocket refused; live mode refuses to serve without a password (503); HMAC session cookie with a login throttle; security headers; outbound actions claimed as `sending` before the call; restart recovery; Stripe idempotency keys; E-STOP gates kit pins; `docs/SECURITY.md` |
| 5. Persistence | #51 | `backend/persist.py` (atomic writes, torn-line repair), incremental audit-log reads, `Store.update_doc`, payout references, a `StationStore` interface; `docs/PERSISTENCE.md` with a PostgreSQL design |
| 6. Dependencies | #52 | Bounded direct dependencies, `requirements.lock` (uv, Python 3.12, Linux) used by Docker and CI, `requirements-dev.txt`, `kits/requirements.txt`, `.python-version` |
| 7. Testing | #53 | Global network guard in `conftest.py`, `integration`/`live` markers, tests for env, secrets, security, persistence, dependencies, reliability and reporting; `docs/DEVELOPMENT.md` |
| 8. CI/CD | #54 | `.github/workflows/ci.yml`: lint (compileall and pyflakes), pytest with coverage, security (gitleaks over the full history, pip-audit), docker (build and smoke test); pyflakes cleanup |
| 9. Code quality | #55 | `json_body()` (malformed bodies are a 400, not a 500); ULTRON's 147-line `run_job` split into run, do and recover; redacted task errors; Node 24 CI actions |
| 10. README | #56 | README rewritten as an overview; the operator manual moved word for word into `docs/CITY.md`, `TRADING.md`, `LIVE_TRADING.md`, `STATION.md` and `OPERATIONS.md` |
| 11. Architecture | #57 | `docs/ARCHITECTURE.md`: layers, runtime model, AI workflow, action state machine, trading flow, request path, persistence, design decisions (7 Mermaid diagrams) |
| 12. Portfolio | #58 | `docs/PORTFOLIO.md`: verified capabilities, resume bullets, interview talking points |
| 13. Recruiter view | #59 | README hero image, at-a-glance table, badges, navigation; four new screenshots from the local simulation |
| 14. Final validation | this PR | This report; the final checks below |

## 3. Files

Totals since the baseline: **91 files changed, 5,179 insertions, 1,623 deletions** (before this report).

**Added (35):**
- **Configuration:** `.env.example`, `.gitleaks.toml`, `.python-version`, `pytest.ini`, `requirements.lock`, `requirements-dev.txt`, `kits/requirements.txt`
- **CI:** `.github/workflows/ci.yml`
- **Backend:** `backend/env.py`, `backend/persist.py`, `backend/redact.py`, `backend/security.py`
- **Docs:** `docs/ARCHITECTURE.md`, `CITY.md`, `DEVELOPMENT.md`, `ENGINEERING_AUDIT.md`, `LIVE_TRADING.md`, `MIGRATION_FROM_STARNET.md`, `OPERATIONS.md`, `PERSISTENCE.md`, `PORTFOLIO.md`, `SECURITY.md`, `STATION.md`, `TRADING.md`; `docs/screenshots/` (4 images)
- **Tests:** `tests/test_dependencies.py`, `test_env.py`, `test_persistence.py`, `test_reliability.py`, `test_reporting.py`, `test_secrets.py`, `test_security.py`

**Removed or renamed:**
- `.github/workflows/tests.yml` was replaced by `ci.yml`.
- `tradingview/starnet_feed.pine` was renamed to `tradingview/nexus_city_feed.pine`.

**Modified (54):**
- **Backend:** most `backend/` and `backend/station/` modules, for the settings reader, redaction, atomic writes, the security gate and the outbound-safety changes.
- **Frontend:** files that changed for naming and escaping.
- **Deployment and repo:** `Dockerfile`, `render.yaml`, `.dockerignore`, `.gitignore`, `requirements.txt`, `README.md`.
- **Tests:** five existing test files.

## 4. Security improvements

| Finding | Fix |
|---|---|
| S-H1: cross-site requests could act on the app | `Origin` / `Sec-Fetch-Site` check on POST and WebSocket (403) |
| S-H2: live mode ran open without a password | 503 until `NEXUS_PASSWORD` is set |
| S-H3: weak session cookie | HMAC with a persisted random key, constant-time check, `Secure` on HTTPS, 10 failures per 15 minutes then 429 |
| Clickjacking and MIME sniffing | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff`, referrer policy |
| Secrets in errors and logs | `redact()` on connector errors, router errors, the feed log, brain/station errors and stored task errors |
| A-H1: possible duplicate outbound sends | `sending` claimed before the call, unexpected errors marked `failed` with "check before resending", restart recovery, Stripe idempotency keys |
| A-H4: kit pins bypassed the E-STOP | E-STOP checked for pins |
| M-1: feed accepted future or non-finite candles | Rejected |
| M-2: unescaped third-party text in `innerHTML` | Escaped |
| L-1: malformed secrets caused 500s | `secret_matches` never raises; bad Stripe timestamps are rejected cleanly |
| Malformed request bodies caused 500s | `json_body()` returns 400 |
| Secret leakage through git | gitleaks over the full history in CI (clean); `.gitleaks.toml` allowlists only the two test files with fake keys |
| Vulnerable dependencies | pip-audit on the shipped lockfile in CI (no known vulnerabilities) |
| Tests reaching real services | Global network guard (sockets and DNS to non-local hosts refused, proxy variables cleared) |

## 5. Tests added

- **New test files (7):**
  - `test_env.py`: settings fallback and deprecation.
  - `test_secrets.py`: redaction.
  - `test_security.py`: gate, cookie, throttle, cross-site, headers, feed validation, and outbound safety (no resend after an unexpected error, restart mid-send flagged, cancel refused mid-send, E-STOP stops kit pins).
  - `test_persistence.py`: atomic writes, torn lines, concurrency, payout references.
  - `test_dependencies.py`: the lockfile matches the direct dependencies.
  - `test_reliability.py`: Claude refusals and cut-offs, connector errors, OAuth state, duplicate webhooks, the order sender, arming, webhook validation.
  - `test_reporting.py`: daily reports, scorecard, notifications.
- **Added to existing files:** failed-task redaction in `test_station.py`, malformed request bodies in `test_api.py`, and fixes to `test_accounts.py` and `test_forge.py`.
- **Infrastructure:** the network guard fixture, `pytest.ini` markers (`integration`, `live`), and a temporary data directory for every run.

## 6. Final validation (8 October 2026)

| # | Check | Result |
|---|---|---|
| 1 | Full test suite (Python 3.12, locked dependencies) | **186 passed, 1 skipped**; **76%** coverage of `backend/` (baseline 117 passed, 69%). The skipped test needs the 21-day data set, which is not committed |
| 2 | Git diff inspection | Reviewed the diff since `794c5b3`, summarized in sections 2–3. No stray files; `__pycache__`, `.coverage` and `.pytest_cache` are ignored and untracked |
| 3 | Accidental secrets | gitleaks 8.28.0 over all 98 commits: **no leaks found**. A working-directory scan flagged 4 matches, all in git-ignored `__pycache__` bytecode of the fake keys in `tests/test_secrets.py`; none are tracked |
| 4 | Legacy branding | No "StarNet" in the frontend. Remaining mentions are intentional: the `STARNET_*` fallback (`env.py`, `security.py`, `redact.py`), old Stripe metadata readers, a one-time venture rename, the kept Render service and disk names in `render.yaml`/`Dockerfile`, and the migration docs |
| 5 | Docker build | **Not run locally**: this environment has no Docker daemon. Verified by CI's `docker` job on every phase PR, including #59: the image builds, starts in simulation mode, and `/healthz`, `/` and `/api/state` respond |
| 6 | Application startup | Started with uvicorn from the locked dependencies in simulation mode, with a temporary data folder. `/healthz` returned `{"ok":true,"ready":true,"problems":[]}`; `/`, `/api/state` and `/station.html` returned 200; a cross-site POST returned 403; a malformed body returned 400; security headers were present. In a separate in-process check, live mode without a password returned 503 |
| 7 | README and doc links | Every relative link and image in README and `docs/` resolves; in-page anchors match the headings |
| 8 | Mermaid diagrams | All 11 diagrams (README, ARCHITECTURE, ENGINEERING_AUDIT, PERSISTENCE, SECURITY) render with mermaid-cli 11.4.2 and contain no syntax errors |
| 9 | GitHub Actions configuration | `actionlint` 1.7.7: no findings. CI green on every phase PR |
| 10 | No production or external actions during testing | See below |

**External actions during the work.**
- **Tests:** they ran behind the network guard, and no service keys were set. No trade, post, email, charge or listing was made.
- **Screenshots:** the Phase 13 screenshots came from a local simulation with a temporary data folder and no service keys.
- **Production:** the only request to production was one read-only `GET /api/state` at the start of Phase 9. The password gate refused it.
- **Deploys:** each merge to `main` redeployed the live app through Render's auto-deploy, which restarts the bots (finding O-H2). The owner merged each phase while the bots were flat.

## 7. Remaining technical debt

**Trading reliability.** These fixes are approved by the owner but not yet implemented. They change trading code, so they were kept out of this documentation-and-safety work.

| ID | Issue |
|---|---|
| C-1 | Nothing supervises the trading loop; an exception stops it while `/healthz` stays green |
| T-H1 | Exits are not sent while disarmed (approved behavior change) |
| T-H2 | Order retries on timeouts can duplicate entries |
| T-H3 | The order worker has no exception guard |
| T-H4 | Time-based flattening depends on candle arrival (approved: wall-clock flatten) |
| T-H5 | Synchronous handlers change the engine from worker threads |
| T-H6 | The restart flatten waits for the Yahoo download |
| T-H7 | A restart clears account halts (approved: persist halts, roll the day during warmup) |
| M-4, M-11 | Book/router divergence after a skipped open; one-symbol feed freezes the partner symbol (approved) |

**Still open, not yet scheduled:**

| ID | Issue |
|---|---|
| M-3 | A TradingView alert's `price` can re-anchor the live mark |
| M-6 | ULTRON's config is mutated from several threads (writes are atomic, mutation is not locked) |
| M-8 | Anthropic 429/529 are treated as job failures instead of a back-off |
| M-12 | Order posting is serial, so one hung webhook delays other accounts |
| M-10 | Station policies default to `auto`. **Not approved for change by the owner**; documented in SECURITY.md |
| L-2 to L-9, L-11, L-13, L-14 | Low-severity hygiene items listed in the audit (for example, no Subresource Integrity on CDN scripts, OAuth tokens in plaintext on the private disk, AI cost booked at one model's prices) |
| O-H2 | Every push to `main` deploys and restarts the bots; Render build filters would skip docs-only changes |
| Persistence | JSON files: one writer, whole-file rewrites, unbounded log growth (PostgreSQL design ready in PERSISTENCE.md) |
| Frontend | No type checking or automated browser tests |
| Code size | Five trading-path functions over 60 lines stay as they are until the reliability fixes, which bring their own tests |

> **Update (trading-reliability work, after this report):** C-1, T-H2, T-H3, T-H5 and T-H6 are fixed, with 24
> regression tests in `tests/test_trading_reliability.py`. Section 7 describes the state at the end of the
> modernization. A second change fixed T-H1, T-H4, T-H7, M-4 and M-11 (owner-approved behaviour changes), with 16
> tests in `tests/test_trading_behaviour.py`. Every approved trading finding is now fixed.

## 8. Recommended future work

1. **Trading reliability**, in this order:
   - the non-behavioral fixes C-1, T-H2, T-H3, T-H5 and T-H6, each with tests first;
   - then the approved behavior changes T-H1, T-H4, T-H7, M-4 and M-11, in a separate, clearly labeled PR merged while flat.
2. **Render build filters** (O-H2), so docs and tests don't restart the bots.
3. **Operations:**
   - daily disk snapshots on Render;
   - an external uptime monitor on `/healthz`;
   - reset the expired Facebook Page token;
   - finish the Pinterest app review.
4. **M-8, M-6 and M-12:** small and contained.
5. **Security:** a Content-Security-Policy with Subresource Integrity once inline scripts move to files, and encryption of OAuth tokens at rest.
6. **PostgreSQL** behind the existing `StationStore` interface, when the data outgrows one disk.

## 9. Breaking changes

None for a deployment that sets no new variables. Behavior visible to users or integrations:

| Change | Effect | Action |
|---|---|---|
| Session cookie is now HMAC-based | Every browser logs in once more | None |
| Live mode without a password returns 503 | A live deployment without `NEXUS_PASSWORD`/`STARNET_PASSWORD` stops serving | Set a password (the Render blueprint already requires one) |
| Cross-site POST/WebSocket refused | A third-party page can no longer act on the app | None for the app's own pages |
| Malformed JSON bodies return 400 instead of 500 | Clearer errors for clients | None |
| TradingView Pine script renamed | The old file name is gone | Existing alerts keep working; re-add the script only if you reinstall it |

## 10. Migration instructions

1. **Settings:**
   - Rename `STARNET_*` variables to `NEXUS_*` at your convenience. Both work, and `NEXUS_*` wins when both are set.
   - Startup logs list the names still to rename (names only).
   - Details: [MIGRATION_FROM_STARNET.md](MIGRATION_FROM_STARNET.md).
2. **Render:** keep the service name `starnet-city` and the disk `starnet-data` (the owner's decision), so the URL and data are unchanged.
3. **Local development:** `pip install -r requirements.lock -r requirements-dev.txt`, then copy `.env.example` to `.env` and run with `--env-file .env`.
4. **Changing dependencies:** edit `requirements.txt` and regenerate `requirements.lock` with the `uv pip compile` command in [DEVELOPMENT.md](DEVELOPMENT.md).
