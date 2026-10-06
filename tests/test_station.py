"""The Space Station: ULTRON's records, approvals, treasury rules and the research → venture → task flow,
with a fake Claude client (no network, no cost)."""
import json
from datetime import datetime
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from backend.station import economy, research
from backend.station.ultron import Ultron

ET = ZoneInfo("America/New_York")
MON_0900 = datetime(2026, 10, 5, 9, 0, tzinfo=ET)


def opp(title, cost=0, rec="build_now", score=82):
    return {"title": title, "category": "service_marketplace", "platform": "Fiverr", "summary": "AI-drafted resumes",
            "evidence": ["buyer requests"], "startup_cost_usd": cost, "monthly_cost_usd": 0, "can_start_today": True,
            "days_to_first_dollar": 3, "price_point": "$25", "demand": 7, "competition": 6, "margin_potential": 8,
            "automation_potential": 8, "speed_to_market": 9, "scalability": 5, "owner_actions": ["Create a Fiverr seller account"],
            "agent_roles": ["Service Delivery"], "platform_restrictions": "Disclose AI use", "risks": ["crowded"],
            "plan_7_day": ["[owner] sign up", "[agent] draft gig"], "kpis": ["orders"], "success_criteria": "2 orders in 14 days",
            "kill_criteria": "0 orders in 21 days", "score": score, "recommendation": rec}


PLAN = {"verdict": "go", "why": "Demand is real.", "offer": "Resume rewrite, $25", "objective": "2 orders in 14 days",
        "tasks": [{"ref": "t1", "title": "Draft the gig listing", "who": "agent", "role": "Service Delivery",
                   "instructions": "Write it", "expected_output": "Listing", "success_criteria": "Clear", "escalate_if": "",
                   "depends_on": [], "priority": 1, "day": 1},
                  {"ref": "t2", "title": "Publish the gig on Fiverr", "who": "owner", "role": "Owner",
                   "instructions": "Paste and publish", "expected_output": "Live gig", "success_criteria": "Live",
                   "escalate_if": "", "depends_on": ["t1"], "priority": 1, "day": 1}],
        "kpis": ["orders"], "success_criteria": "2 orders", "kill_criteria": "none in 21 days"}


class FakeClaude:
    """Answers like the API: research text for web-search calls, JSON for structured ones."""

    def __init__(self, opps):
        self.opps, self.calls = opps, []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        usage = NS(input_tokens=10_000, output_tokens=2_000, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                   server_tool_use=NS(web_search_requests=3 if kw.get("tools") else 0))
        fmt = (kw.get("output_config") or {}).get("format")
        if not fmt:
            return NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text="Fiverr resume gigs sell at $25.")])
        props = fmt["schema"]["properties"]
        if "opportunities" in props:
            body = {"summary": "Found some.", "opportunities": self.opps, "first_pick": self.opps[0]["title"]}
        elif "verdict" in props:
            body = PLAN
        else:
            body = {"deliverable": "# Gig: I will rewrite your resume", "notes": "Check the price.", "owner_next": ["Publish"],
                    "met_success_criteria": True}
        return NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text=json.dumps(body))])


@pytest.fixture
def ultron(tmp_path):
    fake = FakeClaude([opp("Resume rewrite gig on Fiverr"), opp("Etsy planner shop", cost=29, rec="watchlist", score=60)])
    u = Ultron(str(tmp_path), client=fake)
    return u, fake


def test_seeds_once_without_duplicates(tmp_path):
    u = Ultron(str(tmp_path), client=None)
    again = Ultron(str(tmp_path), client=None)
    assert len(again.store.all("routines")) == 5
    assert [a["name"] for a in again.store.all("agents")][:2] == ["ULTRON", "Market Research Agent"]
    assert len(again.store.all("agents")) == 4 and len(again.store.all("ventures")) == 1
    assert again.store.get("ventures", "V-001")["stage"] == "operate"
    assert u.tick(now=MON_0900) is None   # no API key: no research jobs, the rest still runs


def test_routine_schedule():
    radar, brief = research.ROUTINES[0], research.ROUTINES[4]
    assert research.due(radar, MON_0900, None)
    assert not research.due(radar, MON_0900, MON_0900.replace(hour=8, minute=5).isoformat())
    assert not research.due(radar, MON_0900.replace(hour=7), None)                 # before 08:00
    assert not research.due(radar, datetime(2026, 10, 10, 9, tzinfo=ET), None)    # Saturday
    assert not research.due(brief, MON_0900, None) and research.due(brief, MON_0900.replace(hour=10, minute=1), None)


def test_research_to_venture_to_tasks(ultron):
    u, fake = ultron
    job = u.tick(now=MON_0900)
    assert job == {"kind": "routine", "routine": "R-001"}
    u.run_job(job, now=MON_0900)
    opps = u.store.all("opportunities")
    assert len(opps) == 2 and all(o["routine"] == "R-001" for o in opps)
    # ULTRON proposes the $0 opportunity, never the one that needs capital
    pending = u.store.find("approvals", status="pending")
    assert len(pending) == 1 and "Resume rewrite" in pending[0]["action"] and pending[0]["cost"] == 0
    u.tick(now=MON_0900)
    assert len(u.store.find("approvals", status="pending")) == 1                    # one proposal at a time
    u.decide(pending[0]["id"], "approve")
    v = next(v for v in u.store.all("ventures") if v["id"] != "V-001")
    assert v["stage"] == "approved" and u.store.get("opportunities", v["opportunity"])["status"] == "promoted"
    # validation plans the venture into tasks with dependencies, staffing one specialist
    job = u.next_job(MON_0900.replace(hour=9, minute=1))
    assert job == {"kind": "plan", "venture": v["id"]}
    u.run_job(job)
    tasks = u.store.find("tasks", venture=v["id"])
    agent_task = next(t for t in tasks if t["kind"] == "agent")
    owner_task = next(t for t in tasks if t["kind"] == "owner")
    assert owner_task["depends_on"] == [agent_task["id"]]
    assert u.store.get("ventures", v["id"])["stage"] == "build"
    assert [a["role"] for a in u.store.all("agents")].count("Service Delivery") == 1
    # the agent drafts; the owner task only opens once its input is done
    u.tick(now=MON_0900.replace(hour=9, minute=2))
    assert u.store.get("tasks", owner_task["id"])["status"] == "queued"
    job = u.next_job(MON_0900.replace(hour=9, minute=2))
    assert job == {"kind": "task", "task": agent_task["id"]}
    u.run_job(job)
    assert u.store.get("tasks", agent_task["id"])["output"]["deliverable"].startswith("# Gig")
    u.tick(now=MON_0900.replace(hour=9, minute=3))
    assert u.store.get("tasks", owner_task["id"])["status"] == "waiting_owner"
    assert u.store.get("agents", agent_task["assigned_agent"])["status"] == "ON BREAK"   # idle: Crew Lounge
    u.owner_done(owner_task["id"], "gig is live")
    # every step is in the audit log
    kinds = {e["kind"] for e in u.store.events(500)}
    assert {"opportunity.created", "approval.approved", "venture.planned", "task.completed", "task.waiting_owner"} <= kinds
    # every Claude call was charged to the station
    assert u.treasury.ai_spent() == pytest.approx(len(fake.calls) * economy.usage_cost(NS(
        input_tokens=10_000, output_tokens=2_000, cache_read_input_tokens=0, cache_creation_input_tokens=0,
        server_tool_use=NS(web_search_requests=0))) + 0.03 * sum(1 for c in fake.calls if c.get("tools")), abs=0.01)


def test_owner_promotes_from_the_feed(ultron):
    u, _ = ultron
    u.run_job({"kind": "routine", "routine": "R-002"}, now=MON_0900)
    etsy = next(o for o in u.store.all("opportunities") if o["startup_cost_usd"] > 0)
    out = u.promote(etsy["id"])
    assert out["venture"]["name"] == "Etsy planner shop" and out["approval"]["status"] == "approved"
    with pytest.raises(ValueError):
        u.promote(etsy["id"])


def test_money_rules_and_cross_funding(ultron):
    u, _ = ultron
    t = u.treasury
    with pytest.raises(ValueError):
        t.book("income", 50, "station", "A-002", "an agent can't book revenue")
    with pytest.raises(ValueError):
        t.book("income", -5, "station", "owner", "negative")
    # the city's real payout carries the station: one pool
    account = NS(payouts=[[12, 1000.0]])
    assert t.sync_payouts(account) == 1 and t.sync_payouts(account) == 0          # each payout once
    s = t.summary()
    assert s["city"]["income"] == 900.0 and s["pool"] == 900.0 and s["carrying"] == "city"
    # ... which funds the Etsy goal: ULTRON asks the owner, once
    u.tick(now=MON_0900)
    funds = u.store.find("approvals", kind="fund_goal")
    assert len(funds) == 1 and funds[0]["status"] == "pending"
    u.tick(now=MON_0900)
    assert len(u.store.find("approvals", kind="fund_goal")) == 1
    # station income is recorded by the owner, and marks the mission's first dollar
    u.store.create("ventures", {"name": "Gig", "stage": "operate"}, "test")
    u.record("income", 25, "station", "first order", venture="V-002")
    assert u.store.get("missions", "M-001")["first_dollar_at"]
    assert t.pnl("venture", "V-002")["income"] == 25


def test_simulated_payouts_never_reach_the_treasury(ultron):
    u, _ = ultron
    engine = NS(bots={}, account=NS(payouts=[[3, 5000.0]], snapshot=lambda: {"profit": 5000.0}))
    u.tick(engine, now=MON_0900, real_account=False)
    assert u.treasury.summary()["pool"] == 0


def test_ai_budget_cap_stops_research(ultron, monkeypatch):
    u, fake = ultron
    monkeypatch.setattr("backend.station.economy.AI_BUDGET", 5.0)
    assert u.next_job(MON_0900) is not None
    u.treasury.book("ai_usage", 4.5, "station", "api_usage", "earlier calls")   # no room left for another call
    assert u.next_job(MON_0900) is None


def test_stalled_task_is_retried_then_escalated(ultron):
    u, _ = ultron
    t = u.store.create("tasks", {"title": "x", "venture": "V-001", "assigned_agent": "A-003", "kind": "agent", "status": "running",
                                 "depends_on": [], "attempts": 1}, "test")
    with u.store.lock:
        u.store.data["tasks"][t["id"]]["updated_at"] = "2020-01-01T00:00:00+00:00"
    u.tick(now=MON_0900)
    assert u.store.get("tasks", t["id"])["status"] == "queued"
    u.store.update("tasks", t["id"], {"status": "failed", "attempts": 2}, "test")
    u.tick(now=MON_0900)
    assert u.store.get("tasks", t["id"])["escalated"]
    assert any(e["severity"] == "ACTION NEEDED" for e in u.store.events(50))


def test_daily_report_for_jarvis(ultron):
    u, _ = ultron
    u.tick(now=MON_0900)   # after 08:30 ET: the day's report is written once
    reps = u.reports()
    assert len(reps) == 1 and reps[0]["to"] == "Jarvis" and reps[0]["recommendations"]
    u.tick(now=MON_0900.replace(hour=10))
    assert len(u.reports()) == 1


def test_api(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("STARNET_MODE", "sim")
    monkeypatch.setenv("STARNET_PASSWORD", "pw")
    monkeypatch.setenv("STARNET_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import backend.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        assert c.get("/api/station").status_code == 401                     # behind the city's password
        c.auth = ("x", "pw")
        o = c.get("/api/station").json()
        assert o["mission"]["name"] == "First Dollar" and len(o["routines"]) == 5 and not o["ai_enabled"]
        assert c.get("/station.html").status_code == 200
        assert c.post("/api/station/routines/R-001/run").status_code == 503  # no API key: research is off
        r = c.post("/api/station/money", json={"kind": "income", "amount": 40, "unit": "station", "note": "first sale"})
        assert r.status_code == 200 and r.json()["source"] == "owner"
        assert c.post("/api/station/money", json={"kind": "ai_usage", "amount": 1, "unit": "station"}).status_code == 400
        assert c.post("/api/station/money", json={"kind": "income", "amount": 1, "unit": "moon"}).status_code == 400
        assert c.get("/api/station").json()["treasury"]["pool"] == 40
        assert c.get("/api/station/ventures/V-001").json()["stage"] == "operate"
        assert c.post("/api/station/approvals/AP-999", json={"decision": "approve"}).status_code == 404
        assert c.post("/api/station/ventures/V-001/stage", json={"stage": "moon"}).status_code == 400
        assert any(e["kind"] == "money.income" for e in c.get("/api/station/events").json())
        assert "station" in c.get("/api/state").json()
