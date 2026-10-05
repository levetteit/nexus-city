"""Run with:  uvicorn backend.main:app --reload   then open http://localhost:8000"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import TICK_SECONDS
from .engine import Engine

engine = Engine()
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
        await broadcast({"type": "tick", "state": engine.snapshot(), "events": events})
        await asyncio.sleep(TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_city())
    yield
    task.cancel()


app = FastAPI(title="Starnet trading city", lifespan=lifespan)


@app.get("/api/state")
def state() -> dict:
    return engine.snapshot()


@app.post("/api/bots/{bot_id}/{action}")
def toggle(bot_id: str, action: str) -> dict:
    if bot_id not in engine.bots or action not in ("on", "off"):
        raise HTTPException(404)
    engine.set_enabled(bot_id, action == "on")
    return engine.bots[bot_id].snapshot(engine.market)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"type": "tick", "state": engine.snapshot(), "events": []})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="frontend")
