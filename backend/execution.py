"""Real order execution on your Lucid accounts, through TradersPost.

How it works: every time a bot opens, adds to, trims or closes a trade, a webhook
goes to your TradersPost strategy; TradersPost places the market order on
every Lucid (Tradovate) account subscribed to that strategy.

  NEXUS_TRADERSPOST_WEBHOOKS   your TradersPost strategy webhook URL
                                 (comma-separate several to route to more strategies)

Safety, in order of importance:
  * Off until you arm it from the account panel. The armed state is saved, so a
    restart keeps whatever you chose.
  * New entries are blocked whenever the price data is more than
    MAX_DATA_DELAY_MIN minutes old: the free Yahoo feed is ~10 minutes late, so
    real orders need the real-time TradingView feed (see tradingview/nexus_city_feed.pine).
  * No new entries from 15:50 ET: Tradovate's session for the micros ends at 16:00 (the bots are flat by 15:55).
  * Adds and exits are only sent for positions this router actually opened.
    Exits are always sent, even on stale data: getting flat is never blocked.
  * "Flatten all" sends an exit for every symbol and disarms.
  * After a restart, any position the router had open is closed right away
    (the bots restart flat, so a leftover real position would be unmanaged).
  * Every order and response is logged to data/orders.csv.
  * Entries and adds are resent only when the request never reached TradersPost (it couldn't connect). After a
    timeout or any reply, resending could open a second position, so it isn't. Exits and resizes are always
    retried: repeating them can't add risk.
  * An exit waiting in the queue is saved with the router's state, so a restart before it goes out still sends it.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import socket
import urllib.error
import urllib.request
from collections import deque
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from .persist import write_json_atomic
from .env import env
from .redact import redact

MAX_DATA_DELAY_MIN = 2.5
SAFE_TO_REPEAT = ("exit", "resize")   # only reduce a position: sending one twice can't add risk


def never_delivered(exc: BaseException) -> bool:
    """True when a POST certainly didn't reach the server: the connection itself failed (refused, DNS, connect
    timeout, TLS handshake). A timeout or reset after connecting may mean the order was already accepted."""
    if isinstance(exc, urllib.error.HTTPError):
        return False   # the server answered
    if isinstance(exc, urllib.error.URLError):
        return True    # urlopen wraps failures that happen before the request is sent
    return isinstance(exc, (ConnectionRefusedError, socket.gaierror))
QUARTERS = {3: "H", 6: "M", 9: "U", 12: "Z"}


def _targets(pos: dict) -> dict[str, int]:
    """Webhook -> contracts for an open position (older saved state had no per-webhook sizes)."""
    t = pos.get("targets")
    if isinstance(t, list):
        t = pos["targets"] = {u: pos["qty"] for u in t}
    return t if t is not None else {}


def third_friday(year: int, month: int) -> date:
    d = date(year, month, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def front_month(symbol: str, today: Optional[date] = None) -> str:
    """'MNQ' -> 'MNQZ2026'. Equity index futures expire the 3rd Friday of Mar/Jun/Sep/Dec;
    volume rolls to the next contract about 8 days before, so we switch then too."""
    today = today or datetime.now(timezone.utc).date()
    for year in (today.year, today.year + 1):
        for month, code in QUARTERS.items():
            if today < third_friday(year, month) - timedelta(days=8):
                return f"{symbol}{code}{year}"
    raise ValueError("unreachable")


class TradersPostRouter:
    def __init__(self, data_dir: str, webhooks: Optional[list[str]] = None) -> None:
        self.data_dir = data_dir
        configured = env("TRADERSPOST_WEBHOOKS", "")
        self.webhooks = webhooks if webhooks is not None else [u.strip() for u in configured.split(",") if u.strip()]
        self.state_path = os.path.join(data_dir, "execution.json")
        self.armed = False
        self.last_px: dict[str, float] = {}   # last price seen per symbol, sent with every order
        self.open: dict[str, dict] = {}      # symbol -> {"side", "qty", "contract", "targets"} we have on for real
        self.account_urls = lambda: []       # per-account webhooks (accounts.py sets this)
        self.url_names = lambda: {}          # webhook -> account name, for the order log (never the URL itself)
        self.last_error = ""                 # the latest failure on a webhook that hasn't succeeded since
        self.url_errors: dict[str, str] = {}  # webhook -> its latest failure, cleared when that webhook succeeds again
        self.errors: deque = deque(maxlen=20)   # recent failures, newest last (for the account panel)
        self.unsent_exits: dict[str, dict] = {}   # symbol -> exit queued but not yet sent (saved: survives a restart)
        self.sent = 0
        self.blocked = 0
        self.queue: asyncio.Queue | None = None
        self._load()

    # ---------------------------------------------------------------- state
    @property
    def configured(self) -> bool:
        return bool(self.webhooks or self.account_urls())

    def all_urls(self) -> list[str]:
        return list(dict.fromkeys(self.webhooks + self.account_urls()))

    def _load(self) -> None:
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                s = json.load(f)
            self.armed = bool(s.get("armed")) and self.configured
            self.open = s.get("open", {})
            self.unsent_exits = s.get("unsent_exits", {})

    def _save(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        write_json_atomic(self.state_path, {"armed": self.armed, "open": self.open, "unsent_exits": self.unsent_exits},
                          indent=1)

    def arm(self, on: bool) -> None:
        if on and not self.configured:
            raise ValueError("set NEXUS_TRADERSPOST_WEBHOOKS first")
        self.armed = on
        self._save()

    def status(self, delay_min: float) -> dict:
        return {"configured": self.configured, "armed": self.armed, "open": self.open,
                "data_ok": delay_min <= MAX_DATA_DELAY_MIN, "max_delay": MAX_DATA_DELAY_MIN,
                "sent": self.sent, "blocked": self.blocked, "last_error": self.last_error,
                "failing": len(self.url_errors), "errors": list(self.errors)[-5:],
                "targets": len(self.all_urls()), "shared": len(self.webhooks)}

    def recent(self, n: int = 20) -> list[dict]:
        """The last orders from data/orders.csv, newest first: what was sent, skipped or rejected, and what came back."""
        path = os.path.join(self.data_dir, "orders.csv")
        if not os.path.exists(path):
            return []
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        return rows[-n:][::-1]

    # ---------------------------------------------------------------- orders
    def start(self) -> list[str]:
        """Begin sending; close anything left open by a previous run. Returns the symbols it closed."""
        self.queue = asyncio.Queue()
        asyncio.create_task(self._worker())
        closed = list(dict.fromkeys(list(self.open) + list(self.unsent_exits)))
        for symbol, pos in list(self.open.items()):
            self._enqueue(symbol, {"action": "exit", "cancel": True}, "restart: bots start flat", pos["contract"],
                          list(_targets(pos)) or self.all_urls())
            del self.open[symbol]
        for symbol, pending in list(self.unsent_exits.items()):   # queued before the restart, never sent
            if symbol not in self.open:
                self._enqueue(symbol, {"action": "exit", "cancel": True}, "restart: exit that was still queued",
                              pending.get("contract"), pending.get("targets") or self.all_urls())
        self._save()
        return closed

    def handle(self, engine, events: list[dict], delay_min: float, book=None) -> None:
        """Turn the bots' trade events into real orders. The shared webhooks follow the bots exactly;
        per-account webhooks follow `book` (accounts.py): which accounts join a trade, take an add,
        and how many contracts each holds."""
        if not (self.armed and self.queue):
            return
        for ev in events:
            if ev["type"] not in ("trade_open", "trade_add", "trade_trim", "trade_close"):
                continue
            bot = engine.bots.get(ev.get("bot"))
            if bot is None or bot.cfg.instrument != "future":
                continue
            symbol = bot.cfg.underlying
            try:
                self.last_px[symbol] = round(engine.market.underlyings[symbol].price, 2)
            except (AttributeError, KeyError, TypeError):
                pass
            if ev["type"] == "trade_open":
                if getattr(engine.market, "minutes_to_flat", 99) <= 10:   # the broker's session ends at 16:00 ET
                    self.blocked += 1
                    self._log(symbol, {"action": "skip-open"}, "after 15:50 ET: Tradovate's session ends at 16:00", 0)
                    continue
                if delay_min > MAX_DATA_DELAY_MIN:
                    self.blocked += 1
                    self._log(symbol, {"action": "skip-open"}, f"data {delay_min:.1f} min old", 0)
                    continue
                side = "buy" if ev["contract"].endswith("LONG") else "sell"
                contract = front_month(symbol)
                urls = list(dict.fromkeys(self.webhooks + (book.entry_targets(ev["bot"]) if book else self.account_urls())))
                targets = {u: ev["qty"] for u in urls}
                if not targets:
                    self.blocked += 1
                    self._log(symbol, {"action": "skip-open"}, "no account may take new trades now", 0)
                    continue
                self.open[symbol] = {"side": side, "qty": ev["qty"], "contract": contract, "targets": targets}
                self._enqueue(symbol, {"action": side, "quantity": ev["qty"], "orderType": "market",
                                       "signalPrice": round(engine.market.underlyings[symbol].price, 2)}, ev["bot"], contract, list(targets))
            elif ev["type"] == "trade_add" and symbol in self.open:
                if delay_min > MAX_DATA_DELAY_MIN:
                    self.blocked += 1
                    continue
                pos = self.open[symbol]
                pos["qty"] += ev["qty"]
                targets = _targets(pos)
                allowed = set(self.webhooks) | set(book.add_targets(ev["bot"]) if book else targets)
                urls = [u for u in targets if u in allowed]
                for u in urls:
                    targets[u] += ev["qty"]
                if urls:
                    self._enqueue(symbol, {"action": "add", "quantity": ev["qty"], "orderType": "market"}, ev["bot"],
                                  pos["contract"], urls)
            elif ev["type"] == "trade_trim" and symbol in self.open:
                # resize = "end at this many contracts": TradersPost only sends the difference,
                # so a repeat or a missed fill can't over-trim. Never blocked: it only reduces risk.
                pos = self.open[symbol]
                pos["qty"] = left = max(1, pos["qty"] - ev["qty"])
                own = book.target_qty(ev["bot"]) if book else {}
                targets = _targets(pos)
                for u, q in targets.items():
                    want = own.get(u, left) if u not in self.webhooks else left
                    if want < q:
                        targets[u] = want
                        self._enqueue(symbol, {"action": "resize", "quantity": want, "orderType": "market", "cancel": False},
                                      ev["bot"], pos["contract"], [u])
            elif ev["type"] == "trade_close" and symbol in self.open:
                pos = self.open.pop(symbol)
                self._enqueue(symbol, {"action": "exit", "cancel": True}, ev["bot"], pos["contract"], list(_targets(pos)) or None)
        self._save()

    def flatten_all(self, symbols: list[str]) -> None:
        for symbol in set(symbols) | set(self.open):
            self._enqueue(symbol, {"action": "exit", "cancel": True}, "flatten all",
                          self.open.get(symbol, {}).get("contract"), self.all_urls())
        self.open.clear()
        self.armed = False
        self._save()

    def _enqueue(self, symbol: str, msg: dict, reason: str, contract: Optional[str] = None,
                 targets: Optional[list[str]] = None) -> None:
        # Every order is a market order and carries the last price: Tradovate gives TradersPost no quotes, and a
        # subscription that defaults to limit orders would otherwise reject an exit or add that has no price.
        msg = {"orderType": "market", **msg}
        if "signalPrice" not in msg and self.last_px.get(symbol):
            msg["signalPrice"] = self.last_px[symbol]
        payload = {"ticker": contract or front_month(symbol), **msg, "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        targets = targets if targets is not None else self.all_urls()
        if msg.get("action") == "exit":
            self.unsent_exits[symbol] = {"contract": payload["ticker"], "targets": list(targets)}
        if self.queue is not None:
            self.queue.put_nowait((symbol, payload, reason, targets))

    async def _worker(self) -> None:
        """Send orders one at a time, in order, so an exit can never overtake its entry. Never stops: a failure
        while sending or logging one order is recorded and the next order still goes out."""
        while True:
            symbol, payload, reason, targets = await self.queue.get()
            delivered = False
            try:
                results = [await self._send_one(symbol, payload, reason, url) for url in targets]
                delivered = all(results)
            except Exception as exc:   # a bug here must not strand every later order in the queue
                self._fail("worker", redact(f"order worker: {type(exc).__name__}: {exc}")[:200])
            finally:
                # an exit that reached every account is done; one that failed stays saved, so a restart sends it again
                if payload.get("action") == "exit" and delivered and self.unsent_exits.pop(symbol, None) is not None:
                    try:
                        self._save()
                    except Exception as exc:
                        self._fail("worker", redact(f"saving router state: {exc}")[:200])

    async def _send_one(self, symbol: str, payload: dict, reason: str, url: str) -> bool:
        repeatable = payload.get("action") in SAFE_TO_REPEAT
        status, body = 0, ""
        for attempt in range(3):
            try:
                status, body = await asyncio.to_thread(self._post, url, payload)
                if 200 <= status < 300 or not repeatable:
                    break   # done, or TradersPost answered: an entry it may have taken is never sent twice
            except Exception as exc:
                status, body = 0, str(exc)
                if not repeatable and not never_delivered(exc):
                    body = f"not resent (it may have reached TradersPost): {body}"
                    break
            await asyncio.sleep(1 + attempt)
        ok = 200 <= status < 300
        self.sent += ok
        if ok:
            self.url_errors.pop(url, None)
            if not self.url_errors:
                self.last_error = ""
        else:
            self._fail(url, redact(f"{payload['action']} {payload['ticker']}: HTTP {status} {body}")[:200])
        try:
            names = self.url_names()
        except Exception:
            names = {}
        name = names.get(url) or (f"shared webhook {self.webhooks.index(url) + 1}" if url in self.webhooks else "webhook")
        self._log(symbol, payload, f"{reason} → {name}", status, body)
        return ok

    def _fail(self, key: str, message: str) -> None:
        self.url_errors[key] = message
        self.last_error = message
        self.errors.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": message})

    @staticmethod
    def _post(url: str, payload: dict) -> tuple[int, str]:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read().decode(errors="replace")
        except urllib.error.HTTPError as exc:   # TradersPost answered with an error: report it, it's not a network failure
            return exc.code, exc.read().decode(errors="replace") if exc.fp else ""


    def _log(self, symbol: str, payload: dict, reason: str, status: int, body: str = "") -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        path = os.path.join(self.data_dir, "orders.csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["sent_utc", "symbol", "ticker", "action", "quantity", "reason", "http_status", "response"])
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), symbol, payload.get("ticker", ""),
                        payload.get("action"), payload.get("quantity", ""), redact(reason), status, redact(body)[:200]])
