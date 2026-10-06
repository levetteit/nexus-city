"""The whole strategy on real candles: a change that moves these numbers changes how the bots trade."""
import os

import pytest

from backend.account import PropAccount
from backend.backtest import ReplayMarket, load_csv, run
from backend.desk import TradingDesk
from backend.engine import Engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_five_real_days_regression(real_data):
    r = run(real_data)
    # Update these only when a strategy change is intended (and re-run the 21-day check below locally).
    assert (r["days"], r["trades"], round(r["total"], 2)) == (5, 18, 2755.5)


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "data", "MNQ_1m.csv")), reason="needs the 21-day data in data/")
def test_twenty_one_day_baseline():
    data = {s: load_csv(os.path.join(ROOT, "data", f"{s}_1m.csv")) for s in ("MNQ", "MES", "M2K")}
    r = run(data)
    assert round(r["total"]) == 13_224 and r["profitable_day_pct"] == 71.4


def count_events(real_data, mode):
    market = ReplayMarket(real_data)
    engine = Engine(market=market, account=PropAccount())
    if mode:
        from datetime import datetime
        from backend.backtest import ET
        desk = TradingDesk(os.path.join(ROOT, ".pytest_cache", f"desk-{mode}"), client=object())
        desk._set_mode(mode, "test", datetime(2030, 1, 1, tzinfo=ET), "test")
        engine.desk = desk
    n = {"trade_open": 0, "trade_add": 0}
    while market.has_next():
        for ev in engine.tick():
            if ev["type"] in n:
                n[ev["type"]] += 1
    return n


def test_desk_can_only_take_risk_off(real_data):
    normal = count_events(real_data, None)
    assert normal["trade_open"] > 0 and normal["trade_add"] > 0
    assert count_events(real_data, "cautious")["trade_add"] == 0
    assert count_events(real_data, "sit_out") == {"trade_open": 0, "trade_add": 0}


def test_simulated_city_runs():
    engine = Engine()
    for _ in range(2_000):
        engine.tick()
    assert engine.snapshot()["bots"]


@pytest.mark.parametrize("params", [
    {"rsi_filter": {"tf": 5, "ob": 70, "os": 30}}, {"rsi_filter": {"tf": 5, "mode": "momentum"}},
    {"day_open_bias": "discount"}, {"day_open_bias": "trend"}, {"range_bias": "discount"}, {"min_range_pts": 9},
])
def test_context_filters_run_on_real_candles(real_data, params):
    """Each optional filter runs on real candles and changes which PROCs are taken. Off by default, so
    the current settings are unchanged. (Skipping one PROC can lead to more trades later in the day,
    because the daily goal isn't reached as early.)"""
    base, filtered = run(real_data), run(real_data, params=params)
    assert filtered["days"] == base["days"] and filtered["trades"] > 0
