"""Run with:  uvicorn backend.main:app --reload   then open http://localhost:8000

STARNET_MODE=live runs the city on real candles with paper trading (see live.py).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import html
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
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
watchdog = None   # pushes when the feed or data stops (live mode only), see watchdog.py
signals = None    # the bots' PROCs for you to check against your indicator (live mode only), see signals.py
station = None    # ULTRON and the Space Station (both modes), see station/
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
    global scorecard, reports, history, desk, book, watchdog, signals
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
    closed = router.start()
    if closed:   # we restarted while real positions were open: they were just closed
        notifier.send("🔄 Starnet restarted with real positions open",
                      f"Sent exits for {', '.join(closed)}: the bots restart flat. Check your accounts.", "watchdog")
    from .watchdog import Watchdog
    watchdog = Watchdog(live.DATA_DIR)
    while market.i + 1 < market.warm_until:   # read history, don't trade it
        engine.tick(trade=False)
    scorecard = Scorecard(live.DATA_DIR, calendar)
    scorecard.start_day(engine, partial=True)   # we may have come up mid-day
    reports = DayReports(live.DATA_DIR)
    reports.start_day(engine, partial=True)
    from .signals import SignalLog
    signals = SignalLog(live.DATA_DIR)
    signals.start_day(engine)
    from .desk import TradingDesk
    desk = TradingDesk(live.DATA_DIR)
    if desk.enabled:
        engine.desk = desk
        # the desk's Claude calls are real money: the city's AI cost, and they come off the credits count
        desk.on_usage = lambda usage: station and station.treasury.charge_ai(usage, "DESK", "V-001", "trading desk", unit="city")
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
            signals.observe(engine, new)
            report = reports.observe(engine, new)
            finished = scorecard.observe(engine, new)
            if report:   # a trading day just ended: replay it, compare with paper trading, send the report
                reports.save(report)
                asyncio.create_task(check_day(finished, report))
                asyncio.create_task(asyncio.to_thread(history.save))   # add the day that just ended
            events += new
        for title, body in watchdog.check(market, router, desk):
            notifier.send(title, body, "watchdog")
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
    if station:
        cr = station.credits or {}
        snap["station"] = {"coordinating": station.busy, "approvals": len(station.store.find("approvals", status="pending")),
                           "owner_tasks": len(station.store.find("tasks", status="waiting_owner")),
                           "credits": {"state": cr.get("state", "unknown"), "remaining": cr.get("remaining")},
                           "flights": station.treasury.flights()}
    if MODE == "live":
        snap["delay_min"] = round(engine.market.delay_minutes, 1)
        snap["feed"] = engine.market.feed
        snap["feed_symbols"] = sorted(engine.market.realtime_symbols)   # symbols with a live TradingView alert
        snap["feed_last"] = FEED_LOG[-1] if FEED_LOG else None
        if router:
            snap["execution"] = router.status(engine.market.delay_minutes)
        if history:
            snap["history"] = history.status()
        if desk:
            snap["desk"] = desk.status()
        if watchdog:
            snap["watchdog"] = watchdog.status()
        if book:
            st = book.status()
            snap["accounts"] = {k: st[k] for k in ("count", "payouts_ready", "total_balance", "paid_out")}
        if scorecard:
            snap["scorecard"] = scorecard.status(engine.account)
        if notifier:
            snap["push"] = {"web_push": notifier.web_push, "devices": len(notifier.subs), "ntfy": bool(notifier.ntfy_topic)}
    return snap


async def run_station() -> None:
    """ULTRON's loop: housekeeping every 15 s, and one research/agent job at a time in a thread."""
    while True:
        try:
            job = station.tick(engine, real_account=MODE == "live")
            if MODE == "live":
                _scale_plan()   # keeps the next-evaluation goal in step with the accounts and the treasury
            if job:
                await asyncio.to_thread(station.run_job, job)
        except Exception as exc:   # the station must never take the city down
            station.last_error = str(exc)[:200]
            print(f"station tick failed: {exc}")
        await asyncio.sleep(15)


def _station_notify(title: str, body: str) -> None:
    if notifier:
        notifier.send(title, body, "station", url="/station.html")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global station
    from .station.ultron import Ultron
    station = Ultron(os.getenv("STARNET_DATA_DIR", "data"), notify=_station_notify)
    task = asyncio.create_task(run_live() if MODE == "live" else run_city())
    station_task = asyncio.create_task(run_station())
    yield
    task.cancel()
    station_task.cancel()


app = FastAPI(title="Starnet trading city", lifespan=lifespan)

PASSWORD = os.getenv("STARNET_PASSWORD")   # set this whenever the city is reachable from the internet
OPEN_PATHS = ("/healthz", "/api/tradingview", "/api/feed", "/api/station/stripe/webhook", "/api/jarvis/brief")   # health checks, and webhooks (they have their own secret)


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
        if (not self.token or scope["type"] not in ("http", "websocket") or scope["path"] in OPEN_PATHS
                or scope["path"].startswith("/media/")   # post images: Instagram fetches them itself
                or scope["path"] == "/shop" or scope["path"].startswith("/shop/")):   # the storefront is for the public
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


class FreshAssets:
    """Tell browsers to re-check the app's files on every load (a cheap ETag check), so a deploy
    shows up the next time the app opens instead of whenever the phone's cache decides."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)

        async def send_fresh(msg):
            if msg["type"] == "http.response.start":
                headers = [(k, v) for k, v in msg.get("headers", []) if k.lower() != b"cache-control"]
                msg = {**msg, "headers": headers + [(b"cache-control", b"no-cache")]}
            await send(msg)
        return await self.app(scope, receive, send_fresh)


app.add_middleware(PasswordGate)
app.add_middleware(FreshAssets)


@app.get("/healthz")
def healthz() -> dict:
    """Always 200 while the server runs (Render restarts it otherwise); `problems` lists what the watchdog sees."""
    return {"ok": True, "ready": engine is not None, "problems": watchdog.status()["problems"] if watchdog else []}


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


def _signals():
    if signals is None:
        raise HTTPException(503, "the signal check only runs in live mode")
    return signals


@app.get("/api/signals")
def signals_days() -> dict:
    s = _signals()
    return {"days": s.days(), "stats": s.stats()}


@app.get("/api/signals/{day}")
def signals_day(day: str) -> dict:
    doc = _signals().get(day)
    if doc is None:
        raise HTTPException(404, "no signals for that day")
    return doc


@app.post("/api/signals/{day}/{action}")
async def signals_action(day: str, action: str, request: Request) -> dict:
    """vote: {id, vote: yes|no|"", note} · missed: {clock "HH:MM", tf, side, note}"""
    b = await request.json()
    try:
        if action == "vote":
            return _signals().vote(day, str(b["id"]), str(b.get("vote", "")), str(b.get("note", "")))
        if action == "missed":
            return _signals().add_missed(day, str(b["clock"]), int(b["tf"]), str(b["side"]), str(b.get("note", "")))
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    raise HTTPException(404)


@app.get("/api/history")
def history_status() -> dict:
    if history is None:
        raise HTTPException(503, "candle history is only saved in live mode")
    return history.status()


@app.get("/api/history/tradingview/{symbol}.csv")
def history_tv_csv(symbol: str):
    if history is None or symbol not in history.status()["tradingview"]:
        raise HTTPException(404, "no TradingView candles saved for that symbol yet")
    return FileResponse(history.tv_path(symbol), media_type="text/csv", filename=f"{symbol}_tradingview_1m.csv")


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


FEED_LOG: list[dict] = []   # the last few TradingView feed webhooks and what happened to them


def _feed_note(ok: bool, reason: str, ticker: str = "") -> None:
    from datetime import datetime, timezone
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": ok, "reason": reason, "ticker": ticker}
    if not ok and (not FEED_LOG or FEED_LOG[-1]["reason"] != reason):   # shows in Render → Logs
        print(f"feed webhook rejected ({ticker or '?'}): {reason}")
    FEED_LOG.append(entry)
    del FEED_LOG[:-20]


@app.post("/api/feed")
async def feed(request: Request) -> dict:
    """Real-time 1m candles from the Starnet feed script on TradingView (tradingview/starnet_feed.pine)."""
    secret = os.getenv("STARNET_FEED_SECRET") or os.getenv("STARNET_WEBHOOK_SECRET")
    raw = await request.body()
    try:
        p = json.loads(raw)
    except ValueError:
        _feed_note(False, f"not JSON (starts with {raw[:30]!r}): the alert message must be left empty")
        raise HTTPException(400, "body must be JSON")
    ticker = str(p.get("ticker", "")) if isinstance(p, dict) else ""
    if not secret:
        _feed_note(False, "STARNET_FEED_SECRET is not set on the server", ticker)
        raise HTTPException(503, "set STARNET_FEED_SECRET to enable the real-time feed")
    if not isinstance(p, dict) or not hmac.compare_digest(str(p.get("secret", "")), secret):
        got = str(p.get("secret", "")) if isinstance(p, dict) else ""
        hint = "empty: set the secret in the indicator, then create the alert again" if not got else \
            f"doesn't match ({len(got)} characters sent, {len(secret)} expected)"
        _feed_note(False, f"wrong feed secret: {hint}", ticker)
        raise HTTPException(401, "bad secret")
    if engine is None or MODE != "live":
        _feed_note(False, "server still starting", ticker)
        raise HTTPException(503, "live mode is still starting")
    sym = normalize_symbol(ticker)
    sym = FULL_SIZE.get(sym, sym)
    try:
        ts = int(float(p["t"]))
        ts = ts // 1000 if ts > 10**12 else ts
        o, h, l, c = (float(p[k]) for k in ("o", "h", "l", "c"))
    except (KeyError, ValueError, TypeError):
        _feed_note(False, "missing t/o/h/l/c: use the Starnet feed script as is", ticker)
        raise HTTPException(400, "need t, o, h, l, c")
    if sym not in engine.market.underlyings:
        _feed_note(False, f"unknown symbol {ticker!r}: use the MNQ1! and MES1! charts", ticker)
        raise HTTPException(400, f"unknown symbol {ticker}")
    engine.market.push(sym, ts, o, h, l, c)
    if history:   # keep TradingView's own candles for future backtests (Yahoo's copy differs)
        try:
            vol = float(p["v"]) if p.get("v") not in (None, "", "NaN") else None
        except (TypeError, ValueError):
            vol = None
        try:
            history.record_feed(sym, ts, o, h, l, c, vol)
        except OSError as exc:   # a full disk must never stop the feed
            history.last_error = f"tradingview candles: {exc}"[:200]
    _feed_note(True, "ok", sym)
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


def _scale_plan() -> dict:
    """The Lucid scale plan (scale.py): the 👥 accounts, or the main account while the book is empty."""
    from . import scale
    if book and book.accounts:
        accounts = book.status()["accounts"]
    else:
        accounts = [{"id": "main", "name": "Main account", **engine.account.snapshot()}]
    tre = station.treasury if station else None
    cfg = (tre.cfg.get("scale") if tre else None) or {}
    edge = scorecard.edge(engine.account) if scorecard else None
    p = scale.plan(accounts, tre.summary() if tre else None, cfg, edge, datetime.now(ET).date())
    if tre and MODE == "live":   # simulated accounts never ask for real money
        tre.set_eval_goal(scale.eval_goal(cfg, p))
    p["mode"] = MODE
    return p


@app.get("/api/scale")
def scale_plan() -> dict:
    return _scale_plan()


@app.post("/api/scale")
async def scale_set(request: Request) -> dict:
    """Your numbers for the plan: {"eval_price": 99, "max_accounts": 5} (the price Lucid charges you, your limit)."""
    if not station:
        raise HTTPException(503, "the station isn't running")
    b = await request.json()
    try:
        station.treasury.set_scale(None if b.get("eval_price") is None else float(b["eval_price"]),
                                   None if b.get("max_accounts") is None else int(b["max_accounts"]))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return _scale_plan()


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


# ---------------------------------------------------------------- the Space Station (ULTRON)
def _station():
    if station is None:
        raise HTTPException(503, "the station is starting")
    return station


@app.get("/api/station")
def station_overview() -> dict:
    """Everything the Command Board shows: mission, ventures, agents, approvals, queue, treasury, feed."""
    return _station().overview(engine)


@app.get("/api/station/events")
def station_events(limit: int = 100) -> list:
    return _station().store.events(min(limit, 1000))


@app.get("/api/station/reports")
def station_reports() -> list:
    """ULTRON's daily reports to Jarvis."""
    return _station().reports()


@app.get("/api/station/routine-runs")
def station_routine_runs() -> list:
    st = _station()
    return [st.store.load_doc(n) for n in st.store.list_docs("routine-", 15)]


# Registered before /api/station/{collection}/{rid}, which would otherwise answer it with a 404.
@app.get("/api/station/connect/{service}")
def station_connect(service: str):
    """The owner presses Connect: off to Etsy or Pinterest to allow access, then back to the callback."""
    from .station import connectors
    if service not in ("etsy", "pinterest"):
        raise HTTPException(404)
    try:
        return RedirectResponse(connectors.oauth_start(service))
    except connectors.ConnectorError as exc:   # the button opens this in a browser tab: say what to fix, plainly
        return HTMLResponse(f"<!doctype html><meta name=viewport content='width=device-width'><body style='font:15px system-ui;"
                            f"max-width:640px;margin:40px auto;padding:0 16px;line-height:1.5'><h3>{service.title()} isn't ready to "
                            f"connect</h3><p>{html.escape(str(exc))}</p><p><a href='/station.html#/marketing'>Back to the board</a></p>",
                            status_code=400)


@app.get("/api/station/scans/{rid}.csv")
def station_scan_csv(rid: str):
    """The full table of an Etsy API scan (etsyscan.py)."""
    st = _station()
    path = os.path.join(st.store.dir, "scans", f"{os.path.basename(rid)}.csv")
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="text/csv", filename=f"etsy_scan_{os.path.basename(rid)}.csv")


@app.get("/api/station/tasks/{rid}/scan-terms")
def station_scan_terms(rid: str) -> dict:
    from .station import connectors
    return {"terms": _station().scan_terms(rid), "etsy": connectors.etsy_app()}


@app.post("/api/station/tasks/{rid}/etsy-scan")
async def station_etsy_scan(rid: str, request: Request) -> dict:
    """Do an owner's Etsy scan task through the Etsy API: {"terms": "phrase | 20\nphrase | 5"}. Runs in the background."""
    from .station import connectors, etsyscan
    st = _station()
    t = st.store.get("tasks", rid)
    if not t or t.get("kind") != "owner":
        raise HTTPException(404)
    if t["status"] == "done":
        raise HTTPException(409, "already done")
    if (t.get("scan") or {}).get("state") == "running":
        raise HTTPException(409, "a scan is already running")
    if not connectors.etsy_app():
        raise HTTPException(400, "set ETSY_KEYSTRING and ETSY_SHARED_SECRET on the server first")
    terms = etsyscan.parse_terms(str((await request.json()).get("terms", "")))
    if not terms:
        raise HTTPException(400, "give at least one search phrase")

    async def run():
        try:
            await asyncio.to_thread(st.etsy_scan, rid, terms)
        except Exception as exc:   # recorded on the task; the station carries on
            print(f"etsy scan {rid} failed: {exc}")
    asyncio.create_task(run())
    return {"started": True, "terms": terms, "listings": sum(n for _, n in terms)}


@app.get("/api/station/{collection}/{rid}")
def station_record(collection: str, rid: str) -> dict:
    st = _station()
    if collection not in ("ventures", "agents", "tasks", "approvals", "opportunities", "missions", "routines", "actions", "leads"):
        raise HTTPException(404)
    rec = st.store.get(collection, rid)
    if not rec:
        raise HTTPException(404)
    if collection == "ventures":
        rec["pnl"] = st.treasury.pnl("venture", rid)
        rec["health"] = st.health(rec)
        rec["task_list"] = st.store.find("tasks", venture=rid)
        if rid != "V-001":
            from .station import results
            rec["results"] = results.summary(st.store, rid, 30)
    if collection == "agents":
        rec["pnl"] = st.treasury.pnl("agent", rid)
        rec["task_list"] = st.store.find("tasks", assigned_agent=rid)
    return rec


@app.post("/api/station/approvals/{rid}")
async def station_decide(rid: str, request: Request) -> dict:
    """The owner's decision: `{"decision": "approve" | "reject" | "changes", "note": "..."}`."""
    b = await request.json()
    try:
        return _station().decide(rid, b.get("decision", ""), str(b.get("note", ""))[:500])
    except KeyError:
        raise HTTPException(404)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/station/opportunities/{rid}/{action}")
def station_opportunity(rid: str, action: str) -> dict:
    """Promote an opportunity into a venture (the owner's approval), or dismiss it."""
    st = _station()
    try:
        if action == "promote":
            return st.promote(rid)
        if action == "dismiss":
            if not st.store.get("opportunities", rid):
                raise KeyError(rid)
            return st.store.update("opportunities", rid, {"status": "dismissed"}, "owner", "dismissed by the owner",
                                   kind="opportunity.dismissed")
    except KeyError:
        raise HTTPException(404)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    raise HTTPException(404)


@app.post("/api/station/tasks/{rid}/done")
async def station_task_done(rid: str, request: Request) -> dict:
    """Tick off an owner task (`{"note": "made the Fiverr account"}`)."""
    try:
        note = (await request.json()).get("note", "")
    except Exception:
        note = ""
    try:
        return _station().owner_done(rid, str(note)[:500])
    except KeyError:
        raise HTTPException(404)
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/station/money")
async def station_money(request: Request) -> dict:
    """Record real money: `{"kind": "income"|"expense", "amount": 25, "unit": "station"|"city", "note": "...", "venture": "V-002"}`."""
    b = await request.json()
    try:
        return _station().record(b.get("kind", ""), float(b.get("amount", 0)), b.get("unit", "station"),
                                 str(b.get("note", ""))[:300], b.get("venture") or None)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/station/credits")
async def station_credits(request: Request) -> dict:
    """You added Claude credits in the Anthropic Console: `{"amount": 20, "note": "..."}`. Returns the new count."""
    from .station import credits
    b = await request.json()
    st = _station()
    try:
        credits.add(st.store, float(b.get("amount", 0)), str(b.get("note", "")))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return credits.summary(st.store, st.treasury)


@app.post("/api/station/stripe/webhook")
async def station_stripe_webhook(request: Request) -> dict:
    """Stripe → paid checkouts book themselves into the treasury. Verified by the webhook's signing secret."""
    from .station import connectors
    body = await request.body()
    try:
        event = connectors.stripe_verify(body, request.headers.get("stripe-signature", ""))
    except connectors.ConnectorError as exc:
        raise HTTPException(400, str(exc))
    if event.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        sale = _station().treasury.book_stripe_sale(event["data"]["object"])
        if sale:
            _station_notify("💵 Stripe sale", f"${sale['amount']:,.2f}" + (f" · {sale['venture']}" if sale.get("venture") else ""))
    return {"ok": True}


# ---------------------------------------------------------------- the storefront (public) and Connect (Etsy, Pinterest)
@app.get("/shop", response_class=HTMLResponse)
def storefront() -> str:
    from .station import digital
    return digital.page_index(_station().store)


@app.get("/shop/privacy", response_class=HTMLResponse)
def storefront_privacy() -> str:
    from .station import digital
    return digital.page_privacy()


@app.get("/shop/{slug}", response_class=HTMLResponse)
def storefront_product(slug: str) -> str:
    from .station import digital
    p = digital.find(_station().store, slug)
    if not p:
        raise HTTPException(404)
    return digital.page_product(p)


@app.get("/shop/{slug}/thanks", response_class=HTMLResponse)
def storefront_thanks(slug: str, session_id: str = "") -> str:
    """Stripe sends the buyer here. The download appears only for a paid session of this product's link."""
    from .station import digital
    st = _station()
    p = digital.find(st.store, slug)
    if not p:
        raise HTTPException(404)
    sess = digital.verify_purchase(st.store, p, session_id)
    if sess and not sess.get("cached"):
        sale = st.treasury.book_stripe_sale(sess)   # the webhook books it too; each sale is booked once
        if sale:
            _station_notify("💵 Storefront sale", f"{p['title']} · ${sale['amount']:,.2f}")
    return digital.page_thanks(p, session_id, bool(sess))


@app.get("/shop/{slug}/download")
def storefront_download(slug: str, session_id: str = ""):
    from .station import digital
    st = _station()
    p = digital.find(st.store, slug)
    if not p or not digital.verify_purchase(st.store, p, session_id):
        raise HTTPException(403, "this download needs a completed purchase")
    path = digital.pdf_path(os.getenv("STARNET_DATA_DIR", "data"), p["pdf"])
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf", filename=f"{p['slug']}.pdf")


@app.get("/api/station/connect/{service}/callback", response_class=HTMLResponse)
def station_connect_callback(service: str, code: str = "", state: str = "", error: str = "") -> str:
    from .station import connectors
    if service not in ("etsy", "pinterest"):
        raise HTTPException(404)
    if error:
        return f"<p>{service.title()} wasn't connected: {html.escape(error)}. <a href='/station.html#/marketing'>Back</a></p>"
    try:
        connectors.oauth_finish(service, code, state)
    except connectors.ConnectorError as exc:
        return f"<p>{service.title()} wasn't connected: {html.escape(str(exc))}. <a href='/station.html#/marketing'>Back</a></p>"
    _station().store.event("connector.connected", "owner", f"{service.title()} connected")
    return RedirectResponse(f"/station.html#/marketing")


@app.post("/api/station/actions/{rid}/{what}")
async def station_action(rid: str, what: str, request: Request) -> dict:
    """Your outbox: `done` (you posted/sent it by hand), `send` (OK an owner-policy item), `cancel`, `result` (how it went)."""
    from .station import actions
    st = _station()
    a = st.store.get("actions", rid)
    if not a:
        raise HTTPException(404)
    try:
        note = str((await request.json()).get("note", ""))[:500]
    except Exception:
        note = ""
    try:
        if what == "done":
            return actions.owner_done(st.store, rid, note)
        if what == "send":
            if a["status"] != "waiting_owner":
                raise ValueError(f"it's {a['status']}")
            return st.store.update("actions", rid, {"owner_ok": True, "status": "ready"}, "owner", "owner OK'd sending it", kind="action.owner_ok")
        if what == "cancel":
            if a["status"] == "sent":
                raise ValueError("already sent")
            return st.store.update("actions", rid, {"status": "cancelled"}, "owner", f"owner cancelled it {note}".strip(), kind="action.cancelled")
        if what == "result":
            st.store.event("action.result", "owner", f"{a['kind']} result: {note}", ref=a.get("venture"))
            return st.store.update("actions", rid, {"result": {**(a.get("result") or {}), "note": note}}, "owner", "result recorded")
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc))
    raise HTTPException(404)


@app.post("/api/station/outbound")
async def station_outbound(request: Request) -> dict:
    """The Station's E-STOP: `{"on": false}` stops every outgoing post, email and Stripe change at once."""
    st = _station()
    on = bool((await request.json()).get("on"))
    st.cfg["outbound"] = on
    st._save_cfg()
    st.store.event("station.outbound", "owner", "outbound ON: QA-passed work goes out" if on else "OUTBOUND STOPPED by the owner",
                   severity="INFO" if on else "WARNING")
    return {"outbound": on}


@app.post("/api/station/warroom")
def station_warroom() -> dict:
    """Convene the War Room now instead of waiting for Sunday or enough new results."""
    st = _station()
    if not st.brain.enabled:
        raise HTTPException(503, "add ANTHROPIC_API_KEY to run the War Room")
    st.cfg["warroom_now"] = True
    st._save_cfg()
    return {"queued": True}


@app.get("/api/station/finance")
def station_finance(month: str | None = None) -> dict:
    from .station import connectors, finance
    st = _station()
    audits = st.store.list_docs("audit-", 1)
    return {"statement": finance.statement(st.treasury, month), "audit": st.store.load_doc(audits[0]) if audits else None,
            "chain": st.treasury.verify_chain(), "connectors": connectors.status()}


@app.post("/api/station/feedback")
async def station_feedback(request: Request) -> dict:
    """Tell the station what you think about anything (`{"ref": "V-002", "note": "nobody clicks these"}`). The War Room reads it."""
    b = await request.json()
    note = str(b.get("note", "")).strip()[:1000]
    if not note:
        raise HTTPException(400, "note is empty")
    return _station().store.event("owner.feedback", "owner", note, ref=str(b.get("ref") or "")[:40] or None)


@app.get("/media/{name}")
def station_media(name: str):
    """A post's image card or a product design. Names are 128-bit random, so they're unguessable; nothing else is served here."""
    from .station import media
    path = media.path_for(os.getenv("STARNET_DATA_DIR", "data"), name)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png" if path.endswith(".png") else "image/jpeg")


@app.post("/api/station/ventures/{rid}/outreach")
async def station_venture_outreach(rid: str, request: Request) -> dict:
    """Let the Outreach Agent contact businesses for this venture (`{"on": true}`). Off for every venture by default."""
    st = _station()
    if not st.store.get("ventures", rid):
        raise HTTPException(404)
    on = bool((await request.json()).get("on"))
    return st.store.update("ventures", rid, {"outreach_allowed": on}, "owner", f"outreach {'allowed' if on else 'off'} for {rid}",
                           kind="venture.outreach_allowed")


@app.get("/api/jarvis/brief")
def jarvis_brief(request: Request) -> dict:
    """Read-only briefing for Jarvis's morning check-in. Its own token (STARNET_JARVIS_TOKEN), sent as a Bearer header;
    it can read ULTRON's report and the board's summary, and nothing else. Off (404) until the token is set."""
    token = os.getenv("STARNET_JARVIS_TOKEN", "")
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(404)
    if len(token) < 24 or not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401)
    st = _station()
    o = st.overview(engine)
    reports = st.reports(1)
    return {"report": reports[0] if reports else None, "now": o["now"], "coordinating": o["coordinating"],
            "mission": o["mission"], "treasury": {k: o["treasury"][k] for k in ("pool", "runway_months", "city", "station", "ai", "goals")},
            "ventures": [{k: v.get(k) for k in ("id", "name", "stage", "health", "pnl", "tasks", "results", "next_action")} for v in o["ventures"]],
            "waiting_for_owner": [a["action"] for a in o["approvals"]] + [t["title"] for t in o["owner_tasks"]]
                                 + [f"post by hand: {a['payload'].get('platform')}" for a in o["outbox"]["manual"]],
            "outbound": o["outbound"], "connectors": o["connectors"], "alerts": [e["summary"] for e in o["alerts"]],
            "warroom": {k: (o["warroom"] or {}).get(k) for k in ("at", "summary", "stop_doing", "start_doing")},
            "leads_7d": sum(1 for l in o["leads"] if l["created_at"] >= (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()),
            "credits": {k: o["credits"][k] for k in ("state", "remaining", "added", "used", "today", "per_day_7d", "days_left")},
            "city": _city_brief(),
            "error": o["error"]}


def _city_brief() -> dict:
    """The trading city for Jarvis: price feed, real-order router, the account. Never webhook URLs."""
    out: dict = {"mode": MODE}
    if engine is None:
        return out
    a = engine.account.snapshot()
    out["account"] = {k: a.get(k) for k in ("firm", "phase", "balance", "profit", "target", "day_pnl", "daily_stop", "halted",
                                            "open_micros", "days", "payout_eligible")}
    if MODE == "live":
        out["feed"] = {"source": engine.market.feed, "delay_min": round(engine.market.delay_minutes, 1),
                       "realtime_symbols": sorted(engine.market.realtime_symbols),
                       "last": FEED_LOG[-3:][::-1]}   # what happened to the last webhooks (ok / why rejected)
    if router:
        st = router.status(getattr(engine.market, "delay_minutes", 0.0))   # the sim market has no feed delay
        out["real_orders"] = {"configured": st["configured"], "armed": st["armed"], "data_ok": st["data_ok"],
                              "sent": st["sent"], "blocked": st["blocked"], "last_error": st["last_error"],
                              "open": {sym: {k: p.get(k) for k in ("side", "qty", "contract")} for sym, p in st["open"].items()}}
    return out


@app.post("/api/station/ventures/{rid}/leads")
async def station_add_lead(rid: str, request: Request) -> dict:
    """Log a lead: `{"source": "dm"|"whatsapp"|"call"|"comment"|"referral"|"other", "note": "...", "action": "X-012"}`."""
    from .station import results
    b = await request.json()
    try:
        return results.add_lead(_station().store, rid, str(b.get("source", "")), str(b.get("note", ""))[:300], b.get("action") or None)
    except KeyError:
        raise HTTPException(404)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/station/leads/{rid}")
async def station_set_lead(rid: str, request: Request) -> dict:
    """Move a lead along: `{"status": "quoted"|"won"|"lost", "amount": 350}`. Won books the amount as real income."""
    from .station import results
    st = _station()
    b = await request.json()
    try:
        amount = float(b["amount"]) if b.get("amount") not in (None, "") else None
        return results.set_lead(st.store, rid, str(b.get("status", "")), amount, str(b.get("note", ""))[:300], record_income=st.record)
    except KeyError:
        raise HTTPException(404)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/station/ventures/{rid}/link")
async def station_venture_link(rid: str, request: Request) -> dict:
    """Where customers buy (`{"name": "fiverr", "url": "https://www.fiverr.com/..."}`). Content starts once a venture has one."""
    st = _station()
    v = st.store.get("ventures", rid)
    b = await request.json()
    name, url = str(b.get("name", "")).strip().lower()[:30], str(b.get("url", "")).strip()[:500]
    if not v:
        raise HTTPException(404)
    if not name or not url.startswith("https://"):
        raise HTTPException(400, "give a name and an https:// link")
    return st.store.update("ventures", rid, {"links": {**(v.get("links") or {}), name: url}}, "owner", f"{name} link: {url}", kind="venture.link")


@app.post("/api/station/optout")
async def station_optout(request: Request) -> dict:
    """Someone asked not to be contacted: never again, by any agent."""
    from .station import actions
    email = str((await request.json()).get("email", ""))
    if "@" not in email:
        raise HTTPException(400, "not an email address")
    actions.opt_out(_station().store, email)
    return {"ok": True}


@app.post("/api/station/routines/{rid}/run")
async def station_run_routine(rid: str) -> dict:
    """Run a research routine now instead of waiting for its slot."""
    st = _station()
    if not st.store.get("routines", rid):
        raise HTTPException(404)
    if not st.brain.enabled:
        raise HTTPException(503, "add ANTHROPIC_API_KEY to turn research on")
    if st.busy:
        raise HTTPException(409, f"ULTRON is busy: {st.busy}")
    if not st.treasury.ai_allowed():
        raise HTTPException(409, "the station's AI budget for this month is used up")
    st.busy = "starting a routine"
    asyncio.get_running_loop().run_in_executor(None, st.run_job, {"kind": "routine", "routine": rid})
    return {"started": rid}


@app.post("/api/station/ventures/{rid}/stage")
async def station_venture_stage(rid: str, request: Request) -> dict:
    """The owner moves a venture (e.g. to launch, operate, paused or killed)."""
    from .station.store import STAGES
    st = _station()
    stage = (await request.json()).get("stage")
    if not st.store.get("ventures", rid):
        raise HTTPException(404)
    if stage not in STAGES:
        raise HTTPException(400, f"stage must be one of {', '.join(STAGES)}")
    return st.store.update("ventures", rid, {"stage": stage}, "owner", f"owner moved it to {stage}", kind="venture.stage")


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
