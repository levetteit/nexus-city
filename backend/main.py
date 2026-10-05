"""Run with:  uvicorn backend.main:app --reload   then open http://localhost:8000

STARNET_MODE=live runs the city on real candles with paper trading (see live.py).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import TICK_SECONDS
from .bots.pointer import SIGNALS
from .engine import Engine

MODE = os.getenv("STARNET_MODE", "sim")
POLL_SECONDS = 20
engine = Engine() if MODE != "live" else None   # live mode builds its engine at startup (needs a download)
clients: set[WebSocket] = set()


async def broadcast(msg: dict) -> None:
    dead = []
    for ws in clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def run_city() -> None:
    while True:
        events = engine.tick()
        await broadcast({"type": "tick", "state": state(), "events": events})
        await asyncio.sleep(TICK_SECONDS)


async def run_live() -> None:
    """Poll for new real candles and step the bots through each one."""
    global engine
    from . import live
    market = await asyncio.to_thread(live.LiveMarket)
    engine = Engine(market=market, account=live.load_account())
    while market.i + 1 < market.warm_until:   # read history, don't trade it
        engine.tick(trade=False)
    last_poll = 0.0
    while True:
        loop = asyncio.get_running_loop()
        if loop.time() - last_poll >= POLL_SECONDS:
            last_poll = loop.time()
            try:
                await asyncio.to_thread(market.poll)
            except Exception as exc:   # network hiccup: try again next poll
                print(f"live poll failed: {exc}")
        events = []
        while market.has_next():
            new = engine.tick()
            live.record(engine, new)
            events += new
        await broadcast({"type": "tick", "state": state(), "events": events})
        await asyncio.sleep(1)


def state() -> dict:
    snap = engine.snapshot()
    snap["mode"] = MODE
    if MODE == "live":
        snap["delay_min"] = round(engine.market.delay_minutes, 1)
    return snap


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_live() if MODE == "live" else run_city())
    yield
    task.cancel()


app = FastAPI(title="Starnet trading city", lifespan=lifespan)


@app.get("/api/state")
def get_state() -> dict:
    if engine is None:
        raise HTTPException(503, "loading live market data…")
    return state()


@app.post("/api/bots/{bot_id}/{action}")
def toggle(bot_id: str, action: str) -> dict:
    if bot_id not in engine.bots or action not in ("on", "off"):
        raise HTTPException(404)
    engine.set_enabled(bot_id, action == "on")
    return engine.bots[bot_id].snapshot(engine.market)


@app.post("/api/account/reset")
def reset_account() -> dict:
    """Start a fresh evaluation (e.g. after a failed one)."""
    engine.reset_account()
    return engine.account.snapshot()


def normalize_symbol(ticker: str) -> str:
    """'CME_MINI:MNQ1!' / 'MNQZ2026' / 'CME_MINI:MES1!' -> 'MNQ' / 'MNQ' / 'MES'."""
    t = ticker.split(":")[-1].upper()
    t = re.sub(r"\d+!$", "", t)                      # continuous futures: MNQ1!
    m = re.match(r"^(MNQ|MES|M2K|MYM|NQ|ES)[FGHJKMNQUVXZ]\d{2,4}$", t)  # dated futures: MNQZ2026
    return m.group(1) if m else t


@app.post("/api/tradingview")
async def tradingview(request: Request) -> dict:
    """TradingView alert webhook. Put a JSON message in the alert, for example:

    {"secret": "<STARNET_WEBHOOK_SECRET>", "ticker": "{{ticker}}", "signal": "bullish_pointer",
     "price": {{close}}, "high": {{high}}, "low": {{low}}, "tf": "{{interval}}"}
    """
    secret = os.getenv("STARNET_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "set STARNET_WEBHOOK_SECRET to enable the TradingView webhook")
    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise HTTPException(400, "alert message must be JSON")
    if not isinstance(payload, dict) or not hmac.compare_digest(str(payload.get("secret", "")), secret):
        raise HTTPException(401, "bad secret")
    signal = str(payload.get("signal", "")).lower()
    if signal not in SIGNALS:
        raise HTTPException(400, f"signal must be one of {sorted(SIGNALS)}")
    payload["signal"] = signal
    if "ticker" in payload:
        payload["symbol"] = normalize_symbol(str(payload["ticker"]))
    return {"ok": True, "symbol": payload.get("symbol"), "results": engine.signal(payload)}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    if engine is not None:
        await ws.send_json({"type": "tick", "state": state(), "events": []})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="frontend")
