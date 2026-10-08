"""Daily reports, the paper-vs-backtest check and phone notifications: the parts the owner reads every day."""
import csv
import json
import sys
import types
from types import SimpleNamespace

import pytest

from backend.account import PropAccount
from backend.backtest import ReplayMarket
from backend.engine import Engine
from backend.notify import Notifier
from backend.report import DayReports
from backend.scorecard import Scorecard


def _run_days(real_data):
    """Trade the 5 recorded days and collect each finished daily report."""
    market = ReplayMarket(real_data)
    engine = Engine(market=market, account=PropAccount())
    market.step()
    reports = DayReports("unused")
    reports.start_day(engine)
    finished = []
    while market.has_next():
        r = reports.observe(engine, engine.tick())
        if r:
            finished.append(r)
    return engine, finished


def test_daily_reports_follow_the_trading_day(real_data, tmp_path):
    engine, finished = _run_days(real_data)
    assert len(finished) >= 3
    traded = [r for r in finished if r["trades"]]
    assert traded, "the recorded days include trades"
    r = traded[0]
    assert r["wins"] + r["losses"] == len(r["trades"])
    assert sum(r["by_bot"].values()) == pytest.approx(sum(t["pnl"] for t in r["trades"]), abs=0.01)
    assert {"phase", "balance", "mll"} <= set(r["account"]) and r["room"] > 0
    reports = DayReports(str(tmp_path))
    reports.save(r)
    assert reports.get(r["day"])["pnl"] == r["pnl"]
    assert reports.list()[0]["day"] == r["day"]
    assert reports.get("../../etc/passwd") is None                      # only real dates map to files
    title, body = DayReports.message(r)
    assert f"{len(r['trades'])} trade" in title and "W" in body and "room" in body


def test_report_message_for_a_quiet_funded_day():
    r = {"day": "2026-10-07", "pnl": 0, "trades": [], "wins": 0, "losses": 0, "news": ["CPI 08:30"], "passed": False,
         "goal_hit": False, "room": 1800.0, "check": {"verdict": "drift", "matched": 0, "live_trades": 1, "replay_trades": 0,
                                                       "explained_by": ["server restarted during the day"]},
         "account": {"phase": "funded", "profit": 900, "target": None, "profitable_days": 3, "payout_days": 5}}
    title, body = DayReports.message(r)
    assert "0 trades" in title and "no trades today · news: CPI 08:30" in body
    assert "Funded" in body and "server restarted" in body


def test_scorecard_replays_a_day_and_compares_it_with_what_was_traded(real_data, tmp_path):
    market = ReplayMarket(real_data)
    engine = Engine(market=market, account=PropAccount())
    market.step()
    card = Scorecard(str(tmp_path))
    card.start_day(engine)
    finished = None
    while market.has_next() and finished is None:
        finished = card.observe(engine, engine.tick())
    assert finished is not None
    check = card.replay(finished, real_data)                            # the replay uses the same candles: no network
    assert check["verdict"] in ("match", "drift") and check["live_trades"] == len(finished["trades"])
    assert card.status(engine.account)["checks"] == 1
    assert json.loads((tmp_path / "paper_checks.json").read_text())[0]["day"] == check["day"]


def test_scorecard_edge_counts_trades_not_trims(tmp_path):
    with open(tmp_path / "paper_trades.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["closed_at_et", "bot", "contract", "qty", "entry", "exit", "pnl", "reason", "opened_at"])
        w.writerow(["2026-10-07 10:00", "mnq-3m", "MNQ LONG", 3, 1, 2, 300, "pointer against", "09:40"])
        w.writerow(["2026-10-07 10:05", "mnq-3m", "MNQ LONG", 1, 1, 2, 50, "trim: zone", "09:40"])
        w.writerow(["2026-10-07 11:00", "mnq-3m", "MNQ SHORT", 3, 2, 3, -150, "pointer against", "10:40"])
    acct = SimpleNamespace(day_history=[("evaluation", 200.0), ("evaluation", 0.0), ("evaluation", -100.0)])
    edge = Scorecard(str(tmp_path)).edge(acct)
    assert edge["trades"] == 2 and edge["win_rate"] == 50.0
    assert edge["days"] == 2 and edge["profit_factor"] == round(350 / 150, 2)


# ---------------------------------------------------------------- phone notifications
def _engine():
    bot = SimpleNamespace(cfg=SimpleNamespace(persona={"handle": "OG_Pointer"}, name="MNQ OG"))
    return SimpleNamespace(bots={"mnq-3m": bot}, account=SimpleNamespace(day_pnl=420.0))


@pytest.mark.parametrize("ev, expect", [
    ({"type": "trade_open", "bot": "mnq-3m", "contract": "MNQ LONG", "qty": 3, "entry": 25000.0, "note": "3m PROC"}, "went LONG ×3"),
    ({"type": "trade_add", "bot": "mnq-3m", "total": 6, "why": "PROC with the trade"}, "added → 6"),
    ({"type": "trade_trim", "bot": "mnq-3m", "qty": 1, "pnl": 80.0, "why": "zone", "left": 2}, "trimmed 1 +$80"),
    ({"type": "trade_close", "bot": "mnq-3m", "pnl": 300.0, "reason": "pointer against"}, "closed +$300"),
    ({"type": "news_hold", "title": "CPI", "at": "08:30", "until": "08:45"}, "CPI at 08:30"),
    ({"type": "account_halt", "reason": "daily cap reached"}, "done for the day"),
    ({"type": "payout_ready", "number": 1, "limit": 1500, "safe": 900, "balance": 52000}, "Payout #1"),
])
def test_notification_messages(ev, expect):
    title, body, tag = Notifier.message(_engine(), ev, real=True)
    assert expect in title and title.endswith(" · REAL") == (tag == "trade")


def test_quiet_events_send_nothing():
    assert Notifier.message(_engine(), {"type": "tick"}, real=False) is None


def test_ntfy_alerts_are_sent_with_a_link_into_the_app(tmp_path, monkeypatch):
    import backend.notify as notify
    monkeypatch.setenv("NEXUS_NTFY_TOPIC", "nexus-test-topic")
    monkeypatch.setattr(notify, "PUBLIC_URL", "https://city.example.com")
    sent = []

    class Resp:
        def read(self):
            return b"{}"
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda req, timeout=0: sent.append(json.loads(req.data)) or Resp())
    n = Notifier(str(tmp_path))
    n.handle(_engine(), [{"type": "trade_close", "bot": "mnq-3m", "pnl": -50.0, "reason": "end of day"}])
    assert sent[0]["topic"] == "nexus-test-topic" and "closed -$50" in sent[0]["title"]
    assert sent[0]["click"] == "https://city.example.com/" and n.sent == 1


def test_web_push_drops_phones_that_unsubscribed(tmp_path, monkeypatch):
    pytest.importorskip("py_vapid")   # installed from requirements.lock (CI); optional on other setups
    monkeypatch.delenv("NEXUS_NTFY_TOPIC", raising=False)

    class WebPushException(Exception):
        def __init__(self, msg, response=None):
            super().__init__(msg)
            self.response = response
    delivered = []

    def webpush(subscription_info, **kw):
        if "gone" in subscription_info["endpoint"]:
            raise WebPushException("gone", SimpleNamespace(status_code=410))
        delivered.append(subscription_info["endpoint"])
    monkeypatch.setitem(sys.modules, "pywebpush", types.SimpleNamespace(webpush=webpush, WebPushException=WebPushException))
    n = Notifier(str(tmp_path))
    assert n.web_push and n.public_key
    for ep in ("https://push.example/alive", "https://push.example/gone"):
        n.subscribe({"endpoint": ep, "keys": {"p256dh": "x", "auth": "y"}})
    n.send("🔔 test", "body")
    assert delivered == ["https://push.example/alive"]
    assert [s["endpoint"] for s in n.subs] == ["https://push.example/alive"]
    assert [s["endpoint"] for s in Notifier(str(tmp_path)).subs] == ["https://push.example/alive"]   # saved
