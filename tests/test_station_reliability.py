"""ULTRON's settings under concurrent writers (audit M-6) and Claude being busy (audit M-8). Claude is faked."""
import json
import threading

import pytest

from backend.station import ultron as ultron_mod
from backend.station.ultron import Ultron
from tests.test_station import MON_0900, FakeClaude, opp


# ---------------------------------------------------------------- M-6: the settings file is always a whole snapshot
def test_saving_settings_survives_a_change_from_another_thread(tmp_path, monkeypatch):
    u = Ultron(str(tmp_path), client=None)
    real_dumps, calls = json.dumps, []

    def interrupted_once(obj, *a, **kw):                # what json.dumps raises when another thread changes the dict
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("dictionary changed size during iteration")
        return real_dumps(obj, *a, **kw)
    monkeypatch.setattr(ultron_mod.json, "dumps", interrupted_once)
    u.cfg["outbound"] = False
    u._save_cfg()                                         # retried, not crashed
    saved = json.loads((tmp_path / "station" / "docs" / "ultron.json").read_text())
    assert saved["outbound"] is False and len(calls) == 2


def test_many_writers_never_break_a_save(tmp_path):
    u = Ultron(str(tmp_path), client=None)
    stop, errors = threading.Event(), []

    def writer():                                        # the API thread adding and removing a key, under the lock
        i = 0
        try:
            while not stop.is_set():
                with u.cfg_lock:
                    u.cfg[f"k{i % 50}"] = i
                    u.cfg.pop(f"k{(i + 25) % 50}", None)
                i += 1
        except Exception as exc:   # a writer that dies would make this test pass for nothing
            errors.append(exc)
    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(200):
            try:
                u._save_cfg()
            except Exception as exc:   # pragma: no cover - the failure this test exists to catch
                errors.append(exc)
    finally:
        stop.set()
        t.join()
    assert errors == []
    json.loads((tmp_path / "station" / "docs" / "ultron.json").read_text())   # a whole, valid file


def test_outside_writers_take_the_settings_lock(tmp_path):
    from backend import jarvis
    u = Ultron(str(tmp_path), client=None)
    taken = []

    class Recording:
        def __init__(self, lock): self.lock = lock
        def __enter__(self): taken.append(1); return self.lock.__enter__()
        def __exit__(self, *a): return self.lock.__exit__(*a)
    u.cfg_lock = Recording(u.cfg_lock)
    jarvis.act(u, {"op": "warroom"})
    jarvis.act(u, {"op": "routine.run", "id": "R-001"})
    assert len(taken) >= 2 and u.cfg["warroom_now"] is True and "R-001" in u.cfg["run_now"]


# ---------------------------------------------------------------- M-8: a busy Claude is a wait, not a failure
def _api_error(status):
    import anthropic
    import httpx2 as httpx
    resp = httpx.Response(status, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    body = {"type": "error", "error": {"type": "overloaded_error" if status == 529 else "rate_limit_error"}}
    if status == 429:
        return anthropic.RateLimitError("rate limited", response=resp, body=body)
    return anthropic.APIStatusError("Overloaded" if status == 529 else "server error", response=resp, body=body)


def _task_job(tmp_path):
    fake = FakeClaude([opp("x")])
    u = Ultron(str(tmp_path), client=fake)
    v = u.store.create("ventures", {"name": "Copy shop", "stage": "operate", "planned": True}, "test")
    t = u.store.create("tasks", {"title": "write the copy", "venture": v["id"], "assigned_agent": "A-006", "kind": "agent",
                                 "status": "queued", "depends_on": [], "attempts": 0, "instructions": "",
                                 "expected_output": "", "success_criteria": ""}, "test")
    return u, fake, t


@pytest.mark.parametrize("status", [429, 529, 503])
def test_a_busy_claude_keeps_the_task_and_waits_a_little(tmp_path, status):
    u, fake, t = _task_job(tmp_path)

    def busy(**kw):
        raise _api_error(status)
    fake.beta.messages.create = busy
    u.run_job({"kind": "task", "task": t["id"]}, now=MON_0900)
    task = u.store.get("tasks", t["id"])
    assert task["status"] == "queued" and task["attempts"] == 0                    # back in the queue, slot kept
    until = ultron_mod.datetime.fromisoformat(u.cfg["ai_backoff_until"])
    assert until - MON_0900 == ultron_mod.AI_BUSY_BACKOFF                          # minutes, not the 20 for an outage
    kinds = [e["kind"] for e in u.store.events(20)]
    assert "ultron.ai_busy" in kinds and "ultron.job_failed" not in kinds


def test_a_real_error_still_fails_the_task(tmp_path):
    import anthropic
    import httpx2 as httpx
    u, fake, t = _task_job(tmp_path)
    resp = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    def bad(**kw):
        raise anthropic.BadRequestError("prompt too long", response=resp, body={"type": "error"})
    fake.beta.messages.create = bad
    u.run_job({"kind": "task", "task": t["id"]}, now=MON_0900)
    assert u.store.get("tasks", t["id"])["status"] == "failed"
    assert "ultron.job_failed" in [e["kind"] for e in u.store.events(20)]
