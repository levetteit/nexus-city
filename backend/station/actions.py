"""Everything that leaves the station goes through here: one queue, one QA gate, hard limits.

  drafted by an agent → QA (Compliance & QA agent) → sent by a connector, or queued for the owner
                     ↘ fails QA → the author revises once → QA again → rejected (the War Room sees it)

Rules, enforced in code, not by prompts:
  * nothing goes out without passing QA
  * the owner's outbound switch stops all sending at once (the Station's E-STOP)
  * daily caps per action type
  * outreach: never twice to the same address, never to anyone who opted out, and every contact
    must come with the public page where the business invites inquiries
  * no connector for it → it waits in the owner's queue with a Copy button, it's never dropped
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

from . import connectors
from .brain import Brain
from .crew import AGENT_RULES, lessons_text
from .store import Store, now_iso

CAPS = {"social.post": int(os.getenv("STARNET_POSTS_PER_DAY", "6")),
        "outreach.email": int(os.getenv("STARNET_OUTREACH_PER_DAY", "15")),
        "stripe.payment_link": 5}
POLICY = {   # auto: sends once QA passes; owner: waits for the owner's OK even after QA
    "social.post": os.getenv("STARNET_POLICY_SOCIAL", "auto"),
    "outreach.email": os.getenv("STARNET_POLICY_OUTREACH", "auto"),
    "stripe.payment_link": os.getenv("STARNET_POLICY_STRIPE", "auto"),
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)

QA_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail"]},
        "issues": {"type": "array", "items": {"type": "string"}},
        "required_changes": {"type": "array", "items": {"type": "string"}},
        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["verdict", "issues", "required_changes", "risk"],
    "additionalProperties": False,
}
QA_SYSTEM = (AGENT_RULES + " You are Compliance & QA, the last check before anything leaves the station. Fail it if any of "
             "these is true: a claim we can't back up (results, earnings, guarantees, testimonials, credentials, 'as seen "
             "in'); missing disclosure the platform or the FTC requires (#ad / affiliate links, AI-generated content where "
             "the platform requires it); breaks the platform's rules (spam, engagement bait, misleading links, automation "
             "the platform forbids); uses someone else's trademark, copyrighted work or likeness; for email: deceptive "
             "subject line, not clearly from us, a recipient that isn't a business that publicly invites inquiries, or a "
             "mass-mail tone instead of one specific, relevant offer; pressure tactics; anything illegal, unsafe or "
             "discriminatory. Also fail sloppy work: typos, wrong price, broken promise vs. the offer. Pass only what you'd "
             "be comfortable seeing on the front page with the owner's name on it.")


def contacts_doc(store: Store) -> dict:
    return store.load_doc("contacts.json") or {"contacted": {}, "do_not_contact": []}


def create(store: Store, kind: str, agent: str, venture: Optional[str], payload: dict, why: str) -> Optional[dict]:
    """File an outbound action for QA. Outreach to an address we've used or that opted out is refused here."""
    if kind == "outreach.email":
        to = (payload.get("to_email") or "").strip().lower()
        c = contacts_doc(store)
        dup = [a for a in store.find("actions", kind=kind) if a["payload"].get("to_email", "").lower() == to]
        if not EMAIL_RE.match(to) or to in c["do_not_contact"] or to in c["contacted"] or dup or not payload.get("source_url"):
            store.event("action.refused", agent, f"outreach to {to or '?'} refused: invalid, repeat, opted out or no public source",
                        ref=venture)
            return None
    return store.create("actions", {"kind": kind, "agent": agent, "venture": venture, "payload": payload, "status": "qa",
                                    "qa": None, "revisions": 0, "result": None, "why": why}, agent, f"{kind}: {why[:120]}")


def qa(store: Store, brain: Brain, action: dict) -> dict:
    """Compliance & QA reviews one action. Blocking: run in a thread."""
    venture = store.get("ventures", action["venture"]) if action.get("venture") else None
    out = brain.structured("A-011", QA_SYSTEM + lessons_text(store, "Compliance/Policy"), (
        f"ACTION TYPE: {action['kind']}\nVENTURE: {json.dumps({k: (venture or {}).get(k) for k in ('name', 'offer', 'links', 'language', 'market', 'compliance')})}\n"
        "If the venture has a language, the content must be in it, natural and correct. Its compliance list is binding.\n"
        f"WHY: {action['why']}\n\nCONTENT TO CHECK:\n{json.dumps(action['payload'], indent=1)}"), QA_SCHEMA,
        venture=action.get("venture"), effort="medium")
    if out["verdict"] == "pass":
        status = "ready"
    else:
        status = "revise" if action.get("revisions", 0) < 1 else "rejected"
    return store.update("actions", action["id"], {"status": status, "qa": out}, "A-011",
                        f"QA {out['verdict']}" + (f": {'; '.join(out['issues'])[:160]}" if out["issues"] else ""),
                        kind=f"action.qa_{out['verdict']}")


REVISE_SCHEMA = {"type": "object", "properties": {"payload_json": {"type": "string", "description": "The corrected content as a JSON object with the same keys."},
                                                  "what_changed": {"type": "string"}},
                 "required": ["payload_json", "what_changed"], "additionalProperties": False}


def revise(store: Store, brain: Brain, action: dict) -> dict:
    agent = store.get("agents", action["agent"]) or {"id": action["agent"], "role": "Content Strategist"}
    out = brain.structured(agent["id"], AGENT_RULES + f" You are the {agent['role']} agent." + lessons_text(store, agent["role"]), (
        "Compliance & QA sent this back. Fix every required change; don't add new claims.\n\n"
        f"QA: {json.dumps(action['qa'])}\n\nCONTENT:\n{json.dumps(action['payload'], indent=1)}"), REVISE_SCHEMA,
        venture=action.get("venture"), effort="medium")
    try:
        payload = {**action["payload"], **json.loads(out["payload_json"])}
    except (ValueError, TypeError):
        payload = action["payload"]
    return store.update("actions", action["id"], {"payload": payload, "status": "qa", "revisions": action.get("revisions", 0) + 1},
                        agent["id"], f"revised: {out['what_changed'][:140]}", kind="action.revised")


def sent_today(store: Store, kind: str) -> int:
    day = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for a in store.find("actions", kind=kind) if a["status"] == "sent" and (a.get("sent_at") or "").startswith(day))


def dispatch(store: Store, action: dict, outbound_on: bool) -> dict:
    """Send a QA-passed action if its connector, the policy, the caps and the switch all allow it.
    Fast (one HTTP call at most), but call it from a thread for real connectors."""
    kind, p = action["kind"], action["payload"]
    if action["status"] not in ("ready", "waiting_owner") or not (action.get("qa") or {}).get("verdict") == "pass":
        return action   # only what QA passed can ever be sent
    if not outbound_on:
        return action   # held: the owner switched outbound off
    if POLICY.get(kind) == "owner" and not action.get("owner_ok"):
        return store.update("actions", action["id"], {"status": "waiting_owner"}, "A-001", "policy: owner sends this kind",
                            kind="action.waiting_owner") if action["status"] != "waiting_owner" else action
    if sent_today(store, kind) >= CAPS.get(kind, 0):
        return action   # over today's cap: it waits for tomorrow
    try:
        if kind == "stripe.payment_link":
            if not connectors.stripe_configured():
                return _manual(store, action, "Stripe isn't connected")
            res = connectors.stripe_payment_link(p["name"], p.get("description", ""), float(p["price_usd"]), action["venture"])
            v = store.get("ventures", action["venture"])
            if v:
                links = {**(v.get("links") or {}), "stripe": res["url"]}
                store.update("ventures", v["id"], {"links": links}, "A-005", f"payment link live: {res['url']}", kind="venture.link")
        elif kind == "outreach.email":
            if not connectors.email_configured():
                return _manual(store, action, "email isn't connected")
            res = connectors.send_email(p["to_email"], p["subject"], p["body"])
            c = contacts_doc(store)
            c["contacted"][p["to_email"].lower()] = {"at": now_iso(), "venture": action["venture"], "action": action["id"]}
            store.save_doc("contacts.json", c)
        elif kind == "social.post":
            if not connectors.social_configured(p.get("platform", "")):
                return _manual(store, action, f"{p.get('platform')} isn't connected")
            if not connectors.platform_allowed(p.get("platform", ""), action.get("venture")):
                return _manual(store, action, f"the connected {p.get('platform')} account belongs to another venture")
            res = connectors.post_social(p["platform"], p["text"], p.get("link", ""))
        else:
            return _manual(store, action, "no connector for this kind")
    except connectors.ConnectorError as exc:
        return store.update("actions", action["id"], {"status": "failed", "result": {"error": str(exc)}}, "A-001",
                            f"send failed: {exc}", kind="action.failed")
    return store.update("actions", action["id"], {"status": "sent", "sent_at": now_iso(), "result": res}, action["agent"],
                        f"SENT {kind}", kind="action.sent")


def _manual(store: Store, action: dict, why: str) -> dict:
    if action["status"] == "manual":
        return action
    return store.update("actions", action["id"], {"status": "manual", "manual_reason": why}, "A-001",
                        f"QA passed; {why}: waiting in your posting queue", kind="action.manual")


def owner_done(store: Store, action_id: str, note: str = "") -> dict:
    """The owner posted / sent it by hand."""
    a = store.get("actions", action_id)
    if not a:
        raise KeyError(action_id)
    if a["status"] not in ("manual", "waiting_owner", "ready"):
        raise ValueError(f"it's {a['status']}")
    if a["kind"] == "outreach.email":
        c = contacts_doc(store)
        c["contacted"][a["payload"].get("to_email", "").lower()] = {"at": now_iso(), "venture": a["venture"], "action": a["id"]}
        store.save_doc("contacts.json", c)
    return store.update("actions", action_id, {"status": "sent", "sent_at": now_iso(), "result": {"by": "owner", "note": note}},
                        "owner", "owner sent it by hand", kind="action.sent")


def opt_out(store: Store, email: str) -> None:
    c = contacts_doc(store)
    e = email.strip().lower()
    if e and e not in c["do_not_contact"]:
        c["do_not_contact"].append(e)
        store.save_doc("contacts.json", c)
        store.event("contact.opt_out", "owner", f"{e} opted out: never contacted again")
