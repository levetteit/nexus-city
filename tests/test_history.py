"""The TradingView feed's own candles are kept for future backtests."""
from backend.backtest import load_csv
from backend.history import History


def test_tradingview_candles_are_saved_once_and_reload(tmp_path):
    h = History(str(tmp_path))
    assert h.status()["tradingview"] == {} and h.status()["tv_days"] == 0
    t0 = 1_791_400_000                       # a weekday evening in Oct 2026 (UTC)
    assert h.record_feed("MNQ", t0, 25000, 25010, 24995, 25005, 812.0)
    assert not h.record_feed("MNQ", t0, 25000, 25010, 24995, 25005, 812.0)   # TradingView retried: kept once
    assert h.record_feed("MNQ", t0 + 60, 25005, 25012, 25001, 25008)       # an older script: no volume
    assert not h.record_feed("MNQ", t0 - 60, 1, 1, 1, 1)                   # out of order: skipped
    assert h.record_feed("MES", t0, 6800, 6801, 6799, 6800.5, None)
    s = h.status()["tradingview"]
    assert s["MNQ"]["candles"] == 2 and s["MNQ"]["volume"] and not s["MES"]["volume"]
    rows = load_csv(h.tv_path("MNQ"))                                     # the backtester reads it as is
    assert [r[4] for r in rows] == [25005, 25008]
    again = History(str(tmp_path))                                         # after a restart: same counts, same dedupe
    assert again.status()["tradingview"] == h.status()["tradingview"]
    assert not again.record_feed("MNQ", t0 + 60, 1, 1, 1, 1)
