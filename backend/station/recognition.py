"""Milestones and pets: the crew's progress, earned from the audit log, never invented.

Every agent's work count comes from the events it is credited with (tasks delivered, routines run, QA
calls, plans, posts drafted, War Room sessions, audits). Crossing a threshold earns a milestone, once,
with an event in the log; some milestones come with a pet that follows the agent around the 3D station.
Station milestones (first post, first lead, first sale...) are read from the same log and the ledger.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Optional

from .economy import Treasury
from .store import Store

WORK_KINDS = ("task.completed", "routine.completed", "action.qa_pass", "action.qa_fail", "action.revised",
              "venture.marketing_plan", "venture.content", "venture.outreach", "venture.planned", "warroom.session",
              "finance.audit", "opportunity.created", "action.metrics")

MILESTONES = [  # (work count, title, pet unlocked)
    (1, "First delivery", None),
    (5, "Reliable", "robo-cat"),
    (15, "Veteran", "drone"),
    (40, "Legend", "star-jelly"),
    (100, "Station Hall of Fame", "comet-fox"),
]
PET_NAMES = {"robo-cat": ["Bolt", "Pixel", "Widget", "Nano"], "drone": ["Sparky", "Zip", "Hover", "Echo"],
             "star-jelly": ["Nova", "Lumen", "Drift", "Aurora"], "comet-fox": ["Blaze", "Comet", "Vega", "Orbit"]}


def _pet_name(agent_id: str, kind: str) -> str:
    names = PET_NAMES[kind]
    return names[int(hashlib.sha256(f"{agent_id}:{kind}".encode()).hexdigest(), 16) % len(names)]


def work_counts(store: Store, limit: int = 20000) -> Counter:
    counts: Counter = Counter()
    for e in store.events(limit, WORK_KINDS):
        if e.get("by", "").startswith(("A-", "BOT-")):
            counts[e["by"]] += 1
    return counts


def update(store: Store) -> list[dict]:
    """Award milestones (and pets) newly earned. Returns what was awarded."""
    counts = work_counts(store)
    awarded = []
    for a in store.all("agents"):
        if a.get("kind") == "bot":
            continue
        n = counts.get(a["id"], 0)
        have = {m["title"] for m in a.get("achievements") or []}
        new = [(t, title, pet) for t, title, pet in MILESTONES if n >= t and title not in have]
        if not new and a.get("work") == n:
            continue
        achievements = list(a.get("achievements") or [])
        pet = a.get("pet")
        for t, title, kind in new:
            achievements.append({"title": title, "at_work": t})
            if kind:
                pet = {"kind": kind, "name": _pet_name(a["id"], kind)}
        changes = {"work": n, "achievements": achievements, "pet": pet}
        if new:
            what = ", ".join(title for _, title, _ in new)
            store.update("agents", a["id"], changes, "A-001",
                         f"{a['name']} earned {what}" + (f" and a pet {pet['kind']} named {pet['name']}" if any(k for _, _, k in new) else ""),
                         kind="agent.milestone")
            awarded.append({"agent": a["id"], "milestones": [title for _, title, _ in new], "pet": pet})
        else:
            with store.lock:   # just the live count: not an event
                store.data["agents"][a["id"]]["work"] = n
                store._save("agents")
    return awarded


def station_milestones(store: Store, treasury: Treasury) -> list[dict]:
    """The station's own firsts, with when they happened (None = not yet)."""
    def first(kinds, pred=None) -> Optional[str]:
        evs = [e for e in store.events(20000, kinds) if not pred or pred(e)]
        return evs[-1]["at"] if evs else None
    income = sorted((e for e in treasury.entries if e["kind"] in ("income", "lucid_payout")), key=lambda e: e["at"])
    running, hit100, hit1000 = 0.0, None, None
    for e in income:
        running += e["amount"]
        if running >= 100 and not hit100:
            hit100 = e["at"]
        if running >= 1000 and not hit1000:
            hit1000 = e["at"]
    rows = [
        ("First opportunity found", first(("opportunity.created",))),
        ("First venture launched", first(("approval.approved",), lambda e: "Launch" in e.get("summary", ""))),
        ("First post published", first(("action.sent",))),
        ("First lead", first(("lead.created",))),
        ("First sale", income[0]["at"] if income else None),
        ("$100 earned", hit100),
        ("$1,000 earned", hit1000),
        ("First War Room session", first(("warroom.session",))),
    ]
    return [{"title": t, "at": at} for t, at in rows]
