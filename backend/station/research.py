"""The Research Station: ULTRON's opportunity discovery, five recurring routines.

Each routine researches the web, then turns what it found into structured opportunity records that
ULTRON can promote straight into ventures (the export's rule: actionable, not an idea list).

The owner's standing mandate ranks everything: money coming in as fast as possible, first from ventures
the crew can run end to end through the station's own rails (storefront, Etsy digital downloads,
Pinterest), with $0 startup capital. ULTRON launches those on his own (see ultron.py, AUTO_LAUNCH).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from .brain import Brain
from .store import Store

MANDATE = (
    "OWNER'S MANDATE (updated Oct 6 2026): money coming in as fast as possible, from ventures the crew runs "
    "END TO END by itself. Rank first what the crew can make, publish, sell and deliver through the station's own "
    "rails, with $0 startup capital and no work from the owner: no new accounts, no identity checks, no client "
    "calls, no publishing by hand. Today that means digital products the crew writes and designs itself (guides, "
    "checklists, planners, workbooks, template packs, printables, delivered as a PDF) sold on the station storefront "
    "and as Etsy digital downloads, with Pinterest for traffic. Pick niches with proven buyers, a clear search "
    "phrase and room for a better product. Owner-assisted ideas (Fiverr gigs, client services) still get filed but "
    "rank below autonomous ones. Print-on-demand already has its own venture (the Etsy shop): don't propose it. "
    "The station's earnings also fund the trading city and vice versa."
)
OLD_MANDATE_START = "OWNER'S MANDATE: get money coming in as fast as possible"   # replaced on upgrade (ultron.py)

RAILS = {   # what the crew can do with no one's help, and what each needs
    "storefront": "station storefront: our own sales page + Stripe checkout + automatic PDF download after payment",
    "etsy_digital": "Etsy digital downloads on the owner's Etsy shop (Etsy delivers the file)",
    "pinterest": "Pinterest pins that link to the product (free traffic)",
}


def rails_text() -> str:
    from . import connectors
    live = connectors.rails()
    return "RAILS (the crew uses these without the owner): " + "; ".join(
        f"{k}: {v} [{'live' if live.get(k) else 'not connected yet'}]" for k, v in RAILS.items()) + "."


RULES = (
    "Rules: legitimate businesses only, compliant with each platform's terms, intellectual-property law "
    "and disclosure rules (AI-generated content disclosed where a platform requires it). No schemes, no "
    "spam, no fake reviews, no reselling other people's work, no gambling or trading signals. Be honest "
    "about demand and realistic earnings: no hype, no 'passive income' promises. Never invent sources, "
    "numbers or platform rules; when you aren't sure, say so."
)

# The five routines ULTRON reported as active (export section 6). days: Monday=0 ... Sunday=6, times ET.
ROUTINES = [
    {"id": "R-001", "name": "Opportunity Market Radar", "days": [0, 1, 2, 3, 4], "at": "08:00",
     "focus": "Digital products the crew can make and sell on its own rails first (what buyers search for and pay "
              "for on Etsy, Pinterest and Google right now), then cross-market candidates across Etsy, Fiverr and other "
              "service marketplaces, digital "
              "products, faceless content, music/audio assets and adjacent online businesses: demand signals, "
              "competition, startup-cost bands, automation potential, risks.", "count": 5},
    {"id": "R-002", "name": "Etsy and Digital Product Validation Scan", "days": [1, 3], "at": "09:00",
     "focus": "Specific Etsy and digital-product concepts with keyword ideas, price bands and margin assumptions, "
              "platform-policy risks and the agent workflow to make them. Include $0 digital-product channels "
              "(e.g. platforms with no listing or monthly fee) that can earn before Etsy is funded.", "count": 4},
    {"id": "R-003", "name": "Fiverr and AI Service Offer Scan", "days": [2], "at": "09:00",
     "focus": "Services an AI crew can deliver (with the owner as the seller of record): buyer demand, pricing, "
              "the delivery workflow, platform risks, a 7-day test plan.", "count": 4},
    {"id": "R-004", "name": "Faceless Content and Music Opportunity Watch", "days": [4], "at": "09:00",
     "focus": "Faceless short-form video, YouTube, newsletters and music/audio content assets: production "
              "pipelines, monetization paths and how long they take, copyright and reused-content risks.", "count": 4},
    {"id": "R-005", "name": "Weekly Opportunity Command Brief", "days": [0], "at": "10:00",
     "focus": "Synthesize the week: re-rank every open opportunity into a portfolio (#1 build/test now, #2 "
              "investigate, #3 backup, the rest watchlist) with budgets, launch targets, success and kill "
              "criteria.", "count": 3, "brief": True},
]

OPPORTUNITY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "What the research found, 80-160 words."},
        "opportunities": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short, specific name, e.g. 'Resume rewrite gig on Fiverr for nurses'."},
                "category": {"type": "string", "enum": ["etsy", "service_marketplace", "digital_product", "faceless_content",
                                                        "music_audio", "freelance", "other"]},
                "platform": {"type": "string"},
                "summary": {"type": "string", "description": "The offer, the customer and why it sells now. 40-90 words."},
                "evidence": {"type": "array", "items": {"type": "string"}, "description": "Concrete signals with their source."},
                "startup_cost_usd": {"type": "number", "description": "Cash needed before the first sale. 0 if none."},
                "monthly_cost_usd": {"type": "number"},
                "can_start_today": {"type": "boolean"},
                "days_to_first_dollar": {"type": "integer", "description": "Realistic estimate."},
                "price_point": {"type": "string"},
                "demand": {"type": "integer", "description": "1-10"},
                "competition": {"type": "integer", "description": "1-10, 10 = most crowded"},
                "margin_potential": {"type": "integer", "description": "1-10"},
                "automation_potential": {"type": "integer", "description": "1-10"},
                "speed_to_market": {"type": "integer", "description": "1-10"},
                "scalability": {"type": "integer", "description": "1-10"},
                "owner_actions": {"type": "array", "items": {"type": "string"},
                                  "description": "What only the owner can do (sign up, verify ID, publish, payouts)."},
                "agent_roles": {"type": "array", "items": {"type": "string"},
                                "description": "Specialist roles needed, from: Market Research, Opportunity Validation, Etsy Strategist, "
                                               "Product Creation, Listing/SEO, Store Operations, Fiverr Opportunity, Service Delivery, "
                                               "Content Strategist, Scriptwriter, Creative/Design, Video Production, Music/Audio, "
                                               "Marketing, Customer Support, Analytics, Finance/Unit Economics, Automation Engineer, "
                                               "Compliance/Policy."},
                "platform_restrictions": {"type": "string"},
                "risks": {"type": "array", "items": {"type": "string"}},
                "plan_7_day": {"type": "array", "items": {"type": "string"}, "description": "Day-by-day actions, each marked [agent] or [owner]."},
                "kpis": {"type": "array", "items": {"type": "string"}},
                "success_criteria": {"type": "string", "description": "What makes it continue after 14 days."},
                "kill_criteria": {"type": "string"},
                "execution": {"type": "string", "enum": ["autonomous", "owner_assisted"],
                              "description": "autonomous: the crew makes, sells and delivers it through the rails alone."},
                "rails": {"type": "array", "items": {"type": "string", "enum": list(RAILS)},
                          "description": "The rails it sells through (autonomous ventures need storefront and/or etsy_digital)."},
                "product_format": {"type": "string", "enum": ["guide", "checklist", "planner", "workbook", "template_pack",
                                                              "printable", "none"],
                                   "description": "For digital products: what the crew will make. 'none' otherwise."},
                "score": {"type": "integer", "description": "0-100 against the owner's mandate."},
                "recommendation": {"type": "string", "enum": ["build_now", "investigate", "backup", "watchlist"]},
            },
            "required": ["title", "category", "platform", "summary", "evidence", "startup_cost_usd", "monthly_cost_usd",
                         "can_start_today", "days_to_first_dollar", "price_point", "demand", "competition",
                         "margin_potential", "automation_potential", "speed_to_market", "scalability", "owner_actions",
                         "agent_roles", "platform_restrictions", "risks", "plan_7_day", "kpis", "success_criteria",
                         "kill_criteria", "execution", "rails", "product_format", "score", "recommendation"],
            "additionalProperties": False}},
        "first_pick": {"type": "string", "description": "Title of the one opportunity ULTRON should pursue first, and why, in one sentence."},
    },
    "required": ["summary", "opportunities", "first_pick"],
    "additionalProperties": False,
}

SYSTEM = ("You are the Market Research Agent of the StarNet Research Station, reporting to ULTRON, the "
          "station's commander. You find real, current business opportunities and make them executable. "
          + MANDATE + " " + RULES)


def key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def run_routine(routine: dict, store: Store, brain: Brain, now: datetime, mandate: str = MANDATE, focus: str = "") -> dict:
    """Research, then file the results as opportunity records. Blocking: run in a thread."""
    agent = "A-002"   # Market Research Agent
    existing = [o for o in store.all("opportunities") if o.get("status") != "dismissed"]
    known = sorted(existing, key=lambda o: -o.get("score", 0))[:40]
    known_lines = "\n".join(f"- {o['title']} (score {o.get('score')}, {o.get('recommendation')})" for o in known) or "(none yet)"
    from .crew import lessons_text
    system = SYSTEM.replace(MANDATE, mandate) + " " + rails_text() + lessons_text(store, "Market Research") + (
        f"\n\nWAR ROOM RESEARCH FOCUS: {focus}" if focus else "")
    notes, sources = brain.research(agent, system, (
        f"Today is {now.strftime('%A %Y-%m-%d')}. Routine: {routine['name']}.\nFocus: {routine['focus']}\n\n"
        "Search for current evidence (marketplace listings and best-sellers, buyer requests, pricing, fee "
        "schedules, platform policy pages, recent reports). Report concrete findings with sources, prices and "
        "fees. Keep the owner's mandate in mind.\n\nOpportunities already on file (don't repeat them unless "
        f"new evidence changes their ranking):\n{known_lines}"))
    out = brain.structured(agent, system, (
        f"Turn this research into the {routine['count'] if not routine.get('brief') else '3-6'} strongest "
        "opportunities for the station, ranked against the owner's mandate. "
        + ("This is the Weekly Opportunity Command Brief: re-rank the opportunities on file together with "
           "anything new, and give exactly one build_now pick. " if routine.get("brief") else "")
        + "Use only what the research supports.\n\n"
        f"RESEARCH NOTES:\n{notes}\n\nSOURCES:\n" + "\n".join(f"- {s['title']}: {s['url']}" for s in sources)
        + f"\n\nOPPORTUNITIES ON FILE:\n{known_lines}"), OPPORTUNITY_SCHEMA)
    by_key = {key(o["title"]): o for o in existing}
    filed = []
    for opp in out["opportunities"]:
        rec = {**opp, "routine": routine["id"], "sources": sources[:8], "status": "open"}
        old = by_key.get(key(opp["title"]))
        if old:
            filed.append(store.update("opportunities", old["id"], {k: v for k, v in rec.items() if k != "status"},
                                      "A-002", f"{routine['name']} re-scored it ({old.get('score')} → {opp['score']})",
                                      kind="opportunity.rescored"))
        else:
            filed.append(store.create("opportunities", rec, "A-002", f"{routine['name']}: {opp['title']} (score {opp['score']})"))
    doc = {"routine": routine["id"], "name": routine["name"], "at": now.isoformat(), "summary": out["summary"],
           "first_pick": out["first_pick"], "notes": notes, "sources": sources, "filed": [o["id"] for o in filed]}
    store.save_doc(f"routine-{now.strftime('%Y-%m-%d-%H%M')}-{routine['id']}.json", doc)
    return doc


def due(routine: dict, now: datetime, last_run: Optional[str]) -> bool:
    """True once the routine's slot today (ET) has passed and it hasn't run since."""
    if now.weekday() not in routine["days"]:
        return False
    h, m = map(int, routine["at"].split(":"))
    slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return now >= slot and (not last_run or datetime.fromisoformat(last_run) < slot)
