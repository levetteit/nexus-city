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
        "kpis": ["orders"], "success_criteria": "2 orders", "kill_criteria": "none in 21 days",
        "sell_via": "both", "price_usd": 25, "product_name": "Resume rewrite"}


class FakeClaude:
    """Answers like the API: research text for web-search calls, JSON for structured ones (picked by schema)."""

    def __init__(self, opps):
        self.opps, self.calls = opps, []
        self.qa = ["pass"]          # verdicts QA hands out, last one repeats
        self.warroom = {"verdicts": [], "lessons": []}
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
    return u, fake


def test_seeds_once_without_duplicates(tmp_path):
    u = Ultron(str(tmp_path), client=None)
    again = Ultron(str(tmp_path), client=None)
    assert len(again.store.all("routines")) == 5
    assert [a["name"] for a in again.store.all("agents")][:2] == ["ULTRON", "Market Research Agent"]
    assert len(again.store.all("agents")) == 12 and len(again.store.all("ventures")) == 1
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
    v = next(v for v in u.store.all("ventures") if v["id"] != "V-001")
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
                                    "marketing_plan": {"channels": [{"platform": "linkedin"}], "angles": [], "outreach": {"use": False}}}, "test")
    u.cfg["audited"] = MON_0900.date().isoformat()
    u.cfg["kicked_off"] = True
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
