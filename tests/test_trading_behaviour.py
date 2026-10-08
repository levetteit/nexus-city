"""Approved changes to how real orders behave (audit T-H1, T-H4, T-H7, M-4, M-11). Each test states the rule it
pins down. Nothing here reaches TradersPost: orders stop in the router's queue."""
import asyncio
import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from backend import execution
from backend.execution import ET, TradersPostRouter

A, SHARED = "https://tp/a", "https://tp/shared"


def _engine(minutes_to_flat=200):
    bot = SimpleNamespace(cfg=SimpleNamespace(instrument="future", underlying="MNQ"), position=None)
    market = SimpleNamespace(underlyings={"MNQ": SimpleNamespace(price=25_000.0)}, minutes_to_flat=minutes_to_flat)
    return SimpleNamespace(bots={"mnq-3m": bot}, market=market)


def _router(tmp_path, armed=True):
    r = TradersPostRouter(str(tmp_path), webhooks=[SHARED])
    r.armed, r.queue = armed, asyncio.Queue()
    return r


def _sent(r):
    out = []
    while not r.queue.empty():
        _, payload, reason, targets = r.queue.get_nowait()
        out.append((payload["action"], payload.get("quantity"), reason))
    return out


OPEN = {"type": "trade_open", "bot": "mnq-3m", "contract": "MNQ LONG", "qty": 3, "entry": 25_000}
ADD = {"type": "trade_add", "bot": "mnq-3m", "qty": 3, "total": 6, "why": "PROC"}
TRIM = {"type": "trade_trim", "bot": "mnq-3m", "qty": 3, "left": 3, "pnl": 90, "price": 1, "why": "zone"}
CLOSE = {"type": "trade_close", "bot": "mnq-3m", "pnl": 60, "trade_pnl": 150, "reason": "pointer against"}


# ---------------------------------------------------------------- T-H1: disarming never strands a real position
def test_disarmed_router_still_trims_and_exits_what_is_open(tmp_path):
    r = _router(tmp_path)
    r.handle(_engine(), [OPEN], 0.1)
    _sent(r)
    r.arm(False)
    r.handle(_engine(), [ADD], 0.1)                                   # no new risk while disarmed
    r.handle(_engine(), [{**TRIM, "qty": 1, "left": 2}], 0.1)      # reduce risk: still sent
    r.handle(_engine(), [CLOSE], 0.1)
    assert [(a, q) for a, q, _ in _sent(r)] == [("resize", 2), ("exit", None)] and not r.open


def test_disarmed_router_opens_nothing_new(tmp_path):
    r = _router(tmp_path, armed=False)
    r.handle(_engine(), [OPEN, ADD, CLOSE], 0.1)
    assert _sent(r) == [] and not r.open


# ---------------------------------------------------------------- T-H4: time-based exits use the real clock
@pytest.fixture
def main_mod(monkeypatch):
    monkeypatch.delenv("NEXUS_PASSWORD", raising=False)
    import backend.main as main
    importlib.reload(main)
    yield main
    importlib.reload(main)


def _open_router(tmp_path):
    r = _router(tmp_path)
    r.handle(_engine(), [OPEN], 0.1)
    _sent(r)
    return r


@pytest.mark.parametrize("now, closes", [
    (datetime(2026, 10, 7, 15, 55, tzinfo=ET), True),                # Wednesday 15:55: flat now, whatever the candles say
    (datetime(2026, 10, 7, 16, 30, tzinfo=ET), True),
    (datetime(2026, 10, 7, 15, 54, tzinfo=ET), False),
    (datetime(2026, 10, 7, 18, 5, tzinfo=ET), False),                 # the new session
    (datetime(2026, 10, 10, 15, 56, tzinfo=ET), False),               # Saturday: no session
])
def test_the_session_end_flatten_follows_the_clock(main_mod, tmp_path, now, closes):
    r = _open_router(tmp_path)
    sent = []
    main_mod.notifier = SimpleNamespace(send=lambda *a, **k: sent.append(a))
    closed = main_mod._wallclock_flatten(r, None, now)
    assert bool(closed) is closes and bool(r.open) is not closes
    if closes:
        action, _, reason = _sent(r)[0]
        assert action == "exit" and "15:55" in reason and sent
        assert r.armed                                                # flat, but still armed for tomorrow


def test_a_news_flatten_follows_the_clock(main_mod, tmp_path):
    from backend.news import NewsCalendar, NewsEvent
    cpi = NewsEvent(datetime(2026, 10, 7, 8, 30, tzinfo=ET), "CPI m/m")
    cal = NewsCalendar([cpi], flatten=2)
    r = _open_router(tmp_path)
    main_mod.notifier = None
    assert main_mod._wallclock_flatten(r, cal, datetime(2026, 10, 7, 8, 27, tzinfo=ET)) == []
    assert main_mod._wallclock_flatten(r, cal, datetime(2026, 10, 7, 8, 28, 30, tzinfo=ET)) == ["MNQ"]
    assert "CPI m/m" in _sent(r)[0][2]


def test_no_new_real_entries_after_1550_by_the_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(execution, "wall_clock_et", lambda: datetime(2026, 10, 7, 15, 51, tzinfo=ET))
    r = _router(tmp_path)
    r.handle(_engine(minutes_to_flat=200), [OPEN], 0.1)              # the late candle still says 15:45
    assert _sent(r) == [] and not r.open and r.blocked == 1


# ---------------------------------------------------------------- T-H7: today's stops survive a restart
@pytest.fixture
def live_mod(tmp_path, monkeypatch):
    from backend import live
    monkeypatch.setattr(live, "DATA_DIR", str(tmp_path))
    return live


TUE_1400 = datetime(2026, 10, 6, 14, 0, tzinfo=ET)


def _halted_account(live_mod):
    acct = live_mod.load_account(now=TUE_1400)
    acct.day_realized = -450.0
    acct.halted, acct.loss_streak, acct.day_peak = "3 losing trades in a row · stop for the day", 3, 120.0
    live_mod.save_account(acct, now=TUE_1400)
    return acct


def test_a_restart_on_the_same_day_keeps_the_halt(live_mod):
    _halted_account(live_mod)
    again = live_mod.load_account(now=TUE_1400 + timedelta(hours=1))
    assert again.halted.startswith("3 losing trades") and not again.can_trade
    assert again.loss_streak == 3 and again.day_peak == 120.0 and again.day_realized == -450.0


def test_a_restart_across_the_1800_open_rolls_the_day(live_mod):
    before = _halted_account(live_mod)
    days = before.days
    again = live_mod.load_account(now=datetime(2026, 10, 6, 18, 30, tzinfo=ET))   # Wednesday's session
    assert again.days == days + 1 and again.day_history[-1][1] == -450.0
    assert again.day_realized == 0 and again.halted == "" and again.can_trade


def test_a_weekend_restart_does_not_roll_twice(live_mod):
    fri = datetime(2026, 10, 9, 16, 40, tzinfo=ET)
    acct = live_mod.load_account(now=fri)
    acct.day_realized = 200.0
    live_mod.save_account(acct, now=fri)
    # restarted on Saturday: the newest candle is still Friday's, so the engine rolls the day at Sunday's open, once
    again = live_mod.load_account(now=datetime(2026, 10, 9, 16, 44, tzinfo=ET))
    assert again.days == acct.days and again.day_realized == 200.0


def test_an_old_save_without_a_trading_day_starts_the_day_as_before(live_mod, tmp_path):
    import json
    (tmp_path / "paper_account.json").write_text(json.dumps({"balance": 50_500.0, "halted": "old", "loss_streak": 3}))
    acct = live_mod.load_account(now=TUE_1400)
    assert acct.balance == 50_500.0 and acct.halted == "" and acct.loss_streak == 0


# ---------------------------------------------------------------- M-4: the account book follows what was really sent
def _book(tmp_path):
    from backend.accounts import AccountBook
    book = AccountBook(str(tmp_path))
    acc = book.add("Lucid 1", "evaluation", 50_000, 48_000, webhook=A)
    return book, acc


def test_a_skipped_entry_books_nothing_to_the_accounts(tmp_path):
    book, acc = _book(tmp_path)
    eng = SimpleNamespace(**vars(_engine()), account=SimpleNamespace(halted="", phase="evaluation"))
    book.observe(eng, [OPEN])
    assert book.in_trade["mnq-3m"][acc.id] == 3
    r = _router(tmp_path / "r")
    r.handle(eng, [OPEN], 9.0, book)                                  # 9-minute-old data: entry skipped
    assert not r.open and book.in_trade["mnq-3m"] == {}
    balance = acc.account.balance
    book.observe(eng, [CLOSE])
    assert acc.account.balance == balance                             # the trade never reached this account


def test_a_skipped_add_is_taken_back_and_the_trim_keeps_the_real_size(tmp_path):
    book, acc = _book(tmp_path)
    eng = SimpleNamespace(**vars(_engine()), account=SimpleNamespace(halted="", phase="evaluation"))
    r = _router(tmp_path / "r")
    book.observe(eng, [OPEN])
    r.handle(eng, [OPEN], 0.1, book)
    book.observe(eng, [ADD])
    assert book.in_trade["mnq-3m"][acc.id] == 6
    r.handle(eng, [ADD], 9.0, book)                                   # stale: the add isn't sent
    assert book.in_trade["mnq-3m"][acc.id] == 3 and r.open["MNQ"]["qty"] == 3
    _sent(r)
    book.observe(eng, [TRIM])                                          # the bot trims 6 -> 3
    r.handle(eng, [TRIM], 0.1, book)
    assert _sent(r) == [] and r.open["MNQ"]["qty"] == 3               # really 3 already: no resize down to 1


# ---------------------------------------------------------------- M-11: a late symbol catches up instead of freezing
def test_late_candles_for_one_symbol_are_applied_not_dropped(monkeypatch):
    from backend import live
    t0 = datetime(2026, 10, 7, 14, 0, tzinfo=ET)
    ts = lambda m: int((t0 + timedelta(minutes=m)).timestamp())
    yahoo = {"NQ=F": {ts(0): (1, 1, 1, 1)}, "ES=F": {ts(0): (5, 5, 5, 5)}}
    monkeypatch.setattr(live, "fetch_recent", lambda sym, rng="1d": dict(yahoo[sym]))
    m = live.LiveMarket()
    while m.has_next():
        m.step()
    # the real-time feed sends NQ for minutes 1 and 2; ES only comes later from Yahoo
    for minute in (1, 2):
        m.push("MNQ", ts(minute), 2, 2, 2, 2, chart="NQ")
    m.release()
    while m.has_next():
        m.step()
    assert m.underlyings["MES"].bars[-1].close == 5                    # ES hasn't arrived yet
    yahoo["ES=F"].update({ts(1): (6, 6, 6, 6), ts(2): (7, 7, 7, 7)})
    m.poll()
    m.push("MNQ", ts(3), 3, 3, 3, 3, chart="NQ")
    m.release()
    while m.has_next():
        m.step()
    closes = [b.close for b in m.underlyings["MES"].bars[-3:]]
    assert closes == [5, 6, 7]                                         # both late ES minutes, in order
    assert m.underlyings["MES"].price == 7 and m.underlyings["MNQ"].price == 3
