"""The trading desk: the bots review their day, read the news, and plan the next session.

Runs on Claude (set ANTHROPIC_API_KEY; without it the desk stays off and the
bots trade exactly as before).

* Evening meeting (after each day's report): every bot writes a journal entry on
  its trades, the desk updates its standing lessons, and it sets the risk mode
  for the overnight/London session.
* Morning briefing (08:40 ET on weekdays, after the 8:30 data): a web search for
  what is moving NQ/ES today, then the desk sets the risk mode for New York.

The desk can only take risk OFF, never add it:
  normal    trade the strategy as usual (the default)
  cautious  no adds: every position stays at 3 contracts
  sit_out   no new trades until the next meeting
It can't change the strategy, the stops or the daily goal/cap. Learning happens in
the open: lessons are written down and fed back into the next meetings, and the
paper-vs-backtest replay shows what each non-normal mode cost or saved, since the
replay always trades in normal mode. Everything is saved under data/desk/.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from .persist import write_json_atomic
from .env import env
from .backtest import ET

MODEL = env("DESK_MODEL", "claude-opus-5-5")
MODES = ("normal", "cautious", "sit_out")

CONSTITUTION = """You run the trading desk of Nexus City: a team of trading bots that trade \
MNQ (micro Nasdaq futures) on one LucidFlex 50K prop account, with MES as confirmation. \
The desk's money pays for everything. If the account fails, the desk stops existing. \
So every bot is here to win: to be the best trader on the floor, to beat yesterday's version of itself, \
and to come back from every loss sharper. Nobody quits after a red day; every bot shows up to every session ready.

What "never give up" means on this desk: discipline is the weapon. Professionals survive because they \
follow their rules when it hurts. Revenge trading, moving stops, oversizing to win it back: that is how prop \
accounts die, and a dead account can't win anything. The hard rules below are not up for debate, and \
respecting them is part of being a killer, not a weakness.

The strategy (fixed, you can't change it): Andrew Macre's PROC, read on the full-size NQ / ES charts and \
executed on the MNQ / MES micros. A 3-6 minute pointer reacting to the first wick into an untapped 1-6 minute \
FFVG/IFFVG, confirmed by ES within 6 minutes. The Lookout (bot_id "watch") only watches NQ and ES and never \
trades: its read is the confirmation the traders wait for. Entries only in the London \
(02:00-05:00 ET), NY AM (09:30-11:00) and NY PM (14:00-16:00) killzones. 3 micros, adding 3 more (max 6) on \
a new PROC with the trade. No stop loss: the only exit is a pointer/PROC against the trade. The bot "walks" \
after 3 invalidated PROCs in a session.

Hard rules (enforced in code, not by you): daily goal +$600 (no new entries after), cap +$1,200 (flatten), \
daily stop -$600 (flatten), stop after 3 losing trades in a row, EOD trailing drawdown $2,000 (MLL), no new \
trades from 10 min before to 15 min after high-impact news (45 after FOMC), no entries after 15:50 ET and flat by 15:55 ET (Tradovate's session for the micros ends at 16:00).

Your one lever is the risk mode for the next session, and it can only take risk off:
- normal: trade as usual. This is the default and the right answer on most days. The edge only pays if the \
bots take their trades: the backtest made $13,224 in 21 days with 71% green days.
- cautious: no adds, every position stays at 3 contracts. For days with a real reason for extra caution.
- sit_out: no new trades until the next meeting. Only for exceptional conditions: a market-moving shock \
outside the news calendar, a holiday/thin session, or a broken data feed.
Every non-normal mode is measured: the nightly replay trades the same day in normal mode, so the desk sees \
exactly what its caution cost or saved. Being cautious for no reason loses money just like a bad trade.

How to learn: base every lesson on evidence from the trades, reports and replay checks you are given, \
with dates and numbers. One trade is an anecdote; look for patterns across days. Be honest about mistakes \
and about luck. Never invent trades, prices or news."""


def _client():
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()   # a pasted key often carries a space or line break
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


def connection_problem(exc) -> str:
    """Why a Claude call couldn't connect, in words that never include the key or other header values."""
    cause = type(exc.__cause__).__name__ if exc.__cause__ else ""
    if cause == "LocalProtocolError":
        return "can't reach the Claude API: ANTHROPIC_API_KEY contains a space or line break (re-paste it on Render)"
    if cause in ("ConnectTimeout", "ReadTimeout", "TimeoutException"):
        return "can't reach the Claude API: timed out"
    return f"can't reach the Claude API ({cause or 'network'})"


EVENING_SCHEMA = {
    "type": "object",
    "properties": {
        "desk_summary": {"type": "string", "description": "Meeting notes: what happened, what we learned, the plan. 120-220 words."},
        "journals": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "bot_id": {"type": "string"},
                "mood": {"type": "string", "description": "one or two words"},
                "entry": {"type": "string", "description": "First-person journal entry in the bot's own voice, 90-160 words, about its actual trades today (times, prices, why in, why out) and how it will compete tomorrow."},
                "lesson": {"type": "string", "description": "The bot's one concrete takeaway, grounded in today's trades."},
                "focus_tomorrow": {"type": "string"},
            },
            "required": ["bot_id", "mood", "entry", "lesson", "focus_tomorrow"],
            "additionalProperties": False,
        }},
        "lessons": {"type": "array", "items": {"type": "string"},
                    "description": "The desk's full updated list of standing lessons (at most 12): keep what the evidence still supports, merge duplicates, drop what it no longer supports, add new ones with their evidence."},
        "next_mode": {"type": "string", "enum": list(MODES)},
        "next_mode_why": {"type": "string", "description": "One sentence."},
    },
    "required": ["desk_summary", "journals", "lessons", "next_mode", "next_mode_why"],
    "additionalProperties": False,
}

MORNING_SCHEMA = {
    "type": "object",
    "properties": {
        "briefing": {"type": "string", "description": "What matters for NQ/ES today and how the desk will trade it. 80-160 words."},
        "drivers": {"type": "array", "items": {"type": "string"}, "description": "The 2-5 things moving the market today, each one line."},
        "watch": {"type": "array", "items": {"type": "string"}, "description": "Times or levels to watch today (ET)."},
        "mode": {"type": "string", "enum": list(MODES)},
        "mode_why": {"type": "string", "description": "One sentence."},
        "bot_notes": {"type": "array", "items": {
            "type": "object",
            "properties": {"bot_id": {"type": "string"}, "note": {"type": "string", "description": "A one-line pep talk / focus in the bot's voice."}},
            "required": ["bot_id", "note"], "additionalProperties": False}},
    },
    "required": ["briefing", "drivers", "watch", "mode", "mode_why", "bot_notes"],
    "additionalProperties": False,
}


class TradingDesk:
    def __init__(self, data_dir: str, client=None) -> None:
        self.dir = os.path.join(data_dir, "desk")
        self.client = client if client is not None else _client()
        self.last_error = ""
        self.running = False
        self.state = {"mode": "normal", "why": "", "until": None, "set_by": None, "act": True}
        self.lessons: list[str] = []
        os.makedirs(self.dir, exist_ok=True)
        for name, attr in (("state.json", "state"), ("lessons.json", "lessons")):
            path = os.path.join(self.dir, name)
            if os.path.exists(path):
                with open(path) as f:
                    loaded = json.load(f)
                setattr(self, attr, {**self.state, **loaded} if attr == "state" else loaded)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    # ---------------------------------------------------------------- the risk mode
    def mode_now(self, now: datetime) -> Optional[dict]:
        """The active non-normal mode, if any (and if the desk is allowed to act)."""
        s = self.state
        if not s.get("act") or s["mode"] == "normal" or not s.get("until"):
            return None
        return s if now < datetime.fromisoformat(s["until"]) else None

    def set_act(self, act: bool) -> None:
        self.state["act"] = bool(act)
        self._save("state.json", self.state)

    def _set_mode(self, mode: str, why: str, until: datetime, by: str) -> None:
        self.state.update({"mode": mode if mode in MODES else "normal", "why": why, "until": until.isoformat(), "set_by": by})
        self._save("state.json", self.state)

    # ---------------------------------------------------------------- meetings (blocking: run in a thread)
    def evening(self, ctx: dict) -> dict:
        """Journals, lessons and the overnight/London risk mode, from the day that just ended."""
        research, sources = self._research(
            f"It is {ctx['now']}. US index futures just closed for the day. In a few short bullet points: what "
            "moved Nasdaq and S&P futures today, and what is scheduled or developing overnight and for tomorrow "
            "(economic data, Fed speakers, megacap earnings, geopolitics). Facts only, with dates.")
        ctx = {**ctx, "news_research": research}
        out = self._structured(EVENING_SCHEMA, (
            "Evening desk meeting. The trading day just ended. Using the data below, have each bot (one journal entry "
            "per bot in `bots`, in its own voice and vibe, including bots that didn't trade) review its day honestly, "
            "update the desk's standing lessons, and set the risk mode for the overnight and London session "
            "(until the 08:40 ET morning briefing). Remember: normal unless there's a real reason.\n\n"
            + json.dumps(ctx, indent=1, default=str)))
        until = _next_morning(datetime.now(timezone.utc).astimezone(ET))
        self._set_mode(out["next_mode"], out["next_mode_why"], until, "evening meeting")
        self.lessons = out["lessons"][:12]
        self._save("lessons.json", self.lessons)
        out.update({"research": research, "sources": sources, "at": ctx["now"], "mode_until": until.isoformat()})
        self._store(ctx["day"], "evening", out)
        return out

    def morning(self, ctx: dict) -> dict:
        """Pre-New York briefing: today's news via web search, then the NY risk mode."""
        research, sources = self._research(
            f"It is {ctx['now']}. Brief a futures day trader before the New York open: what is moving Nasdaq "
            "(NQ) and S&P (ES) futures right now: overnight action, this morning's economic data (actual vs "
            "forecast), Fed speakers, megacap tech earnings/news, geopolitics, anything scheduled during the "
            "session today with times in ET. Short bullet points, facts only.")
        out = self._structured(MORNING_SCHEMA, (
            "Morning briefing before the New York open. Using the research and data below, brief the desk, list "
            "today's drivers and what to watch, give each bot in `bots` a one-line note in its own voice, and set "
            "the risk mode for today's New York session. Remember: normal unless there's a real reason.\n\n"
            + json.dumps({**ctx, "news_research": research}, indent=1, default=str)))
        now = datetime.now(timezone.utc).astimezone(ET)
        until = now.replace(hour=16, minute=45, second=0, microsecond=0)
        self._set_mode(out["mode"], out["mode_why"], until, "morning briefing")
        out.update({"research": research, "sources": sources, "at": ctx["now"], "mode_until": until.isoformat()})
        self._store(ctx["day"], "morning", out)
        return out

    # ---------------------------------------------------------------- Claude calls
    on_usage = None   # set by the server: books each call's cost (station treasury, the city's unit) and the credits count

    def _request(self, **kw):
        import anthropic
        try:
            resp = self.client.beta.messages.create(
                model=MODEL, betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
            if self.on_usage:
                try:
                    self.on_usage(resp.usage)
                except Exception:
                    pass   # bookkeeping never breaks the desk
            return resp
        except anthropic.APIStatusError as exc:
            self.last_error = f"Claude API {exc.status_code}: {exc.message}"[:200]
            raise
        except anthropic.APIConnectionError as exc:
            self.last_error = connection_problem(exc)
            raise

    def _research(self, question: str) -> tuple[str, list[dict]]:
        """Web search for current market news. Returns (notes, sources)."""
        messages = [{"role": "user", "content": question}]
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
        resp = None
        for _ in range(4):   # resume if the server-side search loop pauses
            resp = self._request(max_tokens=8000, system="You are the desk's market research analyst. Be accurate and brief.",
                                 messages=messages, tools=tools, output_config={"effort": "medium"})
            if resp.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
        if resp.stop_reason == "refusal":
            return "(research unavailable today)", []
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        sources = []
        for b in resp.content:
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                sources += [{"title": r.title, "url": r.url} for r in b.content if getattr(r, "type", "") == "web_search_result"]
        return text, sources[:12]

    def _structured(self, schema: dict, prompt: str) -> dict:
        resp = self._request(max_tokens=16000, system=CONSTITUTION,
                             messages=[{"role": "user", "content": prompt}],
                             output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema}})
        if resp.stop_reason == "refusal":
            raise RuntimeError("the desk model declined this request")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("the desk's answer was cut off")
        return json.loads(next(b.text for b in resp.content if b.type == "text"))

    # ---------------------------------------------------------------- storage
    def _save(self, name: str, data) -> None:
        write_json_atomic(os.path.join(self.dir, name), data, indent=1)

    def _store(self, day: str, kind: str, out: dict) -> None:
        path = os.path.join(self.dir, f"{day}.json")
        doc = {}
        if os.path.exists(path):
            with open(path) as f:
                doc = json.load(f)
        doc[kind] = out
        self._save(f"{day}.json", doc)

    def days(self, limit: int = 10) -> list[dict]:
        names = sorted((n for n in os.listdir(self.dir) if n[:4].isdigit() and n.endswith(".json")), reverse=True)[:limit]
        out = []
        for n in names:
            with open(os.path.join(self.dir, n)) as f:
                out.append({"day": n[:-5], **json.load(f)})
        return out

    def status(self) -> dict:
        s = self.state
        active = s["mode"] != "normal" and s.get("until") and datetime.now(timezone.utc) < datetime.fromisoformat(s["until"])
        return {"enabled": self.enabled, "act": s.get("act", True), "mode": s["mode"] if active else "normal",
                "why": s["why"] if active else "", "until": s.get("until") if active else None,
                "set_by": s.get("set_by"), "running": self.running, "error": self.last_error,
                "lessons": len(self.lessons)}


def _next_morning(now: datetime) -> datetime:
    """08:40 ET on the next weekday."""
    t = (now + timedelta(days=1)).replace(hour=8, minute=40, second=0, microsecond=0)
    while t.weekday() >= 5:
        t += timedelta(days=1)
    return t


def context(engine, report: Optional[dict], recent: list[dict], scorecard_status: Optional[dict], news, lessons: list[str],
            past_modes: list[dict]) -> dict:
    """Everything the desk sees, as plain JSON. Built on the event loop (fast, no network)."""
    now = datetime.now(timezone.utc).astimezone(ET)
    bots = [{"bot_id": b.cfg.id, "name": b.cfg.name, "handle": (b.cfg.persona or {}).get("handle", b.cfg.name),
             "vibe": (b.cfg.persona or {}).get("vibe", ""), "pointer_timeframes": b.p.get("pointer_tfs") if hasattr(b, "p") else None,
             "on_shift": b.status != "disabled", "career_pnl": round(b.career, 2)} for b in engine.bots.values()]
    return {
        "now": now.strftime("%A %Y-%m-%d %H:%M ET"), "day": (report or {}).get("day") or now.strftime("%Y-%m-%d"),
        "bots": bots, "account": engine.account.snapshot() | {"log": None},
        "today": report, "recent_days": recent,
        "paper_vs_backtest": scorecard_status,
        "news_calendar_next_24h": [{"time": e.time.strftime("%a %H:%M"), "event": e.title}
                                   for e in (news.upcoming(now, 24) if news else [])],
        "standing_lessons": lessons,
        "past_risk_modes": past_modes,
    }
