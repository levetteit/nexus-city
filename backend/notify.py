"""Phone notifications when the bots trade.

Two ways, use either or both:

* Web Push to the Nexus City app on your home screen (iPhone iOS 16.4+, Android).
  Tap the bell in the city to turn it on. The app's push keys are generated on
  first run and saved in data/vapid.pem (or set NEXUS_VAPID_PRIVATE_KEY).
* ntfy (free app, App Store / Play Store): set NEXUS_NTFY_TOPIC to a long,
  hard-to-guess topic name and subscribe to it in the ntfy app.

Sent for: entries, adds, exits (with P&L), account stops/caps, news pauses, the
end-of-day report and real-order failures. Only in live mode, so the simulation doesn't spam you.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import urllib.request
from typing import Optional
from .env import env

PUBLIC_URL = env("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL", "")   # Render sets the latter
PUSH_CONTACT = env("PUSH_CONTACT", "mailto:nexus-city-alerts@users.noreply.github.com")   # push services want a contact


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Notifier:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir
        self.subs_path = os.path.join(data_dir, "push_subscriptions.json")
        self.ntfy_topic = env("NTFY_TOPIC", "").strip()
        self.subs: list[dict] = []
        self._vapid = None
        self.public_key = ""
        self.sent = 0
        self.last_error = ""
        if os.path.exists(self.subs_path):
            with open(self.subs_path) as f:
                self.subs = json.load(f)
        self._load_keys()

    # ---------------------------------------------------------------- keys + subscriptions
    def _load_keys(self) -> None:
        try:
            from cryptography.hazmat.primitives import serialization
            from py_vapid import Vapid
        except ImportError:   # pywebpush not installed: web push off, ntfy still works
            return
        pem = env("VAPID_PRIVATE_KEY")
        path = os.path.join(self.data_dir, "vapid.pem")
        if pem:
            v = Vapid.from_pem(pem.encode())
        elif os.path.exists(path):
            v = Vapid.from_file(path)
        else:
            os.makedirs(self.data_dir, exist_ok=True)
            v = Vapid()
            v.generate_keys()
            v.save_key(path)
        self._vapid = v
        self.public_key = _b64url(v.public_key.public_bytes(serialization.Encoding.X962,
                                                            serialization.PublicFormat.UncompressedPoint))

    @property
    def web_push(self) -> bool:
        return self._vapid is not None

    def subscribe(self, sub: dict) -> None:
        if not isinstance(sub, dict) or "endpoint" not in sub or "keys" not in sub:
            raise ValueError("not a push subscription")
        self.subs = [s for s in self.subs if s["endpoint"] != sub["endpoint"]] + [sub]
        self._save()

    def unsubscribe(self, endpoint: str) -> None:
        self.subs = [s for s in self.subs if s["endpoint"] != endpoint]
        self._save()

    def _save(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.subs_path, "w") as f:
            json.dump(self.subs, f)

    def status(self) -> dict:
        return {"web_push": self.web_push, "public_key": self.public_key, "devices": len(self.subs),
                "ntfy": bool(self.ntfy_topic), "sent": self.sent, "last_error": self.last_error}

    # ---------------------------------------------------------------- messages
    @staticmethod
    def message(engine, ev: dict, real: bool) -> Optional[tuple[str, str, str]]:
        """(title, body, tag) for an engine event, or None if it isn't worth a buzz."""
        bot = engine.bots.get(ev.get("bot"))
        who = (bot.cfg.persona.get("handle") if bot and bot.cfg.persona else None) or (bot.cfg.name if bot else "")
        money = lambda v: f"{'+' if v >= 0 else '-'}${abs(v):,.0f}"
        tag = " · REAL" if real else ""
        if ev["type"] == "trade_open":
            side = "LONG" if ev["contract"].endswith("LONG") else "SHORT"
            return (f"📈 {who} went {side} ×{ev['qty']}{tag}", f"{ev['contract']} @ {ev['entry']:,.2f} · {ev.get('note', '')}", "trade")
        if ev["type"] == "trade_add":
            return (f"➕ {who} added → {ev['total']} contracts{tag}", ev.get("why", ""), "trade")
        if ev["type"] == "trade_trim":
            return (f"✂️ {who} trimmed {ev['qty']} {money(ev['pnl'])}{tag}", f"{ev['why']} · {ev['left']} left running", "trade")
        if ev["type"] == "trade_close":
            day, whole = engine.account.day_pnl, ev.get("trade_pnl", ev["pnl"])
            icon = "💰" if whole >= 0 else "🔻"
            return (f"{icon} {who} closed {money(whole)}{tag}", f"{ev['reason']} · today {money(day)}", "trade")
        if ev["type"] == "news_hold":
            return (f"📰 {ev['title']} at {ev['at']} ET", f"bots paused for news · no new trades until {ev['until']}", "news")
        if ev["type"] == "acct_event":
            icon = {"passed": "🏆", "failed": "💀", "payout": "💸", "halt": "⏸️"}.get(ev["what"], "👥")
            return (f"{icon} {ev['name']}", ev["text"], "account")
        if ev["type"] == "account_passed":
            return ("🏆 Evaluation PASSED → funded", "The bots switch to the funded rules. Pass the real account at Lucid too, then sync it in the app.", "account")
        if ev["type"] == "payout_ready":
            safe = f"suggested ${ev['safe']:,.0f} keeps a safe cushion" if ev["safe"] else "wait: a payout now would leave too little room above the MLL"
            return (f"💸 Payout #{ev['number']} available: up to ${ev['limit']:,.0f}", f"{safe} · balance ${ev['balance']:,.0f}", "account")
        if ev["type"] == "account_halt":
            good = any(k in ev["reason"] for k in ("cap", "target"))
            return (f"{'🏁' if good else '🛑'} Account: done for the day", ev["reason"], "account")
        return None

    def handle(self, engine, events: list[dict], real: bool = False) -> None:
        for ev in events:
            msg = self.message(engine, ev, real)
            if msg:
                self.send(*msg)

    def send(self, title: str, body: str, tag: str = "nexus", url: str = "/") -> None:
        """`url`: the page in the app a tap on the notification opens."""
        if not (self.subs or self.ntfy_topic):
            return
        try:
            asyncio.get_running_loop().create_task(asyncio.to_thread(self._send_all, title, body, tag, url))
        except RuntimeError:   # no event loop (tests / scripts)
            self._send_all(title, body, tag, url)

    def _send_all(self, title: str, body: str, tag: str, url: str = "/") -> None:
        if self.web_push and self.subs:
            from pywebpush import WebPushException, webpush
            payload = json.dumps({"title": title, "body": body, "tag": tag, "url": url})
            dead = []
            for sub in list(self.subs):
                try:
                    webpush(subscription_info=sub, data=payload, vapid_private_key=self._vapid,
                            vapid_claims={"sub": PUSH_CONTACT}, ttl=600)
                    self.sent += 1
                except WebPushException as exc:
                    code = getattr(exc.response, "status_code", 0)
                    if code in (404, 410):   # phone unsubscribed or app removed
                        dead.append(sub["endpoint"])
                    self.last_error = f"web push: {exc}"[:200]
                except Exception as exc:
                    self.last_error = f"web push: {exc}"[:200]
            for endpoint in dead:
                self.unsubscribe(endpoint)
        if self.ntfy_topic:
            try:
                note = {"topic": self.ntfy_topic, "title": title, "message": body or title}
                if PUBLIC_URL:   # tapping the ntfy notification opens the app there
                    note["click"] = PUBLIC_URL.rstrip("/") + url
                msg = json.dumps(note).encode()
                req = urllib.request.Request("https://ntfy.sh/", data=msg, method="POST",
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10).read()
                self.sent += 1
            except Exception as exc:
                self.last_error = f"ntfy: {exc}"[:200]
