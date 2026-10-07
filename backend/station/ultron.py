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

from . import actions, connectors, credits, crew, digital, finance, marketing, recognition, research, results, shop, warroom
from .brain import Brain
from .economy import AI_BUDGET, Treasury
from .store import STAGES, Store, now_iso

ET = ZoneInfo("America/New_York")


def _is_connection(exc) -> bool:
    """Claude is out of reach for every job, not just this one: the network, the key, or no API credit left.
    The job keeps its place and its slot; ULTRON waits and tries again."""
    try:
        import anthropic
    except ImportError:
        return False
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    return isinstance(exc, anthropic.APIStatusError) and (exc.status_code in (401, 403)
                                                          or "credit balance" in str(getattr(exc, "message", "")).lower())
MAX_EXPERIMENTS = int(os.getenv("STARNET_STATION_EXPERIMENTS", "3"))      # live ventures besides the trading desk
TASKS_PER_DAY = int(os.getenv("STARNET_STATION_TASKS_PER_DAY", "25"))     # agent drafting runs per ET day
STALL_MINUTES = 30
KICKOFF_RETRY = timedelta(hours=3)   # no opportunities on file: research again this soon instead of tomorrow
AI_BACKOFF = timedelta(minutes=20)   # after a connection failure, wait this long instead of burning the day's slots
ACTIVE_STAGES = ("approved", "build", "launch", "operate", "measure", "optimize", "scale")
REPORT_AT = (8, 30)   # ET, daily
AUDIT_AT = (7, 0)     # ET, daily

APPROVAL_KINDS = ("launch_venture", "fund_goal", "venture_decision", "spend")
# The owner's rule (Oct 6 2026): a $0 venture the crew can run end to end on its own rails launches without
# waiting; the owner is told and can kill it. It closes itself after KILL_AFTER days with no sale.
AUTO_LAUNCH = os.getenv("STARNET_AUTO_LAUNCH", "1") not in ("0", "false", "off")
KILL_AFTER = timedelta(days=int(os.getenv("STARNET_AUTO_KILL_DAYS", "21")))


class Ultron:
    def __init__(self, data_dir: str, client=None, notify: Optional[Callable[[str, str], None]] = None) -> None:
        self.store = Store(data_dir)
        connectors.set_data_dir(data_dir)
        self.treasury = Treasury(self.store)
        self.brain = Brain(self.treasury, client)
        self.notify = notify or (lambda title, body: None)
        self.busy: Optional[str] = None      # what ULTRON is coordinating right now
        self._recognized_at: Optional[datetime] = None
        self.milestones: list[dict] = []
        self.credits: Optional[dict] = None
        self.last_error = ""
        self.cfg = self.store.load_doc("ultron.json") or {"mandate": research.MANDATE, "kicked_off": False,
                                                           "reported": "", "budget_warned": "", "reminded": {}}
        if str(self.cfg.get("mandate", "")).startswith(research.OLD_MANDATE_START):
            self.cfg["mandate"] = research.MANDATE   # the owner's Oct 6 update: autonomous ventures first
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
        if not s.get("ventures", "V-PPS"):
            s.create("ventures", {"id": "V-PPS", "name": "Padilla Property Solutions", "category": "solar", "stage": "operate",
                                  "owner": "owner", "owner_business": True, "unit": "station", "planned": True,
                                  "offer": "Solar panel and battery systems for homes, installed anywhere in Puerto Rico, with financing available",
                                  "objective": "More qualified solar leads (DMs and WhatsApp messages) from Facebook and Instagram",
                                  "language": "es", "market": "Puerto Rico (the whole island)", "channels": ["facebook", "instagram"],
                                  "links": {},
                                  "notes": "We cover the entire island. Customers reach us by DM (Facebook or Instagram) or by the WhatsApp "
                                           "number listed on the Page: every post's call to action is DM or WhatsApp. Financing is "
                                           "available, with payments from $100. The Facebook Page still shows its old name, 'The Auto "
                                           "Plug PR', until the owner can rename it on Oct 13: write as Padilla Property Solutions. "
                                           "Learn from the Page's own recent posts.",
                                  "compliance": ["Payment amounts (like 'desde $100') only together with the down payment, term and APR "
                                                 "(Truth in Lending), which the owner hasn't provided yet: until then say 'financiamiento "
                                                 "disponible' or 'pagos accesibles', never a dollar amount",
                                                 "No savings, price or incentive claims unless the owner has provided them",
                                                 "Don't mention a federal tax credit for home solar unless the owner confirms one applies",
                                                 "Don't promise power during outages except for systems with batteries",
                                                 "Facts about LUMA, net metering or local programs only if accurate and current"],
                                  "success_criteria": "Leads from the Page every week", "kill_criteria": "None: the owner's own business",
                                  "next_action": "Marketing Lead studies the Page and writes the channel plan", "opportunity": None},
                     "owner", "the owner's solar business joins the station; it owns the Facebook Page")
        if not s.get("ventures", shop.VENTURE):
            s.create("ventures", {"id": shop.VENTURE, "name": "Etsy Print-on-Demand Shop", "category": "etsy", "stage": "operate",
                                  "owner": "owner", "owner_business": True, "agent_run": True, "unit": "station", "planned": True,
                                  "offer": "Original text-based t-shirts, sweatshirts, hoodies, mugs and posters, printed on demand "
                                           "by Printify and sold on the owner's Etsy shop",
                                  "objective": "Steady Etsy orders from niches that are selling now",
                                  "market": "Etsy buyers (US first)", "channels": [], "links": {},
                                  "agents": ["A-002", "A-SHOP", "A-DSGN", "A-011"],
                                  "notes": "Run entirely by the crew: research what sells, design our own version, QA, list through "
                                           "Printify, read the orders. The owner records Etsy deposits in Finance.",
                                  "compliance": ["Original designs only: never copy another shop's design, wording, photos or layout",
                                                 "No trademarks, brand names, sports teams, characters, celebrities, real people, "
                                                 "song lyrics or quotes someone owns",
                                                 "Etsy's rules: made-to-order items with a production partner; AI-assisted design "
                                                 "disclosed in the description",
                                                 "No 'best seller', 'official' or other claims we can't back up",
                                                 "Title max 140 characters, 13 tags max 20 characters each"],
                                  "success_criteria": "Orders every week", "kill_criteria": "None for the shop: the War Room "
                                  "drops products that don't sell, not the shop",
                                  "next_action": "Etsy Shop Manager: first best-seller scan", "opportunity": None},
                     "owner", "the owner's Etsy shop joins the station, run end to end by the crew")
        for a in s.find("approvals", kind="fund_goal"):
            if a["status"] == "pending" and a["payload"].get("goal") == "etsy-launch":
                s.update("approvals", a["id"], {"status": "withdrawn"}, "A-004", "the owner already runs the Etsy shop")
        m = s.get("missions", "M-001")
        if m and "first Etsy store" in m.get("goal", ""):
            s.update("missions", "M-001", {"goal": "Real money in from $0-capital ventures as fast as possible: the solar Page, "
                                                   "the crew-run Etsy shop and the first launched venture.",
                                           "success_criteria": "First owner-recorded income from a station venture"},
                     "owner", "the Etsy shop is already open: the mission is earning, not funding it")
        if not s.get("missions", "M-001"):
            s.create("missions", {"id": "M-001", "name": "First Dollar", "priority": 1, "state": "active", "owner": "owner",
                                  "goal": "Real money in from $0-capital ventures as fast as possible: the solar Page, "
                                          "the crew-run Etsy shop and the first launched venture.",
                                  "success_criteria": "First owner-recorded income from a station venture",
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
        self._requeue_connected()
        if not self._recognized_at or now - self._recognized_at >= timedelta(minutes=5):
            self._recognized_at = now
            recognition.update(self.store)
            self.milestones = recognition.station_milestones(self.store, self.treasury)
        self._review_autonomous(now)
        credits.watch(self.store, self.treasury, self.notify)
        self.credits = credits.summary(self.store, self.treasury)   # the city's top bar reads this, no file reads per frame
        self._propose(now)
        if (now.hour, now.minute) >= REPORT_AT and self.cfg.get("reported") != now.date().isoformat():
            self.report(now, engine)
        return None if self.busy else self.next_job(now)

    def next_job(self, now: datetime) -> Optional[dict]:
        s = self.store
        # jobs without a model call first: sending what QA passed, the daily audit
        if self.cfg.get("outbound", True):
            ready = [a for a in s.find("actions", status="ready") if a["kind"] not in self.cfg.get("capped", {}).get(now.date().isoformat(), [])]
            if ready:
                return {"kind": "dispatch", "action": min(ready, key=lambda a: a["created_at"])["id"]}
        if (now.hour, now.minute) >= AUDIT_AT and self.cfg.get("audited") != now.date().isoformat():
            return {"kind": "audit"}
        last = self.cfg.get("metrics_at")
        if (not last or now - datetime.fromisoformat(last) >= results.METRICS_EVERY) and results.posts_to_check(s, now):
            return {"kind": "metrics"}
        if shop.orders_due(self.cfg, now):
            return {"kind": "shop_orders"}
        if credits.reconcile_due(s, now):
            return {"kind": "credits_reconcile"}
        if not self.brain.enabled or not self.treasury.ai_allowed() or credits.blocks_ai(s, self.treasury, now):
            return None
        if self.cfg.get("ai_backoff_until") and now < datetime.fromisoformat(self.cfg["ai_backoff_until"]):
            return None
        for v in s.all("ventures"):
            if v["stage"] == "approved" and v.get("opportunity") and not v.get("planned"):
                return {"kind": "plan", "venture": v["id"]}
        for a in s.find("actions", status="qa"):
            return {"kind": "qa", "action": a["id"]}
        for a in s.find("actions", status="revise"):
            return {"kind": "revise", "action": a["id"]}
        if self.cfg.get("warroom_now") or warroom.due(s, self.cfg, now):
            return {"kind": "warroom"}
        selling = [v for v in s.all("ventures") if v["id"] != "V-001" and v["stage"] in ACTIVE_STAGES and v.get("planned")
                   and v["stage"] != "approved" and not v.get("agent_run")]   # the Etsy shop sells through its own pipeline
        for v in selling:
            mp = v.get("marketing_plan")
            if not mp or (mp.get("failed_at") and now - datetime.fromisoformat(mp["failed_at"]) > timedelta(hours=24)) \
                    or (not mp.get("audience") and not mp.get("failed_at")):   # an empty plan left by an earlier failure
                return {"kind": "marketing_plan", "venture": v["id"]}
        for v in selling:
            if (v.get("links") or v.get("channels")) and v.get("content_day") != now.date().isoformat():
                return {"kind": "content", "venture": v["id"]}
        for v in selling:
            mp = (v.get("marketing_plan") or {}).get("outreach") or {}
            last = v.get("outreach_day")
            if v.get("outreach_allowed") and mp.get("use") and (not last or (now.date() - datetime.fromisoformat(last).date()).days >= 2):
                return {"kind": "outreach", "venture": v["id"]}
        for r in s.all("routines"):
            spec = next((x for x in research.ROUTINES if x["id"] == r["id"]), None)
            if spec and r.get("status") == "active" and research.due(spec, now, r.get("last_run")):
                return {"kind": "routine", "routine": r["id"]}
        if not self.store.all("opportunities") and (not self.cfg.get("kickoff_at")
                                                     or now - datetime.fromisoformat(self.cfg["kickoff_at"]) >= KICKOFF_RETRY):
            # nothing on file yet (first start, or every run so far failed): research now, not at tomorrow's slot
            return {"kind": "routine", "routine": "R-001", "kickoff": True}
        if shop.research_due(s, self.cfg, now):
            return {"kind": "shop_research"}
        for v in digital.ventures(s):
            if digital.due(s, v, now):
                return {"kind": "product", "venture": v["id"]}
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
                doc = research.run_routine(spec, s, self.brain, now, self.cfg.get("mandate", research.MANDATE),
                                           self.cfg.get("research_focus", ""))
                s.update("routines", r["id"], {"last_run": now.isoformat(), "runs": r.get("runs", 0) + 1, "last_summary": doc["summary"],
                                               "last_pick": doc["first_pick"]}, "A-002", f"{r['name']} filed {len(doc['filed'])} opportunities",
                         kind="routine.completed")
                s.update("agents", "A-002", {"status": "COMPLETED", "current_task": None, "last_output": r["name"]}, "A-002", "routine done",
                         kind="agent.state")
                if job.get("kickoff"):
                    self.cfg["kicked_off"] = True
                    self.cfg["kickoff_at"] = now.isoformat()
                    self._save_cfg()
                self._propose(now)
                return doc
            if job["kind"] == "plan":
                v = s.get("ventures", job["venture"])
                self.busy = f"Validating {v['name']}"
                s.update("ventures", v["id"], {"planned": True}, "A-001", "handed to the Validation Agent")
                plan = crew.plan_venture(s, self.brain, v, s.get("opportunities", v["opportunity"]))
                if plan["verdict"] != "no_go" and plan["sell_via"] in ("stripe_link", "both") and plan["price_usd"] > 0:
                    actions.create(s, "stripe.payment_link", "A-005", v["id"], {"name": plan["product_name"], "description": plan["offer"],
                                                                                "price_usd": plan["price_usd"]}, f"checkout for {v['name']}")
                return plan
            if job["kind"] == "dispatch":
                a = s.get("actions", job["action"])
                self.busy = f"Sending {a['kind']}"
                out = actions.dispatch(s, a, self.cfg.get("outbound", True))
                if out["status"] == "ready":   # held by today's cap: don't spin on it until tomorrow
                    self.cfg.setdefault("capped", {})
                    self.cfg["capped"] = {now.date().isoformat(): sorted(set(self.cfg["capped"].get(now.date().isoformat(), [])) | {a["kind"]})}
                    self._save_cfg()
                return out
            if job["kind"] == "shop_research":
                self.busy = "Etsy Shop Manager: what's selling now"
                self.cfg["shop_research_at"] = now.isoformat()
                self._save_cfg()
                return shop.research(s, self.brain, now)
            if job["kind"] == "product":
                v = s.get("ventures", job["venture"])
                self.busy = f"Product Designer: next product for {v['name']}"
                return digital.create(s, self.brain, v, now)
            if job["kind"] == "credits_reconcile":
                self.busy = "Auditor: Anthropic cost report"
                return credits.reconcile(s)
            if job["kind"] == "shop_orders":
                self.busy = "Etsy Shop Manager: reading orders"
                self.cfg["shop_orders_at"] = now.isoformat()
                self._save_cfg()
                return shop.sync_orders(s, now)
            if job["kind"] == "metrics":
                self.busy = "Auditor: reading post engagement"
                self.cfg["metrics_at"] = now.isoformat()
                self._save_cfg()
                return results.refresh_metrics(s, now)
            if job["kind"] == "audit":
                self.busy = "Auditor: daily audit"
                self.cfg["audited"] = now.date().isoformat()
                self._save_cfg()
                return finance.audit(s, self.treasury)
            if job["kind"] in ("qa", "revise"):
                a = s.get("actions", job["action"])
                self.busy = f"Compliance & QA: {a['why'][:60]}" if job["kind"] == "qa" else f"Revising {a['kind']}"
                return (actions.qa if job["kind"] == "qa" else actions.revise)(s, self.brain, a)
            if job["kind"] == "warroom":
                self.busy = "War Room in session"
                self.cfg["warroom_now"] = False
                doc = warroom.convene(s, self.brain, self.treasury, self.health, self.cfg, self.request, now)
                self._save_cfg()
                self.notify("🛰️ War Room", doc["summary"][:200])
                return doc
            if job["kind"] in ("marketing_plan", "content", "outreach"):
                v = s.get("ventures", job["venture"])
                self.busy = {"marketing_plan": "Marketing Lead: channel plan", "content": "Content Creator: today's posts",
                             "outreach": "Outreach Agent: finding customers"}[job["kind"]] + f" ({v['name']})"
                if job["kind"] == "marketing_plan":
                    return marketing.plan(s, self.brain, v)
                if job["kind"] == "content":
                    return marketing.content(s, self.brain, v, now)
                return marketing.outreach(s, self.brain, v, now)
            if job["kind"] == "task":
                t = s.get("tasks", job["task"])
                self.busy = f"{t['title']} ({t['venture']})"
                return crew.run_task(s, self.brain, t)
        except Exception as exc:
            self.last_error = (self.brain.last_error or str(exc))[:200] if _is_connection(exc) else str(exc)[:200]
            if "credit balance" in str(exc).lower():
                credits.mark_empty(s, now)
            if _is_connection(exc):
                # the network or the key, not the job: keep the job and its slot, try again in a few minutes
                self.cfg["ai_backoff_until"] = (now + AI_BACKOFF).isoformat()
                self._save_cfg()
                s.event("ultron.ai_unreachable", "A-001", f"{job['kind']} waiting: {self.last_error}", severity="WARNING")
                if job["kind"] == "plan":
                    s.update("ventures", job["venture"], {"planned": False}, "A-001", "planning will retry")
                if job["kind"] == "shop_research":
                    self.cfg.pop("shop_research_at", None)
                    self._save_cfg()
                if job["kind"] == "product":
                    s.update("ventures", job["venture"], {"product_at": None}, "A-001", "Claude unreachable: product will retry")
                if job["kind"] in ("task",):
                    s.update("tasks", job["task"], {"status": "queued", "attempts": max(0, s.get("tasks", job["task"]).get("attempts", 1) - 1)},
                             "A-001", "Claude unreachable: back in the queue")
                if job["kind"] in ("qa", "revise"):
                    s.update("actions", job["action"], {"status": job["kind"]}, "A-001", "Claude unreachable: will retry")
                return None
            s.event("ultron.job_failed", "A-001", f"{job['kind']} failed: {self.last_error}", ref=job.get("task") or job.get("routine")
                    or job.get("venture"), severity="WARNING")
            if job["kind"] == "routine" and job.get("kickoff"):
                self.cfg["kicked_off"] = True   # don't hammer a failing kickoff: try again in KICKOFF_RETRY
                self.cfg["kickoff_at"] = now.isoformat()
                self._save_cfg()
            if job["kind"] == "shop_research":   # try again in 6 hours, not in 2 days
                self.cfg["shop_research_at"] = (now - shop.RESEARCH_EVERY + timedelta(hours=6)).isoformat()
                self._save_cfg()
            if job["kind"] == "routine":   # a failed slot is skipped, not retried in a loop
                s.update("routines", job["routine"], {"last_run": now.isoformat(), "last_error": self.last_error}, "A-001", "run failed")
            if job["kind"] == "plan":
                s.update("ventures", job["venture"], {"planned": False}, "A-001", "planning failed; will retry")
            if job["kind"] in ("content", "outreach"):
                s.update("ventures", job["venture"], {f"{job['kind']}_day": now.date().isoformat()}, "A-001", "skipped today after a failure")
            if job["kind"] == "marketing_plan":
                s.update("ventures", job["venture"], {"marketing_plan": {"channels": [], "angles": [], "outreach": {"use": False},
                                                                     "failed_at": now.isoformat()}},
                         "A-001", "channel plan failed; using an empty plan until the War Room revisits it")
            if job["kind"] in ("qa", "revise"):
                s.update("actions", job["action"], {"status": "failed", "result": {"error": self.last_error}}, "A-001", "QA could not run")
            if job["kind"] == "warroom":
                self.cfg["warroom_at"] = now.isoformat()   # try again tomorrow, not every 15 seconds
                self._save_cfg()
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

    def _requeue_connected(self) -> None:
        """A platform got connected: what was waiting in the owner's queue for it goes out on its own."""
        live = {"stripe.payment_link": connectors.stripe_configured(), "outreach.email": connectors.email_configured(),
                "shop.listing": connectors.printify_configured(), "digital.publish": connectors.rails()["storefront"]}
        for a in self.store.find("actions", status="manual"):
            plat = a["payload"].get("platform", "")
            ok = live.get(a["kind"]) if a["kind"] in live else (connectors.social_configured(plat)
                                                                 and connectors.platform_allowed(plat, a.get("venture")))
            if ok:
                self.store.update("actions", a["id"], {"status": "ready"}, "A-001", "connector is live now: sending it", kind="action.requeued")

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
                if g.get("one_time"):
                    self.request("fund_goal", "A-004", f"Buy: {g['name']} (${g['monthly']:,.0f})",
                                 f"The treasury now covers it on top of a month of bills. {g.get('why', '')}",
                                 cost=g["monthly"], reversible=False, risk="One-time purchase; an evaluation can fail",
                                 payload={"goal": g["id"]})
                    continue
                self.request("fund_goal", "A-004", f"Fund: {g['name']} (${g['monthly']:.0f}/month)",
                             f"The treasury now covers {g.get('months', 1)} months of it on top of a month of bills. {g.get('why', '')}",
                             cost=g["monthly"], reversible=True, risk="Recurring cost; cancel any time", payload={"goal": g["id"]})

    def _propose(self, now: datetime) -> None:
        """Keep one $0-capital launch proposal in front of the owner while there's room for an experiment."""
        s = self.store
        live = [v for v in s.all("ventures") if v["id"] != "V-001" and not v.get("owner_business") and v["stage"] in ACTIVE_STAGES]
        if len(live) >= MAX_EXPERIMENTS or self._approval_for("launch_venture", None, pending_only=True):
            return
        taken = {v.get("opportunity") for v in s.all("ventures")}
        declined = {a["payload"].get("opportunity") for a in s.all("approvals") if a["kind"] == "launch_venture"}
        pool = [o for o in s.all("opportunities") if o.get("status") == "open" and o["id"] not in taken | declined
                and o.get("startup_cost_usd", 1) == 0 and o.get("recommendation") in ("build_now", "investigate")]
        if not pool:
            return
        rank = lambda o: (o.get("recommendation") == "build_now", o.get("score", 0), -o.get("days_to_first_dollar", 99))
        auto = [o for o in pool if self._can_run_alone(o)]
        if AUTO_LAUNCH and auto and self.cfg.get("auto_launched_day") != now.date().isoformat():
            self._auto_launch(max(auto, key=rank), now)
            return
        o = max(pool, key=rank)
        self.request("launch_venture", "A-001", f"Launch: {o['title']}",
                     f"Score {o['score']}/100, $0 to start, first dollar in about {o['days_to_first_dollar']} days. {o['summary']}",
                     cost=0, reversible=True, risk="; ".join(o.get("risks", [])[:3]), venture=None,
                     payload={"opportunity": o["id"], "owner_actions": o.get("owner_actions", [])})

    def _can_run_alone(self, o: dict) -> bool:
        """The crew can make, sell and deliver it through rails that are live right now, with no owner work."""
        live = connectors.rails()
        return (o.get("execution") == "autonomous" and o.get("startup_cost_usd", 1) == 0 and o.get("product_format") not in (None, "none")
                and live["storefront"] and o.get("score", 0) >= 60)

    def _auto_launch(self, o: dict, now: datetime) -> dict:
        """The owner's standing rule stands in for the approval; the record says so."""
        a = self.store.create("approvals", {"kind": "launch_venture", "requesting_agent": "A-001", "venture": None,
                                            "action": f"Launch: {o['title']}", "reason": f"Score {o['score']}/100, $0, runs on the crew's own rails. {o['summary']}",
                                            "risk": "; ".join(o.get("risks", [])[:3]), "cost": 0, "reversible": True,
                                            "requested_at": now_iso(), "decided_at": now_iso(), "status": "approved",
                                            "owner_response": "auto: the owner's standing rule for autonomous $0 ventures",
                                            "payload": {"opportunity": o["id"], "auto": True}},
                                  "A-001", f"auto-approved by the owner's rule: {o['title']}")
        self.cfg["auto_launched_day"] = now.date().isoformat()
        self._save_cfg()
        v = self._launch(o["id"], a["id"], autonomous=True)
        self.store.event("venture.auto_launched", "A-001", f"launched on its own: {o['title']} (kill it any time; it closes itself "
                         f"after {KILL_AFTER.days} days with no sale)", ref=v["id"], severity="ACTION NEEDED")
        self.notify("🛰️ Launched on its own", f"{o['title']}: the crew makes, sells and delivers it. Kill it any time.")
        return v

    def _review_autonomous(self, now: datetime) -> None:
        """Close autonomous ventures with no sale after KILL_AFTER; take closed ventures' products off sale."""
        s = self.store
        for v in s.all("ventures"):
            if v.get("autonomous") and v["stage"] in ACTIVE_STAGES and v.get("launched_at"):
                age = now - datetime.fromisoformat(v["launched_at"])
                if age >= KILL_AFTER and self.treasury.pnl("venture", v["id"])["income"] <= 0:
                    v = s.update("ventures", v["id"], {"stage": "killed", "next_action": None}, "A-001",
                                 f"no sale in {KILL_AFTER.days} days: closed by the owner's rule", kind="venture.stage")
                    self.notify("🛰️ Venture closed", f"{v['name']}: no sale in {KILL_AFTER.days} days")
            if v["stage"] in ("killed", "paused") and any(p["venture"] == v["id"] and p.get("active") for p in s.all("products")):
                digital.retire(s, v["id"])

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

    def _launch(self, opportunity_id: str, approval_id: str, autonomous: Optional[bool] = None) -> dict:
        s = self.store
        o = s.get("opportunities", opportunity_id)
        if autonomous is None:   # an owner-approved launch of an idea the crew can run alone runs alone too
            autonomous = self._can_run_alone(o)
        extra = {"autonomous": True, "agent_run": True, "planned": True, "stage": "launch", "rails": o.get("rails") or ["storefront"],
                 "product_format": o.get("product_format"), "next_action": "Product Designer: the first product",
                 "agents": ["A-DSGN", "A-011", "A-SHOP", "A-006"]} if autonomous else {}
        v = s.create("ventures", {"name": o["title"], "category": o["category"], "platform": o.get("platform"), "stage": "approved",
                                  "unit": "station", "owner": "owner", "opportunity": o["id"], "opportunity_score": o.get("score"),
                                  "approval": approval_id, "agents": [], "startup_cost": o.get("startup_cost_usd", 0),
                                  "success_criteria": o.get("success_criteria"), "kill_criteria": o.get("kill_criteria"),
                                  "next_action": "Validation Agent is planning the first week", "planned": False,
                                  "launched_at": now_iso(), **extra}, "A-001",
                     ("launched on the owner's rule: " if autonomous else "approved by the owner: ") + o["title"])
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

    def scan_terms(self, task_id: str) -> list[str]:
        """Search phrases the crew wrote for an owner scan task (in its instructions or the inputs it depends on)."""
        from . import etsyscan
        t = self.store.get("tasks", task_id) or {}
        text = t.get("instructions", "") + "\n" + "\n".join(
            ((self.store.get("tasks", d) or {}).get("output") or {}).get("deliverable", "") for d in t.get("depends_on", []))
        return etsyscan.suggest_terms(text)

    def etsy_scan(self, task_id: str, terms: list, call=None) -> dict:
        """Do an owner's Etsy scan task through the Etsy API, and hand the result to the crew. Blocking."""
        from . import etsyscan
        t = self.store.get("tasks", task_id)
        if not t or t["kind"] != "owner":
            raise KeyError(task_id)
        if t["status"] == "done":
            raise ValueError("already done")
        if not terms:
            raise ValueError("give at least one search phrase")
        self.store.update("tasks", task_id, {"scan": {"state": "running", "at": now_iso()}}, "A-002",
                          f"scanning Etsy through the API: {len(terms)} phrases", kind="task.scan")
        try:
            result = etsyscan.scan(terms, call=call)
        except Exception as exc:
            self.store.update("tasks", task_id, {"scan": {"state": "failed", "error": str(exc)[:200], "at": now_iso()}},
                              "A-002", f"Etsy scan failed: {str(exc)[:120]}", kind="task.scan")
            raise
        url = etsyscan.save_csv(self.store.dir, task_id, result["rows"])
        s = result["summary"]
        self.store.update("tasks", task_id, {"status": "done", "scan": {"state": "done", "at": now_iso(), "csv": url, "summary": s},
                                             "output": {"deliverable": etsyscan.deliverable(result, url)}},
                          "A-002", f"Etsy scan done: {s['unique_listings']} listings, median ${s['median_price']}", kind="task.completed")
        return result

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
        if v.get("autonomous"):   # judged on sales, then on products on the shelf
            live = sum(1 for p in self.store.all("products") if p["venture"] == v["id"] and p.get("active"))
            inc = self.treasury.pnl("venture", v["id"])["income"]
            return max(10, min(100, 35 + 5 * min(6, live) + (35 if inc > 0 else 0) - (25 if v["stage"] in ("paused", "killed") else 0)))
        if v["id"] == shop.VENTURE:   # judged on orders, then on listings going up
            sm = shop.summary(self.store, 14)
            return max(20, min(100, 40 + 12 * sm["orders_14d"] + 2 * min(10, len(sm["live"]))))
        if v.get("owner_business"):   # judged on what it brings in: leads and sales in the last 14 days
            r = results.summary(self.store, v["id"], 14)
            return max(20, min(100, 40 + 8 * r["leads"] + 10 * r["by_status"].get("won", 0) + (10 if r["posts_sent"] else 0)))
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
                             "results": results.summary(s, v["id"], 30) if v["id"] != "V-001" else None,
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
            "treasury": self.treasury.summary(paper), "flights": self.treasury.flights(8),
            "outbound": self.cfg.get("outbound", True), "connectors": connectors.status(),
            "outbox": {"manual": s.find("actions", status="manual"), "waiting_owner": s.find("actions", status="waiting_owner"),
                       "in_qa": len(s.find("actions", status="qa")) + len(s.find("actions", status="revise")),
                       "sent": sorted(s.find("actions", status="sent"), key=lambda a: a.get("sent_at", ""), reverse=True)[:15],
                       "rejected": s.find("actions", status="rejected")[-10:], "failed": s.find("actions", status="failed")[-10:]},
            "lessons": s.load_doc("lessons.json") or [],
            "leads": sorted(s.all("leads"), key=lambda l: l["created_at"], reverse=True)[:40],
            "shop": shop.summary(s), "storefront": digital.summary(s, self.treasury),
            "credits": credits.summary(s, self.treasury),
            "milestones": self.milestones or recognition.station_milestones(s, self.treasury), "research_focus": self.cfg.get("research_focus", ""),
            "warroom": s.load_doc(s.list_docs("warroom-", 1)[0]) if s.list_docs("warroom-", 1) else None,
            "audit": s.load_doc(s.list_docs("audit-", 1)[0]) if s.list_docs("audit-", 1) else None,
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
