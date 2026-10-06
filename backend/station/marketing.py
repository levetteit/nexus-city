"""Marketing & Outreach: get new customers, and turn the crew's work into content that sends traffic
to the ventures.

  Marketing Lead    one channel plan per venture (audience, channels, angles, whether to do outreach)
  Content Creator   daily: turns the venture's finished work into posts that link to where customers buy
  Outreach Agent    every other day: finds businesses that publicly invite inquiries and writes each one
                    a specific, honest message

Everything they write is filed as an action (actions.py): QA first, then sent or queued for the owner.
A venture only gets content once it has somewhere to send people (a payment link or a listing URL).
"""
from __future__ import annotations

import json
from datetime import datetime

from . import actions
from .brain import Brain
from .crew import AGENT_RULES, lessons_text
from .store import Store

PLATFORMS = ["x", "instagram", "facebook", "linkedin", "tiktok", "pinterest", "threads", "bluesky", "reddit", "youtube"]

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "audience": {"type": "string"},
        "channels": {"type": "array", "items": {"type": "object", "properties": {
            "platform": {"type": "string", "enum": PLATFORMS}, "why": {"type": "string"},
            "posts_per_week": {"type": "integer"}}, "required": ["platform", "why", "posts_per_week"], "additionalProperties": False}},
        "angles": {"type": "array", "items": {"type": "string"}, "description": "3-6 content angles that sell this offer honestly."},
        "outreach": {"type": "object", "properties": {
            "use": {"type": "boolean"}, "targets": {"type": "string", "description": "Which businesses, and why they'd buy."},
            "hook": {"type": "string"}}, "required": ["use", "targets", "hook"], "additionalProperties": False},
        "kpis": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["audience", "channels", "angles", "outreach", "kpis"],
    "additionalProperties": False,
}

POSTS_SCHEMA = {
    "type": "object",
    "properties": {"posts": {"type": "array", "items": {"type": "object", "properties": {
        "platform": {"type": "string", "enum": PLATFORMS},
        "text": {"type": "string", "description": "The full post, within the platform's length limit, with any disclosure it needs."},
        "angle": {"type": "string"}}, "required": ["platform", "text", "angle"], "additionalProperties": False}}},
    "required": ["posts"], "additionalProperties": False,
}

PROSPECTS_SCHEMA = {
    "type": "object",
    "properties": {"prospects": {"type": "array", "items": {"type": "object", "properties": {
        "company": {"type": "string"}, "contact_name": {"type": "string", "description": "Only if published; else empty."},
        "to_email": {"type": "string", "description": "A business address published for inquiries (info@, hello@, a listed contact)."},
        "source_url": {"type": "string", "description": "The page where that address is published."},
        "why_them": {"type": "string"}, "subject": {"type": "string"},
        "body": {"type": "string", "description": "Under 120 words, specific to them, one clear offer, no hype. No footer (added automatically)."}},
        "required": ["company", "contact_name", "to_email", "source_url", "why_them", "subject", "body"], "additionalProperties": False}}},
    "required": ["prospects"], "additionalProperties": False,
}


def _link(v: dict) -> str:
    links = v.get("links") or {}
    return links.get("stripe") or next(iter(links.values()), "")


def _work(store: Store, v: dict, n: int = 6) -> list[dict]:
    done = [t for t in store.find("tasks", venture=v["id"], status="done") if t.get("kind") == "agent" and t.get("output")]
    return [{"task": t["title"], "work": t["output"].get("deliverable", "")[:2500]} for t in done[-n:]]


def plan(store: Store, brain: Brain, v: dict) -> dict:
    out = brain.structured("A-005", AGENT_RULES + " You are the Marketing Lead." + lessons_text(store, "Marketing", v["id"]), (
        "Write the channel plan for this venture: where its customers actually are, the few channels worth our time "
        "(we have no ad budget), honest angles, and whether direct outreach to businesses makes sense.\n\n"
        + json.dumps({k: v.get(k) for k in ("name", "category", "platform", "offer", "objective", "links")}, indent=1)),
        PLAN_SCHEMA, venture=v["id"])
    return store.update("ventures", v["id"], {"marketing_plan": out}, "A-005", f"channel plan: {', '.join(c['platform'] for c in out['channels'])}",
                        kind="venture.marketing_plan")


def content(store: Store, brain: Brain, v: dict, now: datetime) -> list[dict]:
    mp = v.get("marketing_plan") or {}
    channels = [c["platform"] for c in mp.get("channels", [])] or ["x"]
    out = brain.structured("A-006", AGENT_RULES + " You are the Content Creator." + lessons_text(store, "Content Strategist", v["id"]), (
        f"Write today's posts for {', '.join(channels)} (one per channel, at most 3). Turn the crew's real work below into "
        "useful content (a tip, a before/after, a sample) that makes the right customer click through. The link is added "
        "for you; don't invent results or testimonials.\n\n"
        f"VENTURE: {json.dumps({k: v.get(k) for k in ('name', 'offer')})}\nANGLES: {json.dumps(mp.get('angles', []))}\n"
        f"AUDIENCE: {mp.get('audience', '')}\nWORK:\n{json.dumps(_work(store, v), indent=1)}"), POSTS_SCHEMA, venture=v["id"], effort="medium")
    filed = []
    for p in out["posts"][:3]:
        a = actions.create(store, "social.post", "A-006", v["id"], {"platform": p["platform"], "text": p["text"], "link": _link(v)},
                           f"{p['platform']} post for {v['name']}: {p['angle']}")
        if a:
            filed.append(a)
    store.update("ventures", v["id"], {"content_day": now.date().isoformat()}, "A-006", f"{len(filed)} posts drafted", kind="venture.content")
    return filed


def outreach(store: Store, brain: Brain, v: dict, now: datetime) -> list[dict]:
    mp = (v.get("marketing_plan") or {}).get("outreach") or {}
    c = actions.contacts_doc(store)
    skip = sorted(set(c["contacted"]) | set(c["do_not_contact"]))[-200:]
    system = (AGENT_RULES + " You are the Outreach Agent. Only contact businesses (never private individuals) at an address "
              "they publish for business inquiries, and include the page where you found it. Never guess or construct an "
              "email address." + lessons_text(store, "Outreach", v["id"]))
    notes, sources = brain.research("A-007", system, (
        f"Find up to 8 businesses that fit this target and publicly invite inquiries by email: {mp.get('targets')}\n"
        f"Our offer: {v.get('offer')}\nFor each: the company, the published inquiry email, the page it's on, and one "
        f"specific reason our offer fits them. Skip these addresses: {', '.join(skip) or 'none'}."), venture=v["id"], max_searches=6)
    out = brain.structured("A-007", system, (
        f"Write one outreach email per prospect you can verify from the research below. Hook: {mp.get('hook')}. "
        f"Where they buy: {_link(v) or 'reply to this email'}.\n\nRESEARCH:\n{notes}\n\nSOURCES:\n"
        + "\n".join(f"- {s['title']}: {s['url']}" for s in sources)), PROSPECTS_SCHEMA, venture=v["id"], effort="medium")
    filed = []
    for p in out["prospects"][:8]:
        a = actions.create(store, "outreach.email", "A-007", v["id"], p, f"outreach to {p['company']}: {p['why_them'][:80]}")
        if a:
            filed.append(a)
    store.update("ventures", v["id"], {"outreach_day": now.date().isoformat()}, "A-007", f"{len(filed)} outreach emails drafted",
                 kind="venture.outreach")
    return filed
