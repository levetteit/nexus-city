"""Lucid's rules: they decide whether the account lives, passes and pays out."""
import pytest

from backend.account import PropAccount


def day(acct, pnl):
    """Close one trade worth `pnl` and end the day."""
    acct.closed("bot", "MNQ", pnl)
    acct.end_of_day()


def test_eod_drawdown_trails_closes_and_locks():
    a = PropAccount()
    assert a.mll == 48_000
    day(a, 1_000)
    assert a.mll == 49_000                 # trails the highest close
    day(a, -500)
    assert a.mll == 49_000                 # never moves down
    day(a, 1_700)                          # closes at 52,200 > 52,100
    assert a.mll == 50_100 and a.mll_locked


def test_consistency_raises_the_target():
    a = PropAccount()
    day(a, 1_600)                          # best day > 50% of $3,000
    assert a.target_needed == pytest.approx(3_200)


def test_passing_moves_to_a_fresh_funded_account():
    a = PropAccount()
    day(a, 1_400)
    day(a, 1_400)
    assert a.phase == "evaluation"         # $2,800 < $3,000
    day(a, 400)
    assert a.phase == "funded" and a.balance == 50_000 and a.mll == 48_000


def test_daily_stop_shrinks_near_the_mll_and_size_drops():
    a = PropAccount()
    a.sync("evaluation", 48_600, 48_000)
    assert a.day_stop == pytest.approx(350)   # $600 room - $250 cushion
    assert a.max_micros == 3


def test_touching_the_mll_fails_the_account():
    a = PropAccount()
    assert a.check(-2_000) == "max loss limit"
    assert a.phase == "failed" and not a.can_trade


def test_daily_cap_and_goal():
    a = PropAccount()
    a.closed("bot", "MNQ", 650)
    assert a.goal_reached and a.request("bot", "MNQ", 3) == 0       # no new entries after the goal
    assert a.request("bot", "MNQ", 3, adding=True) == 3               # open trades may still add
    assert "cap" in a.check(600)                                      # +$1,250 open + closed -> flatten


def funded(balance=50_000, mll=48_000, payouts=0, cycle=0):
    a = PropAccount()
    a.sync("funded", balance, mll, payouts, cycle)
    return a


def test_payout_needs_five_150_days_and_500_minimum():
    a = funded()
    for _ in range(4):
        day(a, 1_000)
    day(a, 100)                            # under $150: doesn't count
    assert a.cycle_days == 4 and not a.payout_eligible
    day(a, 1_000)
    assert a.cycle_days == 5 and a.payout_eligible
    assert a.payout_limit == 2_000         # 50% of $5,100, capped at $2,000

    small = funded()
    for _ in range(5):
        day(small, 160)
    assert small.payout_limit == 400 and not small.payout_eligible   # under the $500 minimum


def test_payout_cycle_must_be_net_positive():
    a = funded(55_000, 50_100, payouts=1, cycle=0)
    for pnl in (300, 300, 300, 300, 300, -2_000):
        day(a, pnl)
    assert a.cycle_days == 5 and not a.payout_eligible


def test_taking_a_payout_locks_the_mll_and_restarts_the_cycle():
    a = funded()
    for _ in range(5):
        day(a, 1_000)
    assert a.safe_payout == 2_000           # $55,000 - $50,100 - $1,500 keep-room = $3,400 > limit
    with pytest.raises(ValueError):
        a.take_payout(2_500)                # over the limit
    with pytest.raises(ValueError):
        a.take_payout(400)                  # under the minimum
    a.take_payout(2_000)
    assert a.balance == 53_000 and a.mll == 50_100 and a.mll_locked
    assert a.cycle_days == 0 and not a.payout_eligible and len(a.payouts) == 1


def test_suggested_payout_keeps_room_above_the_mll():
    a = funded(52_700, 50_100, payouts=1, cycle=5)
    a.cycle_start = 52_000
    assert a.payout_eligible and a.payout_limit == 1_350
    assert a.safe_payout == 1_100           # 52,700 - 50,100 - 1,500


def test_five_payouts_then_none():
    a = funded(60_000, 50_100, payouts=5, cycle=5)
    a.cycle_start = 55_000
    assert not a.payout_eligible


def test_funded_scaling_plan_by_profit():
    assert funded().scale_micros == 20
    assert funded(51_500, 49_500).scale_micros == 30
    assert funded(52_500, 50_100).scale_micros == 40


def test_sync_with_todays_real_pnl_lifts_a_stop_from_trades_that_never_reached_the_account():
    a = PropAccount()
    a.filled("mnq-3m", "MNQ", 6)
    a.closed("mnq-3m", "MNQ", -420.0)          # paper trades before real orders worked
    a.filled("mnq-6m", "MNQ", 3)
    a.closed("mnq-6m", "MNQ", -286.0)          # the one trade that really happened
    assert a.check(0.0) and a.halted.startswith("daily stop")
    a.sync("evaluation", 49_714.0, 48_000.0, day_pnl=-286.0)
    assert a.halted == "" and a.day_pnl == -286.0 and a.check(0.0) is None and a.can_trade
    a.filled("mnq-3m", "MNQ", 3)
    a.closed("mnq-3m", "MNQ", -320.0)          # the real day reaches -$606: the stop applies again
    assert a.check(0.0) and a.halted.startswith("daily stop")
    b = PropAccount()                          # without day_pnl a sync keeps the paper day, as before
    b.closed("x", "MNQ", -100.0)
    b.sync("evaluation", 49_900.0, 48_000.0)
    assert b.day_realized == -100.0


def test_engine_brings_stopped_bots_back_after_a_sync():
    from backend.engine import Engine
    e = Engine()
    e.account.closed("x", "MNQ", -700.0)
    e._risk_check()
    stopped = [b for b in e.bots.values() if b.status == "stopped"]
    assert stopped and e.account.halted
    walked = stopped[0]
    walked.status = "walked"                                  # the strategy's own decision stays
    e.account.sync("evaluation", 49_714.0, 48_000.0, day_pnl=-286.0)
    back = e.resume_after_sync()
    assert walked.cfg.id not in back and all(e.bots[i].status == "scanning" for i in back) and len(back) == len(stopped) - 1
    assert e.events[-1]["type"] == "account_resumed"
