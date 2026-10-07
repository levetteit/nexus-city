"""Jarvis works the board for the owner; money, accounts and the trading desk stay the owner's."""
import pytest

from backend import jarvis
from backend.station.ultron import Ultron


@pytest.fixture
def st(tmp_path):
    return Ultron(str(tmp_path), client=None)


def _task(st, **kw):
    return st.store.create("tasks", {"title": "Draft the pin copy", "venture": "V-PPS", "assigned_agent": "A-006", "kind": "agent",
                                     "priority": 1, "day": 1, "instructions": "", "depends_on": [], "status": "failed",
                                     "attempts": 2, "escalated": True, "output": None, **kw}, "test")


def test_retry_and_cancel_tasks_unblock_the_work(st):
    t = _task(st)
    after = _task(st, title="Post it", status="queued", attempts=0, escalated=False, depends_on=[t["id"]])
    assert jarvis.act(st, {"op": "task.retry", "id": t["id"]})["status"] == "queued"
    jarvis.act(st, {"op": "task.cancel", "id": t["id"], "why": "superseded"})
    from backend.station import crew
    assert crew.ready(st.store, st.store.get("tasks", after["id"]))   # a cancelled dependency no longer blocks
    ev = st.store.events(5)
    assert any(e["by"] == "jarvis" for e in ev)                      # every move is on the audit log


def test_owner_tasks_that_need_an_account_stay_the_owners(st):
    t = _task(st, kind="owner", status="waiting_owner", assigned_agent="OWNER", title="Create the Fiverr seller account")
    with pytest.raises(jarvis.Refused):
        jarvis.act(st, {"op": "task.done", "id": t["id"], "why": "done"})
    t2 = _task(st, kind="owner", status="waiting_owner", assigned_agent="OWNER", title="Pick the cover color")
    assert jarvis.act(st, {"op": "task.done", "id": t2["id"], "why": "navy, matches the brand"})["status"] == "done"


def test_money_kill_and_the_desk_are_refused(st):
    a = st.store.create("approvals", {"kind": "spend", "action": "Buy Printify Premium", "cost": 29, "status": "pending",
                                      "payload": {}}, "test")
    with pytest.raises(jarvis.Refused):
        jarvis.act(st, {"op": "approval.decide", "id": a["id"], "decision": "approve", "why": "x"})
    with pytest.raises(jarvis.Refused):
        jarvis.act(st, {"op": "venture.stage", "id": "V-001", "stage": "paused", "why": "x"})
    with pytest.raises(jarvis.Refused):
        jarvis.act(st, {"op": "venture.stage", "id": "V-PPS", "stage": "killed", "why": "x"})
    assert jarvis.act(st, {"op": "venture.stage", "id": "V-PPS", "stage": "paused", "why": "test"})["stage"] == "paused"


def test_fix_a_draft_and_send_it_back_through_qa(st):
    a = st.store.create("actions", {"kind": "social.post", "agent": "A-006", "venture": "V-PPS", "status": "rejected", "qa": None,
                                    "revisions": 1, "result": None, "why": "post",
                                    "payload": {"platform": "facebook", "text": "Pagos desde $100", "link": ""}}, "test")
    out = jarvis.act(st, {"op": "action.edit", "id": a["id"], "payload": {"text": "Financiamiento disponible", "link": "x"}})
    assert out["status"] == "qa" and out["payload"]["text"] == "Financiamiento disponible" and out["payload"]["link"] == ""


def test_directive_reaches_the_crew_and_the_war_room(st):
    from backend.station import crew
    jarvis.act(st, {"op": "directive", "why": "Every Padilla post ends with the WhatsApp call to action", "applies_to": "V-PPS"})
    assert "WhatsApp" in crew.lessons_text(st.store, "Content Strategist", "V-PPS")
    assert st.store.events(1, ("owner.feedback",))


def test_routine_run_now_and_unknown_ops(st):
    rid = st.store.all("routines")[0]["id"]
    jarvis.act(st, {"op": "routine.run", "id": rid})
    assert st.cfg["run_now"] == [rid]
    with pytest.raises(ValueError):
        jarvis.act(st, {"op": "account.arm"})
