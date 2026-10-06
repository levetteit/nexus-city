"""The crew: who works on the station, and how a task gets done.

The roster starts small on purpose (the export: no agents just to inflate the count). ULTRON adds a
specialist only when a venture needs that role, and reuses one that already has it. The trading bots
are on the roster too, as the crew of Venture #1, so the station sees the whole economy.

Agents draft. They write the gig description, the product, the listing copy, the outreach message,
the content calendar. Anything that touches the outside world (making an account, publishing, sending,
paying, talking to a customer) is an owner task: it waits, marked WAITING FOR OWNER, until you do it
and tick it off. No agent ever claims to have done something outside the station.
"""
from __future__ import annotations

import json
from typing import Optional

from .brain import Brain
from .store import Store

CORE = [
    {"id": "A-001", "name": "ULTRON", "role": "Commander", "department": "command", "kind": "overseer",
     "specialty": "Portfolio decisions, delegation, approvals, the daily report to Jarvis"},
    {"id": "A-002", "name": "Market Research Agent", "role": "Market Research", "department": "research", "kind": "ai",
     "specialty": "Runs the Research Station's five routines; files opportunities"},
    {"id": "A-003", "name": "Opportunity Validation Agent", "role": "Opportunity Validation", "department": "research",
     "kind": "ai", "specialty": "Checks an approved opportunity and turns it into a venture plan and tasks"},
    {"id": "A-004", "name": "Finance Agent", "role": "Finance/Unit Economics", "department": "finance", "kind": "logic",
     "specialty": "Keeps the treasury: payouts, costs, AI budget, runway, funding goals"},
]

DEPARTMENT = {"Etsy Strategist": "marketplace", "Store Operations": "marketplace", "Fiverr Opportunity": "marketplace",
              "Service Delivery": "marketplace", "Listing/SEO": "marketplace", "Product Creation": "creative",
              "Creative/Design": "creative", "Video Production": "creative", "Music/Audio": "creative",
              "Scriptwriter": "creative", "Content Strategist": "marketing", "Marketing": "marketing",
              "Customer Support": "revenue", "Analytics": "finance", "Automation Engineer": "engineering",
              "Compliance/Policy": "command"}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["go", "go_with_changes", "no_go"]},
        "why": {"type": "string", "description": "2-4 sentences."},
        "offer": {"type": "string", "description": "The exact offer: what is sold, to whom, at what price."},
        "objective": {"type": "string", "description": "The 14-day goal, measurable."},
        "tasks": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Short handle like t1, t2 used in depends_on."},
                "title": {"type": "string"},
                "who": {"type": "string", "enum": ["agent", "owner"]},
                "role": {"type": "string", "description": "For agent tasks: the specialist role. For owner tasks: 'Owner'."},
                "instructions": {"type": "string", "description": "What needs to happen and why it matters."},
                "expected_output": {"type": "string"},
                "success_criteria": {"type": "string"},
                "escalate_if": {"type": "string"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "integer", "description": "1 = highest"},
                "day": {"type": "integer", "description": "Which day of the first week (1-7)."},
            },
            "required": ["ref", "title", "who", "role", "instructions", "expected_output", "success_criteria",
                         "escalate_if", "depends_on", "priority", "day"],
            "additionalProperties": False}},
        "kpis": {"type": "array", "items": {"type": "string"}},
        "success_criteria": {"type": "string"},
        "kill_criteria": {"type": "string"},
    },
    "required": ["verdict", "why", "offer", "objective", "tasks", "kpis", "success_criteria", "kill_criteria"],
    "additionalProperties": False,
}

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "deliverable": {"type": "string", "description": "The finished work, ready for the owner to use as-is (markdown)."},
        "notes": {"type": "string", "description": "Assumptions and anything the owner should check, 1-3 sentences."},
        "owner_next": {"type": "array", "items": {"type": "string"}, "description": "What the owner must do with it, if anything."},
        "met_success_criteria": {"type": "boolean"},
    },
    "required": ["deliverable", "notes", "owner_next", "met_success_criteria"],
    "additionalProperties": False,
}

AGENT_RULES = ("You work on the StarNet Space Station under ULTRON. You produce finished, honest work. You "
               "cannot browse marketplaces as a user, create accounts, publish, send messages, take payments or "
               "contact anyone: the owner does all of that. Never claim or imply that anything was published, sent, "
               "sold or verified. Follow platform rules and IP law; disclose AI use where the platform requires it. "
               "No fake reviews, testimonials, credentials or results.")


def seed(store: Store) -> None:
    for a in CORE:
        if not store.get("agents", a["id"]):
            store.create("agents", {**a, "status": "ON BREAK", "current_task": None, "current_venture": None,
                                    "tasks_done": 0, "achievements": []}, "station", "crew member joined")


def sync_bots(store: Store, engine) -> None:
    """Trading bots join the roster as Venture #1's crew; their status follows the city."""
    for b in engine.bots.values():
        aid = f"BOT-{b.cfg.id}"
        status = {"in_trade": "WORKING", "scanning": "THINKING", "disabled": "ON BREAK"}.get(b.status, "WAITING")
        rec = store.get("agents", aid)
        if not rec:
            store.create("agents", {"id": aid, "name": b.cfg.name, "role": "Trader", "department": "city", "kind": "bot",
                                    "specialty": f"PROC strategy on {b.cfg.underlying}", "status": status,
                                    "current_venture": "V-001", "current_task": None, "tasks_done": 0,
                                    "achievements": []}, "city", "trading bot joined the station roster")
        elif rec.get("status") != status:
            with store.lock:   # live status, not an audited decision: keep it out of the event log
                store.data["agents"][aid]["status"] = status
                store._save("agents")


def staff(store: Store, role: str, venture: str, by: str = "A-001") -> str:
    """The agent for a role: reuse whoever already has it, otherwise add one specialist."""
    role = role.strip() or "Generalist"
    for a in store.all("agents"):
        if a.get("role", "").lower() == role.lower() and a.get("kind") == "ai":
            if a.get("status") == "BENCHED":
                store.update("agents", a["id"], {"status": "ON BREAK"}, by, f"called back from the bench for {venture}")
            return a["id"]
    rec = store.create("agents", {"name": f"{role} Agent", "role": role, "department": DEPARTMENT.get(role, "revenue"),
                                  "kind": "ai", "specialty": role, "status": "ON BREAK", "current_task": None,
                                  "current_venture": venture, "tasks_done": 0, "achievements": []},
                       by, f"{venture} needs a {role}")
    return rec["id"]


def plan_venture(store: Store, brain: Brain, venture: dict, opp: dict) -> dict:
    """The Validation Agent's check, then the venture's first tasks with their dependencies."""
    plan = brain.structured("A-003", AGENT_RULES + " You are the Opportunity Validation Agent.", (
        "The owner approved this opportunity. Validate it and plan the first week as tasks. Agent tasks are drafting "
        "work an AI can finish from text alone; owner tasks are everything external (accounts, publishing, sending, "
        "payments, client calls). Order them so the owner can start today and the first sale can happen as early as "
        "possible. Keep it to 6-12 tasks.\n\nOPPORTUNITY:\n" + json.dumps(opp, indent=1, default=str)),
        PLAN_SCHEMA, venture=venture["id"])
    refs = {}
    for t in sorted(plan["tasks"], key=lambda t: (t["day"], t["priority"])):
        agent = "OWNER" if t["who"] == "owner" else staff(store, t["role"], venture["id"])
        rec = store.create("tasks", {
            "title": t["title"], "venture": venture["id"], "assigned_agent": agent, "kind": t["who"],
            "priority": t["priority"], "day": t["day"], "instructions": t["instructions"],
            "expected_output": t["expected_output"], "success_criteria": t["success_criteria"],
            "escalate_if": t["escalate_if"], "depends_on": [refs[d] for d in t["depends_on"] if d in refs],
            "status": "queued", "output": None, "attempts": 0}, "A-003", f"{venture['name']}: {t['title']}")
        refs[t["ref"]] = rec["id"]
    store.update("ventures", venture["id"], {
        "offer": plan["offer"], "objective": plan["objective"], "kpi_names": plan["kpis"],
        "success_criteria": plan["success_criteria"], "kill_criteria": plan["kill_criteria"],
        "validation": {"verdict": plan["verdict"], "why": plan["why"]},
        "agents": sorted({store.get("tasks", i)["assigned_agent"] for i in refs.values()} - {"OWNER"}),
        "stage": "build" if plan["verdict"] != "no_go" else "paused",
        "next_action": "Owner tasks are waiting" if plan["verdict"] != "no_go" else "Validation said no-go: review"},
        "A-003", f"validation: {plan['verdict']}: {plan['why'][:160]}", kind="venture.planned")
    return plan


def ready(store: Store, task: dict) -> bool:
    return all((store.get("tasks", d) or {}).get("status") == "done" for d in task.get("depends_on", []))


def run_task(store: Store, brain: Brain, task: dict) -> dict:
    """An agent does one drafting task. Blocking: run in a thread."""
    agent = store.get("agents", task["assigned_agent"])
    venture = store.get("ventures", task["venture"]) or {}
    inputs = [{"task": d["title"], "output": (d.get("output") or {}).get("deliverable", "")[:6000]}
              for d in (store.get("tasks", i) for i in task.get("depends_on", [])) if d]
    store.update("agents", agent["id"], {"status": "WORKING", "current_task": task["id"], "current_venture": venture.get("id")},
                 agent["id"], f"started {task['title']}", kind="agent.state")
    store.update("tasks", task["id"], {"status": "running", "attempts": task.get("attempts", 0) + 1}, agent["id"], "started")
    try:
        out = brain.structured(agent["id"], AGENT_RULES + f" You are the {agent['role']} agent.", (
            f"VENTURE: {venture.get('name')}\nOFFER: {venture.get('offer')}\nOBJECTIVE: {venture.get('objective')}\n\n"
            f"YOUR TASK: {task['title']}\n{task['instructions']}\nEXPECTED OUTPUT: {task['expected_output']}\n"
            f"SUCCESS CRITERIA: {task['success_criteria']}\n\nINPUTS FROM EARLIER TASKS:\n"
            + (json.dumps(inputs, indent=1) if inputs else "(none)")), TASK_SCHEMA, venture=venture.get("id"), effort="medium")
    except Exception as exc:
        store.update("tasks", task["id"], {"status": "failed", "error": str(exc)[:200]}, agent["id"], f"failed: {str(exc)[:120]}",
                     kind="task.failed")
        store.update("agents", agent["id"], {"status": "WAITING", "current_task": None}, agent["id"], "task failed", kind="agent.state")
        raise
    done = store.update("tasks", task["id"], {"status": "done", "output": out}, agent["id"],
                        f"delivered: {task['title']}", kind="task.completed")
    store.update("agents", agent["id"], {"status": "COMPLETED", "current_task": None, "tasks_done": agent.get("tasks_done", 0) + 1,
                                         "last_output": task["title"]}, agent["id"], "task delivered", kind="agent.state")
    return done
