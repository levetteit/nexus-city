from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.backtest import ET
from backend.watchdog import Watchdog, market_open


def et(*a):
    return datetime(*a, tzinfo=ET)


def test_market_hours():
    assert market_open(et(2026, 10, 6, 10, 0))          # Tuesday morning
    assert not market_open(et(2026, 10, 6, 17, 30))     # daily break
    assert market_open(et(2026, 10, 6, 18, 0))
    assert not market_open(et(2026, 10, 9, 17, 5))      # Friday close
    assert not market_open(et(2026, 10, 10, 12, 0))     # Saturday
    assert not market_open(et(2026, 10, 11, 17, 59)) and market_open(et(2026, 10, 11, 18, 0))   # Sunday open


def market(live, last):
    return SimpleNamespace(realtime_symbols=set(live), timeline=[(last, {})])


def test_feed_drop_alert_and_recovery(tmp_path):
    w = Watchdog(str(tmp_path))
    w.checked_on = "2026-10-06"                                                   # today's systems check already sent
    t0 = et(2026, 10, 6, 10, 0).astimezone(timezone.utc)
    assert w.check(market({"MNQ", "MES"}, t0), now=t0) == []                    # learns the expected symbols
    lost = w.check(market({"MNQ"}, t0 + timedelta(minutes=6)), now=t0 + timedelta(minutes=6))
    assert len(lost) == 1 and "MES" in lost[0][1]
    assert w.check(market({"MNQ"}, t0 + timedelta(minutes=7)), now=t0 + timedelta(minutes=7)) == []   # once
    back = w.check(market({"MNQ", "MES"}, t0 + timedelta(minutes=8)), now=t0 + timedelta(minutes=8))
    assert back and back[0][0].startswith("✅")


def test_stall_alert_only_while_open(tmp_path):
    w = Watchdog(str(tmp_path))
    t0 = et(2026, 10, 6, 10, 0).astimezone(timezone.utc)
    w.check(market(set(), t0), now=t0)
    stale = t0 + timedelta(minutes=30)
    assert any("No new candles" in b for _, b in w.check(market(set(), t0), now=stale))
    sat = et(2026, 10, 10, 12, 0).astimezone(timezone.utc)
    w2 = Watchdog(str(tmp_path / "x"))
    assert w2.check(market(set(), sat - timedelta(hours=10)), now=sat) == []


def test_daily_check_once_per_weekday(tmp_path):
    w = Watchdog(str(tmp_path))
    t = et(2026, 10, 6, 8, 31).astimezone(timezone.utc)
    first = w.check(market({"MNQ", "MES"}, t), now=t)
    assert len(first) == 1 and "systems check" in first[0][0]
    assert w.check(market({"MNQ", "MES"}, t), now=t + timedelta(minutes=1)) == []
