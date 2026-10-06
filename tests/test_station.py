"""The Space Station: ULTRON's records, approvals, treasury rules and the research → venture → task flow,
with a fake Claude client (no network, no cost)."""
import json
import os
from datetime import datetime
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from backend.station import economy, research
from backend.station.store import now_iso
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
        "kpis": ["orders"], "success_criteria": "2 orders", "kill_criteria": "none in 21 days",
        "sell_via": "both", "price_usd": 25, "product_name": "Resume rewrite"}


class FakeClaude:
    """Answers like the API: research text for web-search calls, JSON for structured ones (picked by schema)."""

    def __init__(self, opps):
        self.opps, self.calls = opps, []
        self.qa = ["pass"]          # verdicts QA hands out, last one repeats
        self.warroom = {"verdicts": [], "lessons": []}
        self.shop_briefs = []
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
        elif "tasks" in props:
            body = PLAN
        elif "issues" in props:
            v = self.qa.pop(0) if len(self.qa) > 1 else self.qa[0]
            body = {"verdict": v, "issues": [] if v == "pass" else ["claims a guaranteed job offer"],
                    "required_changes": [] if v == "pass" else ["remove the guarantee"], "risk": "low"}
        elif "payload_json" in props:
            body = {"payload_json": json.dumps({"text": "Revised post"}), "what_changed": "removed the guarantee"}
        elif "channels" in props:
            body = {"audience": "nurses", "channels": [{"platform": "linkedin", "why": "nurses network", "posts_per_week": 3}],
                    "angles": ["before/after"], "outreach": {"use": True, "targets": "staffing agencies", "hook": "faster placements"},
                    "kpis": ["clicks"]}
        elif "posts" in props:
            body = {"posts": [{"platform": "linkedin", "text": "3 resume fixes for nurses", "angle": "tips"}]}
        elif "prospects" in props:
            body = {"prospects": [{"company": "Acme Staffing", "contact_name": "", "to_email": "hello@acmestaffing.com",
                                   "source_url": "https://acmestaffing.com/contact", "why_them": "they place nurses",
                                   "subject": "Resume help for your nurses", "body": "Hi Acme team, ..."}]}
        elif "sections" in props:
            body = PRODUCT
        elif "market_notes" in props:
            body = {"market_notes": "Occupation humor tees sell; fall mugs trending.", "products": self.shop_briefs}
        elif "verdicts" in props:
            body = {"summary": "Mixed week.", "stop_doing": ["long posts"], "start_doing": ["before/after posts"],
                    "research_focus": "B2B services for clinics", **self.warroom}
        else:
            body = {"deliverable": "# Gig: I will rewrite your resume", "notes": "Check the price.", "owner_next": ["Publish"],
                    "met_success_criteria": True}
        return NS(stop_reason="end_turn", usage=usage, content=[NS(type="text", text=json.dumps(body))])


def drain(u, now, kinds=None, limit=40):
    """Run ULTRON's jobs until none are left (or only other kinds are)."""
    ran = []
    for _ in range(limit):
        job = u.next_job(now)
        if not job or (kinds and job["kind"] not in kinds):
            break
        u.run_job(job, now=now)
        u.tick(now=now)
        ran.append(job["kind"])
    return ran


@pytest.fixture
def ultron(tmp_path):
    fake = FakeClaude([opp("Resume rewrite gig on Fiverr"), opp("Etsy planner shop", cost=29, rec="watchlist", score=60)])
    u = Ultron(str(tmp_path), client=fake)
    u.store.update("ventures", "V-PPS", {"stage": "paused"}, "test")   # the solar business has its own test
    return u, fake


def test_seeds_once_without_duplicates(tmp_path):
    u = Ultron(str(tmp_path), client=None)
    again = Ultron(str(tmp_path), client=None)
    assert len(again.store.all("routines")) == 5
    assert [a["name"] for a in again.store.all("agents")][:2] == ["ULTRON", "Market Research Agent"]
    assert len(again.store.all("agents")) == 14 and len(again.store.all("ventures")) == 3
    pps = again.store.get("ventures", "V-PPS")
    assert pps["language"] == "es" and pps["channels"] == ["facebook", "instagram"] and pps["owner_business"]
    assert not pps.get("outreach_allowed")
    teams = {a["department"] for a in again.store.all("agents")}
    assert {"marketing", "finance", "legal", "warroom"} <= teams
    assert again.store.get("ventures", "V-001")["stage"] == "operate"
    assert u.tick(now=MON_0900) == {"kind": "audit"}   # no API key: no research jobs; the books still run
    u.run_job({"kind": "audit"}, now=MON_0900)
    assert u.tick(now=MON_0900) is None


def test_routine_schedule():
    radar, brief = research.ROUTINES[0], research.ROUTINES[4]
    assert research.due(radar, MON_0900, None)
    assert not research.due(radar, MON_0900, MON_0900.replace(hour=8, minute=5).isoformat())
    assert not research.due(radar, MON_0900.replace(hour=7), None)                 # before 08:00
    assert not research.due(radar, datetime(2026, 10, 10, 9, tzinfo=ET), None)    # Saturday
    assert not research.due(brief, MON_0900, None) and research.due(brief, MON_0900.replace(hour=10, minute=1), None)


def test_research_to_venture_to_tasks(ultron):
    u, fake = ultron
    u.run_job({"kind": "audit"}, now=MON_0900)
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
    v = next(v for v in u.store.all("ventures") if v["id"] not in ("V-001", "V-PPS", "V-ETSY"))
    assert v["stage"] == "approved" and u.store.get("opportunities", v["opportunity"])["status"] == "promoted"
    # validation plans the venture into tasks with dependencies, staffing one specialist
    now = MON_0900.replace(hour=9, minute=1)
    job = u.next_job(now)
    assert job == {"kind": "plan", "venture": v["id"]}
    u.run_job(job, now=now)
    tasks = u.store.find("tasks", venture=v["id"])
    agent_task = next(t for t in tasks if t["kind"] == "agent")
    owner_task = next(t for t in tasks if t["kind"] == "owner")
    assert owner_task["depends_on"] == [agent_task["id"]]
    assert u.store.get("ventures", v["id"])["stage"] == "build"
    assert [a["role"] for a in u.store.all("agents")].count("Service Delivery") == 1
    # sells through its own checkout too: a payment link is filed for QA
    link = u.store.find("actions", kind="stripe.payment_link")
    assert len(link) == 1 and link[0]["payload"]["price_usd"] == 25
    u.tick(now=now)
    assert u.store.get("tasks", owner_task["id"])["status"] == "queued"
    u.store.update("ventures", v["id"], {"outreach_allowed": True}, "owner")   # the owner allows outreach for this one
    # QA passes the link; Stripe isn't connected, so it waits for the owner instead of being dropped;
    # marketing writes the channel plan; the agent drafts; outreach is drafted and QA'd
    ran = drain(u, now)
    assert {"qa", "dispatch", "marketing_plan", "task", "outreach"} <= set(ran)
    assert u.store.find("actions", kind="stripe.payment_link")[0]["status"] == "manual"
    assert u.store.get("ventures", v["id"])["marketing_plan"]["channels"][0]["platform"] == "linkedin"
    assert u.store.get("tasks", agent_task["id"])["output"]["deliverable"].startswith("# Gig")
    mail = u.store.find("actions", kind="outreach.email")
    assert len(mail) == 1 and mail[0]["status"] == "manual"       # no email connector yet: your queue
    u.tick(now=now)
    assert u.store.get("tasks", owner_task["id"])["status"] == "waiting_owner"
    assert u.store.get("agents", agent_task["assigned_agent"])["status"] == "ON BREAK"   # idle: Crew Lounge
    u.owner_done(owner_task["id"], "gig is live")
    # every step is in the audit log
    kinds = {e["kind"] for e in u.store.events(500)}
    assert {"opportunity.created", "approval.approved", "venture.planned", "task.completed", "task.waiting_owner",
            "action.qa_pass", "action.manual", "finance.audit"} <= kinds
    # every Claude call was charged to the station
    per_call = economy.usage_cost(NS(input_tokens=10_000, output_tokens=2_000, cache_read_input_tokens=0,
                                     cache_creation_input_tokens=0, server_tool_use=NS(web_search_requests=0)))
    assert u.treasury.ai_spent() == pytest.approx(len(fake.calls) * per_call + 0.03 * sum(1 for c in fake.calls if c.get("tools")), abs=0.01)


def test_content_only_once_a_venture_has_a_link(ultron):
    u, fake = ultron
    v = u.store.create("ventures", {"name": "Gig", "stage": "operate", "planned": True, "offer": "Resumes",
                                    "marketing_plan": {"audience": "nurses", "channels": [{"platform": "linkedin"}], "angles": [],
                                                       "outreach": {"use": False}}}, "test")
    u.cfg["audited"] = MON_0900.date().isoformat()
    u.cfg["kicked_off"] = True
    u.cfg["kickoff_at"] = MON_0900.isoformat()
    u.cfg["shop_research_at"] = MON_0900.isoformat()
    for r in u.store.all("routines"):
        u.store.update("routines", r["id"], {"last_run": MON_0900.isoformat()}, "test")
    assert u.next_job(MON_0900) is None
    u.store.update("ventures", v["id"], {"links": {"fiverr": "https://fiverr.com/x/gig"}}, "owner")
    assert u.next_job(MON_0900) == {"kind": "content", "venture": v["id"]}
    u.run_job({"kind": "content", "venture": v["id"]}, now=MON_0900)
    post = u.store.find("actions", kind="social.post")[0]
    assert post["payload"]["link"] == "https://fiverr.com/x/gig" and post["status"] == "qa"
    assert u.next_job(MON_0900) == {"kind": "qa", "action": post["id"]}     # content is done for today


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


def test_shuttle_flights_are_real_money_in(ultron):
    u, _ = ultron
    t = u.treasury
    assert t.flights() == []
    t.sync_payouts(NS(payouts=[[3, 1000.0]]))
    t.book("ai_usage", 0.4, "station", "api_usage", "a call")                 # costs never fly
    t.book("expense", 9, "station", "owner", "domain")
    t.book_stripe_sale({"id": "cs_test_abc12345", "payment_status": "paid", "amount_total": 2700, "metadata": {}})
    f = t.flights()
    assert [(x["kind"], x["amount"]) for x in f] == [("sale", 27.0), ("payout", 900.0)]
    assert len({x["id"] for x in f}) == 2
    assert t.flights() is f                                                    # cached until the ledger grows
    assert u.overview()["flights"] == f


def test_scale_plan_and_next_evaluation_goal(ultron):
    from datetime import date
    from backend import scale
    u, _ = ultron
    t = u.treasury
    accts = [{"id": "a", "name": "Eval", "phase": "evaluation", "target": 3000, "profit": 1200},
             {"id": "b", "name": "Funded", "phase": "funded", "profit": 800, "payout_days": 5, "cycle_days": 2,
              "payouts": 0, "max_payouts": 5, "payout_eligible": False},
             {"id": "c", "name": "Ready", "phase": "funded", "profit": 2500, "payout_eligible": True, "safe_payout": 1200,
              "payouts": 1, "max_payouts": 5},
             {"id": "d", "name": "Blown", "phase": "failed"}]
    p = scale.plan(accts, t.summary(), {}, None, date(2026, 10, 6))   # a Tuesday
    stages = {r["id"]: r["stage"] for r in p["accounts"]}
    assert stages == {"a": "evaluation", "b": "funded", "c": "payout ready", "d": "failed"}
    a = p["accounts"][0]
    assert a["left"] == 1800 and a["eta_days"] == 5 and a["eta"] == "2026-10-13"      # 5 trading days, over the weekend
    assert p["accounts"][1]["eta_days"] == 6 and p["accounts"][1]["payout"] == 1600   # 3 qualifying days at ~55%
    assert [c["amount"] for c in p["coming"]] == [1080.0, 1440.0]                      # the trader's 90%, soonest first
    assert scale.eval_goal({}, p) is None and "Set the evaluation price" in p["next_eval"]["text"]
    # a price: short of it until a payout lands, then a one-time goal ULTRON asks the owner to approve
    cfg = t.set_scale(150, 5)
    p = scale.plan(accts, t.summary(), cfg, None, date(2026, 10, 6))
    assert not p["next_eval"]["can_fund"] and p["next_eval"]["eta"] == "2026-10-06"
    t.set_eval_goal(scale.eval_goal(cfg, p))
    t.sync_payouts(NS(payouts=[[3, 1000.0]]))
    p = scale.plan(accts, t.summary(), cfg, None, date(2026, 10, 6))
    assert p["next_eval"]["can_fund"]
    u.tick(now=MON_0900)
    ask = [a for a in u.store.find("approvals", kind="fund_goal") if a["payload"]["goal"] == "lucid-eval-5"]
    assert len(ask) == 1 and ask[0]["cost"] == 150 and not ask[0]["reversible"] and "/month" not in ask[0]["action"]
    # the limit stops the plan (and drops the goal); the paper pace takes over after 10 traded days
    cfg = t.set_scale(None, 3)
    p = scale.plan(accts, t.summary(), cfg, {"days": 12, "avg_day": 250.0}, date(2026, 10, 6))
    assert "limit" in p["next_eval"]["text"] and p["pace"]["avg_day"] == 250.0
    t.set_eval_goal(scale.eval_goal(cfg, p))
    assert not any(g["id"].startswith("lucid-eval-") for g in t.cfg["goals"])
    with pytest.raises(ValueError):
        t.set_scale(-1, None)


def test_ai_budget_cap_stops_research(ultron, monkeypatch):
    u, fake = ultron
    monkeypatch.setattr("backend.station.economy.AI_BUDGET", 5.0)
    u.cfg["audited"] = MON_0900.date().isoformat()   # the audit is plain code: it runs even at the cap
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


# ---------------------------------------------------------------- the outbound gate
def _post(u, text="3 resume fixes"):
    from backend.station import actions
    return actions.create(u.store, "social.post", "A-006", "V-001", {"platform": "linkedin", "text": text, "link": ""}, "test post")


def test_nothing_leaves_without_qa_and_failures_get_one_revision(ultron):
    from backend.station import actions
    u, fake = ultron
    assert all(a["status"] != "ready" for a in u.store.all("actions"))
    a = _post(u, "Guaranteed job offer in 7 days!")
    fake.qa = ["fail", "fail"]
    actions.qa(u.store, u.brain, u.store.get("actions", a["id"]))
    assert u.store.get("actions", a["id"])["status"] == "revise"
    actions.revise(u.store, u.brain, u.store.get("actions", a["id"]))
    assert u.store.get("actions", a["id"])["payload"]["text"] == "Revised post"
    actions.qa(u.store, u.brain, u.store.get("actions", a["id"]))
    assert u.store.get("actions", a["id"])["status"] == "rejected"           # twice failed: never sent


def test_outbound_switch_caps_and_owner_queue(ultron, monkeypatch):
    from backend.station import actions
    u, fake = ultron
    a = _post(u)
    actions.qa(u.store, u.brain, a)
    ready = u.store.get("actions", a["id"])
    assert actions.dispatch(u.store, ready, outbound_on=False)["status"] == "ready"    # E-STOP: held
    sent = []
    monkeypatch.setitem(actions.connectors.SOCIAL, "linkedin", {"configured": lambda: True,
                                                                "post": lambda text, link: sent.append(text) or {"id": "p1"}})
    assert actions.dispatch(u.store, ready, outbound_on=True)["status"] == "sent" and sent == ["3 resume fixes"]
    monkeypatch.setitem(actions.CAPS, "social.post", 1)
    b = _post(u, "another")
    actions.qa(u.store, u.brain, b)
    assert actions.dispatch(u.store, u.store.get("actions", b["id"]), True)["status"] == "ready"   # over today's cap
    monkeypatch.delitem(actions.connectors.SOCIAL, "linkedin")
    monkeypatch.setitem(actions.CAPS, "social.post", 5)
    assert actions.dispatch(u.store, u.store.get("actions", b["id"]), True)["status"] == "manual"   # no connector: your queue
    monkeypatch.setitem(actions.connectors.SOCIAL, "linkedin", {"configured": lambda: True, "post": lambda text, link: {"id": "p2"}})
    u.tick(now=MON_0900)                                                                     # connected now: it goes out
    assert u.store.get("actions", b["id"])["status"] == "ready"
    c = _post(u, "third")
    actions.qa(u.store, u.brain, c)
    u.store.update("actions", c["id"], {"status": "manual"}, "test")
    monkeypatch.delitem(actions.connectors.SOCIAL, "linkedin")
    u.tick(now=MON_0900)
    assert actions.owner_done(u.store, c["id"], "posted it")["status"] == "sent"


def test_outreach_rules(ultron):
    from backend.station import actions
    u, _ = ultron
    good = {"company": "Acme", "to_email": "hello@acme.com", "source_url": "https://acme.com/contact", "subject": "Hi", "body": "..."}
    assert actions.create(u.store, "outreach.email", "A-007", "V-001", good, "x")
    assert actions.create(u.store, "outreach.email", "A-007", "V-001", good, "x") is None          # never twice
    assert actions.create(u.store, "outreach.email", "A-007", "V-001", {**good, "to_email": "b@b.com", "source_url": ""}, "x") is None
    assert actions.create(u.store, "outreach.email", "A-007", "V-001", {**good, "to_email": "not-an-email"}, "x") is None
    actions.opt_out(u.store, "Opted@Out.com")
    assert actions.create(u.store, "outreach.email", "A-007", "V-001", {**good, "to_email": "opted@out.com"}, "x") is None


def test_stripe_link_sale_and_webhook_signature(ultron, monkeypatch):
    import hashlib, hmac, time
    from backend.station import actions, connectors
    u, _ = ultron
    v = u.store.create("ventures", {"name": "Templates", "stage": "build"}, "test")
    a = actions.create(u.store, "stripe.payment_link", "A-005", v["id"], {"name": "Budget template", "price_usd": 12}, "checkout")
    actions.qa(u.store, u.brain, a)
    monkeypatch.setattr(connectors, "stripe_configured", lambda: True)
    monkeypatch.setattr(connectors, "stripe_payment_link", lambda *a: {"url": "https://buy.stripe.com/x", "payment_link": "plink_1"})
    actions.dispatch(u.store, u.store.get("actions", a["id"]), True)
    assert u.store.get("ventures", v["id"])["links"]["stripe"] == "https://buy.stripe.com/x"
    # a paid checkout books itself (sale + estimated fee), once, against the right venture
    session = {"id": "cs_test_123", "payment_status": "paid", "amount_total": 1200, "payment_link": "plink_1", "metadata": {}}
    assert u.treasury.book_stripe_sale(session) and u.treasury.book_stripe_sale(session) is None
    pnl = u.treasury.pnl("venture", v["id"])
    assert pnl["income"] == 12 and round(pnl["costs"] - pnl["ai_costs"], 2) == connectors.stripe_fee(12)   # + the QA call
    # webhook signatures
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    body = json.dumps({"type": "checkout.session.completed"}).encode()
    t = str(int(time.time()))
    sig = hmac.new(b"whsec_test", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    assert connectors.stripe_verify(body, f"t={t},v1={sig}")["type"] == "checkout.session.completed"
    with pytest.raises(connectors.ConnectorError):
        connectors.stripe_verify(body, f"t={t},v1={'0' * 64}")
    with pytest.raises(connectors.ConnectorError):
        connectors.stripe_verify(body, f"t={int(t) - 3600},v1={sig}")


def test_ledger_is_tamper_evident_and_audited(ultron):
    from backend.station import finance
    u, _ = ultron
    u.record("income", 40, "station", "first sale")
    u.record("expense", 5, "station", "domain")
    assert u.treasury.verify_chain()["intact"] and finance.audit(u.store, u.treasury)["clean"]
    u.treasury.entries[0]["amount"] = 4000          # someone edits history
    doc = finance.audit(u.store, u.treasury)
    assert not doc["chain"]["intact"] and doc["findings"][0]["severity"] == "CRITICAL"
    st = finance.statement(u.treasury)
    assert st["units"]["station"]["income"] == 4000 and st["tax_set_aside"] == round((4000 - 5) * finance.TAX_RATE, 2)


def test_war_room_cuts_what_does_not_work_and_teaches_the_crew(ultron):
    u, fake = ultron
    a = u.store.create("ventures", {"name": "Dud", "stage": "operate", "planned": True}, "test")
    b = u.store.create("ventures", {"name": "Winner", "stage": "operate", "planned": True}, "test")
    t = u.store.create("tasks", {"title": "more dud work", "venture": a["id"], "assigned_agent": "A-006", "kind": "agent",
                                 "status": "queued", "depends_on": [], "attempts": 0}, "test")
    fake.warroom = {"verdicts": [
        {"venture": a["id"], "verdict": "pivot", "why": "0 clicks in 9 days", "evidence": ["0 clicks"], "changes": []},
        {"venture": b["id"], "verdict": "double_down", "why": "3 sales", "evidence": ["3 sales"],
         "changes": [{"title": "Post a before/after daily", "role": "Content Strategist", "instructions": "..."}]},
        {"venture": "V-001", "verdict": "kill", "why": "nope", "evidence": [], "changes": []}],
        "lessons": [{"lesson": "Before/after posts beat tips", "evidence": "3 sales vs 0", "applies_to": "Content Strategist"}]}
    u.cfg["warroom_now"] = True
    u.cfg["audited"] = MON_0900.date().isoformat()
    assert u.next_job(MON_0900) == {"kind": "warroom"}
    u.run_job({"kind": "warroom"}, now=MON_0900)
    assert u.store.get("ventures", a["id"])["stage"] == "paused"                  # cut on the spot
    assert u.store.get("tasks", t["id"])["status"] == "cancelled"
    assert u.store.get("ventures", "V-001")["stage"] == "operate"                 # the trading desk isn't the War Room's call
    new = [x for x in u.store.find("tasks", venture=b["id"]) if x.get("from") == "warroom"]
    assert new and new[0]["assigned_agent"] == "A-006"                            # standing team, no new hire
    assert u.cfg["research_focus"] == "B2B services for clinics"
    # the lesson reaches the next agent that works
    u.run_job({"kind": "task", "task": new[0]["id"]}, now=MON_0900)
    assert "Before/after posts beat tips" in fake.calls[-1]["system"]
    assert not u.next_job(MON_0900) == {"kind": "warroom"}                        # not again today


def test_api_outbound_webhook_and_links(tmp_path, monkeypatch):
    import hashlib, hmac, importlib, time
    from fastapi.testclient import TestClient
    monkeypatch.setenv("STARNET_MODE", "sim")
    monkeypatch.setenv("STARNET_PASSWORD", "pw")
    monkeypatch.setenv("STARNET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import backend.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        # the webhook needs no password, only Stripe's signature
        body = json.dumps({"type": "checkout.session.completed", "data": {"object": {
            "id": "cs_1", "payment_status": "paid", "amount_total": 2500, "metadata": {"starnet_venture": "V-001"}}}}).encode()
        t = str(int(time.time()))
        sig = hmac.new(b"whsec_x", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
        assert c.post("/api/station/stripe/webhook", content=body, headers={"stripe-signature": f"t={t},v1=bad"}).status_code == 400
        for _ in range(2):   # Stripe retries: booked once
            assert c.post("/api/station/stripe/webhook", content=body, headers={"stripe-signature": f"t={t},v1={sig}"}).status_code == 200
        c.auth = ("x", "pw")
        assert c.get("/api/station").json()["treasury"]["station"]["income"] == 25
        assert c.post("/api/station/outbound", json={"on": False}).json() == {"outbound": False}
        assert c.get("/api/station").json()["outbound"] is False
        assert c.post("/api/station/ventures/V-001/link", json={"name": "x", "url": "http://insecure"}).status_code == 400
        assert c.post("/api/station/ventures/V-001/link", json={"name": "site", "url": "https://example.com"}).status_code == 200
        assert c.post("/api/station/feedback", json={"ref": "V-001", "note": "nobody clicks"}).status_code == 200
        assert c.post("/api/station/optout", json={"email": "a@b.com"}).status_code == 200
        f = c.get("/api/station/finance").json()
        assert f["chain"]["intact"] and f["statement"]["units"]["station"]["income"] == 25


def test_facebook_and_linkedin_connectors(monkeypatch):
    from backend.station import connectors
    calls = []

    def fake(method, url, headers=None, form=None, body=None):
        calls.append((method, url, headers, form, body))
        if url.endswith("/userinfo"):
            return {"sub": "abc123"}
        if url.endswith("/ugcPosts") and headers["Authorization"] == "Bearer expired":
            raise connectors.ConnectorError("HTTP 401: expired")
        return {"id": "post_1"}
    monkeypatch.setattr(connectors, "_http_json", fake)
    for k in ("STARNET_FB_PAGE_ID", "STARNET_FB_PAGE_TOKEN", "STARNET_LINKEDIN_TOKEN", "STARNET_LINKEDIN_PERSON"):
        monkeypatch.delenv(k, raising=False)
    assert not connectors.social_configured("facebook") and not connectors.social_configured("linkedin")
    with pytest.raises(connectors.ConnectorError):
        connectors.post_social("facebook", "hi")
    monkeypatch.setenv("STARNET_FB_PAGE_ID", "123")
    monkeypatch.setenv("STARNET_FB_PAGE_TOKEN", "pagetok")
    assert connectors.post_social("Facebook", "Resume tips", "https://buy.stripe.com/x") == {"platform": "facebook", "id": "post_1"}
    method, url, _, form, _ = calls[-1]
    assert url == "https://graph.facebook.com/123/feed" and form == {"message": "Resume tips", "access_token": "pagetok",
                                                                    "link": "https://buy.stripe.com/x"}
    monkeypatch.setenv("STARNET_LINKEDIN_TOKEN", "lt")
    assert connectors.post_social("linkedin", "Resume tips", "https://buy.stripe.com/x")["id"] == "post_1"
    body = calls[-1][4]
    assert body["author"] == "urn:li:person:abc123" and calls[-2][1].endswith("/userinfo")
    share = body["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert share["shareCommentary"]["text"] == "Resume tips" and share["media"][0]["originalUrl"] == "https://buy.stripe.com/x"
    monkeypatch.setenv("STARNET_LINKEDIN_TOKEN", "expired")
    with pytest.raises(connectors.ConnectorError, match="expired"):
        connectors.post_social("linkedin", "x")
    assert connectors.status()["social"] == ["facebook", "linkedin"]


def test_solar_venture_owns_the_page_writes_spanish_and_studies_its_posts(tmp_path, monkeypatch):
    from backend.station import actions, connectors
    fake = FakeClaude([opp("x")])
    u = Ultron(str(tmp_path), client=fake)
    monkeypatch.setenv("STARNET_FB_PAGE_ID", "1150312211499349")
    monkeypatch.setenv("STARNET_FB_PAGE_TOKEN", "pagetok")
    monkeypatch.setattr(connectors, "facebook_recent_posts",
                        lambda limit=12: [{"at": "2026-10-01", "text": "¡Instala tus placas solares con nosotros!", "url": ""}])
    u.cfg.update({"audited": MON_0900.date().isoformat(), "kicked_off": True})
    for r in u.store.all("routines"):
        u.store.update("routines", r["id"], {"last_run": MON_0900.isoformat()}, "test")
    assert u.next_job(MON_0900) == {"kind": "marketing_plan", "venture": "V-PPS"}
    u.run_job({"kind": "marketing_plan", "venture": "V-PPS"}, now=MON_0900)
    prompt = fake.calls[-1]["messages"][0]["content"]
    assert "Puerto Rico" in prompt and "Instala tus placas" in prompt and "fixed: facebook, instagram" in prompt
    assert "hasn't allowed outreach" in prompt
    assert u.next_job(MON_0900) == {"kind": "content", "venture": "V-PPS"}     # no link needed: it has its own channel
    card = {"headline": "Energía solar para tu hogar", "points": ["Servicio en toda la isla"], "cta": "Escríbenos por DM"}
    fake_posts = {"posts": [{"platform": "facebook", "text": "Energía solar para tu hogar", "angle": "tips", "card": card},
                            {"platform": "instagram", "text": "Energía solar ☀️", "angle": "tips", "card": card}]}
    orig = fake.create
    fake.create = lambda **kw: orig(**kw) if "posts" not in str(kw.get("output_config")) else NS(
        stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                                         server_tool_use=None), content=[NS(type="text", text=json.dumps(fake_posts))])
    fake.beta.messages.create = fake.create
    u.run_job({"kind": "content", "venture": "V-PPS"}, now=MON_0900)
    post, ig = sorted(u.store.find("actions", kind="social.post", venture="V-PPS"), key=lambda a: a["payload"]["platform"])
    assert post["payload"]["link"] == ""                                        # no link back to its own Page
    from backend.station import media
    assert media.path_for(str(tmp_path), post["payload"]["image"])              # each post has its own card
    actions.qa(u.store, u.brain, post)
    assert "compliance" in fake.calls[-1]["messages"][0]["content"]
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.delenv("STARNET_PUBLIC_URL", raising=False)
    assert actions.dispatch(u.store, u.store.get("actions", post["id"]), True)["status"] == "manual"   # no public address yet
    u.store.update("actions", post["id"], {"status": "ready"}, "test")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://starnet-city.onrender.com")
    sent_fb = []
    monkeypatch.setitem(connectors.SOCIAL["facebook"], "post", lambda text, link, image_url="": sent_fb.append((text, image_url)) or {"id": "fb1"})
    assert actions.dispatch(u.store, u.store.get("actions", post["id"]), True)["status"] == "sent"
    assert sent_fb == [("Energía solar para tu hogar", f"https://starnet-city.onrender.com/media/{post['payload']['image']}")]
    # Instagram: the same Page's account, with the card
    monkeypatch.setenv("STARNET_IG_USER_ID", "1784")
    calls = []

    def graph(method, url, headers=None, form=None, body=None):
        calls.append((method, url, form))
        return {"id": "box1"} if url.endswith("/media") else {"status_code": "FINISHED"} if "status_code" in url else {"id": "ig1"}
    monkeypatch.setattr(connectors, "_http_json", graph)
    actions.qa(u.store, u.brain, ig)
    assert actions.dispatch(u.store, u.store.get("actions", ig["id"]), True)["status"] == "sent"
    assert calls[0][1].endswith("1784/media") and calls[0][2]["image_url"].endswith(ig["payload"]["image"])
    assert calls[-1][1].endswith("1784/media_publish") and calls[-1][2]["creation_id"] == "box1"
    # another venture's Facebook post never lands on the solar Page
    other = actions.create(u.store, "social.post", "A-006", "V-001", {"platform": "facebook", "text": "trading", "link": ""}, "x")
    actions.qa(u.store, u.brain, other)
    assert actions.dispatch(u.store, u.store.get("actions", other["id"]), True)["status"] == "manual"
    # and the War Room can improve it, never pause or kill it
    from backend.station import warroom
    fake.warroom = {"verdicts": [{"venture": "V-PPS", "verdict": "kill", "why": "x", "evidence": [], "changes": []}], "lessons": []}
    warroom.convene(u.store, u.brain, u.treasury, u.health, u.cfg, u.request, MON_0900)
    assert u.store.get("ventures", "V-PPS")["stage"] == "operate" and not u.store.find("approvals", kind="venture_decision")


def test_media_route_is_public_but_unguessable(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    from backend.station import media
    monkeypatch.setenv("STARNET_MODE", "sim")
    monkeypatch.setenv("STARNET_PASSWORD", "pw")
    monkeypatch.setenv("STARNET_DATA_DIR", str(tmp_path))
    import backend.main as main
    importlib.reload(main)
    name = media.render_card(str(tmp_path), "Padilla Property Solutions", "Energía solar", ["Toda la isla"], "DM", "solar")
    with TestClient(main.app) as c:
        r = c.get(f"/media/{name}")                                   # no password: Instagram fetches it
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
        assert c.get("/media/../station/ledger.jsonl").status_code in (401, 404)   # never served
        assert c.get("/media/..%2Fstation%2Fledger.jsonl").status_code == 404
        assert c.get("/media/abc.jpg").status_code == 404
        assert c.get("/api/station").status_code == 401                 # everything else still needs the password
        c.auth = ("x", "pw")
        assert c.post("/api/station/ventures/V-PPS/outreach", json={"on": True}).json()["outreach_allowed"] is True


def test_post_engagement_and_leads_feed_the_war_room(tmp_path, monkeypatch):
    from backend.station import actions, connectors, results, warroom
    fake = FakeClaude([opp("x")])
    u = Ultron(str(tmp_path), client=fake)
    now = datetime.now(ZoneInfo("America/New_York"))
    # two Padilla posts went out: one on Facebook, one on Instagram
    ids = []
    for plat, pid in (("facebook", "1150_99"), ("instagram", "1789")):
        a = actions.create(u.store, "social.post", "A-006", "V-PPS", {"platform": plat, "text": f"{plat} post", "link": ""}, "post")
        u.store.update("actions", a["id"], {"status": "sent", "sent_at": now_iso(), "result": {"platform": plat, "id": pid}}, "test")
        ids.append(a["id"])
    monkeypatch.setattr(connectors, "facebook_post_metrics", lambda pid: {"reactions": 14, "comments": 3, "shares": 1})
    monkeypatch.setattr(connectors, "instagram_media_metrics", lambda mid: {"likes": 22, "comments": 2})
    u.cfg.update({"audited": now.date().isoformat()})
    assert u.next_job(now) == {"kind": "metrics"}
    u.run_job({"kind": "metrics"}, now=now)
    assert u.store.get("actions", ids[0])["result"]["metrics"] == {"reactions": 14, "comments": 3, "shares": 1}
    assert u.next_job(now) != {"kind": "metrics"}                         # not again for 6 hours
    # leads: logged from a post, quoted, won (booked as real income), lost
    l1 = results.add_lead(u.store, "V-PPS", "whatsapp", "casa en Bayamón", action=ids[0])
    l2 = results.add_lead(u.store, "V-PPS", "dm")
    with pytest.raises(ValueError):
        results.add_lead(u.store, "V-PPS", "carrier pigeon")
    results.set_lead(u.store, l1["id"], "quoted")
    with pytest.raises(ValueError):
        results.set_lead(u.store, l1["id"], "won", None, record_income=u.record)   # a sale needs its amount
    results.set_lead(u.store, l1["id"], "won", 450, record_income=u.record)
    results.set_lead(u.store, l2["id"], "lost")
    assert u.treasury.pnl("venture", "V-PPS")["income"] == 450
    with pytest.raises(ValueError):
        results.set_lead(u.store, l1["id"], "lost")                        # a booked sale isn't undone here
    r = results.summary(u.store, "V-PPS")
    assert r["leads"] == 2 and r["by_status"] == {"won": 1, "lost": 1} and r["won_value"] == 450
    assert r["best_posts"][0]["post"] == ids[0] and r["best_posts"][0]["leads"] == 1
    assert u.health(u.store.get("ventures", "V-PPS")) > 60
    # the War Room sees it all
    data = warroom.inputs(u.store, u.treasury, u.health, None)
    pps = next(v for v in data["ventures"] if v["id"] == "V-PPS")
    assert pps["results_30d"]["won_value"] == 450 and any("lead" in x for x in data["new_results"])


def test_lead_api(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("STARNET_MODE", "sim")
    monkeypatch.setenv("STARNET_PASSWORD", "pw")
    monkeypatch.setenv("STARNET_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    import backend.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        c.auth = ("x", "pw")
        lead = c.post("/api/station/ventures/V-PPS/leads", json={"source": "whatsapp", "note": "Caguas"}).json()
        assert lead["status"] == "new"
        assert c.post("/api/station/ventures/V-PPS/leads", json={"source": "fax"}).status_code == 400
        assert c.post("/api/station/ventures/V-999/leads", json={"source": "dm"}).status_code == 404
        assert c.post(f"/api/station/leads/{lead['id']}", json={"status": "won"}).status_code == 400
        assert c.post(f"/api/station/leads/{lead['id']}", json={"status": "won", "amount": 300}).json()["amount"] == 300
        o = c.get("/api/station").json()
        assert o["treasury"]["station"]["income"] == 300 and o["leads"][0]["id"] == lead["id"]
        pps = next(v for v in o["ventures"] if v["id"] == "V-PPS")
        assert pps["results"]["leads"] == 1


def test_jarvis_brief_is_read_only_and_token_gated(tmp_path, monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("STARNET_MODE", "sim")
    monkeypatch.setenv("STARNET_PASSWORD", "pw")
    monkeypatch.setenv("STARNET_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STARNET_JARVIS_TOKEN", raising=False)
    import backend.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        assert c.get("/api/jarvis/brief").status_code == 404                     # off until the token is set
        monkeypatch.setenv("STARNET_JARVIS_TOKEN", "j" * 40)
        assert c.get("/api/jarvis/brief").status_code == 401
        assert c.get("/api/jarvis/brief", headers={"Authorization": "Bearer wrong"}).status_code == 401
        b = c.get("/api/jarvis/brief", headers={"Authorization": "Bearer " + "j" * 40}).json()
        assert b["mission"]["name"] == "First Dollar" and any(v["id"] == "V-PPS" for v in b["ventures"])
        assert b["city"]["mode"] == "sim" and "balance" in b["city"]["account"]
        # real-order status, without ever leaking a webhook URL (anyone with one can place orders)
        from backend.execution import TradersPostRouter
        r = TradersPostRouter(str(tmp_path), webhooks=["https://tp.example/secret-hook-123"])
        r.armed, r.open = True, {"MNQ": {"side": "buy", "qty": 3, "contract": "MNQZ2026", "targets": {"https://tp.example/secret-hook-123": 3}}}
        monkeypatch.setattr(main, "router", r)
        cb = main._city_brief()
        assert cb["real_orders"]["armed"] and cb["real_orders"]["open"]["MNQ"] == {"side": "buy", "qty": 3, "contract": "MNQZ2026"}
        assert "secret-hook" not in json.dumps(cb)
        assert c.post("/api/jarvis/brief", headers={"Authorization": "Bearer " + "j" * 40}).status_code == 405   # read only
        assert c.get("/api/station", headers={"Authorization": "Bearer " + "j" * 40}).status_code == 401      # token opens nothing else
        monkeypatch.setenv("STARNET_JARVIS_TOKEN", "short")
        assert c.get("/api/jarvis/brief", headers={"Authorization": "Bearer short"}).status_code == 401       # weak tokens refused


def test_a_bad_key_or_network_doesnt_burn_the_day(tmp_path, monkeypatch):
    import anthropic
    import httpx2 as httpx
    from backend.station import brain
    monkeypatch.setenv("ANTHROPIC_API_KEY", "  sk-ant-api03-secretvalue\n")
    c = brain._client()
    assert c.api_key == "sk-ant-api03-secretvalue"                       # a pasted space/line break is trimmed
    # the error the SDK raises for a key with a line break: reported without the key
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIConnectionError(request=req)
    try:
        raise err from httpx.LocalProtocolError("Illegal header value b'sk-ant-api03-secretvalue\\n'")
    except anthropic.APIConnectionError as e:
        msg = brain.connection_problem(e)
    assert "space or line break" in msg and "secret" not in msg
    # a connection failure keeps the routine's slot and retries after the backoff
    fake = FakeClaude([opp("x")])
    u = Ultron(str(tmp_path), client=fake)
    u.store.update("ventures", "V-PPS", {"stage": "paused"}, "test")
    u.cfg["audited"] = MON_0900.date().isoformat()

    def down(**kw):
        try:
            raise anthropic.APIConnectionError(request=req) from httpx.ConnectTimeout("timed out")
        except anthropic.APIConnectionError:
            raise
    fake.beta.messages.create = down
    job = u.next_job(MON_0900)
    assert job["kind"] == "routine"
    u.run_job(job, now=MON_0900)
    assert u.store.get("routines", job["routine"])["last_run"] is None        # the slot isn't used up
    assert u.next_job(MON_0900.replace(minute=10)) is None                    # backing off
    assert "timed out" in u.last_error
    fake.beta.messages.create = fake.create
    assert u.next_job(MON_0900.replace(minute=25)) == job                     # and then it tries again
    # an empty channel plan left by an old failure is redone
    u.store.update("ventures", "V-PPS", {"stage": "operate", "marketing_plan": {"channels": [], "angles": [], "outreach": {"use": False}}}, "t")
    u.cfg["kicked_off"] = True
    for r in u.store.all("routines"):
        u.store.update("routines", r["id"], {"last_run": MON_0900.isoformat()}, "test")
    assert u.next_job(MON_0900.replace(minute=30)) == {"kind": "marketing_plan", "venture": "V-PPS"}


def test_milestones_and_pets_come_from_real_work(tmp_path):
    from backend.station import recognition
    u = Ultron(str(tmp_path), client=FakeClaude([opp("x")]))
    for i in range(5):
        u.store.event("task.completed", "A-006", f"delivered {i}")
    u.store.event("task.completed", "owner", "owner work doesn't count for agents")
    awarded = recognition.update(u.store)
    a = u.store.get("agents", "A-006")
    assert a["work"] == 5 and [m["title"] for m in a["achievements"]] == ["First delivery", "Reliable"]
    assert a["pet"]["kind"] == "robo-cat" and a["pet"]["name"] in recognition.PET_NAMES["robo-cat"]
    assert awarded and awarded[0]["agent"] == "A-006"
    assert recognition.update(u.store) == []                                    # once only
    assert sum(1 for e in u.store.events(200) if e["kind"] == "agent.milestone") == 1
    assert u.store.get("agents", "A-002").get("pet") is None                   # nothing earned, nothing given
    ms = {m["title"]: m["at"] for m in recognition.station_milestones(u.store, u.treasury)}
    assert ms["First sale"] is None
    u.record("income", 150, "station", "first order", venture="V-PPS")
    ms = {m["title"]: m["at"] for m in recognition.station_milestones(u.store, u.treasury)}
    assert ms["First sale"] and ms["$100 earned"] and not ms["$1,000 earned"]
    u.tick(now=MON_0900)
    assert next(m for m in u.overview()["milestones"] if m["title"] == "First sale")["at"]


BRIEF = {"niche": "nurse humor", "product_type": "tshirt", "our_angle": "night-shift wordplay nobody else has",
         "competitors": [{"shop": "ScrubLife", "listing": "Funny Nurse Shirt", "price_usd": 24.0, "url": "https://etsy.com/listing/1",
                          "why_it_sells": "1,200 reviews"}],
         "headline": "Running on coffee and charting", "subline": "night shift edition", "ink": "dark", "accent": "#d65c3c",
         "title": "Funny Nurse Shirt, Night Shift Nurse Gift", "description": "Soft unisex tee for night-shift nurses.",
         "tags": ["nurse shirt", "night shift nurse gift for her and him", "nurse shirt", "rn gift"] + [f"tag{i}" for i in range(15)],
         "price_usd": 9.0}


class FakePrintify:
    """Answers like Printify's API for the calls the shop makes."""

    def __init__(self):
        self.calls, self.orders = [], []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/shops.json":
            return [{"id": 77, "title": "My POS", "sales_channel": "custom_integration"}, {"id": 42, "title": "Etsy", "sales_channel": "etsy"}]
        if path == "/catalog/blueprints.json":
            return [{"id": 5, "title": "Unisex Jersey Short Sleeve Tee"}, {"id": 68, "title": "Ceramic Mug (11oz)"}]
        if path.endswith("/print_providers.json"):
            return [{"id": 29, "title": "Monster Digital"}]
        if path.endswith("/variants.json"):
            return {"variants": [{"id": i, "title": f"{c} / {z}", "options": {"color": c, "size": z}}
                                 for i, (c, z) in enumerate([(c, z) for c in ("White", "Black", "Natural") for z in ("XS", "S", "M", "L", "XL", "2XL", "3XL")])]}
        if path == "/uploads/images.json":
            assert body["contents"] and body["file_name"].endswith(".png")
            return {"id": "img1"}
        if path == "/shops/42/products.json" and method == "POST":
            return {"id": "prod1", "variants": [{"id": v["id"], "cost": 1200, "price": v["price"]} for v in body["variants"]]}
        if path.startswith("/shops/42/orders.json"):
            return {"data": self.orders}
        return {}


def test_the_crew_runs_the_etsy_shop_end_to_end(ultron, monkeypatch):
    from backend.station import actions, connectors, shop
    u, fake = ultron
    fake.shop_briefs = [BRIEF, {**BRIEF, "title": "Duplicate idea"}, {**BRIEF, "headline": "Mug life", "product_type": "mug", "ink": "light"}]
    assert shop.research_due(u.store, u.cfg, MON_0900)
    u.run_job({"kind": "shop_research"}, now=MON_0900)
    drafts = u.store.find("actions", kind="shop.listing")
    assert len(drafts) == 2                                                     # the same headline twice is one product
    tee, mug = drafts
    assert len(tee["payload"]["tags"]) == 13 and all(len(t) <= 20 for t in tee["payload"]["tags"])
    assert len({t.lower() for t in tee["payload"]["tags"]}) == 13               # no repeated tags
    assert mug["payload"]["ink"] == "dark"                                      # white mugs get dark ink
    assert all(media_ok(u, a["payload"]["image"]) for a in drafts)
    assert not shop.research_due(u.store, u.cfg, MON_0900)                      # just ran
    # QA, then no Printify yet: it waits in the owner's queue, never dropped
    for a in drafts:
        u.run_job({"kind": "qa", "action": a["id"]}, now=MON_0900)
    out = actions.dispatch(u.store, u.store.get("actions", tee["id"]), True)
    assert out["status"] == "manual" and "Printify" in out["manual_reason"]
    # connect Printify: ULTRON requeues it and the Shop Manager lists it, priced above cost
    api = FakePrintify()
    monkeypatch.setenv("PRINTIFY_API_TOKEN", "test-token")
    monkeypatch.setattr(connectors, "_printify", api)
    connectors._printify_cache.clear()
    u.tick(now=MON_0900)
    assert u.store.get("actions", tee["id"])["status"] == "ready"
    out = actions.dispatch(u.store, u.store.get("actions", tee["id"]), True)
    assert out["status"] == "sent" and out["result"]["id"] == "prod1"
    create = next(b for m, p, b in api.calls if p == "/shops/42/products.json")
    colors = {v["options"]["color"] for v in api("GET", "/catalog/blueprints/5/print_providers/29/variants.json")["variants"]
              if v["id"] in [x["id"] for x in create["variants"]]}
    sizes = {v["options"]["size"] for v in api("GET", "/catalog/blueprints/5/print_providers/29/variants.json")["variants"]
             if v["id"] in [x["id"] for x in create["variants"]]}
    assert colors == {"White", "Natural"} and sizes == set(shop.APPAREL_SIZES)  # dark ink on light shirts, S-2XL
    assert "AI tools" in create["description"]                                  # Etsy's disclosure, always
    put = next(b for m, p, b in api.calls if m == "PUT")
    assert {v["price"] for v in put["variants"]} == {shop.min_price(1200)} == {1899}   # $9 brief < cost + fees + profit
    assert any(p.endswith("/publish.json") for _, p, _ in api.calls)
    # the cap: STARNET_SHOP_LISTINGS_PER_DAY a day
    monkeypatch.setitem(actions.CAPS, "shop.listing", 1)
    assert actions.dispatch(u.store, u.store.get("actions", mug["id"]), True)["status"] == "ready"
    # orders come back as results, once each
    api.orders = [{"id": "o1", "created_at": "2026-10-05 12:00:00+00:00", "status": "fulfilled", "total_price": 1899,
                   "total_shipping": 475, "line_items": [{"product_id": "prod1", "quantity": 1, "cost": 1200, "shipping_cost": 475,
                                                          "metadata": {"title": "Funny Nurse Shirt"}}]}]
    assert shop.sync_orders(u.store)["new"] == 1 and shop.sync_orders(u.store)["new"] == 0
    sm = u.overview()["shop"]
    assert sm["orders_total"] == 1 and sm["live"][0]["orders"] == 1 and sm["pipeline"]["sent"] == 1
    assert u.treasury.summary()["station"]["income"] == 0                       # sales are booked by the owner, not the shop
    assert sum(1 for e in u.store.events(200) if e["kind"] == "shop.order") == 1


def media_ok(u, name):
    from backend.station import media
    from PIL import Image
    path = media.path_for(os.path.dirname(u.store.dir), name)
    return bool(path) and Image.open(path).mode == "RGBA"


def test_old_etsy_goal_is_retired(tmp_path):
    import os as _os
    d = tmp_path / "station"
    d.mkdir()
    (d / "treasury.json").write_text(json.dumps({"goals": [{"id": "etsy-launch", "name": "Open the first Etsy store", "monthly": 29.0,
                                                            "months": 2, "unit": "station"}]}))
    u = Ultron(str(tmp_path), client=FakeClaude([opp("x")]))
    assert [g["id"] for g in u.treasury.cfg["goals"]] == ["printify-premium"]
    assert "Etsy store (~$29" not in u.store.get("missions", "M-001")["goal"]


def test_no_api_credit_waits_instead_of_failing_jobs(tmp_path):
    import anthropic
    import httpx2 as httpx
    fake = FakeClaude([opp("x")])
    u = Ultron(str(tmp_path), client=fake)
    u.cfg["audited"] = MON_0900.date().isoformat()
    resp = httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    def broke(**kw):
        raise anthropic.BadRequestError("Your credit balance is too low to access the Anthropic API.", response=resp,
                                        body={"type": "error", "error": {"type": "invalid_request_error"}})
    fake.beta.messages.create = broke
    job = u.next_job(MON_0900)
    assert job["kind"] == "marketing_plan"
    u.run_job(job, now=MON_0900)
    assert not (u.store.get("ventures", job["venture"]).get("marketing_plan") or {}).get("failed_at")   # not marked failed
    assert u.next_job(MON_0900.replace(minute=10)) is None and "credit balance" in u.last_error
    fake.beta.messages.create = fake.create
    assert u.next_job(MON_0900.replace(minute=25)) == job



PRODUCT = {"title": "Weekly Meal Prep Planner", "subtitle": "Plan, shop and prep a week of meals in 30 minutes",
           "format": "planner", "audience": "busy parents",
           "sections": [{"heading": "How to use this planner", "kind": "text", "text": "Pick a prep day.\n\nFill the grid.", "items": [],
                         "columns": [], "rows": 1},
                        {"heading": "Week at a glance", "kind": "table", "text": "", "items": [],
                         "columns": ["Day", "Breakfast", "Lunch", "Dinner"], "rows": 7},
                        {"heading": "Prep day checklist", "kind": "checklist", "text": "", "items": [f"Step {i}" for i in range(30)],
                         "columns": [], "rows": 1},
                        {"heading": "Notes", "kind": "lines", "text": "", "items": [], "columns": [], "rows": 20}],
           "price_usd": 6.5, "sales": {"headline": "Meal prep, sorted", "subheadline": "A printable weekly planner",
                                       "bullets": ["7-day grid", "Shopping list"], "faq": [{"q": "Is anything shipped?", "a": "No, it's a PDF."}]},
           "etsy": {"title": "Meal Prep Planner Printable, Weekly Meal Planner PDF", "description": "Printable planner.",
                    "tags": ["meal planner", "meal prep printable"] + [f"tag{i}" for i in range(14)]},
           "pin": {"title": "Weekly meal prep planner (printable)", "description": "Plan a week of meals in 30 minutes."},
           "cover": {"headline": "Meal prep planner", "subline": "Printable · 7 days", "accent": "#2e7d5b"}}


def auto_opp(**kw):
    return {**opp("Printable meal prep planners", score=81), "category": "digital_product", "execution": "autonomous",
            "rails": ["storefront", "etsy_digital", "pinterest"], "product_format": "planner", **kw}


def test_autonomous_venture_launches_sells_and_closes_on_its_own(tmp_path, monkeypatch):
    from datetime import timedelta
    from backend.station import actions, connectors, digital
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setenv("STARNET_PUBLIC_URL", "https://city.example.com")
    stripe_calls, etsy_calls, pins, vid = [], [], [], [None]

    def fake_stripe(method, path, params=None):
        stripe_calls.append((method, path, params))
        if path == "/products":
            return {"id": "prod_1"}
        if path == "/prices":
            return {"id": "price_1"}
        if path == "/payment_links":
            return {"id": "plink_1", "url": "https://buy.stripe.com/test_1"}
        if path.startswith("/checkout/sessions/"):
            return {"id": path.rsplit("/", 1)[1], "payment_status": "paid", "status": "complete", "payment_link": "plink_1",
                    "amount_total": 650, "metadata": {"starnet_venture": vid[0], "starnet_product": slug[0]}}
        return {}
    monkeypatch.setattr(connectors, "stripe_request", fake_stripe)
    notes = []
    fake = FakeClaude([auto_opp(), opp("Resume gig on Fiverr")])
    u = Ultron(str(tmp_path), client=fake, notify=lambda t, b: notes.append(t))
    u.run_job({"kind": "routine", "routine": "R-001"}, now=MON_0900)
    # the autonomous idea launches by itself: recorded as approved by the owner's rule, owner notified
    u.tick(now=MON_0900)
    v = next(v for v in u.store.all("ventures") if v.get("autonomous"))
    vid[0] = v["id"]
    assert v["stage"] == "launch" and v["planned"] and v["rails"] == ["storefront", "etsy_digital", "pinterest"]
    ap = u.store.get("approvals", v["approval"])
    assert ap["status"] == "approved" and ap["owner_response"].startswith("auto")
    assert any("on its own" in n for n in notes)
    u.tick(now=MON_0900)
    assert len([x for x in u.store.all("ventures") if x.get("autonomous")]) == 1        # one auto-launch a day
    assert not u.store.find("approvals", status="pending") or all("Fiverr" in a["action"] for a in u.store.find("approvals", status="pending"))
    # the Product Designer makes a real, multi-page PDF and a cover, then QA
    u.cfg["shop_research_at"] = MON_0900.isoformat()
    u.store.update("ventures", "V-PPS", {"stage": "paused"}, "test")
    for r in u.store.all("routines"):
        u.store.update("routines", r["id"], {"last_run": MON_0900.isoformat()}, "test")
    u.cfg["audited"] = MON_0900.date().isoformat()
    job = u.next_job(MON_0900)
    assert job == {"kind": "product", "venture": v["id"]}
    a = u.run_job(job, now=MON_0900)
    assert a["kind"] == "digital.publish" and a["payload"]["pages"] >= 3
    dd = str(tmp_path)
    assert digital.pdf_path(dd, a["payload"]["pdf"]) and open(digital.pdf_path(dd, a["payload"]["pdf"]), "rb").read(5) == b"%PDF-"
    assert len(a["payload"]["etsy"]["tags"]) == 13
    assert u.next_job(MON_0900) != job                                                   # one in the works at a time
    u.run_job({"kind": "qa", "action": a["id"]}, now=MON_0900)
    # published: Stripe link that returns to a verified download, Etsy digital listing, a pin
    monkeypatch.setattr(connectors, "etsy_connected", lambda: True)
    monkeypatch.setattr(connectors, "pinterest_connected", lambda: True)
    monkeypatch.setattr(connectors, "etsy_digital_listing", lambda *a_, **k: etsy_calls.append(a_) or {"listing_id": 99, "url": "https://etsy.com/listing/99"})
    monkeypatch.setattr(connectors, "etsy_deactivate", lambda lid: etsy_calls.append(("off", lid)))
    monkeypatch.setattr(connectors, "pinterest_pin", lambda *a_, **k: pins.append(a_) or {"id": "pin1"})
    out = actions.dispatch(u.store, u.store.get("actions", a["id"]), True)
    assert out["status"] == "sent", out.get("result")
    link = next(p for m, path, p in stripe_calls if path == "/payment_links")
    assert link["after_completion"]["redirect"]["url"].endswith("/thanks?session_id={CHECKOUT_SESSION_ID}")
    prod = u.store.all("products")[0]
    slug = [prod["slug"]]
    assert link["metadata"] == {"starnet_venture": v["id"], "starnet_product": prod["slug"]}
    assert prod["url"] == f"https://city.example.com/shop/{prod['slug']}" and prod["etsy"]["listing_id"] == 99
    assert etsy_calls[0][3] == 6.5 and etsy_calls[0][4][:5] == b"%PDF-"                 # price and the PDF itself
    assert pins[0][3] == prod["url"] and pins[0][4].startswith("https://city.example.com/media/")
    # the storefront: page, then the download only for a paid session of this product
    assert "Buy now" in digital.page_product(prod) and prod["title"] in digital.page_index(u.store)
    assert "Privacy policy" in digital.page_privacy() and "/shop/privacy" in digital.page_product(prod)
    assert digital.verify_purchase(u.store, prod, "not-a-session") is None
    sess = digital.verify_purchase(u.store, {**prod, "payment_link": "plink_other"}, "cs_test_abcdefghijkl")
    assert sess is None                                                                  # another product's payment
    sess = digital.verify_purchase(u.store, prod, "cs_test_abcdefghijkl")
    assert sess["payment_status"] == "paid"
    assert u.treasury.book_stripe_sale(sess) and not u.treasury.book_stripe_sale(sess)  # booked once
    assert digital.verify_purchase(u.store, prod, "cs_test_abcdefghijkl")["cached"]
    sm = u.overview()["storefront"]
    assert sm["products"][0]["sales"] == 1 and sm["products"][0]["etsy"] and sm["products"][0]["pinned"]
    # a venture that sold stays; one with no sale in 21 days closes itself and its products come off sale
    later = datetime.now(ET) + timedelta(days=22)
    u.tick(now=later)
    assert u.store.get("ventures", v["id"])["stage"] == "launch"
    u.treasury.entries = [e for e in u.treasury.entries if e["kind"] != "income"]
    u.tick(now=later)
    assert u.store.get("ventures", v["id"])["stage"] == "killed"
    assert not u.store.get("products", prod["id"])["active"] and ("off", 99) in etsy_calls
    assert "no longer available" in digital.page_product(u.store.get("products", prod["id"]))


def test_owner_assisted_ideas_still_wait_for_the_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setenv("STARNET_PUBLIC_URL", "https://city.example.com")
    u = Ultron(str(tmp_path), client=FakeClaude([opp("Resume gig on Fiverr"), auto_opp(score=50)]))
    u.run_job({"kind": "routine", "routine": "R-001"}, now=MON_0900)
    u.tick(now=MON_0900)
    assert not any(v.get("autonomous") for v in u.store.all("ventures"))                # score 50: below the bar
    assert len(u.store.find("approvals", status="pending")) == 1


def test_research_restarts_when_every_run_failed(tmp_path):
    u = Ultron(str(tmp_path), client=FakeClaude([opp("x")]))
    u.cfg.update({"kicked_off": True, "audited": MON_0900.date().isoformat()})   # an old station whose kickoff failed
    u.store.update("ventures", "V-PPS", {"stage": "paused"}, "test")
    for r in u.store.all("routines"):
        u.store.update("routines", r["id"], {"last_run": MON_0900.isoformat()}, "test")
    assert u.next_job(MON_0900) == {"kind": "routine", "routine": "R-001", "kickoff": True}
    u.cfg["kickoff_at"] = MON_0900.isoformat()
    assert u.next_job(MON_0900.replace(minute=40))["kind"] != "routine"
    for r in u.store.all("routines"):
        u.store.update("routines", r["id"], {"last_run": MON_0900.replace(hour=12).isoformat()}, "test")
    assert u.next_job(MON_0900.replace(hour=12, minute=1)) == {"kind": "routine", "routine": "R-001", "kickoff": True}


def test_credits_counter(tmp_path, monkeypatch):
    from datetime import timedelta
    from backend.station import connectors, credits
    notes = []
    u = Ultron(str(tmp_path), client=FakeClaude([opp("x")]), notify=lambda t, b: notes.append(t))
    t = u.treasury
    assert credits.summary(u.store, t)["state"] == "unknown"                    # nothing recorded yet
    with pytest.raises(ValueError):
        credits.add(u.store, -5)
    credits.add(u.store, 20, "first top-up")
    usage = NS(input_tokens=1_000_000, output_tokens=100_000, cache_read_input_tokens=0, cache_creation_input_tokens=0,
               server_tool_use=None)                                            # $4 + $2 = $6
    t.charge_ai(usage, "A-002", None, "research")
    t.charge_ai(usage, "DESK", "V-001", "trading desk", unit="city")            # the desk's calls come off too...
    s = credits.summary(u.store, t)
    assert s["state"] == "ok" and s["added"] == 20 and s["used"] == 12 and s["remaining"] == 8
    assert t.ai_spent() == 6                                                    # ...but not off the station's own cap
    t.charge_ai(usage, "A-002", None, "research")
    assert credits.summary(u.store, t)["state"] == "low"
    u.tick(now=MON_0900)
    u.tick(now=MON_0900)
    assert notes.count("🛰️ Claude credits low") == 1                          # warned once per top-up
    # Anthropic's own cost report wins when it's higher (usage outside the station)
    monkeypatch.setenv("ANTHROPIC_ADMIN_KEY", "sk-ant-admin01-test")
    assert credits.reconcile_due(u.store, datetime.now(ET))
    monkeypatch.setattr(connectors, "_http_json", lambda m, url, h=None, **k: (
        {"data": [{"results": [{"amount": "1500.00", "currency": "USD"}]}], "has_more": False}
        if "cost_report" in url and h["x-api-key"].startswith("sk-ant-admin") else {}))
    credits.reconcile(u.store)
    s = credits.summary(u.store, t)
    assert s["reported"] == 15.0 and s["used"] == 18.0 and s["remaining"] == 2.0
    assert not credits.reconcile_due(u.store, datetime.now(ET))
    # Anthropic says empty: Claude jobs wait, then one tries again; a top-up clears it
    now = datetime.now(ET) + timedelta(seconds=5)                                   # after the last successful call
    credits.mark_empty(u.store, now)
    assert credits.summary(u.store, t)["state"] == "empty"
    assert credits.blocks_ai(u.store, t, now + timedelta(minutes=5))
    assert not credits.blocks_ai(u.store, t, now + timedelta(minutes=21))
    credits.add(u.store, 50)
    s = credits.summary(u.store, t)
    assert s["state"] == "ok" and s["added"] == 70 and not credits.blocks_ai(u.store, t, now)
    assert u.overview()["credits"]["remaining"] == s["remaining"]


def test_connect_buttons_reach_their_route(tmp_path, monkeypatch):
    """/api/station/connect/<service> must not be swallowed by /api/station/{collection}/{rid}."""
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("STARNET_MODE", "sim")
    monkeypatch.delenv("STARNET_PASSWORD", raising=False)
    monkeypatch.setenv("STARNET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ETSY_KEYSTRING", "key")
    monkeypatch.setenv("ETSY_SHARED_SECRET", "secret")
    monkeypatch.setenv("STARNET_PUBLIC_URL", "https://city.example.com")
    import backend.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        r = c.get("/api/station/connect/etsy", follow_redirects=False)
        assert r.status_code in (302, 307) and r.headers["location"].startswith("https://www.etsy.com/oauth/connect?")
        assert "redirect_uri=https%3A%2F%2Fcity.example.com%2Fapi%2Fstation%2Fconnect%2Fetsy%2Fcallback" in r.headers["location"]
        assert c.get("/api/station/connect/pinterest", follow_redirects=False).status_code == 400   # no app keys yet: says so
