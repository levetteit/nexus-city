"""Failure paths: what happens when Claude, a connector, OAuth or a webhook misbehaves, and that repeated events have
no repeated effect. Everything outside is faked; nothing here reaches a real service."""
import asyncio
import json
import time
import urllib.error
from types import SimpleNamespace

import pytest

from backend.execution import TradersPostRouter
from backend.station import connectors
from backend.station.brain import Brain


# ---------------------------------------------------------------- the network guard itself
def test_tests_cannot_reach_the_network():
    import urllib.request
    with pytest.raises(Exception) as err:
        urllib.request.urlopen("https://example.com", timeout=2)
    assert "must not use the network" in str(err.value) or "must not use the network" in repr(err.value.__context__)


# ---------------------------------------------------------------- Claude: refusals, cut-offs, malformed output
class _FakeBrain(Brain):
    def __init__(self, replies):
        self.replies, self.calls = list(replies), 0

    def _request(self, agent, venture, note, **kw):
        self.calls += 1
        stop, text = self.replies.pop(0)
        content = [SimpleNamespace(type="text", text=text)] if text is not None else []
        return SimpleNamespace(stop_reason=stop, content=content)


@pytest.mark.parametrize("replies, message", [
    ([("refusal", "")], "declined"),
    ([("max_tokens", "{"), ("max_tokens", "{")], "cut off"),
    ([("end_turn", None)], "no text"),
    ([("end_turn", "not json at all")], "valid JSON"),
])
def test_bad_model_answers_raise_clear_errors(replies, message):
    b = _FakeBrain(replies)
    with pytest.raises(RuntimeError, match=message):
        b.structured("A-002", "system", "prompt", {})


def test_a_cut_off_answer_is_retried_once_then_succeeds():
    b = _FakeBrain([("max_tokens", "{"), ("end_turn", '{"ok": 1}')])
    assert b.structured("A-002", "system", "prompt", {}) == {"ok": 1} and b.calls == 2


# ---------------------------------------------------------------- connectors: HTTP and network failures
def test_connector_http_and_network_errors_become_connector_errors(monkeypatch):
    def http_error(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)
    monkeypatch.setattr(connectors.urllib.request, "urlopen", http_error)
    with pytest.raises(connectors.ConnectorError, match="HTTP 400"):
        connectors._http_json("GET", "https://graph.example.com/x")

    def unreachable(req, timeout=0):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(connectors.urllib.request, "urlopen", unreachable)
    with pytest.raises(connectors.ConnectorError, match="can't reach graph.example.com"):
        connectors._http_json("GET", "https://graph.example.com/x?access_token=secret-in-url")


# ---------------------------------------------------------------- OAuth: state, expiry, success
def test_oauth_rejects_a_wrong_or_expired_state_and_accepts_the_right_one(tmp_path, monkeypatch):
    connectors.set_data_dir(str(tmp_path))
    monkeypatch.setenv("PINTEREST_APP_ID", "app")
    monkeypatch.setenv("PINTEREST_APP_SECRET", "app-secret")
    monkeypatch.setenv("NEXUS_PUBLIC_URL", "https://city.example.com")
    url = connectors.oauth_start("pinterest")
    state = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))["state"]
    with pytest.raises(connectors.ConnectorError):
        connectors.oauth_finish("pinterest", "code-1", "forged-state")
    with pytest.raises(connectors.ConnectorError):
        connectors.oauth_finish("pinterest", "", state)                       # no code
    exchanged = []
    monkeypatch.setattr(connectors, "_http_form", lambda url, form, headers=None: exchanged.append(form) or
                        {"access_token": "at", "refresh_token": "rt", "expires_in": 3600})
    assert connectors.oauth_finish("pinterest", "code-1", state) == {"connected": "pinterest"}
    assert exchanged[0]["code"] == "code-1"
    with pytest.raises(connectors.ConnectorError):                            # one use only
        connectors.oauth_finish("pinterest", "code-1", state)
    url = connectors.oauth_start("pinterest")
    state = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))["state"]
    pending = connectors._tokens()["pinterest_pending"]
    connectors._save_token("pinterest_pending", {**pending, "at": time.time() - 3600})   # older than 15 minutes
    with pytest.raises(connectors.ConnectorError, match="expired"):
        connectors.oauth_finish("pinterest", "code-2", state)


@pytest.mark.integration
def test_oauth_callback_page_escapes_what_the_provider_sends(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    import backend.main as main
    monkeypatch.delenv("NEXUS_PASSWORD", raising=False)
    importlib.reload(main)
    r = TestClient(main.app).get("/api/station/connect/etsy/callback", params={"error": "<script>alert(1)</script>"})
    assert r.status_code == 200 and "<script>" not in r.text and "&lt;script&gt;" in r.text
    assert TestClient(main.app).get("/api/station/connect/evil/callback").status_code == 404


# ---------------------------------------------------------------- duplicate events have one effect
def test_a_stripe_sale_delivered_twice_is_booked_once(tmp_path):
    from backend.station.economy import Treasury
    from backend.station.store import Store
    t = Treasury(Store(str(tmp_path)))
    session = {"id": "cs_test_1", "payment_status": "paid", "amount_total": 1200, "metadata": {"nexus_venture": "V-009"}}
    assert t.book_stripe_sale(session) and t.book_stripe_sale(session) is None
    assert sum(1 for e in t.entries if e["kind"] == "income") == 1


def test_unpaid_or_empty_stripe_sessions_book_nothing(tmp_path):
    from backend.station.economy import Treasury
    from backend.station.store import Store
    t = Treasury(Store(str(tmp_path)))
    assert t.book_stripe_sale({"id": "cs_2", "payment_status": "unpaid", "amount_total": 900}) is None
    assert t.book_stripe_sale({"id": "", "payment_status": "paid", "amount_total": 900}) is None
    assert not t.entries


# ---------------------------------------------------------------- the real-order sender (TradersPost)
def _run_worker(router, items, fake_post, monkeypatch):
    """Drive TradersPostRouter._worker over `items` with `fake_post` instead of HTTP, without real sleeps."""
    import backend.execution as execution
    real_sleep = asyncio.sleep
    monkeypatch.setattr(execution.asyncio, "sleep", lambda s: real_sleep(0))
    monkeypatch.setattr(router, "_post", fake_post)

    async def go():
        router.queue = asyncio.Queue()
        task = asyncio.create_task(router._worker())
        for item in items:
            router.queue.put_nowait(item)
        for _ in range(200):
            await real_sleep(0)
            if router.queue.empty():
                await real_sleep(0.01)
        task.cancel()
    asyncio.run(go())


def test_order_sender_logs_every_send_and_reports_failures_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_TRADERSPOST_WEBHOOKS", "https://webhooks.traderspost.io/trading/webhook/secret-path-123")
    r = TradersPostRouter(str(tmp_path))
    url = r.webhooks[0]
    posts = []

    def post(u, payload):
        posts.append((u, payload["action"]))
        return (500, f"server error at {u}") if payload["action"] == "buy" else (200, "ok")
    exit_order = ("MNQ", {"ticker": "MNQZ2026", "action": "exit", "orderType": "market"}, "bot", [url])
    entry = ("MNQ", {"ticker": "MNQZ2026", "action": "buy", "quantity": 3, "orderType": "market"}, "bot", [url])
    _run_worker(r, [exit_order, entry], post, monkeypatch)
    assert posts[0] == (url, "exit") and r.sent >= 1
    assert "secret-path-123" not in r.last_error and "HTTP 500" in r.last_error
    log = (tmp_path / "orders.csv").read_text()
    assert "exit" in log and "secret-path-123" not in log


def test_disarmed_router_sends_nothing(tmp_path):
    r = TradersPostRouter(str(tmp_path), webhooks=["https://tp/shared"])
    r.armed, r.queue = False, asyncio.Queue()
    eng = SimpleNamespace(bots={"b": SimpleNamespace(cfg=SimpleNamespace(instrument="future", underlying="MNQ"))},
                          market=SimpleNamespace(underlyings={"MNQ": SimpleNamespace(price=1.0)}, minutes_to_flat=200))
    r.handle(eng, [{"type": "trade_open", "bot": "b", "contract": "MNQ LONG", "qty": 3}], 0.1)
    assert r.queue.empty() and not r.open


def test_router_refuses_new_entries_on_stale_data_and_after_1550(tmp_path):
    r = TradersPostRouter(str(tmp_path), webhooks=["https://tp/shared"])
    r.armed, r.queue = True, asyncio.Queue()
    bots = {"b": SimpleNamespace(cfg=SimpleNamespace(instrument="future", underlying="MNQ"))}
    ev = [{"type": "trade_open", "bot": "b", "contract": "MNQ LONG", "qty": 3}]
    fresh = SimpleNamespace(bots=bots, market=SimpleNamespace(underlyings={"MNQ": SimpleNamespace(price=1.0)}, minutes_to_flat=200))
    late = SimpleNamespace(bots=bots, market=SimpleNamespace(underlyings={"MNQ": SimpleNamespace(price=1.0)}, minutes_to_flat=8))
    r.handle(fresh, ev, 9.0)          # prices 9 minutes old
    r.handle(late, ev, 0.2)           # 15:52 ET
    assert r.queue.empty() and r.blocked == 2


# ---------------------------------------------------------------- API validation
@pytest.mark.integration
def test_arming_real_orders_needs_the_explicit_confirmation(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    import backend.main as main
    monkeypatch.delenv("NEXUS_PASSWORD", raising=False)
    importlib.reload(main)
    main.router = TradersPostRouter(str(tmp_path), webhooks=["https://tp/shared"])
    main.engine = SimpleNamespace(market=SimpleNamespace(delay_minutes=0.5), bots={})
    c = TestClient(main.app)
    assert c.post("/api/execution", json={"armed": True}).status_code == 400
    assert main.router.armed is False
    assert c.post("/api/execution", json={"armed": True, "confirm": "ARM"}).json()["armed"] is True
    main.router.queue = asyncio.Queue()
    assert c.post("/api/execution/flatten").json()["armed"] is False      # flatten also disarms
    main.router, main.engine = None, None


def test_account_webhooks_must_be_https(tmp_path):
    from backend.accounts import AccountBook
    book = AccountBook(str(tmp_path))
    with pytest.raises(ValueError):
        book.add("A", "evaluation", 50_000, 48_000, webhook="http://insecure.example/hook")
    assert book.add("B", "evaluation", 50_000, 48_000, webhook="https://webhooks.traderspost.io/x").webhook


@pytest.mark.integration
def test_tradingview_signal_webhook_validates_and_routes(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    import backend.main as main
    monkeypatch.setenv("NEXUS_WEBHOOK_SECRET", "tv-secret-12345")
    monkeypatch.delenv("NEXUS_PASSWORD", raising=False)
    importlib.reload(main)
    seen = []
    main.engine = SimpleNamespace(signal=lambda p: seen.append(p) or [{"bot": "mnq-3m", "action": "long order"}])
    c = TestClient(main.app)
    body = {"secret": "tv-secret-12345", "ticker": "CME_MINI:MNQ1!", "signal": "long"}
    assert c.post("/api/tradingview", json={**body, "secret": "wrong"}).status_code == 401
    assert c.post("/api/tradingview", json={**body, "signal": "buy everything"}).status_code == 400
    assert c.post("/api/tradingview", content=b"not json").status_code == 400
    r = c.post("/api/tradingview", json=body)
    assert r.status_code == 200 and r.json()["symbol"] == "MNQ"
    assert "secret" not in seen[0]                                         # it goes no further than the check
    main.engine = None
