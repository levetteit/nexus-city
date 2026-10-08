"""The front door and the outbound safety rails (Phase 4): no forged cross-site actions, no open live app,
a server-signed session cookie, brute-force limits, security headers, robust secret checks, and outbound
actions that can never be sent twice."""
import hashlib
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient

from backend.security import MAX_FAILURES, PasswordGate, is_cross_site, secret_matches


async def _ok(request):
    return PlainTextResponse("ok")


async def _ws(ws):
    await ws.accept()
    await ws.send_text("hi")
    await ws.close()


def _client(tmp_path, password="pw", mode="live", **kw):
    inner = Starlette(routes=[Route("/", _ok), Route("/api/x", _ok, methods=["GET", "POST"]),
                              Route("/api/feed", _ok, methods=["POST"]), Route("/healthz", _ok), WebSocketRoute("/ws", _ws)])
    gate = PasswordGate(inner, password=password, mode=mode, data_dir=str(tmp_path), open_paths=("/healthz", "/api/feed"),
                        public_prefixes=("/shop/",))
    return TestClient(gate, base_url="https://city.example.com"), gate


def test_cross_site_writes_are_refused_and_same_site_ones_work(tmp_path):
    c, _ = _client(tmp_path)
    auth = ("x", "pw")
    assert c.post("/api/x", auth=auth, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/x", auth=auth, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.post("/api/x", auth=auth, headers={"Origin": "null"}).status_code == 403
    assert c.post("/api/x", auth=auth, headers={"Origin": "https://city.example.com"}).status_code == 200
    assert c.post("/api/x", auth=auth).status_code == 200                       # scripts send no Origin: not a browser
    assert c.get("/api/x", auth=auth, headers={"Origin": "https://evil.example"}).status_code == 200   # reads are fine
    assert c.post("/api/feed", headers={"Origin": "https://tradingview.com"}).status_code == 200    # webhooks: own secret


def test_cross_site_websocket_is_refused(tmp_path):
    c, _ = _client(tmp_path)
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as refused:
        with c.websocket_connect("/ws", headers={"Origin": "https://evil.example", "Authorization": "Basic eDpwdw=="}):
            pass
    assert refused.value.code == 4403
    # the test client's WebSocket host is "testserver": a same-origin page connects fine
    with c.websocket_connect("/ws", headers={"Origin": "http://testserver", "Authorization": "Basic eDpwdw=="}) as ws:
        assert ws.receive_text() == "hi"


def test_live_mode_without_a_password_is_closed(tmp_path):
    c, _ = _client(tmp_path, password="", mode="live")
    assert c.get("/api/x").status_code == 503
    assert c.get("/healthz").status_code == 200                                  # health checks and webhooks still answer
    sim, _ = _client(tmp_path, password="", mode="sim")
    assert sim.get("/api/x").status_code == 200                                  # local simulation stays open


def test_session_cookie_is_server_signed_secure_and_constant_time(tmp_path):
    c, gate = _client(tmp_path)
    r = c.get("/", auth=("x", "pw"), headers={"X-Forwarded-Proto": "https"})
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie
    assert gate.token not in (hashlib.sha256(b"starnet:pw").hexdigest(), hashlib.sha256(b"pw").hexdigest())
    assert (tmp_path / "session.key").stat().st_mode & 0o777 == 0o600
    assert gate._authorized({b"cookie": f"nexus_auth={gate.token}".encode()}) == (True, False)
    assert gate._authorized({b"cookie": f"nexus_auth={gate.token[:-1]}0".encode()}) == (False, False)
    assert gate._authorized({b"cookie": f"other=nexus_auth={gate.token}".encode()}) == (False, False)   # no substring tricks
    again = PasswordGate(None, password="pw", mode="live", data_dir=str(tmp_path))
    assert again.token == gate.token                                             # the key survives a restart


def test_repeated_wrong_passwords_are_locked_out(tmp_path):
    c, _ = _client(tmp_path)
    for _ in range(MAX_FAILURES):
        assert c.get("/api/x", auth=("x", "guess")).status_code == 401
    r = c.get("/api/x", auth=("x", "pw"))
    assert r.status_code == 429 and r.headers["retry-after"]


def test_security_headers_on_every_response(tmp_path):
    c, _ = _client(tmp_path)
    for r in (c.get("/", auth=("x", "pw")), c.get("/api/x"), c.get("/healthz")):
        assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_secret_checks_never_crash():
    assert secret_matches("abc", "abc") and not secret_matches("abd", "abc")
    assert not secret_matches("ñandú", "abc") and not secret_matches(None, "abc") and not secret_matches({"a": 1}, "abc")
    assert not secret_matches("abc", None) and not secret_matches("", "")
    assert is_cross_site({b"origin": b"https://a.example", b"host": b"b.example"})
    assert not is_cross_site({b"origin": b"https://b.example", b"host": b"b.example"})


def test_stripe_signature_with_a_bad_timestamp_is_rejected_not_a_crash(monkeypatch):
    from backend.station import connectors
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    for header in ("t=abc,v1=00", "t=,v1=00", "v1=00", f"t={int(time.time())},v1=ñ"):
        with pytest.raises(connectors.ConnectorError):
            connectors.stripe_verify(b"{}", header)


def test_stripe_network_errors_are_connector_errors(monkeypatch):
    import urllib.error
    from backend.station import connectors
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")

    def boom(*a, **k):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(connectors.urllib.request, "urlopen", boom)
    with pytest.raises(connectors.ConnectorError):
        connectors.stripe_request("POST", "/products", {"name": "x"}, idempotency_key="X-1")


def test_feed_rejects_future_and_impossible_candles(monkeypatch):
    import importlib
    import backend.main as main
    monkeypatch.setenv("NEXUS_FEED_SECRET", "feed-secret-123")
    importlib.reload(main)
    main.MODE = "live"   # the checks below run before the live-mode check
    main.engine = type("E", (), {"market": type("M", (), {"underlyings": {"MNQ": 1}, "push": lambda *a: True, "charts": {}})()})()
    c = TestClient(main.app)
    base = {"secret": "feed-secret-123", "ticker": "NQ1!", "t": int(time.time()) - 60, "o": 10, "h": 12, "l": 9, "c": 11}
    assert c.post("/api/feed", json={**base, "t": int(time.time()) + 3600}).status_code == 400
    assert c.post("/api/feed", content=json.dumps({**base, "h": float("inf")}).encode()).status_code == 400
    assert c.post("/api/feed", json={**base, "l": 13}).status_code == 400          # low above the close
    assert c.post("/api/feed", content=b'{"secret":"feed-secret-123","t":1,"o":"nan","h":1,"l":1,"c":1}').status_code == 400
    main.engine, main.MODE = None, "sim"


# ---------------------------------------------------------------- outbound actions can't be sent twice
def _ready_action(u, kind="stripe.payment_link", payload=None):
    a = u.store.create("actions", {"kind": kind, "agent": "A-005", "venture": "V-PPS", "status": "ready",
                                   "qa": {"verdict": "pass", "issues": []}, "revisions": 0, "result": None, "why": "test",
                                   "payload": payload or {"name": "Binder", "price_usd": 9}}, "test")
    return a


def test_an_unexpected_error_after_sending_is_never_retried(tmp_path, monkeypatch):
    from backend.station import actions, connectors
    from backend.station.ultron import Ultron
    u = Ultron(str(tmp_path), client=None)
    monkeypatch.setattr(connectors, "stripe_configured", lambda: True)
    calls = []

    def flaky(*a, **k):
        calls.append(k.get("idempotency_key"))
        raise KeyError("url")   # e.g. Stripe made the link, then the reply was unexpected
    monkeypatch.setattr(connectors, "stripe_payment_link", flaky)
    a = _ready_action(u)
    out = actions.dispatch(u.store, a, True)
    assert out["status"] == "failed" and out["result"]["check_before_resending"]
    assert actions.dispatch(u.store, out, True)["status"] == "failed" and len(calls) == 1   # not picked up again
    assert calls == [a["id"]]


def test_a_send_interrupted_by_a_restart_is_flagged_not_resent(tmp_path):
    from backend.station.ultron import Ultron
    u = Ultron(str(tmp_path), client=None)
    a = _ready_action(u)
    u.store.update("actions", a["id"], {"status": "sending"}, "test")
    again = Ultron(str(tmp_path), client=None)
    rec = again.store.get("actions", a["id"])
    assert rec["status"] == "failed" and rec["result"]["check_before_resending"]


def test_cancel_is_refused_while_a_send_is_in_flight(tmp_path):
    from backend import jarvis
    from backend.station.ultron import Ultron
    u = Ultron(str(tmp_path), client=None)
    a = _ready_action(u, "social.post", {"platform": "facebook", "text": "hola"})
    u.store.update("actions", a["id"], {"status": "sending"}, "test")
    with pytest.raises(ValueError):
        jarvis.act(u, {"op": "action.cancel", "id": a["id"], "why": "x"})


def test_opt_out_and_a_send_record_both_survive(tmp_path):
    from backend.station import actions
    from backend.station.ultron import Ultron
    u = Ultron(str(tmp_path), client=None)
    actions._mark_contacted(u.store, "ann@roof.example", "V-PPS", "X-1")
    actions.opt_out(u.store, "bob@solar.example")
    actions._mark_contacted(u.store, "cat@home.example", "V-PPS", "X-2")
    c = actions.contacts_doc(u.store)
    assert "bob@solar.example" in c["do_not_contact"] and {"ann@roof.example", "cat@home.example"} <= set(c["contacted"])


def test_outbound_stop_also_stops_kit_pins(tmp_path, monkeypatch):
    from backend.station import kits
    from backend.station.ultron import Ultron
    u = Ultron(str(tmp_path), client=None)
    monkeypatch.setattr(kits, "pins_due", lambda s, now: ["kit-1"])
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    assert (u.next_job(now) or {}).get("kind") == "kit_pin"
    u.cfg["outbound"] = False
    assert (u.next_job(now) or {}).get("kind") != "kit_pin"
