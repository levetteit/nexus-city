# Developing Nexus City

## Requirements

- **Python 3.12.** This is what the Docker image and CI run, and it's pinned in `.python-version`. The code also
  runs on 3.11 and 3.13.
- No database, Node or build step. The frontend is plain ES modules served by the app. Three.js loads from a CDN.

## Set up

```bash
git clone https://github.com/levetteit/nexus-city.git
cd nexus-city
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.lock -r requirements-dev.txt
```

## Run

The simulated market needs no keys, accounts or network:

```bash
uvicorn backend.main:app --reload            # http://localhost:8000
```

With settings from a file:

```bash
cp .env.example .env    # then edit .env; it is git-ignored
uvicorn backend.main:app --env-file .env
```

`.env.example` documents every setting. In live mode (`NEXUS_MODE=live`) the app reads real candles and needs
`NEXUS_PASSWORD`. Real orders still stay off until you arm them in the app.

## Test

```bash
python -m pytest -q                     # the whole suite, about 30-80 s
python -m pytest -q -m "not integration"   # unit tests only
python -m pytest -q --cov=backend --cov-report=term-missing   # with coverage
python -m pyflakes backend              # static checks
```

The suite has three kinds of tests:

| Kind | Marker | What it covers |
|---|---|---|
| Unit | none | One module at a time: strategy, account rules, router, station, connectors (faked), persistence, security helpers |
| Integration | `@pytest.mark.integration` | The FastAPI app end to end through its HTTP API, in process: auth gate, webhooks, arming, OAuth callback |
| Live | `@pytest.mark.live` | Reaches a real external service. **Skipped** unless `NEXUS_LIVE_TESTS=1`, and never run in CI. There are none today |

**Tests never touch the outside world.**
- `tests/conftest.py` blocks every network connection and DNS lookup except to this machine, and clears proxy
  variables, so a test that forgets to fake a connector fails loudly instead of posting, emailing, trading or paying.
- Each connector (Stripe, Meta, Etsy, Printify, Pinterest, SMTP/IMAP, TradersPost, Claude) is replaced with a
  fake inside the test that needs it.
- App files go to a temporary directory.

**Skipped tests.**
- `test_twenty_one_day_baseline` needs 21 days of candle files in `data/` and is skipped without them.
- `test_web_push_drops_phones_that_unsubscribed` needs `py-vapid` from `requirements.lock`.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and on every pull request. It has four jobs:

| Job | What it checks |
|---|---|
| `lint` | Every Python file byte-compiles; `pyflakes` finds no undefined names, unused imports or shadowing |
| `pytest` | The full suite on Python 3.12 with the exact locked dependencies, plus a coverage summary |
| `security` | `gitleaks` over the **whole git history** (config: `.gitleaks.toml`); `pip-audit` of `requirements.lock` against known vulnerabilities |
| `docker` | Builds the production image, starts it in simulation mode, and checks `/healthz`, the page and the API |

Before you push, you can run the same checks locally:

```bash
python -m compileall -q backend tests kits && python -m pyflakes backend tests && python -m pytest -q
```

## Dependencies

| File | What it is |
|---|---|
| `requirements.txt` | Direct runtime dependencies, as version ranges (tested minimum to next major) |
| `requirements.lock` | Every package with an exact version, resolved for Python 3.12 on Linux. **Docker and CI install this file**, so what is tested is what ships |
| `requirements-dev.txt` | Test and lint tools on top of the runtime: pytest, pytest-cov, httpx (TestClient), pyflakes |
| `kits/requirements.txt` | Only for rebuilding a kit's PDFs and images from `kits/<kit>/source` (reportlab, fontTools, Pillow) |

**Changing a dependency.**
1. Edit `requirements.txt`.
2. Regenerate the lock, which needs [uv](https://docs.astral.sh/uv/):

   ```bash
   uv pip compile requirements.txt --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
       -o requirements.lock --no-header --annotation-style line
   ```

3. Run the tests against the new lock and commit both files.

To pick up security fixes within the allowed ranges, run the same command with `--upgrade`.

## Project layout

```text
backend/            FastAPI app (main.py), trading engine, bots, order router, accounts, Strategy Forge
backend/station/    the AI operations station: ULTRON, agents, connectors, store, treasury
frontend/           the 3D city, the station board, rooms and charts (vanilla JS + Three.js)
tests/              pytest suite (fixtures/ holds 5 days of real 1-minute candles)
kits/               owner-made products the station can publish
tradingview/        Pine script that streams 1-minute candles to the app
docs/               the deep documentation: city, trading, live trading, station, operations, security, persistence, audit
```
