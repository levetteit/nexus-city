"""The War Room: what works, what doesn't, and what we do instead. Chaired by ULTRON.

It convenes every Sunday 17:00 ET, and sooner whenever enough new results have come in (sales, sent
posts and emails, QA rejections, finished work, your feedback): the station gets better with every input.

What it decides, and what happens:
  double_down / keep   the venture carries on; its new tasks are queued
  modify               the changes become tasks for the right agents
  pivot / pause        the venture is paused on the spot (reversible) and ULTRON looks for the next one
  kill                 an approval for the owner (killing is the one call it doesn't make alone)
Lessons replace the old list and are fed into every agent's instructions. The research focus steers the
next Research Station routines.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import results
from .brain import Brain
from .crew import AGENT_RULES, staff
from .economy import Treasury
from .store import Store, now_iso

INPUT_KINDS = ("money.", "lead.", "action.sent", "action.qa_fail", "action.result", "task.completed", "owner.feedback",
               "venture.stage", "routine.completed", "task.escalated")
TRIGGER_INPUTS = 8          # this many new results, and at least a day since the last session
WEEKLY = (6, 17)            # Sunday 17:00 ET

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "What the numbers say, 80-160 words. Blunt."},
        "verdicts": {"type": "array", "items": {"type": "object", "properties": {
            "venture": {"type": "string", "description": "Venture id, e.g. V-002"},
            "verdict": {"type": "string", "enum": ["double_down", "keep", "modify", "pivot", "pause", "kill"]},
            "why": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "string"}},
            "changes": {"type": "array", "items": {"type": "object", "properties": {
                "title": {"type": "string"}, "role": {"type": "string"}, "instructions": {"type": "string"}},
                "required": ["title", "role", "instructions"], "additionalProperties": False}}},
            "required": ["venture", "verdict", "why", "evidence", "changes"], "additionalProperties": False}},
        "stop_doing": {"type": "array", "items": {"type": "string"}},
        "start_doing": {"type": "array", "items": {"type": "string"}},
        "lessons": {"type": "array", "items": {"type": "object", "properties": {
            "lesson": {"type": "string"}, "evidence": {"type": "string"},
            "applies_to": {"type": "string", "description": "'all', a role (e.g. 'Content Strategist', 'Outreach', 'Market Research') or a venture id"}},
            "required": ["lesson", "evidence", "applies_to"], "additionalProperties": False},
            "description": "The full updated list (at most 20): keep what the evidence supports, drop what it doesn't."},
        "research_focus": {"type": "string", "description": "What the Research Station should hunt for next, one or two sentences."},
    },
    "required": ["summary", "verdicts", "stop_doing", "start_doing", "lessons", "research_focus"],
    "additionalProperties": False,
}

SYSTEM = (AGENT_RULES + " You are the War Room Strategist of the Nexus City Space Station, with ULTRON in the chair. Your job "
          "is to look at what actually happened and be ruthless about it. Leads and sales beat likes: a post angle that "
          "brings DMs and WhatsApp messages is worth more than one that only gets reactions, and results_30d shows which "
          "posts brought leads. Then: what makes money or clearly moves toward it gets "
          "more; what doesn't, after a fair test, gets changed or cut, and we try something else. Judge on evidence "
          "(sales, replies, clicks, QA rejections, time spent, AI cost), not on hope. A venture younger than 5 days with no "
          "data yet is 'keep' unless something is clearly broken. Every lesson must cite evidence from the data given. "
          "The owner's mandate: money in as fast as possible with $0 startup capital; every part of the economy must earn "
          "its keep.")


def due(store: Store, cfg: dict, now: datetime) -> bool:
    last = datetime.fromisoformat(cfg["warroom_at"]) if cfg.get("warroom_at") else None
    if last and now - last < timedelta(hours=24):
        return False
    if (now.weekday(), now.hour) >= WEEKLY and (not last or now - last > timedelta(days=6)):
        return True
    since = last.astimezone(timezone.utc).isoformat() if last else ""
    return sum(1 for e in store.events(800, INPUT_KINDS) if e["at"] > since) >= TRIGGER_INPUTS


def shop_summary(venture: str, store: Store) -> Optional[dict]:
    """The Etsy shop's listings and orders: which products sell, which don't."""
    from . import shop
    if venture != shop.VENTURE:
        return None
    sm = shop.summary(store)
    return {k: sm[k] for k in ("pipeline", "orders_30d", "units_30d", "retail_30d", "cost_30d")} | {
        "listings": [{"title": x["title"], "type": x["type"], "orders": x["orders"], "listed": x["sent_at"]} for x in sm["live"]]}


def inputs(store: Store, treasury: Treasury, health: Callable[[dict], int], since: Optional[str]) -> dict:
    ventures = []
    for v in store.all("ventures"):
        acts = store.find("actions", venture=v["id"])
        stats = {}
        for a in acts:
            k = stats.setdefault(a["kind"], {})
            k[a["status"]] = k.get(a["status"], 0) + 1
        tasks = store.find("tasks", venture=v["id"])
        ventures.append({"id": v["id"], "name": v["name"], "stage": v["stage"], "offer": v.get("offer"), "launched": v.get("launched_at"),
                         "links": v.get("links"), "pnl": treasury.pnl("venture", v["id"]), "health": health(v),
                         "tasks": {s: sum(1 for t in tasks if t["status"] == s) for s in ("done", "queued", "waiting_owner", "failed")},
                         "outbound": stats, "results": [a["result"] for a in acts if a.get("result") and a["result"].get("note")][-10:],
                         "qa_rejections": [a["qa"]["issues"] for a in acts if a["status"] == "rejected"][-5:],
                         "results_30d": results.summary(store, v["id"], 30),
                         "shop_30d": shop_summary(v["id"], store),
                         "products": [{"title": p["title"], "price": p["price_usd"], "active": p.get("active"), "etsy": bool(p.get("etsy")),
                                       "listed": p["created_at"][:10], "sales": sum(1 for e in treasury.entries if e["kind"] == "income"
                                                                                    and p["slug"] in (e.get("note") or ""))}
                                      for p in store.all("products") if p["venture"] == v["id"]] or None,
                         "success_criteria": v.get("success_criteria"), "kill_criteria": v.get("kill_criteria")})
    ev = [e for e in store.events(1500, INPUT_KINDS) if not since or e["at"] > since]
    return {"ventures": ventures, "treasury": treasury.summary(), "new_results": [f"{e['at'][:16]} {e['summary']}" for e in ev[:80]],
            "owner_feedback": [f"{e['at'][:10]} on {e.get('ref', '-')}: {e['summary']}" for e in store.events(300, ("owner.feedback",))][:20],
            "lessons_now": store.load_doc("lessons.json") or [],
            "agents_cost_vs_output": [{"agent": a["name"], "delivered": a.get("tasks_done", 0), "ai_cost": treasury.pnl("agent", a["id"])["ai_costs"]}
                                      for a in store.all("agents") if a.get("kind") == "ai"],
            "top_open_opportunities": [{k: o.get(k) for k in ("id", "title", "score", "startup_cost_usd", "days_to_first_dollar")}
                                       for o in sorted(store.find("opportunities", status="open"), key=lambda o: -o.get("score", 0))[:8]]}


def convene(store: Store, brain: Brain, treasury: Treasury, health: Callable[[dict], int], cfg: dict,
            request_approval: Callable[..., dict], now: datetime) -> dict:
    """Hold the session and act on it. Blocking: run in a thread."""
    since = cfg.get("warroom_at")
    since_utc = datetime.fromisoformat(since).astimezone(timezone.utc).isoformat() if since else None
    data = inputs(store, treasury, health, since_utc)
    out = brain.structured("A-012", SYSTEM, "War Room session. The data:\n\n" + json.dumps(data, indent=1, default=str), SCHEMA)
    known = {v["id"] for v in store.all("ventures")}
    applied = []
    for vd in out["verdicts"]:
        vid = vd["venture"]
        if vid not in known:
            continue
        v = store.get("ventures", vid)
        if (vid == "V-001" or v.get("owner_business")) and vd["verdict"] in ("pause", "pivot", "kill"):
            continue   # the trading desk and the owner's own businesses get improved, not shut down, by the War Room
        if vd["verdict"] in ("pause", "pivot") and v["stage"] not in ("paused", "killed"):
            store.update("ventures", vid, {"stage": "paused", "next_action": f"War Room: {vd['verdict']}"}, "A-012",
                         f"WAR ROOM {vd['verdict'].upper()}: {vd['why'][:160]}", kind="venture.stage")
            for t in store.find("tasks", venture=vid, status="queued"):
                store.update("tasks", t["id"], {"status": "cancelled"}, "A-012", "venture paused by the War Room")
        elif vd["verdict"] == "kill" and v["stage"] != "killed":
            request_approval("venture_decision", "A-012", f"Kill: {v['name']}", vd["why"], venture=vid,
                             risk="Stops the venture and its tasks", payload={"stage": "killed"})
        for ch in vd["changes"][:5] if vd["verdict"] in ("double_down", "keep", "modify") else []:
            agent = staff(store, ch["role"], vid, by="A-012")
            store.create("tasks", {"title": ch["title"], "venture": vid, "assigned_agent": agent, "kind": "agent", "priority": 1,
                                   "day": 1, "instructions": ch["instructions"], "expected_output": "As described",
                                   "success_criteria": "Addresses the War Room's finding", "escalate_if": "", "depends_on": [],
                                   "status": "queued", "output": None, "attempts": 0, "from": "warroom"}, "A-012", f"War Room: {ch['title']}")
        applied.append({"venture": vid, "verdict": vd["verdict"]})
    store.save_doc("lessons.json", [dict(l, updated=now_iso()) for l in out["lessons"][:20]])
    cfg["warroom_at"] = now.isoformat()
    cfg["research_focus"] = out["research_focus"]
    doc = {**out, "at": now.isoformat(), "applied": applied}
    store.save_doc(f"warroom-{now.strftime('%Y-%m-%d-%H%M')}.json", doc)
    store.event("warroom.session", "A-012", out["summary"][:200], severity="ACTION NEEDED" if any(
        a["verdict"] in ("pause", "pivot", "kill") for a in applied) else "INFO", data={"applied": applied})
    return doc
