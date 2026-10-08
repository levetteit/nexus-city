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
python -m pytest -q            # about 30 s; external services are faked, nothing is sent anywhere
python -m pyflakes backend     # static checks
```

The tests never call paid APIs, post, email, trade or charge:
- every connector is replaced with a fake in the test;
- app files go to a temporary directory (`tests/conftest.py`).

One test (`test_twenty_one_day_baseline`) needs 21 days of candle files in `data/` and is skipped without them.

## Dependencies

| File | What it is |
|---|---|
| `requirements.txt` | Direct runtime dependencies, as version ranges (tested minimum to next major) |
| `requirements.lock` | Every package with an exact version, resolved for Python 3.12 on Linux. **Docker and CI install this file**, so what is tested is what ships |
| `requirements-dev.txt` | Test and lint tools on top of the runtime: pytest, httpx (TestClient), pyflakes |
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
docs/               architecture, security, persistence, migration and audit documents
```
