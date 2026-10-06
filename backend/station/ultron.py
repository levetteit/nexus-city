"""ULTRON, the station's commander. He reports to Jarvis (the owner's Claude operations lead).

Every tick ULTRON:
  * keeps the roster and the treasury current (trading bots, Lucid payouts)
  * runs the Research Station's routines on schedule, one job at a time
  * plans approved ventures and hands drafting tasks to agents as their inputs become ready
  * catches stalled and failed work and retries or escalates it
  * benches idle agents to the Crew Lounge and calls them back when there's work
  * proposes the next $0-capital venture to launch, and funding goals the treasury can now cover
  * writes a daily report for Jarvis and the owner

What ULTRON never does: spend or move money, act on an outside account, publish, contact anyone, or
touch the trading bots' orders and risk. Each of those is an approval that waits for the owner.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from . import crew, research
from .brain import Brain
from .economy import AI_BUDGET, Treasury
from .store import STAGES, Store, now_iso

ET = ZoneInfo("America/New_York")
MAX_EXPERIMENTS = int(os.getenv("STARNET_STATION_EXPERIMENTS", "3"))      # live ventures besides the trading desk
TASKS_PER_DAY = int(os.getenv("STARNET_STATION_TASKS_PER_DAY", "25"))     # agent drafting runs per ET day
STALL_MINUTES = 30
ACTIVE_STAGES = ("approved", "build", "launch", "operate", "measure", "optimize", "scale")
REPORT_AT = (8, 30)   # ET, daily

APPROVAL_KINDS = ("launch_venture", "fund_goal", "venture_decision", "spend")


class Ultron:
    def __init__(self, data_dir: str, client=None, notify: Optional[Callable[[str, str], None]] = None) -> None:
        self.store = Store(data_dir)
        self.treasury = Treasury(self.store)
        self.brain = Brain(self.treasury, client)
        self.notify = notify or (lambda title, body: None)
        self.busy: Optional[str] = None      # what ULTRON is coordinating right now
        self.last_error = ""
        self.cfg = self.store.load_doc("ultron.json") or {"mandate": research.MANDATE, "kicked_off": False,
                                                           "reported": "", "budget_warned": "", "reminded": {}}
        self._seed()

    # ---------------------------------------------------------------- setup
    def _seed(self) -> None:
        s = self.store
        crew.seed(s)
        for r in research.ROUTINES:
            if not s.get("routines", r["id"]):
                s.create("routines", {"id": r["id"], "name": r["name"], "station": "research", "days": r["days"],
                                      "at": r["at"], "output_type": "opportunities", "last_run": None,
                                      "status": "active", "runs": 0}, "A-001", "routine scheduled")
        if not s.get("ventures", "V-001"):
            s.create("ventures", {"id": "V-001", "name": "Starnet City Trading Desk", "category": "trading",
                                  "stage": "operate", "owner": "owner", "unit": "city", "agents": [],
                                  "offer": "MNQ micro futures on a LucidFlex 50K prop account (PROC strategy)",
                                  "objective": "Pass the evaluation, then take funded payouts",
                                  "success_criteria": "Payouts taken", "kill_criteria": "Account failure (the desk's own rules)",
                                  "next_action": "Trade the killzones", "opportunity": None}, "A-001",
                     "the trading city joins the station as Venture #1")
        if not s.get("missions", "M-001"):
            s.create("missions", {"id": "M-001", "name": "First Dollar", "priority": 1, "state": "active", "owner": "owner",
                                  "goal": "Real money in from a $0-capital venture as fast as possible, then fund the first "
                                          "Etsy store (~$29/month) from earnings.",
                                  "success_criteria": "First owner-recorded income from a station venture; Etsy launch funded",
                                  "kill_criteria": "None: re-plan if no venture earns within 30 days",
                                  "budget": f"$0 cash; station AI capped at ${AI_BUDGET:.0f}/month",
                                  "ventures": []}, "owner", "mission set by the owner")
        self._save_cfg()

    def _save_cfg(self) -> None:
        self.store.save_doc("ultron.json", self.cfg)

    # ---------------------------------------------------------------- the tick (fast, no network)
    def tick(self, engine=None, now: Optional[datetime] = None, real_account: bool = True) -> Optional[dict]:
        """Housekeeping, then the next job to run (or None). Call often; run the job in a thread.
        real_account=False (the simulation) keeps simulated payouts out of the treasury."""
        now = now or datetime.now(timezone.utc).astimezone(ET)
        if engine is not None:
            crew.sync_bots(self.store, engine)
            if real_account:
                self.treasury.sync_payouts(engine.account)
        self._watch_tasks(now)
        self._watch_money(now)
        self._propose(now)
        if (now.hour, now.minute) >= REPORT_AT and self.cfg.get("reported") != now.date().isoformat():
            self.report(now, engine)
        return None if self.busy else self.next_job(now)

    def next_job(self, now: datetime) -> Optional[dict]:
        if not self.brain.enabled or not self.treasury.ai_allowed():
            return None
        for v in self.store.all("ventures"):
            if v["stage"] == "approved" and v.get("opportunity") and not v.get("planned"):
                return {"kind": "plan", "venture": v["id"]}
        for r in self.store.all("routines"):
            spec = next((x for x in research.ROUTINES if x["id"] == r["id"]), None)
            if spec and r.get("status") == "active" and research.due(spec, now, r.get("last_run")):
                return {"kind": "routine", "routine": r["id"]}
        if not self.cfg.get("kicked_off") and not self.store.all("opportunities"):
            return {"kind": "routine", "routine": "R-001", "kickoff": True}   # first start: research now, not tomorrow
        if self._tasks_today(now) < TASKS_PER_DAY:
            queued = [t for t in self.store.find("tasks", status="queued", kind="agent") if crew.ready(self.store, t)]
            if queued:
                t = min(queued, key=lambda t: (t.get("day", 9), t.get("priority", 9), t["created_at"]))
                return {"kind": "task", "task": t["id"]}
        return None

    def run_job(self, job: dict, now: Optional[datetime] = None) -> Optional[dict]:
        """Do one job. Blocking (Claude calls): run in a thread."""
        now = now or datetime.now(timezone.utc).astimezone(ET)
        s = self.store
        try:
            if job["kind"] == "routine":
                r = s.get("routines", job["routine"])
                spec = next(x for x in research.ROUTINES if x["id"] == r["id"])
                self.busy = f"Research Station: {r['name']}"
                s.update("agents", "A-002", {"status": "WORKING", "current_task": r["name"]}, "A-002", f"running {r['name']}", kind="agent.state")
                doc = research.run_routine(spec, s, self.brain, now, self.cfg.get("mandate", research.MANDATE))
                s.update("routines", r["id"], {"last_run": now.isoformat(), "runs": r.get("runs", 0) + 1, "last_summary": doc["summary"],
                                               "last_pick": doc["first_pick"]}, "A-002", f"{r['name']} filed {len(doc['filed'])} opportunities",
                         kind="routine.completed")
                s.update("agents", "A-002", {"status": "COMPLETED", "current_task": None, "last_output": r["name"]}, "A-002", "routine done",
                         kind="agent.state")
                if job.get("kickoff"):
                    self.cfg["kicked_off"] = True
                    self._save_cfg()
                self._propose(now)
                return doc
            if job["kind"] == "plan":
                v = s.get("ventures", job["venture"])
                self.busy = f"Validating {v['name']}"
                s.update("ventures", v["id"], {"planned": True}, "A-001", "handed to the Validation Agent")
                return crew.plan_venture(s, self.brain, v, s.get("opportunities", v["opportunity"]))
            if job["kind"] == "task":
                t = s.get("tasks", job["task"])
                self.busy = f"{t['title']} ({t['venture']})"
                return crew.run_task(s, self.brain, t)
        except Exception as exc:
            self.last_error = str(exc)[:200]
            s.event("ultron.job_failed", "A-001", f"{job['kind']} failed: {self.last_error}", ref=job.get("task") or job.get("routine")
                    or job.get("venture"), severity="WARNING")
            if job["kind"] == "routine" and job.get("kickoff"):
                self.cfg["kicked_off"] = True   # don't hammer a failing kickoff; the schedule takes over
                self._save_cfg()
            if job["kind"] == "routine":   # a failed slot is skipped, not retried in a loop
                s.update("routines", job["routine"], {"last_run": now.isoformat(), "last_error": self.last_error}, "A-001", "run failed")
            if job["kind"] == "plan":
                s.update("ventures", job["venture"], {"planned": False}, "A-001", "planning failed; will retry")
        finally:
            self.busy = None
        return None

    def _tasks_today(self, now: datetime) -> int:
        day = now.astimezone(timezone.utc).date().isoformat()
        return sum(1 for e in self.store.events(500, ("task.completed", "task.failed")) if e["at"].startswith(day))

    # ---------------------------------------------------------------- oversight
    def _watch_tasks(self, now: datetime) -> None:
        s = self.store
        stall = (now - timedelta(minutes=STALL_MINUTES)).astimezone(timezone.utc).isoformat()
        for t in s.all("tasks"):
            if t["status"] == "running" and t["updated_at"] < stall and not self.busy:
                s.update("tasks", t["id"], {"status": "failed", "error": "stalled"}, "A-001", "stalled: no progress in 30 minutes",
                         kind="task.stalled")
                t = s.get("tasks", t["id"])
            if t["status"] == "failed":
                if t.get("attempts", 0) < 2:
                    s.update("tasks", t["id"], {"status": "queued"}, "A-001", "retrying once", kind="task.requeued")
                elif not t.get("escalated"):
                    s.update("tasks", t["id"], {"escalated": True}, "A-001", f"failed twice: {t.get('error', '')[:100]}",
                             kind="task.escalated")
                    s.event("alert", "A-001", f"Task {t['id']} '{t['title']}' failed twice and needs a look", ref=t["id"], severity="ACTION NEEDED")
            if t["kind"] == "owner" and t["status"] == "queued" and crew.ready(s, t):
                s.update("tasks", t["id"], {"status": "waiting_owner", "waiting_since": now_iso()}, "A-001",
                         f"WAITING FOR OWNER: {t['title']}", kind="task.waiting_owner")
                self.notify("🛰️ Station: your turn", f"{t['title']} ({t['venture']})")
        # idle crew goes to the lounge
        busy_agents = {t["assigned_agent"] for t in s.all("tasks") if t["status"] in ("queued", "running")}
        for a in s.all("agents"):
            if a.get("kind") == "ai" and a["status"] in ("COMPLETED", "WAITING") and a["id"] not in busy_agents and a["id"] != "A-002":
                s.update("agents", a["id"], {"status": "ON BREAK", "current_task": None}, "A-001", "no work queued: Crew Lounge",
                         kind="agent.state")
            elif a.get("kind") == "ai" and a["status"] == "ON BREAK" and a["id"] in busy_agents:
                s.update("agents", a["id"], {"status": "WAITING"}, "A-001", "back from the lounge: work queued", kind="agent.state")
        if s.get("agents", "A-002")["status"] == "COMPLETED" and not (self.busy or "").startswith("Research"):
            s.update("agents", "A-002", {"status": "ON BREAK"}, "A-001", "routines done for now: Crew Lounge", kind="agent.state")

    def _watch_money(self, now: datetime) -> None:
        month = now.strftime("%Y-%m")
        spent = self.treasury.ai_spent()
        if spent >= 0.8 * AI_BUDGET and self.cfg.get("budget_warned") != month:
            self.cfg["budget_warned"] = month
            self._save_cfg()
            self.store.event("alert", "A-004", f"Station AI spend ${spent:.2f} of ${AI_BUDGET:.0f} this month: research slows at the cap",
                             severity="WARNING")
            self.notify("🛰️ Station AI budget at 80%", f"${spent:.2f} of ${AI_BUDGET:.0f} this month")
        for g in self.treasury.summary()["goals"]:
            if g["funded"] and not self._approval_for("fund_goal", g["id"]):
                self.request("fund_goal", "A-004", f"Fund: {g['name']} (${g['monthly']:.0f}/month)",
                             f"The treasury now covers {g.get('months', 1)} months of it on top of a month of bills. {g.get('why', '')}",
                             cost=g["monthly"], reversible=True, risk="Recurring cost; cancel any time", payload={"goal": g["id"]})

    def _propose(self, now: datetime) -> None:
        """Keep one $0-capital launch proposal in front of the owner while there's room for an experiment."""
        s = self.store
        live = [v for v in s.all("ventures") if v["id"] != "V-001" and v["stage"] in ACTIVE_STAGES]
        if len(live) >= MAX_EXPERIMENTS or self._approval_for("launch_venture", None, pending_only=True):
            return
        taken = {v.get("opportunity") for v in s.all("ventures")}
        declined = {a["payload"].get("opportunity") for a in s.all("approvals") if a["kind"] == "launch_venture"}
        pool = [o for o in s.all("opportunities") if o.get("status") == "open" and o["id"] not in taken | declined
                and o.get("startup_cost_usd", 1) == 0 and o.get("recommendation") in ("build_now", "investigate")]
        if not pool:
            return
        o = max(pool, key=lambda o: (o.get("recommendation") == "build_now", o.get("score", 0), -o.get("days_to_first_dollar", 99)))
        self.request("launch_venture", "A-001", f"Launch: {o['title']}",
                     f"Score {o['score']}/100, $0 to start, first dollar in about {o['days_to_first_dollar']} days. {o['summary']}",
                     cost=0, reversible=True, risk="; ".join(o.get("risks", [])[:3]), venture=None,
                     payload={"opportunity": o["id"], "owner_actions": o.get("owner_actions", [])})

    def _approval_for(self, kind: str, goal: Optional[str], pending_only: bool = False) -> Optional[dict]:
        for a in self.store.all("approvals"):
            if a["kind"] == kind and (goal is None or a["payload"].get("goal") == goal):
                if not pending_only or a["status"] == "pending":
                    return a
        return None

    # ---------------------------------------------------------------- approvals (the owner's desk)
    def request(self, kind: str, agent: str, action: str, reason: str, cost: float = 0.0, reversible: bool = True,
                risk: str = "", venture: Optional[str] = None, payload: Optional[dict] = None) -> dict:
        rec = self.store.create("approvals", {"kind": kind, "requesting_agent": agent, "venture": venture, "action": action,
                                              "reason": reason, "risk": risk, "cost": cost, "reversible": reversible,
                                              "requested_at": now_iso(), "status": "pending", "owner_response": None,
                                              "payload": payload or {}}, agent, f"WAITING FOR OWNER: {action}")
        self.store.event("approval.requested", agent, action, ref=rec["id"], severity="WAITING FOR OWNER")
        self.notify("🛰️ Waiting for you", action)
        return rec

    def decide(self, approval_id: str, decision: str, note: str = "") -> dict:
        s = self.store
        a = s.get("approvals", approval_id)
        if not a:
            raise KeyError(approval_id)
        if a["status"] != "pending":
            raise ValueError(f"already {a['status']}")
        if decision not in ("approve", "reject", "changes"):
            raise ValueError("decision must be approve, reject or changes")
        status = {"approve": "approved", "reject": "rejected", "changes": "changes_requested"}[decision]
        a = s.update("approvals", approval_id, {"status": status, "owner_response": note or None, "decided_at": now_iso()},
                     "owner", f"{status}: {a['action']}" + (f" ({note})" if note else ""), kind=f"approval.{status}")
        if status == "approved":
            if a["kind"] == "launch_venture":
                self._launch(a["payload"]["opportunity"], a["id"])
            elif a["kind"] == "fund_goal":
                s.create("tasks", {"title": a["action"].replace("Fund: ", ""), "venture": a.get("venture") or "M-001",
                                   "assigned_agent": "OWNER", "kind": "owner", "priority": 1, "day": 1,
                                   "instructions": "Approved. Set it up, then record the cost as a station expense so the treasury stays true.",
                                   "expected_output": "Done, cost recorded", "success_criteria": "Running", "escalate_if": "",
                                   "depends_on": [], "status": "queued", "output": None, "attempts": 0}, "A-001", "approved funding goal")
            elif a["kind"] == "venture_decision":
                stage = a["payload"].get("stage")
                if stage in STAGES and a.get("venture"):
                    s.update("ventures", a["venture"], {"stage": stage}, "owner", f"owner approved: {stage}", kind="venture.stage")
        return a

    def promote(self, opportunity_id: str) -> dict:
        """The owner promotes an opportunity straight from the Intelligence Feed (that is the approval)."""
        o = self.store.get("opportunities", opportunity_id)
        if not o:
            raise KeyError(opportunity_id)
        if o.get("status") != "open":
            raise ValueError(f"already {o.get('status')}")
        for a in self.store.all("approvals"):   # a pending proposal for the same opportunity is now decided
            if a["status"] == "pending" and a["payload"].get("opportunity") == opportunity_id:
                return {"approval": self.decide(a["id"], "approve", "promoted from the feed")}
        a = self.store.create("approvals", {"kind": "launch_venture", "requesting_agent": "owner", "venture": None,
                                            "action": f"Launch: {o['title']}", "reason": "Promoted by the owner", "risk": "",
                                            "cost": o.get("startup_cost_usd", 0), "reversible": True, "requested_at": now_iso(),
                                            "status": "approved", "owner_response": "promoted from the feed",
                                            "decided_at": now_iso(), "payload": {"opportunity": opportunity_id}},
                              "owner", f"owner promoted {o['title']}")
        return {"approval": a, "venture": self._launch(opportunity_id, a["id"])}

    def _launch(self, opportunity_id: str, approval_id: str) -> dict:
        s = self.store
        o = s.get("opportunities", opportunity_id)
        v = s.create("ventures", {"name": o["title"], "category": o["category"], "platform": o.get("platform"), "stage": "approved",
                                  "unit": "station", "owner": "owner", "opportunity": o["id"], "opportunity_score": o.get("score"),
                                  "approval": approval_id, "agents": [], "startup_cost": o.get("startup_cost_usd", 0),
                                  "success_criteria": o.get("success_criteria"), "kill_criteria": o.get("kill_criteria"),
                                  "next_action": "Validation Agent is planning the first week", "planned": False,
                                  "launched_at": now_iso()}, "A-001", f"approved by the owner: {o['title']}")
        s.update("opportunities", o["id"], {"status": "promoted", "venture": v["id"]}, "A-001", f"promoted to {v['id']}",
                 kind="opportunity.promoted")
        m = s.get("missions", "M-001")
        if m and m["state"] == "active":
            s.update("missions", "M-001", {"ventures": m.get("ventures", []) + [v["id"]]}, "A-001", f"{v['id']} joins the mission")
        return v

    def owner_done(self, task_id: str, note: str = "") -> dict:
        t = self.store.get("tasks", task_id)
        if not t or t["kind"] != "owner":
            raise KeyError(task_id)
        if t["status"] == "done":
            raise ValueError("already done")
        return self.store.update("tasks", task_id, {"status": "done", "output": {"deliverable": note or "done by the owner"}},
                                 "owner", f"owner did: {t['title']}", kind="task.completed")

    def record(self, kind: str, amount: float, unit: str, note: str, venture: Optional[str] = None) -> dict:
        """Real money, entered by the owner (a sale, a fee, a bill)."""
        if kind not in ("income", "expense"):
            raise ValueError("record income or expense")
        e = self.treasury.book(kind, amount, unit, "owner", note, venture=venture)
        if kind == "income" and venture and venture != "V-001":
            m = self.store.get("missions", "M-001")
            if m and m["state"] == "active" and not m.get("first_dollar_at"):
                self.store.update("missions", "M-001", {"first_dollar_at": now_iso()}, "owner",
                                  f"FIRST DOLLAR: ${amount:,.2f} from {venture}", kind="mission.milestone")
        return e

    # ---------------------------------------------------------------- reading
    def health(self, v: dict) -> int:
        """0-100: money, progress and time since the last progress."""
        if v["id"] == "V-001":
            return 70
        tasks = self.store.find("tasks", venture=v["id"])
        done = sum(1 for t in tasks if t["status"] == "done")
        pnl = self.treasury.pnl("venture", v["id"])
        score = 40 + (30 if pnl["income"] > 0 else 0) + (10 if pnl["net"] > 0 else 0) + int(20 * done / len(tasks) if tasks else 0)
        last = max([t["updated_at"] for t in tasks] + [v["updated_at"]])
        idle_days = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days
        return max(0, min(100, score - 5 * max(0, idle_days - 2) - (25 if v["stage"] in ("paused", "killed") else 0)))

    def overview(self, engine=None) -> dict:
        s = self.store
        ventures = []
        for v in sorted(s.all("ventures"), key=lambda v: v["id"]):
            tasks = s.find("tasks", venture=v["id"])
            ventures.append({**v, "pnl": self.treasury.pnl("venture", v["id"]), "health": self.health(v),
                             "tasks": {st: sum(1 for t in tasks if t["status"] == st) for st in
                                       ("queued", "running", "done", "failed", "waiting_owner")}})
        tasks = s.all("tasks")
        for t in tasks:
            if t["status"] == "queued" and not crew.ready(s, t):
                t["status"] = "blocked"
        queue = sorted((t for t in tasks if t["status"] not in ("done", "cancelled")),
                       key=lambda t: (t["status"] != "waiting_owner", t.get("priority", 9), t["created_at"]))
        opps = sorted((o for o in s.all("opportunities") if o.get("status") == "open"), key=lambda o: -o.get("score", 0))
        paper = engine.account.snapshot()["profit"] if engine is not None else None
        return {
            "now": datetime.now(timezone.utc).astimezone(ET).strftime("%a %Y-%m-%d %H:%M ET"),
            "coordinating": self.busy or "Watching the portfolio",
            "ai_enabled": self.brain.enabled, "error": self.last_error or self.brain.last_error,
            "mission": s.get("missions", "M-001"), "missions": s.all("missions"),
            "ventures": ventures, "agents": sorted(s.all("agents"), key=lambda a: a["id"]),
            "approvals": sorted((a for a in s.all("approvals") if a["status"] == "pending"), key=lambda a: a["requested_at"]),
            "owner_tasks": [t for t in queue if t["status"] == "waiting_owner"],
            "queue": queue[:40], "opportunities": opps[:25],
            "routines": sorted(s.all("routines"), key=lambda r: r["id"]),
            "treasury": self.treasury.summary(paper),
            "alerts": [e for e in s.events(60) if e["severity"] in ("WARNING", "CRITICAL", "ACTION NEEDED", "WAITING FOR OWNER")][:12],
            "events": s.events(40),
        }

    def report(self, now: datetime, engine=None) -> dict:
        """ULTRON's daily report to Jarvis: plain facts from the records, no model call."""
        s = self.store
        since = (now - timedelta(days=1)).astimezone(timezone.utc).isoformat()
        evs = [e for e in s.events(2000) if e["at"] >= since]
        t = self.treasury.summary(engine.account.snapshot()["profit"] if engine is not None else None)
        o = self.overview(engine)
        recs = []
        if o["approvals"]:
            recs.append(f"{len(o['approvals'])} approval(s) waiting for the owner: " + "; ".join(a["action"] for a in o["approvals"][:3]))
        if o["owner_tasks"]:
            recs.append(f"{len(o['owner_tasks'])} owner task(s) blocking ventures: " + "; ".join(x["title"] for x in o["owner_tasks"][:3]))
        for v in o["ventures"]:
            if v["id"] != "V-001" and v["stage"] in ACTIVE_STAGES and v["health"] < 40:
                recs.append(f"{v['name']} health {v['health']}: consider modify or pause")
        if t["ai"]["spent_month"] >= 0.8 * t["ai"]["budget"]:
            recs.append("AI budget nearly used: research will slow at the cap")
        doc = {"date": now.date().isoformat(), "at": now.isoformat(), "from": "ULTRON", "to": "Jarvis",
               "mission": o["mission"], "treasury": {k: t[k] for k in ("pool", "monthly_bills", "runway_months", "city", "station", "ai", "goals", "paper_pnl")},
               "ventures": [{k: v.get(k) for k in ("id", "name", "stage", "health", "pnl", "tasks", "next_action")} for v in o["ventures"]],
               "last_24h": {"events": len(evs),
                            "opportunities_filed": sum(1 for e in evs if e["kind"] == "opportunity.created"),
                            "tasks_completed": sum(1 for e in evs if e["kind"] == "task.completed"),
                            "routines_run": sum(1 for e in evs if e["kind"] == "routine.completed"),
                            "failures": sum(1 for e in evs if e["kind"] in ("ultron.job_failed", "task.failed", "task.stalled"))},
               "top_opportunities": [{k: x.get(k) for k in ("id", "title", "score", "startup_cost_usd", "days_to_first_dollar", "recommendation")}
                                     for x in o["opportunities"][:5]],
               "waiting_for_owner": [a["action"] for a in o["approvals"]] + [x["title"] for x in o["owner_tasks"]],
               "recommendations": recs or ["Nothing needs the owner today."]}
        s.save_doc(f"report-{doc['date']}.json", doc)
        self.cfg["reported"] = now.date().isoformat()
        self._save_cfg()
        s.event("ultron.report", "A-001", f"daily report: pool ${t['pool']:,.2f}, {len(doc['waiting_for_owner'])} waiting for owner")
        self.notify("🛰️ ULTRON daily report", f"Pool ${t['pool']:,.2f} · {len(doc['waiting_for_owner'])} waiting for you · "
                    + doc["recommendations"][0][:140])
        return doc

    def reports(self, limit: int = 7) -> list[dict]:
        return [self.store.load_doc(n) for n in self.store.list_docs("report-", limit)]
