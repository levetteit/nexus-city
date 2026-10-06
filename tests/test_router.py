"""Real orders: what goes to which TradersPost webhook. Mistakes here cost real money."""
import asyncio
from types import SimpleNamespace

import pytest

from backend.execution import TradersPostRouter, front_month

SHARED, A, B = "https://tp/shared", "https://tp/a", "https://tp/b"


def engine():
    bot = SimpleNamespace(cfg=SimpleNamespace(instrument="future", underlying="MNQ"))
    market = SimpleNamespace(underlyings={"MNQ": SimpleNamespace(price=25_000.0)})
    return SimpleNamespace(bots={"mnq-3m": bot}, market=market)


class Book:
    """Stands in for accounts.AccountBook: A and B join the trade, only A takes the add, A ends up with 4."""
    def entry_targets(self, bot): return [A, B]
    def add_targets(self, bot): return [A]
    def target_qty(self, bot): return {A: 4, B: 3}


def router(tmp_path, shared=()):
    r = TradersPostRouter(str(tmp_path), webhooks=list(shared))
    r.account_urls = lambda: [A, B]
    r.armed, r.queue = True, asyncio.Queue()
    return r


def sent(r):
    out = []
    while not r.queue.empty():
        _, payload, _, targets = r.queue.get_nowait()
        out += [(t, payload["action"], payload.get("quantity")) for t in targets]
    return out


OPEN = {"type": "trade_open", "bot": "mnq-3m", "contract": "MNQ LONG", "qty": 3, "entry": 25_000}
ADD = {"type": "trade_add", "bot": "mnq-3m", "qty": 3, "total": 6, "why": "PROC"}
TRIM = {"type": "trade_trim", "bot": "mnq-3m", "qty": 2, "left": 4, "pnl": 100, "price": 1, "why": "zone"}
CLOSE = {"type": "trade_close", "bot": "mnq-3m", "pnl": 50, "trade_pnl": 150, "reason": "pointer against"}


def test_per_account_open_add_trim_close(tmp_path):
    r = router(tmp_path, [SHARED])
    r.handle(engine(), [OPEN, ADD, TRIM, CLOSE], 0.5, Book())
    orders = sent(r)
    assert (SHARED, "buy", 3) in orders and (A, "buy", 3) in orders and (B, "buy", 3) in orders
    assert (SHARED, "add", 3) in orders and (A, "add", 3) in orders and (B, "add", 3) not in orders
    assert (SHARED, "resize", 4) in orders                  # the shared strategy follows the bot: 6 -> 4
    assert (A, "resize", 4) in orders                       # A took the add (6), the book says 4 now
    assert not [o for o in orders if o[0] == B and o[1] == "resize"]   # B never added: still 3
    assert {(t, a) for t, a, _ in orders if a == "exit"} == {(SHARED, "exit"), (A, "exit"), (B, "exit")}


def test_trim_resizes_each_account_to_its_own_size(tmp_path):
    class Book2(Book):
        def target_qty(self, bot): return {A: 2, B: 3}
    r = router(tmp_path)
    r.handle(engine(), [OPEN, ADD, TRIM], 0.5, Book2())
    orders = sent(r)
    assert (A, "resize", 2) in orders                       # A had 6, book says 2
    assert not [o for o in orders if o[0] == B and o[1] == "resize"]   # B already at 3


def test_stale_data_blocks_entries_but_never_exits(tmp_path):
    r = router(tmp_path)
    r.handle(engine(), [OPEN], 5.0, Book())                 # data 5 minutes old
    assert sent(r) == [] and r.blocked == 1
    r.open["MNQ"] = {"side": "buy", "qty": 3, "contract": "MNQZ2026", "targets": {A: 3}}
    r.handle(engine(), [CLOSE], 5.0, Book())
    assert sent(r) == [(A, "exit", None)]


def test_no_account_may_trade_means_no_order(tmp_path):
    class Closed(Book):
        def entry_targets(self, bot): return []
    r = router(tmp_path)
    r.handle(engine(), [OPEN], 0.5, Closed())
    assert sent(r) == [] and "MNQ" not in r.open


def test_restart_closes_leftover_positions(tmp_path):
    r = router(tmp_path)
    r.open["MNQ"] = {"side": "buy", "qty": 3, "contract": "MNQZ2026", "targets": [A]}   # older saved format
    r._save()
    r2 = TradersPostRouter(str(tmp_path), webhooks=[])
    r2.account_urls = lambda: [A]

    async def go():
        closed = r2.start()
        return closed, r2.queue.get_nowait()
    closed, (_, payload, _, targets) = asyncio.run(go())
    assert closed == ["MNQ"] and payload["action"] == "exit" and targets == [A]


@pytest.mark.parametrize("day,expected", [("2026-10-06", "MNQZ2026"), ("2026-12-10", "MNQH2027"), ("2027-03-01", "MNQH2027")])
def test_front_month_rolls_eight_days_before_expiry(day, expected):
    from datetime import date
    assert front_month("MNQ", date.fromisoformat(day)) == expected
