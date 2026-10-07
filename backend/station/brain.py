"""The station's Claude calls: one place that checks the budget first and books every call's cost.

Same pattern as the trading desk (desk.py): Claude Opus with server-side refusal fallback, web search
for research, structured JSON output for anything the station acts on. Without ANTHROPIC_API_KEY the
station still runs (records, approvals, treasury, ULTRON's checks); only research and agent drafting
wait for the key.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from ..env import env
from ..redact import redact
from .economy import Treasury

MODEL = env("STATION_MODEL", "claude-opus-5-5")


class BudgetExceeded(RuntimeError):
    pass


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


class Brain:
    def __init__(self, treasury: Treasury, client=None) -> None:
        self.treasury = treasury
        self.client = client if client is not None else _client()
        self.last_error = ""

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _request(self, agent: str, venture: Optional[str], note: str, **kw):
        if not self.treasury.ai_allowed():
            raise BudgetExceeded(f"the station's AI budget for this month (${self.treasury.ai_spent():.2f} spent) is used up")
        import anthropic
        try:
            resp = self.client.beta.messages.create(
                model=MODEL, betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except anthropic.APIStatusError as exc:
            self.last_error = redact(f"Claude API {exc.status_code}: {exc.message}")[:200]
            raise
        except anthropic.APIConnectionError as exc:
            self.last_error = redact(connection_problem(exc))
            raise
        self.treasury.charge_ai(resp.usage, agent, venture, note)
        self.last_error = ""
        return resp

    def research(self, agent: str, system: str, question: str, venture: Optional[str] = None,
                 max_searches: int = 8) -> tuple[str, list[dict]]:
        """Web research. Returns (notes, sources)."""
        messages = [{"role": "user", "content": question}]
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
        resp = None
        for _ in range(4):   # resume if the server-side search loop pauses
            resp = self._request(agent, venture, "research", max_tokens=12000, system=system, messages=messages,
                                 tools=tools, output_config={"effort": "medium"})
            if resp.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
        if resp.stop_reason == "refusal":
            return "(research unavailable)", []
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        sources = []
        for b in resp.content:
            if b.type == "web_search_tool_result" and isinstance(b.content, list):
                sources += [{"title": r.title, "url": r.url} for r in b.content if getattr(r, "type", "") == "web_search_result"]
        return text, sources[:20]

    def structured(self, agent: str, system: str, prompt: str, schema: dict, venture: Optional[str] = None,
                   effort: str = "high") -> dict:
        for level in dict.fromkeys((effort, "low")):   # cut off: once more with less thinking, so the answer fits
            resp = self._request(agent, venture, "structured", max_tokens=16000, system=system,
                                 messages=[{"role": "user", "content": prompt}],
                                 output_config={"effort": level, "format": {"type": "json_schema", "schema": schema}})
            if resp.stop_reason != "max_tokens":
                break
        if resp.stop_reason == "refusal":
            raise RuntimeError("the model declined this request")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("the answer was cut off")
        return json.loads(next(b.text for b in resp.content if b.type == "text"))
