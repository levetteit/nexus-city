"""The web server: password gate, fresh app files, the TradingView endpoints."""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    os.environ.update({"NEXUS_MODE": "sim", "NEXUS_PASSWORD": "pw", "NEXUS_FEED_SECRET": "s3cret"})
    import backend.main as main
    importlib.reload(main)
    return TestClient(main.app), main


def test_password_gate(client):
    c, main = client
    assert c.get("/").status_code == 401
    assert c.get("/api/state").status_code == 401
    assert c.post("/api/execution/flatten").status_code == 401
    assert c.get("/healthz").status_code == 200            # Render's health check needs no password
    assert TestClient(main.app).get("/", auth=("x", "wrong")).status_code == 401
    logged_in = TestClient(main.app)
    r = logged_in.get("/", auth=("x", "pw"))
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    assert logged_in.get("/api/state").status_code == 200   # the login cookie lets the app's own requests in


def test_feed_rejects_wrong_secret_and_explains(client):
    c, main = client
    body = {"secret": "", "ticker": "MNQ1!", "t": 1, "o": 1, "h": 1, "l": 1, "c": 1}
    assert c.post("/api/feed", json=body).status_code == 401
    assert "empty" in main.FEED_LOG[-1]["reason"]
    assert c.post("/api/feed", content=b"hello").status_code == 400
    body["secret"] = "s3cret"
    assert c.post("/api/feed", json=body).status_code == 503   # right secret, but this is the simulation


@pytest.mark.parametrize("ticker,sym", [("MNQ1!", "MNQ"), ("CME_MINI:MES1!", "MES"), ("MNQZ2026", "MNQ"), ("NQ1!", "NQ")])
def test_ticker_names(client, ticker, sym):
    _, main = client
    assert main.normalize_symbol(ticker) == sym



def test_scale_plan(client):
    c, main = client
    c = TestClient(main.app)
    c.get("/", auth=("x", "pw"))
    p = c.get("/api/scale").json()
    assert p["mode"] == "sim" and p["accounts"][0]["stage"] == "evaluation"
    assert p["next_eval"]["can_fund"] is False and "Set the evaluation price" in p["next_eval"]["text"]


def test_jarvis_act_needs_its_token_and_refuses_money(client, monkeypatch):
    c, main = client
    assert c.post("/api/jarvis/act", json={"op": "warroom"}).status_code == 404     # off until the token is set
    monkeypatch.setenv("NEXUS_JARVIS_TOKEN", "t" * 32)
    assert c.post("/api/jarvis/act", json={"op": "warroom"}).status_code == 401
    h = {"Authorization": "Bearer " + "t" * 32}
    if main.station is None:
        return
    assert c.post("/api/jarvis/act", json={"op": "venture.stage", "id": "V-001", "stage": "paused", "why": "x"}, headers=h).status_code == 403
    assert c.post("/api/jarvis/act", json={"op": "warroom"}, headers=h).json() == {"queued": "warroom"}
