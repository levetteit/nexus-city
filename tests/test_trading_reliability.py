"""Trading-loop and order-router reliability (audit C-1, T-H2, T-H3, T-H5, T-H6). No strategy or risk rule changes:
these tests only check that orders are neither duplicated nor lost, and that a failure is seen instead of silent."""
import asyncio
import importlib
import inspect
import socket
import urllib.error
from types import SimpleNamespace

import pytest

from backend import execution
from backend.execution import TradersPostRouter, never_delivered

A, B = "https://tp/a", "https://tp/b"


def _drive(router, items, post, monkeypatch):
    """Run the order worker over `items` with `post` in place of HTTP, no real sleeping and no threads, so the
    outcome never depends on timing."""
    real_sleep = asyncio.sleep

    async def inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(execution.asyncio, "sleep", lambda s: real_sleep(0))
    monkeypatch.setattr(execution.asyncio, "to_thread", inline)
    monkeypatch.setattr(router, "_post", post)

    async def go():
        router.queue = asyncio.Queue()
        task = asyncio.create_task(router._worker())
        for item in items:
            router.queue.put_nowait(item)
        for _ in range(300):
            await real_sleep(0)
        task.cancel()
    asyncio.run(go())


def _order(action, symbol="MNQ", targets=(A,)):
    return (symbol, {"ticker": "MNQZ2026", "action": action, "quantity": 3, "orderType": "market"}, "bot", list(targets))


# ---------------------------------------------------------------- T-H2: no duplicate entries
@pytest.mark.parametrize("exc, delivered", [
    (TimeoutError("read timed out"), False),                       # connected, sent, no answer: may have been taken
    (ConnectionResetError("reset"), False),
    (urllib.error.URLError(ConnectionRefusedError("refused")), True),   # never connected
    (urllib.error.URLError(socket.gaierror("no such host")), True),
    (ConnectionRefusedError("refused"), True),
])
def test_never_delivered_only_when_the_connection_itself_failed(exc, delivered):
    assert never_delivered(exc) is delivered


@pytest.mark.parametrize("action", ["buy", "sell", "add"])
def test_an_entry_that_timed_out_is_not_sent_again(tmp_path, monkeypatch, action):
    r = TradersPostRouter(str(tmp_path), webhooks=[A])
    calls = []

    def post(url, payload):
        calls.append(payload["action"])
        raise TimeoutError("read timed out")
    _drive(r, [_order(action)], post, monkeypatch)
    assert calls == [action]                                     # once: TradersPost may already have the order
    assert "not resent" in r.last_error


def test_an_entry_that_could_not_connect_is_retried(tmp_path, monkeypatch):
    r = TradersPostRouter(str(tmp_path), webhooks=[A])
    calls = []

    def post(url, payload):
        calls.append(1)
        if len(calls) < 2:
            raise urllib.error.URLError(ConnectionRefusedError("refused"))
        return 200, "ok"
    _drive(r, [_order("buy")], post, monkeypatch)
    assert len(calls) == 2 and r.sent == 1 and r.last_error == ""


def test_an_entry_the_server_rejected_is_not_retried(tmp_path, monkeypatch):
    r = TradersPostRouter(str(tmp_path), webhooks=[A])
    calls = []
    _drive(r, [_order("buy")], lambda u, p: calls.append(1) or (502, "bad gateway"), monkeypatch)
    assert len(calls) == 1 and "HTTP 502" in r.last_error


def test_exits_are_still_retried_after_a_timeout(tmp_path, monkeypatch):
    r = TradersPostRouter(str(tmp_path), webhooks=[A])
    calls = []

    def post(url, payload):
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("read timed out")
        return 200, "ok"
    _drive(r, [_order("exit")], post, monkeypatch)
    assert len(calls) == 3 and r.sent == 1                      # an exit can't add risk: keep trying


def test_http_errors_are_answers_not_network_failures(monkeypatch):
    class Err(urllib.error.HTTPError):
        def __init__(self):
            super().__init__("https://tp/a", 500, "Server Error", {}, None)

        def read(self):
            return b"boom"
    monkeypatch.setattr(execution.urllib.request, "urlopen", lambda req, timeout=0: (_ for _ in ()).throw(Err()))
    assert TradersPostRouter._post("https://tp/a", {"action": "buy"})[0] == 500


# ---------------------------------------------------------------- T-H3: the worker never dies, errors aren't hidden
def test_the_worker_survives_a_failure_and_sends_the_next_order(tmp_path, monkeypatch):
    r = TradersPostRouter(str(tmp_path), webhooks=[A])
    r.url_names = lambda: 1 / 0                                  # a bug in a helper used while logging
    monkeypatch.setattr(r, "_log", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    calls = []
    _drive(r, [_order("buy"), _order("exit")], lambda u, p: calls.append(p["action"]) or (200, "ok"), monkeypatch)
    assert calls == ["buy", "exit"]                              # the second order still went out
    assert "disk full" in r.last_error and r.errors


def test_a_failure_on_one_account_is_not_hidden_by_a_success_on_another(tmp_path, monkeypatch):
    r = TradersPostRouter(str(tmp_path), webhooks=[A, B])

    def post(url, payload):
        return (500, "down") if url == A else (200, "ok")
    _drive(r, [_order("exit", targets=(A, B))], post, monkeypatch)
    assert "HTTP 500" in r.last_error and r.status(0)["failing"] == 1


def test_an_exit_queued_before_a_restart_is_sent_after_it(tmp_path):
    r = TradersPostRouter(str(tmp_path), webhooks=[A])
    r.armed = True

    async def close_then_crash():
        r.queue = asyncio.Queue()                                # no worker: the process dies before sending
        r.open["MNQ"] = {"side": "buy", "qty": 3, "contract": "MNQZ2026", "targets": {A: 3}}
        bot = SimpleNamespace(cfg=SimpleNamespace(instrument="future", underlying="MNQ"))
        eng = SimpleNamespace(bots={"b": bot}, market=SimpleNamespace(underlyings={"MNQ": SimpleNamespace(price=1.0)}))
        r.handle(eng, [{"type": "trade_close", "bot": "b"}], 0.1)
    asyncio.run(close_then_crash())
    assert not r.open and "MNQ" in r.unsent_exits                # popped from open, but the exit is remembered

    r2 = TradersPostRouter(str(tmp_path), webhooks=[A])

    async def restart():
        closed = r2.start()
        return closed, r2.queue.get_nowait()
    closed, (symbol, payload, reason, targets) = asyncio.run(restart())
    assert closed == ["MNQ"] and payload["action"] == "exit" and targets == [A] and "still queued" in reason


def test_a_sent_exit_is_forgotten_and_a_failed_one_is_kept(tmp_path, monkeypatch):
    ok = TradersPostRouter(str(tmp_path / "ok"), webhooks=[A])
    ok.unsent_exits["MNQ"] = {"contract": "MNQZ2026", "targets": [A]}
    _drive(ok, [_order("exit")], lambda u, p: (200, "ok"), monkeypatch)
    assert ok.unsent_exits == {} and TradersPostRouter(str(tmp_path / "ok")).unsent_exits == {}

    bad = TradersPostRouter(str(tmp_path / "bad"), webhooks=[A])
    bad.unsent_exits["MNQ"] = {"contract": "MNQZ2026", "targets": [A]}
    _drive(bad, [_order("exit")], lambda u, p: (503, "down"), monkeypatch)
    assert "MNQ" in bad.unsent_exits                             # a restart will try it again


# ---------------------------------------------------------------- C-1: the trading loop is supervised
@pytest.fixture
def app_main(monkeypatch):
    monkeypatch.delenv("NEXUS_PASSWORD", raising=False)
    import backend.main as main
    importlib.reload(main)
    yield main
    importlib.reload(main)


def test_a_failing_step_is_recorded_and_alerted_once_and_the_loop_goes_on(app_main):
    sent = []
    app_main.notifier = SimpleNamespace(send=lambda *a, **k: sent.append(a))
    assert app_main._guarded("trade log", lambda: 1 / 0) is None
    assert app_main._guarded("trade log", lambda: 1 / 0) is None
    assert app_main._guarded("order router", lambda: "ran") == "ran"
    assert app_main.LOOP["errors"] == 2 and "ZeroDivisionError" in app_main.LOOP["last_error"]
    assert len(sent) == 1                                        # one alert an hour per place, not one per candle


def test_healthz_fails_when_the_trading_loop_died(app_main):
    from fastapi.testclient import TestClient
    sent = []
    app_main.notifier = SimpleNamespace(send=lambda *a, **k: sent.append(a))

    async def crash():
        raise RuntimeError("yahoo down at startup")
    asyncio.run(app_main.supervised(crash))
    r = TestClient(app_main.app).get("/healthz")
    assert r.status_code == 503 and r.json()["ok"] is False and "yahoo down" in r.json()["problems"][0]
    assert sent and "stopped" in sent[0][0]


def test_healthz_fails_when_the_live_loop_stalls(app_main, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(app_main, "MODE", "live")
    c = TestClient(app_main.app)
    app_main.LOOP["beat"] = app_main.time.time() - 10
    assert c.get("/healthz").status_code == 200
    app_main.LOOP["beat"] = app_main.time.time() - app_main.LOOP_STALL_SECONDS - 5
    r = c.get("/healthz")
    assert r.status_code == 503 and "stalled" in r.json()["problems"][0]


# ---------------------------------------------------------------- T-H5: engine changes run on the event loop
@pytest.mark.parametrize("name", ["toggle", "execution_flatten", "reset_account"])
def test_engine_changing_endpoints_run_on_the_event_loop(app_main, name):
    assert inspect.iscoroutinefunction(getattr(app_main, name))


# ---------------------------------------------------------------- T-H6: the restart flatten doesn't wait for Yahoo
def test_leftover_positions_are_closed_before_any_market_download(app_main, tmp_path, monkeypatch):
    from backend import history, live, news
    monkeypatch.setattr(live, "DATA_DIR", str(tmp_path))
    started = []
    monkeypatch.setattr(execution.TradersPostRouter, "start", lambda self: started.append(1) or [])
    monkeypatch.setattr(history, "History", lambda d: SimpleNamespace(save=lambda *a: None))

    def yahoo_down(self, *a):
        assert started, "the router must start before the downloads"
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(news.NewsCalendar, "refresh", yahoo_down)
    with pytest.raises(RuntimeError, match="yahoo down"):
        asyncio.run(app_main.run_live())
    assert started == [1]


def test_a_broken_trade_log_cannot_stop_real_orders(app_main, tmp_path, monkeypatch, capsys):
    """One pass of the live loop where the trade log raises: the order router still sees the candle's close."""
    import backend.accounts as accounts_mod
    import backend.desk as desk_mod
    import backend.forge as forge_mod
    import backend.report as report_mod
    import backend.scorecard as scorecard_mod
    import backend.signals as signals_mod
    import backend.watchdog as watchdog_mod
    from backend import history, live, news

    class Stop(BaseException):
        pass

    class Market:
        i, warm_until, delay_minutes = 0, 0, 0.0
        _left = 1

        def poll(self): pass
        def release(self): pass

        def has_next(self):
            self._left -= 1
            return self._left >= 0

    class Engine:
        bots = {}
        def __init__(self, **kw): self.market = kw["market"]
        def tick(self, trade=True): return [{"type": "trade_close", "bot": "b"}]

    quiet = SimpleNamespace(start_day=lambda *a, **k: None, observe=lambda *a, **k: None)
    monkeypatch.setattr(live, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(live, "LiveMarket", Market)
    monkeypatch.setattr(live, "load_account", lambda: None)
    monkeypatch.setattr(live, "load_careers", lambda e: None)
    monkeypatch.setattr(live, "record", lambda *a: 1 / 0)                      # the broken step
    monkeypatch.setattr(app_main, "Engine", Engine)
    monkeypatch.setattr(forge_mod, "live_params", lambda d: None)
    monkeypatch.setattr(app_main, "run_forge", lambda: asyncio.sleep(0))
    monkeypatch.setattr(history, "History", lambda d: SimpleNamespace(save=lambda *a: None))
    monkeypatch.setattr(news.NewsCalendar, "refresh", lambda self, *a: None)
    monkeypatch.setattr(accounts_mod.AccountBook, "observe", lambda self, e, new: [])
    monkeypatch.setattr(watchdog_mod.Watchdog, "check", lambda self, *a: [])
    monkeypatch.setattr(scorecard_mod, "Scorecard", lambda *a: quiet)
    monkeypatch.setattr(report_mod, "DayReports", lambda *a: quiet)
    monkeypatch.setattr(signals_mod, "SignalLog", lambda *a: quiet)
    monkeypatch.setattr(desk_mod, "TradingDesk", lambda *a: SimpleNamespace(enabled=False))
    seen = []
    monkeypatch.setattr(execution.TradersPostRouter, "handle", lambda self, eng, new, *a: seen.append(new))

    def stop(*a):
        raise Stop
    monkeypatch.setattr(app_main, "state", stop)                                # end the test after one pass
    with pytest.raises(Stop):
        asyncio.run(app_main.run_live())
    assert seen and seen[0][0]["type"] == "trade_close"                         # real orders still got the close
    assert "trading loop error: trade log: ZeroDivisionError" in capsys.readouterr().out   # recorded, not silent
