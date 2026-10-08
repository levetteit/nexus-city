"""The web front door: login, cross-site request protection and security headers.

PasswordGate (ASGI middleware) guards every page, API call and the WebSocket:

* **Login.** HTTP Basic with NEXUS_PASSWORD. A successful login sets a session cookie
  `nexus_auth = HMAC-SHA256(server key, password)`. The server key is random, kept in `<data dir>/session.key`
  (mode 0600), so the cookie is not a hash anyone can recompute from a guessed password. Changing the password
  or deleting the key file signs every browser out. Comparisons are constant-time. The cookie is HttpOnly,
  SameSite=Lax, and Secure whenever the request came over https.
* **Brute force.** More than MAX_FAILURES wrong passwords from one address within FAILURE_WINDOW returns 429
  until the window passes.
* **Cross-site requests.** A state-changing request (anything but GET/HEAD/OPTIONS) or a WebSocket whose Origin
  is another site, or that the browser marks `Sec-Fetch-Site: cross-site`, is refused (403). Without this, a page
  on another site could make the owner's browser arm real orders or flatten them using cached Basic credentials.
  Clients that send neither header (curl, scripts) are not browsers and are unaffected.
* **Live mode needs a password.** With NEXUS_MODE=live and no NEXUS_PASSWORD, everything except the open paths
  answers 503: a missed setting must never mean an open trading app.
* **Open paths** keep their own protection: webhooks check their own secrets, `/api/jarvis/*` its bearer token,
  `/healthz` exposes nothing sensitive, `/media/*` names are unguessable, `/shop*` is the public storefront.
* **Headers** on every response: nosniff, no framing (clickjacking on the order buttons), same-origin referrer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from http.cookies import CookieError, SimpleCookie
from typing import Optional
from urllib.parse import urlsplit

COOKIE, LEGACY_COOKIE = "nexus_auth", "starnet_auth"   # the old name is still read (docs/MIGRATION_FROM_STARNET.md)
COOKIE_MAX_AGE = 30 * 24 * 3600
MAX_FAILURES = 10
FAILURE_WINDOW = 15 * 60
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"referrer-policy", b"same-origin"),
]


def secret_matches(given, expected: Optional[str]) -> bool:
    """Constant-time check of a shared secret from a webhook body. Never raises (non-text or non-ASCII input is just wrong)."""
    if not expected or not isinstance(given, (str, int, float)):
        return False
    return hmac.compare_digest(str(given).encode("utf-8"), expected.encode("utf-8"))


def session_key(data_dir: str) -> bytes:
    """The server's random signing key for session cookies, created once and kept in the data directory."""
    path = os.path.join(data_dir, "session.key")
    try:
        with open(path, "rb") as f:
            key = f.read()
        if len(key) >= 32:
            return key
    except OSError:
        pass
    key = secrets.token_bytes(32)
    try:
        os.makedirs(data_dir, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key)
    except OSError:
        pass   # read-only disk: the key lives for this process (browsers log in again after a restart)
    return key


def _header(headers: dict, name: bytes) -> str:
    return headers.get(name, b"").decode("latin-1")


def is_cross_site(headers: dict) -> bool:
    """True when a browser says the request comes from another site."""
    if _header(headers, b"sec-fetch-site").lower() == "cross-site":
        return True
    origin = _header(headers, b"origin")
    if not origin:
        return False
    if origin == "null":   # sandboxed frames, data: URLs: never our own pages
        return True
    host = _header(headers, b"x-forwarded-host") or _header(headers, b"host")
    return urlsplit(origin).netloc.lower() != host.split(",")[0].strip().lower()


def client_ip(scope) -> str:
    fwd = _header(dict(scope.get("headers") or []), b"x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    client = scope.get("client") or ("?", 0)
    return str(client[0])


def is_https(scope) -> bool:
    proto = _header(dict(scope.get("headers") or []), b"x-forwarded-proto")
    return scope.get("scheme") in ("https", "wss") or proto.split(",")[0].strip().lower() == "https"


class PasswordGate:
    """See the module docstring. `password` / `mode` / `data_dir` default to the app's settings."""

    def __init__(self, app, password: Optional[str] = None, mode: Optional[str] = None, data_dir: Optional[str] = None,
                 open_paths: tuple = (), public_prefixes: tuple = ()) -> None:
        from .env import env
        self.app = app
        self.password = env("PASSWORD") if password is None else password
        self.mode = env("MODE", "sim") if mode is None else mode
        self.open_paths = open_paths
        self.public_prefixes = public_prefixes
        key = session_key(data_dir or env("DATA_DIR", "data")) if self.password else b""
        self.token = hmac.new(key, self.password.encode(), hashlib.sha256).hexdigest() if self.password else None
        self.failures: dict[str, list[float]] = {}

    # ---------------------------------------------------------------- checks
    def _is_open(self, path: str) -> bool:
        return path in self.open_paths or any(path == p.rstrip("/") or path.startswith(p) for p in self.public_prefixes)

    def _cookie_ok(self, headers: dict) -> bool:
        raw = _header(headers, b"cookie")
        if not raw or not self.token:
            return False
        try:
            jar = SimpleCookie()
            jar.load(raw)
        except CookieError:
            return False
        return any(name in jar and hmac.compare_digest(jar[name].value.encode(), self.token.encode())
                   for name in (COOKIE, LEGACY_COOKIE))

    def _authorized(self, headers: dict) -> tuple[bool, bool]:
        """(allowed, set_cookie)."""
        if self._cookie_ok(headers):
            return True, False
        auth = _header(headers, b"authorization")
        if auth.lower().startswith("basic "):
            try:
                _, _, pw = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
            except Exception:
                return False, False
            if hmac.compare_digest(pw.encode(), self.password.encode()):
                return True, True
        return False, False

    def _locked_out(self, ip: str, now: float) -> bool:
        recent = [t for t in self.failures.get(ip, []) if now - t < FAILURE_WINDOW]
        self.failures[ip] = recent
        return len(recent) >= MAX_FAILURES

    def _failed(self, ip: str, now: float) -> None:
        self.failures.setdefault(ip, []).append(now)
        if len(self.failures) > 10_000:   # bound memory under a flood of addresses
            self.failures.clear()

    # ---------------------------------------------------------------- responses
    @staticmethod
    async def _reply(send, status: int, text: str, extra: Optional[list] = None) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")] + SECURITY_HEADERS + (extra or [])})
        await send({"type": "http.response.body", "body": text.encode()})

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        is_ws = scope["type"] == "websocket"

        async def send_secured(msg):
            if msg["type"] == "http.response.start":
                names = {k.lower() for k, _ in msg.get("headers", [])}
                msg = {**msg, "headers": list(msg.get("headers", [])) + [h for h in SECURITY_HEADERS if h[0] not in names]}
            await send(msg)

        if self._is_open(scope["path"]):
            return await self.app(scope, receive, send if is_ws else send_secured)

        # cross-site requests that could change something (or open the live WebSocket) never get in
        if (is_ws or scope.get("method", "GET") not in SAFE_METHODS) and is_cross_site(headers):
            if is_ws:
                return await send({"type": "websocket.close", "code": 4403})
            return await self._reply(send, 403, "cross-site request refused")

        if not self.password:
            if self.mode == "live":
                if is_ws:
                    return await send({"type": "websocket.close", "code": 4503})
                return await self._reply(send, 503, "set NEXUS_PASSWORD: live mode never runs without a password")
            return await self.app(scope, receive, send if is_ws else send_secured)   # local simulation

        now, ip = time.time(), client_ip(scope)
        if self._locked_out(ip, now):
            if is_ws:
                return await send({"type": "websocket.close", "code": 4429})
            return await self._reply(send, 429, "too many wrong passwords: try again later",
                                     [(b"retry-after", str(FAILURE_WINDOW).encode())])
        ok, set_cookie = self._authorized(headers)
        if not ok:
            if _header(headers, b"authorization"):
                self._failed(ip, now)
            if is_ws:
                return await send({"type": "websocket.close", "code": 4401})
            return await self._reply(send, 401, "password required", [(b"www-authenticate", b'Basic realm="Nexus City"')])
        if is_ws:
            return await self.app(scope, receive, send)
        if not set_cookie:
            return await self.app(scope, receive, send_secured)
        secure = "; Secure" if is_https(scope) else ""
        cookie = f"{COOKIE}={self.token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={COOKIE_MAX_AGE}{secure}".encode()

        async def send_with_cookie(msg):
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": list(msg.get("headers", [])) + [(b"set-cookie", cookie)]}
            await send_secured(msg)
        return await self.app(scope, receive, send_with_cookie)
