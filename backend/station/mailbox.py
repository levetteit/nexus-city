"""The outreach inbox: replies to the station's emails, read so nobody has to watch for them.

Every 20 minutes (once email is connected) the station reads new mail in the outreach inbox over IMAP,
with the same login as sending (a Gmail app password works for both). It only looks at mail from
addresses it emailed; everything else in the inbox is ignored. Mail is read without being marked as read.

  * an opt-out ("unsubscribe", "remove me", "stop emailing", "not interested"...) goes on the do-not-contact
    list at once: the law asks for it within 10 business days, this does it within the hour
  * any other reply is a lead: it's added to the venture's leads and the owner gets a push to answer it

  NEXUS_IMAP_HOST   optional; worked out from the SMTP host when it's Gmail, Outlook or smtp.<domain>
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Optional

from ..env import env
from . import actions, connectors
from .store import Store

CHECK_EVERY = timedelta(minutes=20)
DOC = "mailbox.json"
OPT_OUT = re.compile(r"\b(unsubscribe|opt[\s-]?out|remove me|take me off|stop (e-?mailing|contacting|sending)|"
                     r"(do not|don'?t|please don'?t) (e-?mail|contact|message) (me|us)|not interested|no thanks|no thank you)\b", re.I)
QUOTE_START = re.compile(r"^(on .+ wrote:|-----original message-----|from: .+|sent from my)", re.I)


def imap_host() -> Optional[str]:
    if env("IMAP_HOST"):
        return env("IMAP_HOST").strip()
    smtp = (env("SMTP_HOST") or "").strip().lower()
    known = {"smtp.gmail.com": "imap.gmail.com", "smtp.office365.com": "outlook.office365.com",
             "smtp-mail.outlook.com": "outlook.office365.com"}
    if smtp in known:
        return known[smtp]
    return "imap." + smtp[5:] if smtp.startswith("smtp.") else None


def configured() -> bool:
    return connectors.email_configured() and bool(imap_host())


def due(store: Store, now: datetime) -> bool:
    if not configured():
        return False
    last = (store.load_doc(DOC) or {}).get("checked_at")
    return not last or now - datetime.fromisoformat(last) >= CHECK_EVERY


def own_words(text: str) -> str:
    """The reply itself: stop at the quoted email underneath."""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(">") or QUOTE_START.match(s):
            break
        out.append(s)
    return " ".join(x for x in out if x)[:2000]


def _text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", "replace")


def fetch(since_uid: int, limit: int = 200) -> list[dict]:
    """New messages after `since_uid`, read-only (nothing gets marked as read)."""
    try:
        with imaplib.IMAP4_SSL(imap_host(), 993, timeout=30) as m:
            m.login(*connectors.mail_login())
            m.select("INBOX", readonly=True)
            _, data = m.uid("search", None, f"UID {since_uid + 1}:*")
            uids = [int(u) for u in (data[0] or b"").split() if int(u) > since_uid][-limit:]
            out = []
            for uid in uids:
                _, parts = m.uid("fetch", str(uid), "(BODY.PEEK[])")
                raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                if raw is None:
                    continue
                msg = email.message_from_bytes(raw)
                out.append({"uid": uid, "from": parseaddr(msg.get("From", ""))[1].lower(), "subject": str(msg.get("Subject", ""))[:200],
                            "text": _text(msg)})
            return out
    except (imaplib.IMAP4.error, OSError) as exc:
        raise connectors.ConnectorError(f"inbox check failed: {connectors.mail_error(exc)}"[:300])


def process(store: Store, messages: list[dict], notify=None) -> dict:
    """Opt-outs to the do-not-contact list, other replies to leads. Only mail from addresses the station emailed."""
    from . import results
    c = actions.contacts_doc(store)
    seen = {"opt_outs": 0, "replies": 0, "ignored": 0}
    for msg in messages:
        who = msg["from"]
        sent = c["contacted"].get(who)
        if not sent or who in c["do_not_contact"]:
            seen["ignored"] += 1
            continue
        words = own_words(msg["text"])
        if OPT_OUT.search(words) or OPT_OUT.search(msg["subject"]):
            actions.opt_out(store, who)
            store.event("contact.opt_out_reply", "A-011", f"{who} replied asking not to be contacted: on the do-not-contact list now",
                        ref=sent.get("venture"))
            seen["opt_outs"] += 1
            continue
        venture = sent.get("venture")
        if venture and store.get("ventures", venture):
            results.add_lead(store, venture, "email", f"Reply from {who}: {msg['subject']} · {words[:180]}", action=sent.get("action"))
        store.event("outreach.reply", "A-005", f"{who} replied: {msg['subject'][:80]}", ref=venture, severity="ACTION NEEDED")
        if notify:
            notify("📬 Outreach reply", f"{who}: {words[:120] or msg['subject']}")
        seen["replies"] += 1
    return seen


def check(store: Store, now: datetime, notify=None, fetcher=None) -> dict:
    doc = store.load_doc(DOC) or {}
    try:
        msgs = (fetcher or fetch)(int(doc.get("last_uid", 0)))
    except connectors.ConnectorError as exc:
        doc.update(checked_at=now.isoformat(), error=str(exc))
        store.save_doc(DOC, doc)
        return {"error": str(exc)}
    out = process(store, msgs, notify)
    if msgs:
        doc["last_uid"] = max(m["uid"] for m in msgs)
    doc.update(checked_at=now.isoformat(), error="", last=out)
    store.save_doc(DOC, doc)
    return out


def test(store: Store) -> dict:
    """The owner's check: send a test email to the outreach inbox itself, then log in to read it."""
    out = {}
    try:
        connectors.send_email(connectors.mail_login()[0], "Nexus City test email",
                              "This is a test from your Space Station: sending works.")
        out["send"] = "ok: a test email is in the outreach inbox"
    except connectors.ConnectorError as exc:
        out["send"] = str(exc)
    try:
        with imaplib.IMAP4_SSL(imap_host(), 993, timeout=30) as m:
            m.login(*connectors.mail_login())
            m.select("INBOX", readonly=True)
        out["read"] = "ok: the station can read replies"
        doc = store.load_doc(DOC) or {}
        if doc.get("error"):
            doc["error"] = ""
            store.save_doc(DOC, doc)
    except (imaplib.IMAP4.error, OSError) as exc:
        out["read"] = f"inbox login failed: {connectors.mail_error(exc)}"
    return out


def status(store: Store) -> dict:
    doc = store.load_doc(DOC) or {}
    return {"configured": configured(), "host": imap_host(), "checked_at": doc.get("checked_at"), "error": doc.get("error", ""),
            "last": doc.get("last")}
