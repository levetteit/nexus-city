"""The Strategy Forge: honest tests, a paper shadow, and nothing goes live without the owner."""
from datetime import date, datetime, timedelta

import pytest

from backend import forge
from backend.backtest import ET


def fake_days(n=20, start=date(2026, 9, 1)):
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    rows = [(datetime(x.year, x.month, x.day, 10, 0, tzinfo=ET), 1.0, 1.0, 1.0, 1.0) for x in days]
    return {"MNQ": rows, "MES": list(rows)}, days


def result(total, green=60.0, worst=-300.0, failed=0):
    return {"total": total, "days_traded": 5, "profitable_day_pct": green, "worst_day": worst, "best_day": 500,
            "trades": 10, "win_rate": 50, "profit_factor": 1.5, "evals_failed": failed}


def test_candidates_are_changes_to_the_live_settings_never_zone_settings():
    base = {k: v[0] for k, v in forge.KNOBS.items()}
    cs = forge.candidates(base, 40, seed=1)
    assert len(cs) == 40 and base not in cs
    assert len({str(sorted(c.items())) for c in cs}) == 40
    assert all(set(c) == set(forge.KNOBS) for c in cs)
    assert "pivot_len" not in forge.KNOBS and "use_iffvg" not in forge.KNOBS   # those match the owner's chart
    assert forge.candidates(base, 40, seed=1) == cs                              # a run repeats


def test_forge_needs_enough_days_and_a_win_on_every_split():
    data, days = fake_days(20)
    base = {k: v[0] for k, v in forge.KNOBS.items()}

    def run(d, params):
        n = len(forge._days(d))
        if params.get("trim"):
            return result(150.0 * n, green=70)                 # better everywhere
        if params.get("walk_after") == 4:
            first = min(forge._days(d)) == days[0]
            return result(400.0 * n if first else -50.0 * n, green=80)   # great on early days only: overfit
        return result(100.0 * n)
    out = forge.forge(data, base, run=run, n=40)
    assert out["ok"] and out["tried"] == 40
    assert out["winner"]["change"] == {"trim": True}
    overfit = [f for f in out["finalists"] if f["change"] == {"walk_after": 4}]
    assert overfit and not overfit[0]["passed"]                 # beat training as a whole, failed the second half
    short, _ = fake_days(10)
    assert not forge.forge(short, base, run=run)["ok"]


def test_shadow_scoring_proposes_only_after_it_holds_up(tmp_path):
    d = str(tmp_path)
    st = forge.state(d)
    st["shadow"] = {"params": {}, "change": {"trim": True}, "since": "2026-09-05", "backtest": {}, "days": []}
    forge.save_state(d, st)
    data, days = fake_days(30)
    later = [x for x in days if str(x) > "2026-09-05"]
    replay = lambda data_, key, params: 120.0 if params.get("trim") else 80.0
    for x in later[:9]:
        assert forge.score_shadow_day(d, x, data, replay)["verdict"] is None
    assert forge.score_shadow_day(d, later[0], data, replay) is None             # each day once
    assert forge.score_shadow_day(d, later[9], data, replay)["verdict"] == "promote"
    p = forge.state(d)["proposal"]
    assert p["params"] == {"trim": True} and p["shadow"]["shadow_total"] == 1200 and p["shadow"]["live_total"] == 800

    st = forge.state(d)                                                           # a shadow that lags is retired
    st["proposal"] = None
    st["shadow"] = {"params": {}, "change": {"walk_after": 2}, "since": "2026-09-05", "backtest": {}, "days": []}
    forge.save_state(d, st)
    worse = lambda data_, key, params: 50.0 if params.get("walk_after") == 2 else 80.0
    verdicts = [forge.score_shadow_day(d, x, data, worse)["verdict"] for x in later[:10]]
    assert verdicts[-1] == "retire" and forge.state(d)["shadow"] is None and forge.state(d)["retired"]


def test_promotion_is_saved_and_switches_in_at_the_session_roll(tmp_path):
    from backend.engine import Engine
    d = str(tmp_path)
    forge.promote(d, {"trim": True, "pivot_len": 2}, "test")
    assert forge.live_params(d) == {"trim": True}                                 # zone settings never promoted
    assert forge.baseline(d)["trim"] is True
    e = Engine()
    bot = next(iter(e.bots.values()))
    before = bot.p["pivot_len"]
    e.pending_params = forge.live_params(d)
    day = e.market.day
    while e.market.day == day:
        e.tick()
    assert all(b.p["trim"] is True and b.cfg.params["trim"] is True for b in e.bots.values())
    assert bot.p["pivot_len"] == before and e.pending_params is None


def test_replay_day_runs_on_real_candles(real_data):
    from backend.backtest import trading_day
    last = max(trading_day(r[0]) for r in real_data["MNQ"])
    a = forge.replay_day(real_data, last, None)
    assert isinstance(a, float) and a == forge.replay_day(real_data, last, None)   # deterministic: a fair A/B
