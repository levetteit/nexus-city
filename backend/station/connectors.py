"""Connections to the outside world. Each one is off until its credentials are set on the server
(Render → Environment). The station never sees or stores the keys anywhere else.

  Stripe   STRIPE_API_KEY (a restricted key: Products, Prices, Payment Links write; Checkout Sessions read)
           STRIPE_WEBHOOK_SECRET (the signing secret of a webhook to /api/station/stripe/webhook)
           Agents create products and payment links; paid checkouts book themselves into the treasury.
           Refunds and payouts are not wired at all: those stay in your Stripe dashboard.
  Email    STARNET_SMTP_HOST, STARNET_SMTP_PORT (587), STARNET_SMTP_USER, STARNET_SMTP_PASSWORD,
           STARNET_MAIL_FROM ("Name <you@yourdomain.com>"), STARNET_MAIL_ADDRESS (your postal address,
           required by CAN-SPAM in every commercial email)
           Outreach email, after QA, within the daily cap, never twice to the same address.

Fiverr and Etsy have no seller API for this. Driving their sites with a bot breaks their terms and gets
accounts banned, so the crew prepares everything and you publish and reply there.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Optional

STRIPE_API = "https://api.stripe.com/v1"
STRIPE_FEE = (0.029, 0.30)   # standard US card pricing, used only to estimate fees on booked sales


class ConnectorError(RuntimeError):
    pass


# ---------------------------------------------------------------------------- Stripe
def stripe_configured() -> bool:
    return bool(os.getenv("STRIPE_API_KEY"))


def _flatten(prefix: str, value, out: list) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}[{k}]" if prefix else k, v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)
    else:
        out.append((prefix, str(value)))


def stripe_request(method: str, path: str, params: Optional[dict] = None) -> dict:
    key = os.getenv("STRIPE_API_KEY")
    if not key:
        raise ConnectorError("Stripe isn't connected (STRIPE_API_KEY)")
    pairs: list = []
    _flatten("", params or {}, pairs)
    data = urllib.parse.urlencode(pairs).encode() if method == "POST" else None
    url = STRIPE_API + path + (("?" + urllib.parse.urlencode(pairs)) if method == "GET" and pairs else "")
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise ConnectorError(f"Stripe {exc.code}: {msg or exc.reason}"[:200])


def stripe_payment_link(name: str, description: str, price_usd: float, venture: str) -> dict:
    meta = {"starnet_venture": venture}
    product = stripe_request("POST", "/products", {"name": name[:250], "description": description[:500], "metadata": meta})
    price = stripe_request("POST", "/prices", {"product": product["id"], "currency": "usd",
                                               "unit_amount": int(round(price_usd * 100))})
    link = stripe_request("POST", "/payment_links", {"line_items": [{"price": price["id"], "quantity": 1}], "metadata": meta})
    return {"url": link["url"], "payment_link": link["id"], "product": product["id"], "price": price["id"]}


def stripe_verify(payload: bytes, header: str, tolerance: int = 300) -> dict:
    """Check a webhook's Stripe-Signature against STRIPE_WEBHOOK_SECRET; return the event."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise ConnectorError("STRIPE_WEBHOOK_SECRET isn't set")
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    sigs = [p.split("=", 1)[1] for p in (header or "").split(",") if p.startswith("v1=")]
    t = parts.get("t", "")
    if not t or not sigs:
        raise ConnectorError("missing signature")
    if abs(time.time() - int(t)) > tolerance:
        raise ConnectorError("signature too old")
    expected = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise ConnectorError("bad signature")
    return json.loads(payload)


def stripe_fee(amount: float) -> float:
    return round(amount * STRIPE_FEE[0] + STRIPE_FEE[1], 2)


def stripe_paid_sessions(limit: int = 50) -> list[dict]:
    return stripe_request("GET", "/checkout/sessions", {"limit": limit, "status": "complete"}).get("data", [])


# ---------------------------------------------------------------------------- Email (SMTP)
def email_configured() -> bool:
    return all(os.getenv(k) for k in ("STARNET_SMTP_HOST", "STARNET_SMTP_USER", "STARNET_SMTP_PASSWORD",
                                      "STARNET_MAIL_FROM", "STARNET_MAIL_ADDRESS"))


def send_email(to: str, subject: str, body: str) -> dict:
    if not email_configured():
        raise ConnectorError("email isn't connected (STARNET_SMTP_* settings)")
    footer = (f"\n\n--\n{os.getenv('STARNET_MAIL_FROM')}\n{os.getenv('STARNET_MAIL_ADDRESS')}\n"
              "Not interested? Reply \"unsubscribe\" and you won't hear from us again.")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = os.getenv("STARNET_MAIL_FROM"), to, subject
    msg.set_content(body + footer)
    host, port = os.getenv("STARNET_SMTP_HOST"), int(os.getenv("STARNET_SMTP_PORT", "587"))
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(os.getenv("STARNET_SMTP_USER"), os.getenv("STARNET_SMTP_PASSWORD"))
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise ConnectorError(f"email failed: {exc}"[:200])
    return {"sent_to": to}


# ---------------------------------------------------------------------------- Social
# Each platform needs its own API app and token; none is connected yet. Until one is, approved posts
# wait in the posting queue on the Command Board with a Copy button.
SOCIAL: dict = {}


def social_configured(platform: str) -> bool:
    return platform.lower() in SOCIAL and SOCIAL[platform.lower()]["configured"]()


def post_social(platform: str, text: str, link: str = "") -> dict:
    if not social_configured(platform):
        raise ConnectorError(f"{platform} isn't connected")
    return SOCIAL[platform.lower()]["post"](text, link)


def status() -> dict:
    return {"stripe": stripe_configured(), "stripe_webhook": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
            "email": email_configured(), "social": sorted(p for p in SOCIAL if social_configured(p)),
            "fiverr": "manual (no seller API)", "etsy": "manual until funded"}
