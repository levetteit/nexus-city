"""Jarvis's hands on the board: the owner's operations lead works the station on the owner's behalf.

The owner's rule (Oct 7 2026): Jarvis does whatever needs doing on the board without asking, and only brings
the owner what involves real money or an account. So Jarvis can only call the operations below, each one is
written to the station's audit log as done by "jarvis", and anything touching money, an account, the
trading desk or a live order is refused here (it stays the owner's):

  task.retry        a failed task goes back in the queue (its tries start over)
  task.cancel       drop a task that can't or shouldn't be done (with why)
  task.done         an owner task Jarvis did on the owner's behalf (with what was done); not one that needs
                    an account, a payment or a signature
  action.edit       fix the words of a draft (post, email, listing); it goes back through Compliance & QA
  action.requeue    send a rejected or failed draft back through QA
  action.send       OK a QA-passed social post that waits for the owner's OK
  action.cancel     drop a draft (with why)
  venture.stage     pause a venture, or move it back to build / launch / operate (never kill: the owner does)
  venture.replan    the Marketing Lead writes the channel plan again
  venture.content   the Content Creator writes today's posts again
  approval.decide   a $0 decision with no account to open: launching a $0 venture, keep/pause a venture
  routine.run       run a research routine now
  warroom           convene the War Room now
  directive         tell ULTRON and the crew something: becomes a standing lesson and War Room input
  notify            push a message to the owner's phone (for what involves money or an account)

Auth: the same NEXUS_JARVIS_TOKEN as the briefing (Bearer header).
"""
from __future__ import annotations


from .station.store import now_iso

BY = "jarvis"
MONEY_KINDS = ("fund_goal", "spend", "strategy_promote")       # approvals that stay the owner's
ACCOUNT_WORDS = ("account", "sign up", "signup", "register", "password", "pay ", "payment", "card", "bank", "subscribe",
                 "purchase", "buy ", "tax", "w-9", "identity", "verify your", "kyc")
EDITABLE = ("text", "subject", "body", "title", "description", "headline", "tags", "pin_title", "pin_description")
STAGES = ("paused", "build", "launch", "operate")


class Refused(Exception):
    """Not Jarvis's to do: money, an account or the trading desk (the owner's)."""


def _need(store, kind: str, rid: str) -> dict:
    rec = store.get(kind, rid or "")
    if not rec:
        raise KeyError(f"{kind} {rid}")
    return rec


def _why(b: dict) -> str:
    why = str(b.get("why") or b.get("note") or "").strip()[:500]
    if not why:
        raise ValueError("say why (why / note)")
    return why


def act(st, b: dict, notify=None) -> dict:
    """One operation on the board. Raises Refused (owner's), KeyError (not found) or ValueError (bad request)."""
    s, op = st.store, str(b.get("op", ""))
    rid = str(b.get("id", ""))

    if op == "task.retry":
        t = _need(s, "tasks", rid)
        if t["status"] not in ("failed", "cancelled") and not t.get("escalated"):
            raise ValueError(f"it's {t['status']}")
        return s.update("tasks", rid, {"status": "queued", "attempts": 0, "escalated": False, "error": None}, BY,
                        f"Jarvis retried it: {b.get('why') or 'cleared for another try'}"[:200], kind="task.requeued")
    if op == "task.cancel":
        t = _need(s, "tasks", rid)
        if t["status"] == "done":
            raise ValueError("already done")
        return s.update("tasks", rid, {"status": "cancelled"}, BY, f"Jarvis cancelled it: {_why(b)}", kind="task.cancelled")
    if op == "task.done":
        t = _need(s, "tasks", rid)
        if t["kind"] != "owner" or t["status"] == "done":
            raise ValueError("only an open owner task")
        text = (t["title"] + " " + t.get("instructions", "")).lower()
        if any(w in text for w in ACCOUNT_WORDS):
            raise Refused("it needs an account, a payment or the owner's identity")
        return s.update("tasks", rid, {"status": "done", "output": {"deliverable": _why(b)}}, BY,
                        f"Jarvis did it for the owner: {t['title']}", kind="task.completed")

    if op.startswith("action."):
        a = _need(s, "actions", rid)
        if a["kind"] == "stripe.payment_link":
            raise Refused("payment links are money")
        if op == "action.edit":
            changes = {k: v for k, v in (b.get("payload") or {}).items() if k in EDITABLE and isinstance(v, (str, list))}
            if not changes:
                raise ValueError(f"nothing editable (only {', '.join(EDITABLE)})")
            if a["status"] in ("sent", "cancelled"):
                raise ValueError(f"it's {a['status']}")
            payload = {**a["payload"], **changes}
            if a["kind"] == "digital.publish":
                from .station import digital
                payload = digital.rerender(s, payload)
            return s.update("actions", rid, {"payload": payload, "status": "qa", "revisions": 0}, BY,
                            f"Jarvis fixed the copy ({', '.join(changes)}): {b.get('why') or 'back to QA'}"[:200], kind="action.revised")
        if op == "action.requeue":
            if a["status"] not in ("rejected", "failed", "manual"):
                raise ValueError(f"it's {a['status']}")
            return s.update("actions", rid, {"status": "qa", "revisions": 0}, BY,
                            f"Jarvis sent it back through QA: {b.get('why') or ''}".strip()[:200], kind="action.requeued")
        if op == "action.send":
            if a["kind"] != "social.post" or a["status"] != "waiting_owner":
                raise ValueError("only a social post waiting for the owner's OK")
            return s.update("actions", rid, {"owner_ok": True, "status": "ready"}, BY, "Jarvis OK'd it for the owner",
                            kind="action.owner_ok")
        if op == "action.cancel":
            if a["status"] in ("sent", "sending"):
                raise ValueError("already sent" if a["status"] == "sent" else "it's being sent right now")
            return s.update("actions", rid, {"status": "cancelled"}, BY, f"Jarvis cancelled it: {_why(b)}", kind="action.cancelled")

    if op.startswith("venture."):
        v = _need(s, "ventures", rid)
        if v["id"] == "V-001":
            raise Refused("the trading desk is the owner's")
        if op == "venture.stage":
            stage = b.get("stage")
            if stage not in STAGES:
                raise Refused("killing a venture is the owner's") if stage == "killed" else ValueError(f"stage: {', '.join(STAGES)}")
            return s.update("ventures", rid, {"stage": stage}, BY, f"Jarvis moved it to {stage}: {_why(b)}", kind="venture.stage")
        if op == "venture.replan":
            return s.update("ventures", rid, {"marketing_plan": None}, BY, f"Jarvis asked for a new channel plan: {b.get('why') or ''}".strip(),
                            kind="venture.replan")
        if op == "venture.content":
            return s.update("ventures", rid, {"content_day": None}, BY, f"Jarvis asked for today's posts again: {b.get('why') or ''}".strip(),
                            kind="venture.content_again")

    if op == "approval.decide":
        a = _need(s, "approvals", rid)
        owner_actions = (a.get("payload") or {}).get("owner_actions") or []
        if a["kind"] in MONEY_KINDS or (a.get("cost") or 0) > 0 or owner_actions:
            raise Refused("it costs money, touches the trading desk, or needs the owner to open an account")
        if a["kind"] == "venture_decision" and (a.get("payload") or {}).get("stage") == "killed":
            raise Refused("killing a venture is the owner's")
        decided = st.decide(rid, str(b.get("decision", "")), f"Jarvis for the owner: {_why(b)}")
        s.event("jarvis.decided", BY, f"Jarvis decided {rid}: {decided['status']}", ref=rid)
        return decided

    if op == "routine.run":
        _need(s, "routines", rid)
        with st.cfg_lock:
            st.cfg.setdefault("run_now", [])
            if rid not in st.cfg["run_now"]:
                st.cfg["run_now"].append(rid)
        st._save_cfg()
        return {"queued": rid}
    if op == "warroom":
        with st.cfg_lock:
            st.cfg["warroom_now"] = True
        st._save_cfg()
        return {"queued": "warroom"}
    if op == "directive":
        note = _why(b)
        lessons = s.load_doc("lessons.json") or []
        lessons = [l for l in lessons if l.get("lesson") != note]
        lessons.insert(0, {"lesson": note, "applies_to": str(b.get("applies_to") or "all")[:40], "source": "jarvis", "updated": now_iso()})
        s.save_doc("lessons.json", lessons[:20])
        return s.event("owner.feedback", BY, f"Jarvis (for the owner): {note}", ref=str(b.get("ref") or "")[:40] or None)
    if op == "notify":
        title, body = str(b.get("title") or "Jarvis")[:80], str(b.get("body") or "")[:400]
        if not body:
            raise ValueError("body is empty")
        s.event("jarvis.notified", BY, f"{title}: {body}", severity="ACTION NEEDED")
        if notify:
            notify(f"🤖 {title}", body)
        return {"sent": True}
    raise ValueError(f"unknown op {op!r}")
