import pytest

from backend.account import PropAccount
from backend.backtest import ReplayMarket
from backend.engine import Engine
from backend.signals import SignalLog


@pytest.fixture(scope="module")
def logged(real_data, tmp_path_factory):
    d = tmp_path_factory.mktemp("signals")
    market = ReplayMarket(real_data)
    engine = Engine(market=market, account=PropAccount())
    log = SignalLog(str(d))
    market.step(); engine.market = market
    log.start_day(engine)
    opens = 0
    while market.has_next():
        evs = engine.tick()
        opens += sum(1 for e in evs if e["type"] == "trade_open" and engine.bots[e["bot"]].cfg.underlying == "MNQ")
        log.observe(engine, evs)
    log.finish(engine)
    return log, opens


def test_every_traded_proc_is_logged_with_its_chart(logged):
    log, opens = logged
    days = log.days()
    assert sum(d["signals"] for d in days) == opens > 0
    doc = log.get(days[-1]["day"]) if days[-1]["signals"] else log.get(days[0]["day"])
    s = doc["signals"][0]
    assert s["tf"] in (3, 4, 5, 6) and s["side"] in ("long", "short") and len(s["candles"]) > 20
    assert s["clock"] <= s["closed"]                  # labelled by the candle's open, like TradingView
    assert any(doc["counts"].values())                # PROCs seen per killzone


def test_votes_and_missed(logged):
    log, _ = logged
    day = next(d for d in log.days() if d["signals"])["day"]
    sig = log.get(day)["signals"][0]["id"]
    log.vote(day, sig, "no", "no PROC on my 3m chart")
    assert log.stats()["reviewed"] == 1 and log.stats()["match_pct"] == 0.0
    log.vote(day, sig, "yes")
    assert log.stats()["match_pct"] == 100.0
    log.add_missed(day, "09:42", 3, "long")
    assert log.stats()["missed"] == 1
    with pytest.raises(ValueError):
        log.add_missed(day, "9am", 3, "long")
    with pytest.raises(KeyError):
        log.vote(day, "nope", "yes")
    assert log.get("../../etc/passwd") is None
