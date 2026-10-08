"""Each Lucid account follows the trades it was actually in, at its own size."""
from types import SimpleNamespace

from backend.account import PropAccount
from backend.accounts import AccountBook


def engine():
    return SimpleNamespace(account=PropAccount(), bots={}, broker=None, market=None)


def test_accounts_get_their_own_size_and_pnl(tmp_path):
    book = AccountBook(str(tmp_path))
    thin = book.add("Thin", "evaluation", 48_600, 48_000, webhook="https://tp/thin")   # near the MLL: 3 micros max
    full = book.add("Full", "evaluation", 50_000, 48_000, webhook="https://tp/full")
    copy = book.add("Copy", "funded", 52_000, 50_100)                                 # copies every trade
    e = engine()
    book.observe(e, [{"type": "trade_open", "bot": "b", "contract": "MNQ LONG", "qty": 3}])
    book.observe(e, [{"type": "trade_add", "bot": "b", "qty": 3, "total": 6, "why": "PROC"}])
    assert book.in_trade["b"] == {thin.id: 3, full.id: 6, copy.id: 6}
    assert book.add_targets("b") == ["https://tp/full"]
    book.observe(e, [{"type": "trade_close", "bot": "b", "pnl": 600.0, "trade_pnl": 600.0, "reason": "x"}])
    assert thin.account.balance == 48_900 and full.account.balance == 50_600 and copy.account.balance == 52_600


def test_trims_follow_each_accounts_size(tmp_path):
    book = AccountBook(str(tmp_path))
    a = book.add("A", "evaluation", 50_000, 48_000, webhook="https://tp/a")
    e = engine()
    book.observe(e, [{"type": "trade_open", "bot": "b", "contract": "MNQ LONG", "qty": 3},
                     {"type": "trade_add", "bot": "b", "qty": 3, "total": 6, "why": "PROC"},
                     {"type": "trade_trim", "bot": "b", "qty": 2, "left": 4, "pnl": 200.0, "price": 1, "why": "zone"}])
    assert book.target_qty("b") == {"https://tp/a": 4} and a.account.balance == 50_200
    book.observe(e, [{"type": "trade_close", "bot": "b", "pnl": -40.0, "trade_pnl": 160.0, "reason": "x"}])
    assert a.account.balance == 50_160 and a.account.loss_streak == 0   # the whole trade won


def test_stopped_accounts_skip_new_entries(tmp_path):
    book = AccountBook(str(tmp_path))
    done = book.add("Done", "evaluation", 50_000, 48_000, webhook="https://tp/done")
    done.account.halted = "profit target reached"
    book.add("Live", "evaluation", 50_000, 48_000, webhook="https://tp/live")
    book.observe(engine(), [{"type": "trade_open", "bot": "b", "contract": "MNQ LONG", "qty": 3}])
    assert book.entry_targets("b") == ["https://tp/live"]


def test_webhooks_stay_on_the_server(tmp_path):
    book = AccountBook(str(tmp_path))
    book.add("A", "evaluation", 50_000, 48_000, webhook="https://tp/secret-token")
    assert "secret-token" not in str(book.status())
    assert AccountBook(str(tmp_path)).accounts[0].webhook == "https://tp/secret-token"   # but persisted


def test_alerts_only_when_an_account_differs_from_the_bots(tmp_path):
    book = AccountBook(str(tmp_path))
    acc = book.add("A", "evaluation", 50_000, 48_000, webhook="https://tp/a")
    e = engine()
    acc.account.halted = ""
    acc.account.closed("b", "", -700)          # this account alone is past its daily stop
    alerts = book.observe(e, [])
    assert alerts and alerts[0]["what"] == "halt"
    e.account.halted = "daily stop"            # the bots stopped for everyone: no extra alert
    acc2 = book.add("B", "evaluation", 50_000, 48_000)
    acc2.account.closed("b", "", -700)
    assert not book.observe(e, [])
