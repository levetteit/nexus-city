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
  Facebook STARNET_FB_PAGE_ID, STARNET_FB_PAGE_TOKEN: posts to your Page
  LinkedIn STARNET_LINKEDIN_TOKEN: posts to your profile (the token lasts 60 days)

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
# Facebook Page   STARNET_FB_PAGE_ID, STARNET_FB_PAGE_TOKEN (a Page access token with pages_manage_posts); the Page
#                 belongs to one venture (STARNET_FB_PAGE_VENTURE, default V-PPS): other ventures never post there
# LinkedIn        STARNET_LINKEDIN_TOKEN (w_member_social; expires every 60 days), optional STARNET_LINKEDIN_PERSON
# Instagram       STARNET_IG_USER_ID (the Instagram professional account linked to the Page; same Page token,
#                 which also needs instagram_basic + instagram_content_publish). Every post carries a card (media.py).
# TikTok needs a video with every post and an audited app: its posts wait in the posting queue.
def _http_json(method: str, url: str, headers: Optional[dict] = None, form: Optional[dict] = None,
               body: Optional[dict] = None) -> dict:
    data, hdrs = None, dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            out = json.loads(raw) if raw else {}
            if not out and r.headers.get("x-restli-id"):
                out = {"id": r.headers.get("x-restli-id")}
            return out
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode()[:200]
        except Exception:
            detail = ""
        raise ConnectorError(f"HTTP {exc.code}: {detail or exc.reason}"[:240])
    except urllib.error.URLError as exc:
        raise ConnectorError(f"can't reach {url.split('/')[2]}: {exc.reason}"[:200])


def _graph_base() -> str:
    version = os.getenv("STARNET_META_GRAPH_VERSION", "")   # empty: the app's default Graph API version
    return "https://graph.facebook.com/" + (f"{version}/" if version else "")


def _facebook_post(text: str, link: str, image_url: str = "") -> dict:
    page, token = os.getenv("STARNET_FB_PAGE_ID"), os.getenv("STARNET_FB_PAGE_TOKEN")
    try:
        if image_url:   # a photo post: the card, with the text (and link) as its caption
            res = _http_json("POST", f"{_graph_base()}{page}/photos", form={
                "url": image_url, "caption": text + (f"\n\n{link}" if link else ""), "access_token": token})
        else:
            form = {"message": text, "access_token": token}
            if link:
                form["link"] = link
            res = _http_json("POST", f"{_graph_base()}{page}/feed", form=form)
    except ConnectorError as exc:
        raise ConnectorError(f"Facebook: {exc}")
    return {"platform": "facebook", "id": res.get("post_id") or res.get("id")}


def _instagram_post(text: str, link: str, image_url: str = "") -> dict:
    """Instagram only takes posts with an image: create the media container, wait for it, publish it."""
    ig, token = os.getenv("STARNET_IG_USER_ID"), os.getenv("STARNET_FB_PAGE_TOKEN")
    if not image_url:
        raise ConnectorError("Instagram needs an image with every post")
    try:
        box = _http_json("POST", f"{_graph_base()}{ig}/media", form={"image_url": image_url, "caption": text, "access_token": token})
        for _ in range(6):
            st = _http_json("GET", f"{_graph_base()}{box['id']}?" + urllib.parse.urlencode({"fields": "status_code", "access_token": token}))
            if st.get("status_code") in ("FINISHED", None):
                break
            if st.get("status_code") == "ERROR":
                raise ConnectorError("Instagram couldn't process the image")
            time.sleep(3)
        res = _http_json("POST", f"{_graph_base()}{ig}/media_publish", form={"creation_id": box["id"], "access_token": token})
    except ConnectorError as exc:
        raise ConnectorError(f"Instagram: {exc}")
    return {"platform": "instagram", "id": res.get("id")}


def _linkedin_person() -> str:
    person = os.getenv("STARNET_LINKEDIN_PERSON", "")
    if not person:
        me = _http_json("GET", "https://api.linkedin.com/v2/userinfo",
                        headers={"Authorization": f"Bearer {os.getenv('STARNET_LINKEDIN_TOKEN')}"})
        person = me.get("sub", "")
        if not person:
            raise ConnectorError("LinkedIn: couldn't read your member id (add the openid and profile scopes)")
        os.environ["STARNET_LINKEDIN_PERSON"] = person   # cache for this run
    return person if person.startswith("urn:li:") else f"urn:li:person:{person}"


def _linkedin_post(text: str, link: str) -> dict:
    token = os.getenv("STARNET_LINKEDIN_TOKEN")
    try:
        author = _linkedin_person()
        share = {"shareCommentary": {"text": text}, "shareMediaCategory": "NONE"}
        if link:
            share.update({"shareMediaCategory": "ARTICLE", "media": [{"status": "READY", "originalUrl": link}]})
        res = _http_json("POST", "https://api.linkedin.com/v2/ugcPosts",
                         headers={"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0"},
                         body={"author": author, "lifecycleState": "PUBLISHED",
                               "specificContent": {"com.linkedin.ugc.ShareContent": share},
                               "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}})
    except ConnectorError as exc:
        hint = " (the token has probably expired: make a new one and update STARNET_LINKEDIN_TOKEN)" if "401" in str(exc) else ""
        raise ConnectorError(f"LinkedIn: {exc}{hint}")
    return {"platform": "linkedin", "id": res.get("id")}


def page_venture() -> str:
    """The Facebook Page is Padilla Property Solutions' Page: only that venture posts there."""
    return os.getenv("STARNET_FB_PAGE_VENTURE", "V-PPS")


def platform_allowed(platform: str, venture: Optional[str]) -> bool:
    if platform.lower() in ("facebook", "instagram"):   # the Page and its linked Instagram account
        return venture == page_venture()
    return True


def facebook_recent_posts(limit: int = 12) -> list[dict]:
    """The Page's own latest posts, so the crew writes in its voice and doesn't repeat itself."""
    page, token = os.getenv("STARNET_FB_PAGE_ID"), os.getenv("STARNET_FB_PAGE_TOKEN")
    if not (page and token):
        return []
    base = _graph_base()
    q = urllib.parse.urlencode({"fields": "message,created_time,permalink_url", "limit": limit, "access_token": token})
    res = _http_json("GET", f"{base}{page}/posts?{q}")
    return [{"at": x.get("created_time", "")[:10], "text": (x.get("message") or "")[:700], "url": x.get("permalink_url", "")}
            for x in res.get("data", []) if x.get("message")]


SOCIAL: dict = {
    "facebook": {"configured": lambda: bool(os.getenv("STARNET_FB_PAGE_ID") and os.getenv("STARNET_FB_PAGE_TOKEN")),
                 "post": _facebook_post},
    "instagram": {"configured": lambda: bool(os.getenv("STARNET_IG_USER_ID") and os.getenv("STARNET_FB_PAGE_TOKEN")),
                  "post": _instagram_post},
    "linkedin": {"configured": lambda: bool(os.getenv("STARNET_LINKEDIN_TOKEN")), "post": _linkedin_post},
}


def social_configured(platform: str) -> bool:
    return platform.lower() in SOCIAL and SOCIAL[platform.lower()]["configured"]()


def post_social(platform: str, text: str, link: str = "", image_url: str = "") -> dict:
    if not social_configured(platform):
        raise ConnectorError(f"{platform} isn't connected")
    return SOCIAL[platform.lower()]["post"](text, link, **({"image_url": image_url} if image_url else {}))


def status() -> dict:
    return {"stripe": stripe_configured(), "stripe_webhook": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
            "email": email_configured(), "social": sorted(p for p in SOCIAL if social_configured(p)),
            "tiktok": "queue (needs a video; API needs TikTok's audit)",
            "fiverr": "manual (no seller API)", "etsy": "manual until funded"}
