"""Crash safety of the app's files: atomic JSON writes, append-only logs that survive a torn last line, and money
that is never booked twice."""
import json
import os

import pytest

from backend import persist
from backend.station.economy import Treasury
from backend.station.store import Store


def test_atomic_write_replaces_whole_file_and_leaves_no_temp(tmp_path):
    path = tmp_path / "state.json"
    persist.write_json_atomic(str(path), {"a": 1})
    persist.write_json_atomic(str(path), {"a": 2})
    assert json.loads(path.read_text()) == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_a_crash_mid_write_keeps_the_previous_version(tmp_path, monkeypatch):
    path = tmp_path / "execution.json"
    persist.write_json_atomic(str(path), {"armed": False, "open": {}})

    def crash(obj, f, **kw):
        f.write('{"armed": tr')   # half the new file is on disk...
        raise OSError("disk full")  # ...when the write dies
    monkeypatch.setattr(persist.json, "dump", crash)
    with pytest.raises(OSError):
        persist.write_json_atomic(str(path), {"armed": True, "open": {"MNQ": {}}})
    assert json.loads(path.read_text()) == {"armed": False, "open": {}}
    assert [p.name for p in tmp_path.iterdir()] == ["execution.json"]


def test_torn_audit_log_line_is_set_aside_and_the_log_keeps_working(tmp_path):
    s = Store(str(tmp_path))
    s.event("test.one", "test", "first")
    with open(s.events_path, "a") as f:
        f.write('{"at": "2026-10-08T00:00:00+00:00", "kind": "test.tw')   # the app died mid-append
    again = Store(str(tmp_path))                                           # restart
    again.event("test.two", "test", "after the restart")
    kinds = [e["kind"] for e in again.events(10)]
    assert kinds[:3] == ["test.two", "storage.repaired", "test.one"]
    torn = [p for p in os.listdir(again.dir) if p.startswith("events.jsonl.torn-")]
    assert torn and "test.tw" in open(os.path.join(again.dir, torn[0])).read()   # kept for review, not lost
    with open(again.events_path) as f:
        assert all(json.loads(line) for line in f)                       # every line in the log parses


def test_events_are_read_incrementally_and_skip_a_line_still_being_written(tmp_path):
    s = Store(str(tmp_path))
    s.event("a.one", "t", "1")
    assert s.events(5)[0]["kind"] == "a.one"
    with open(s.events_path, "a") as f:
        f.write('{"at": "x", "kind": "a.half"')                               # not finished yet
    assert s.events(5)[0]["kind"] == "a.one"
    with open(s.events_path, "a") as f:
        f.write(', "by": "t", "summary": "2", "severity": "INFO"}\n')         # now it is
    assert [e["kind"] for e in s.events(5)][:2] == ["a.half", "a.one"]
    assert [e["kind"] for e in s.events(5, ("a.one",))] == ["a.one"]


def test_torn_ledger_still_loads_with_an_intact_chain(tmp_path):
    s = Store(str(tmp_path))
    t = Treasury(s)
    t.book("expense", 5, "station", "owner", "domain")
    t.book("income", 20, "station", "owner", "sale")
    with open(t.path, "a") as f:
        f.write('{"at": "2026-10-08", "kind": "inco')
    again = Treasury(Store(str(tmp_path)))
    assert len(again.entries) == 2 and again.verify_chain()["intact"]
    again.book("expense", 1, "station", "owner", "after restart")
    assert len(Treasury(Store(str(tmp_path))).entries) == 3
    assert any(e["kind"] == "storage.repaired" for e in again.store.events(20))


def test_an_unreadable_ledger_line_is_skipped_and_reported(tmp_path):
    s = Store(str(tmp_path))
    t = Treasury(s)
    t.book("expense", 5, "station", "owner", "domain")
    with open(t.path, "a") as f:
        f.write("not json\n")
    again = Treasury(Store(str(tmp_path)))
    assert len(again.entries) == 1 and again.bad_lines == 1


def test_a_lucid_payout_is_never_booked_twice(tmp_path):
    t = Treasury(Store(str(tmp_path)))

    class Account:
        payouts = [(12, 1000.0)]
    assert t.sync_payouts(Account()) == 1
    t.cfg["payouts_synced"] = 0   # as if the app crashed after booking, before saving the counter
    t.sync_payouts(Account())
    assert sum(1 for e in t.entries if e["kind"] == "lucid_payout") == 1


def test_counters_and_collections_survive_a_restart(tmp_path):
    s = Store(str(tmp_path))
    v = s.create("ventures", {"name": "Test venture", "stage": "research"}, "test")
    again = Store(str(tmp_path))
    assert again.get("ventures", v["id"])["name"] == "Test venture"
    w = again.create("ventures", {"name": "Next", "stage": "research"}, "test")
    assert w["id"] != v["id"]
