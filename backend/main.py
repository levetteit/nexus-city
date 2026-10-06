"""Run with:  uvicorn backend.main:app --reload   then open http://localhost:8000

STARNET_MODE=live runs the city on real candles with paper trading (see live.py).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import TICK_SECONDS
from .bots.pointer import SIGNALS
from .backtest import ET
from .engine import Engine

MODE = os.getenv("STARNET_MODE", "sim")
POLL_SECONDS = 20
engine = Engine() if MODE != "live" else None   # live mode builds its engine at startup (needs a download)
router = None     # real-order router (live mode only), see execution.py
notifier = None   # phone notifications (live mode only), see notify.py
scorecard = None  # live vs backtest checks (live mode only), see scorecard.py
reports = None    # end-of-day reports (live mode only), see report.py
history = None    # saved 1m candles for future backtests (live mode only), see history.py
desk = None       # the bots' evening meeting / morning briefing on Claude (live mode only), see desk.py
book = None       # your Lucid accounts, each tracked through the trades (live mode only), see accounts.py
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
    global engine, router, notifier
    global scorecard, reports, history, desk, book
    from . import execution, live, news, notify
    from .report import DayReports
    from .scorecard import Scorecard
    notifier = notify.Notifier(live.DATA_DIR)
    from .history import History
    history = History(live.DATA_DIR)
    asyncio.create_task(asyncio.to_thread(history.save, True))   # keep the last 29 days before Yahoo drops them
    calendar = news.NewsCalendar(data_dir=live.DATA_DIR)
    await asyncio.to_thread(calendar.refresh, True)
    market = await asyncio.to_thread(live.LiveMarket)
    engine = Engine(market=market, account=live.load_account(), news=calendar)
    live.load_careers(engine)
    router = execution.TradersPostRouter(live.DATA_DIR)
    from .accounts import AccountBook
    book = AccountBook(live.DATA_DIR)
    router.account_urls = book.urls
    router.url_names = lambda: {a.webhook: a.name for a in book.accounts if a.webhook}
    router.start()
    while market.i + 1 < market.warm_until:   # read history, don't trade it
        engine.tick(trade=False)
    scorecard = Scorecard(live.DATA_DIR, calendar)
    scorecard.start_day(engine, partial=True)   # we may have come up mid-day
    reports = DayReports(live.DATA_DIR)
    reports.start_day(engine, partial=True)
    from .desk import TradingDesk
    desk = TradingDesk(live.DATA_DIR)
    if desk.enabled:
        engine.desk = desk
    morning_done = ""
    last_poll = 0.0
    last_order_error = ""
    while True:
        loop = asyncio.get_running_loop()
        if loop.time() - last_poll >= POLL_SECONDS:
            last_poll = loop.time()
            try:
                await asyncio.to_thread(calendar.refresh)   # no-op unless the cached week is stale
                await asyncio.to_thread(market.poll)
            except Exception as exc:   # network hiccup: try again next poll
                print(f"live poll failed: {exc}")
        market.release()   # candles pushed by the real-time TradingView feed
        et = datetime.now(timezone.utc).astimezone(ET)
        if desk.enabled and et.weekday() < 5 and (8, 40) <= (et.hour, et.minute) < (9, 25) and morning_done != et.date().isoformat():
            morning_done = et.date().isoformat()
            asyncio.create_task(run_desk("morning"))
        events = []
        while market.has_next():
            new = engine.tick()
            live.record(engine, new)
            alerts = book.observe(engine, new)                  # each Lucid account follows the trades it's in
            router.handle(engine, new, market.delay_minutes, book)   # real orders, if armed
            notifier.handle(engine, new + alerts, real=router.armed)   # buzz your phone
            new += alerts
            report = reports.observe(engine, new)
            finished = scorecard.observe(engine, new)
            if report:   # a trading day just ended: replay it, compare with paper trading, send the report
                reports.save(report)
                asyncio.create_task(check_day(finished, report))
                asyncio.create_task(asyncio.to_thread(history.save))   # add the day that just ended
            events += new
        if router.last_error and router.last_error != last_order_error:   # a real order failed: tell you now
            notifier.send("⚠️ Real order failed", router.last_error, "error")
        last_order_error = router.last_error
        await broadcast({"type": "tick", "state": state(), "events": events})
        await asyncio.sleep(1)


async def check_day(day: dict | None, report: dict) -> None:
    from .scorecard import BASELINE
    try:
        if day:
            report["check"] = await asyncio.to_thread(scorecard.replay, day)
            reports.save(report)
    except Exception as exc:   # e.g. Yahoo down: send the report without the check
        print(f"replay check failed: {exc}")
    title, body = reports.message(report, scorecard.edge(engine.account), BASELINE)
    notifier.send(title, body, "report", url=f"/?report={report['day']}")
    if desk.enabled:
        await run_desk("evening", report)


async def run_desk(kind: str, report: dict | None = None) -> dict | None:
    """Hold the evening meeting or the morning briefing (Claude, in a thread), then tell the city and your phone."""
    from .desk import context
    if desk.running:
        return None
    desk.running = True
    try:
        recent = [reports.get(r["day"]) for r in reports.list(6)]
        recent = [{"day": r["day"], "pnl": r["pnl"], "trades": r["trades"], "halts": r["halts"], "news": r["news"],
                   "check": r.get("check")} for r in recent if r and (not report or r["day"] != report["day"])]
        past = [{"day": c["day"], "mode": c["desk"], "cost_or_saved": c["desk_effect"]}
                for c in scorecard.checks if c.get("desk")][-10:]
        ctx = context(engine, report, recent, scorecard.status(engine.account), engine.news, desk.lessons, past)
        out = await asyncio.to_thread(desk.evening if kind == "evening" else desk.morning, ctx)
    except Exception as exc:
        desk.last_error = desk.last_error or str(exc)[:200]
        print(f"desk {kind} failed: {exc}")
        return None
    finally:
        desk.running = False
    desk.last_error = ""
    mode = out["next_mode"] if kind == "evening" else out["mode"]
    why = out["next_mode_why"] if kind == "evening" else out["mode_why"]
    if kind == "evening" and report:
        report["desk"] = {"summary": out["desk_summary"], "journals": out["journals"], "mode": mode, "why": why}
        reports.save(report)
    session = "overnight + London" if kind == "evening" else "New York"
    engine.events.append({"type": "desk_meeting", "kind": kind, "mode": mode, "why": why, "session": session})
    head = out["desk_summary"] if kind == "evening" else out["briefing"]
    notifier.send(f"🧠 {'Desk meeting' if kind == 'evening' else 'Morning briefing'} · {session}: {mode.replace('_', ' ').upper()}",
                  f"{why}\n{head[:220]}", "desk", url="/?desk=1")
    return out

def state() -> dict:
    snap = engine.snapshot()
    snap["mode"] = MODE
    if MODE == "live":
        snap["delay_min"] = round(engine.market.delay_minutes, 1)
        snap["feed"] = engine.market.feed
        if router:
            snap["execution"] = router.status(engine.market.delay_minutes)
        if history:
            snap["history"] = history.status()
        if desk:
            snap["desk"] = desk.status()
        if book:
            st = book.status()
            snap["accounts"] = {k: st[k] for k in ("count", "payouts_ready", "total_balance", "paid_out")}
        if scorecard:
            snap["scorecard"] = scorecard.status(engine.account)
        if notifier:
            snap["push"] = {"web_push": notifier.web_push, "devices": len(notifier.subs), "ntfy": bool(notifier.ntfy_topic)}
    return snap


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_live() if MODE == "live" else run_city())
    yield
    task.cancel()


app = FastAPI(title="Starnet trading city", lifespan=lifespan)

PASSWORD = os.getenv("STARNET_PASSWORD")   # set this whenever the city is reachable from the internet
OPEN_PATHS = ("/healthz", "/api/tradingview", "/api/feed")   # health checks, and webhooks (they have their own secret)


class PasswordGate:
    """HTTP Basic auth for every page, API call and the WebSocket when STARNET_PASSWORD is set.
    A successful login also sets a cookie, so the browser's WebSocket gets in too."""

    def __init__(self, app) -> None:
        self.app = app
        self.token = hashlib.sha256(f"starnet:{PASSWORD}".encode()).hexdigest() if PASSWORD else None

    def _authorized(self, headers: dict) -> tuple[bool, bool]:
        """(allowed, set_cookie)"""
        cookie = headers.get(b"cookie", b"").decode()
        if f"starnet_auth={self.token}" in cookie:
            return True, False
        auth = headers.get(b"authorization", b"").decode()
        if auth.lower().startswith("basic "):
            try:
                _, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
            except Exception:
                return False, False
            if hmac.compare_digest(pw, PASSWORD):
                return True, True
        return False, False

    async def __call__(self, scope, receive, send):
        if not self.token or scope["type"] not in ("http", "websocket") or scope["path"] in OPEN_PATHS:
            return await self.app(scope, receive, send)
        ok, set_cookie = self._authorized(dict(scope["headers"]))
        if not ok:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 4401})
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"www-authenticate", b'Basic realm="Starnet City"'),
                                    (b"content-type", b"text/plain")]})
            return await send({"type": "http.response.body", "body": b"password required"})
        if not set_cookie:
            return await self.app(scope, receive, send)

        async def send_with_cookie(msg):
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": list(msg.get("headers", [])) + [
                    (b"set-cookie", f"starnet_auth={self.token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000".encode())]}
            await send(msg)
        return await self.app(scope, receive, send_with_cookie)


app.add_middleware(PasswordGate)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "ready": engine is not None}


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
    if scorecard:
        scorecard.toggled()
    return engine.bots[bot_id].snapshot(engine.market)


@app.get("/api/desk")
def desk_info() -> dict:
    if desk is None:
        raise HTTPException(503, "the trading desk only runs in live mode")
    return {**desk.status(), "lessons_list": desk.lessons, "days": desk.days(7)}


@app.post("/api/desk/meeting")
async def desk_meeting(request: Request) -> dict:
    """Hold a meeting now (`{"kind": "morning"}` or `"evening"`)."""
    if desk is None or not desk.enabled:
        raise HTTPException(503, "add ANTHROPIC_API_KEY to turn the trading desk on")
    kind = (await request.json()).get("kind", "morning")
    if kind not in ("morning", "evening") or desk.running:
        raise HTTPException(409, "a meeting is already running" if desk.running else "kind must be morning or evening")
    last = reports.get(reports.list(1)[0]["day"]) if kind == "evening" and reports.list(1) else None
    asyncio.create_task(run_desk(kind, last))
    return {"started": kind}


@app.post("/api/desk/act")
async def desk_act(request: Request) -> dict:
    """Let the desk's risk mode affect trading (true) or keep it advisory (false)."""
    if desk is None:
        raise HTTPException(503, "the trading desk only runs in live mode")
    desk.set_act(bool((await request.json()).get("act")))
    return desk.status()


@app.get("/api/history")
def history_status() -> dict:
    if history is None:
        raise HTTPException(503, "candle history is only saved in live mode")
    return history.status()


@app.get("/api/history/{symbol}.csv")
def history_csv(symbol: str):
    if history is None or symbol not in history.status()["symbols"]:
        raise HTTPException(404, "no saved candles for that symbol")
    return FileResponse(history.path(symbol), media_type="text/csv", filename=f"{symbol}_1m.csv")


@app.get("/api/reports")
def list_reports() -> list:
    return reports.list() if reports else []


@app.get("/api/reports/{day}")
def get_report(day: str) -> dict:
    r = reports.get(day) if reports else None
    if r is None:
        raise HTTPException(404, "no report for that day")
    return r


@app.get("/api/scorecard")
def get_scorecard() -> dict:
    if scorecard is None:
        raise HTTPException(503, "the live vs backtest check only runs in live mode")
    return {**scorecard.status(engine.account), "days": scorecard.checks}


@app.get("/api/bots/{bot_id}/chart")
def bot_chart(bot_id: str, tf: int = 1, count: int = 180) -> dict:
    if engine is None or bot_id not in engine.bots or tf not in (1, 2, 3, 4, 5, 6, 15):
        raise HTTPException(404)
    return engine.bots[bot_id].chart(engine.market, tf, max(30, min(count, 400)))


@app.get("/api/bots/{bot_id}/room")
def bot_room(bot_id: str) -> dict:
    if engine is None or bot_id not in engine.bots:
        raise HTTPException(404)
    return engine.bots[bot_id].room(engine.market)


FULL_SIZE = {"NQ": "MNQ", "ES": "MES", "RTY": "M2K", "YM": "MYM"}   # full-size charts feed their micro


@app.post("/api/feed")
async def feed(request: Request) -> dict:
    """Real-time 1m candles from the Starnet feed script on TradingView (tradingview/starnet_feed.pine)."""
    secret = os.getenv("STARNET_FEED_SECRET") or os.getenv("STARNET_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "set STARNET_FEED_SECRET to enable the real-time feed")
    try:
        p = json.loads(await request.body())
    except ValueError:
        raise HTTPException(400, "body must be JSON")
    if not isinstance(p, dict) or not hmac.compare_digest(str(p.get("secret", "")), secret):
        raise HTTPException(401, "bad secret")
    if engine is None or MODE != "live":
        raise HTTPException(503, "live mode is still starting")
    sym = normalize_symbol(str(p.get("ticker", "")))
    sym = FULL_SIZE.get(sym, sym)
    try:
        ts = int(float(p["t"]))
        ts = ts // 1000 if ts > 10**12 else ts
        o, h, l, c = (float(p[k]) for k in ("o", "h", "l", "c"))
    except (KeyError, ValueError, TypeError):
        raise HTTPException(400, "need t, o, h, l, c")
    engine.market.push(sym, ts, o, h, l, c)
    return {"ok": True, "symbol": sym}


def _router():
    if router is None:
        raise HTTPException(503, "real execution is only available in live mode")
    return router


@app.get("/api/execution")
def execution_status() -> dict:
    return _router().status(engine.market.delay_minutes)


@app.post("/api/execution")
async def execution_arm(request: Request) -> dict:
    """Arm or disarm real orders. Arming needs {"armed": true, "confirm": "ARM"}."""
    r = _router()
    body = json.loads(await request.body() or b"{}")
    on = bool(body.get("armed"))
    if on and body.get("confirm") != "ARM":
        raise HTTPException(400, 'to arm real orders send {"armed": true, "confirm": "ARM"}')
    try:
        r.arm(on)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return r.status(engine.market.delay_minutes)


@app.post("/api/execution/flatten")
def execution_flatten() -> dict:
    """Kill switch: exit every real position, close the paper ones, disarm."""
    r = _router()
    for bot in engine.bots.values():
        if bot.position:
            bot._close("flatten all", engine.market)
    r.flatten_all([b.cfg.underlying for b in engine.bots.values()])
    return r.status(engine.market.delay_minutes)


def _notifier():
    if notifier is None:
        raise HTTPException(503, "notifications are only available in live mode")
    return notifier


@app.get("/api/push")
def push_status() -> dict:
    return _notifier().status()


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request) -> dict:
    n = _notifier()
    try:
        n.subscribe(json.loads(await request.body()))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    n.send("🔔 Starnet alerts are on", "You'll get a buzz every time a bot enters, adds, or exits a trade.", "setup")
    return n.status()


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request) -> dict:
    n = _notifier()
    n.unsubscribe(json.loads(await request.body()).get("endpoint", ""))
    return n.status()


@app.post("/api/push/test")
def push_test() -> dict:
    n = _notifier()
    n.send("💰 Test: MNQ OG closed +$420", "pointer against (PROC) · today +$420", "test")
    return n.status()


def _book():
    if book is None:
        raise HTTPException(503, "accounts are only tracked in live mode")
    return book


@app.get("/api/accounts")
def accounts_list() -> dict:
    return _book().status()


@app.post("/api/accounts")
async def accounts_add(request: Request) -> dict:
    """Add a Lucid account: name, phase, balance, mll, payouts, cycle_days, optional webhook."""
    b = await request.json()
    try:
        _book().add(str(b.get("name", "")), b["phase"], float(b["balance"]), float(b["mll"]),
                    int(b.get("payouts") or 0), int(b.get("cycle_days") or 0), str(b.get("webhook") or ""))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return book.status()


@app.post("/api/accounts/{acc_id}/{action}")
async def accounts_action(acc_id: str, action: str, request: Request) -> dict:
    """sync (phase, balance, mll, payouts, cycle_days) · payout (amount) · webhook (url) · remove"""
    b = await request.json() if action != "remove" else {}
    try:
        acc = _book().get(acc_id)
        if action == "sync":
            acc.account.sync(b["phase"], float(b["balance"]), float(b["mll"]), int(b.get("payouts") or 0), int(b.get("cycle_days") or 0))
        elif action == "payout":
            acc.account.take_payout(float(b["amount"]))
        elif action == "webhook":
            book.set_webhook(acc_id, str(b.get("url") or ""))
        elif action == "remove":
            book.remove(acc_id)
        else:
            raise HTTPException(404)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    book.save()
    return book.status()


@app.post("/api/account/payout")
async def account_payout(request: Request) -> dict:
    """Record a payout you took at the firm (`{"amount": 1000}`)."""
    try:
        engine.account.take_payout(float((await request.json())["amount"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    _save_account()
    return engine.account.snapshot()


@app.post("/api/account/sync")
async def account_sync(request: Request) -> dict:
    """Match the paper account to the real one: phase, balance, MLL, payouts taken, cycle days."""
    b = await request.json()
    try:
        engine.account.sync(b["phase"], float(b["balance"]), float(b["mll"]), int(b.get("payouts", 0)), int(b.get("cycle_days", 0)))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    _save_account()
    return engine.account.snapshot()


def _save_account() -> None:
    if MODE == "live":
        from . import live
        live.save_account(engine.account)


@app.post("/api/account/reset")
def reset_account() -> dict:
    """Start a fresh evaluation (e.g. after a failed one)."""
    engine.reset_account()
    return engine.account.snapshot()


def normalize_symbol(ticker: str) -> str:
    """'CME_MINI:MNQ1!' / 'MNQZ2026' / 'CME_MINI:MES1!' -> 'MNQ' / 'MNQ' / 'MES'."""
    t = ticker.split(":")[-1].upper()
    t = re.sub(r"\d+!$", "", t)                      # continuous futures: MNQ1!
    m = re.match(r"^(MNQ|MES|M2K|MYM|NQ|ES|RTY|YM)[FGHJKMNQUVXZ]\d{2,4}$", t)  # dated futures: MNQZ2026
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
