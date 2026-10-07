"""The Lookout watches NQ / ES and never trades; the feed prefers the full-size charts."""
from backend import live
from backend.config import WORKERS
from backend.engine import Engine


def test_m2k_is_gone_and_the_lookout_has_its_building():
    ids = [cfg.id for _, cfg in WORKERS]
    assert "m2k" not in ids and "watch" in ids
    e = Engine()
    assert "M2K" not in e.market.underlyings
    w = e.bots["watch"]
    assert w.status == "watching" and w.snapshot(e.market)["watcher"] is True


def test_lookout_reads_nq_and_es_but_never_trades():
    e = Engine()
    opened = []
    for _ in range(2400):
        opened += [ev for ev in e.tick() if ev["type"] == "trade_open" and ev["bot"] == "watch"]
    w = e.bots["watch"]
    assert not opened and w.position is None and not w.trades
    info = w.info()
    assert set(info["marks"]) == {"NQ", "ES"} and info["read"]
    # the traders' ES confirmation is the Lookout's ES read: the same shared engine, not a copy
    og = e.bots["mnq-3m"]
    assert og.partner is w.partner and og.engine is w.engine
    assert og.info()["confirm"].startswith("ES ")


def test_account_stop_sends_traders_home_but_the_lookout_keeps_watching():
    e = Engine()
    e._halt_all("daily stop")
    assert e.bots["mnq-3m"].status == "stopped" and e.bots["watch"].status == "watching"
    e.bots["watch"].new_session()
    assert e.bots["watch"].status == "watching"


def _market(monkeypatch):
    t0 = 1_791_000_000 - 1_791_000_000 % 60
    monkeypatch.setattr(live, "fetch_recent", lambda src, period: {t0 + 60 * i: (1.0, 2.0, 0.5, 1.5) for i in range(5)})
    return live.LiveMarket(["MNQ", "MES"]), t0 + 60 * 10


def test_full_size_chart_wins_over_the_micro_chart(monkeypatch):
    m, t = _market(monkeypatch)
    assert m.charts == {"MNQ": "NQ", "MES": "ES"}            # Yahoo's NQ=F / ES=F are the full-size contracts
    assert m.push("MNQ", t, 1, 2, 0.5, 1.5, "MNQ") is True    # a micro chart alone still feeds the bots
    assert m.charts["MNQ"] == "MNQ"
    assert m.push("MNQ", t + 60, 10, 20, 5, 15, "NQ") is True
    assert m.push("MNQ", t + 60, 1, 2, 0.5, 1.5, "MNQ") is False   # while NQ1! feeds, the MNQ1! alert is ignored
    assert m._pending[live.datetime.fromtimestamp(t + 60, tz=live.timezone.utc).astimezone(live.ET)]["MNQ"][1] == 10
    assert m.charts["MNQ"] == "NQ"
