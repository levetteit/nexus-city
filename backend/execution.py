"""Real order execution on your Lucid accounts, through TradersPost.

How it works: every time a bot opens, adds to, trims or closes a trade, a webhook
goes to your TradersPost strategy; TradersPost places the market order on
every Lucid (Tradovate) account subscribed to that strategy.

  STARNET_TRADERSPOST_WEBHOOKS   your TradersPost strategy webhook URL
                                 (comma-separate several to route to more strategies)

Safety, in order of importance:
  * Off until you arm it from the account panel. The armed state is saved, so a
    restart keeps whatever you chose.
  * New entries are blocked whenever the price data is more than
    MAX_DATA_DELAY_MIN minutes old: the free Yahoo feed is ~10 minutes late, so
    real orders need the real-time TradingView feed (see tradingview/starnet_feed.pine).
  * Adds and exits are only sent for positions this router actually opened.
    Exits are always sent, even on stale data: getting flat is never blocked.
  * "Flatten all" sends an exit for every symbol and disarms.
  * After a restart, any position the router had open is closed right away
    (the bots restart flat, so a leftover real position would be unmanaged).
  * Every order and response is logged to data/orders.csv.
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Optional

MAX_DATA_DELAY_MIN = 2.5
QUARTERS = {3: "H", 6: "M", 9: "U", 12: "Z"}


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
        env = os.getenv("STARNET_TRADERSPOST_WEBHOOKS", "")
        self.webhooks = webhooks if webhooks is not None else [u.strip() for u in env.split(",") if u.strip()]
        self.state_path = os.path.join(data_dir, "execution.json")
        self.armed = False
        self.open: dict[str, dict] = {}      # symbol -> {"side", "qty", "contract"} we have on for real
        self.last_error = ""
        self.sent = 0
        self.blocked = 0
        self.queue: asyncio.Queue | None = None
        self._load()

    # ---------------------------------------------------------------- state
    @property
    def configured(self) -> bool:
        return bool(self.webhooks)

    def _load(self) -> None:
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                s = json.load(f)
            self.armed = bool(s.get("armed")) and self.configured
            self.open = s.get("open", {})

    def _save(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump({"armed": self.armed, "open": self.open}, f, indent=1)

    def arm(self, on: bool) -> None:
        if on and not self.configured:
            raise ValueError("set STARNET_TRADERSPOST_WEBHOOKS first")
        self.armed = on
        self._save()

    def status(self, delay_min: float) -> dict:
        return {"configured": self.configured, "armed": self.armed, "open": self.open,
                "data_ok": delay_min <= MAX_DATA_DELAY_MIN, "max_delay": MAX_DATA_DELAY_MIN,
                "sent": self.sent, "blocked": self.blocked, "last_error": self.last_error}

    # ---------------------------------------------------------------- orders
    def start(self) -> None:
        """Begin sending; close anything left open by a previous run."""
        self.queue = asyncio.Queue()
        asyncio.create_task(self._worker())
        for symbol, pos in list(self.open.items()):
            self._enqueue(symbol, {"action": "exit", "cancel": True}, "restart: bots start flat", pos["contract"])
            del self.open[symbol]
        self._save()

    def handle(self, engine, events: list[dict], delay_min: float) -> None:
        """Turn the bots' trade events into real orders."""
        if not (self.armed and self.queue):
            return
        for ev in events:
            if ev["type"] not in ("trade_open", "trade_add", "trade_trim", "trade_close"):
                continue
            bot = engine.bots.get(ev.get("bot"))
            if bot is None or bot.cfg.instrument != "future":
                continue
            symbol = bot.cfg.underlying
            if ev["type"] == "trade_open":
                if delay_min > MAX_DATA_DELAY_MIN:
                    self.blocked += 1
                    self._log(symbol, {"action": "skip-open"}, f"data {delay_min:.1f} min old", 0)
                    continue
                side = "buy" if ev["contract"].endswith("LONG") else "sell"
                contract = front_month(symbol)
                self.open[symbol] = {"side": side, "qty": ev["qty"], "contract": contract}
                self._enqueue(symbol, {"action": side, "quantity": ev["qty"], "orderType": "market",
                                       "signalPrice": round(engine.market.underlyings[symbol].price, 2)}, ev["bot"], contract)
            elif ev["type"] == "trade_add" and symbol in self.open:
                if delay_min > MAX_DATA_DELAY_MIN:
                    self.blocked += 1
                    continue
                self.open[symbol]["qty"] += ev["qty"]
                self._enqueue(symbol, {"action": "add", "quantity": ev["qty"], "orderType": "market"}, ev["bot"],
                              self.open[symbol]["contract"])
            elif ev["type"] == "trade_trim" and symbol in self.open:
                # resize = "end at this many contracts": TradersPost only sends the difference,
                # so a repeat or a missed fill can't over-trim. Never blocked: it only reduces risk.
                left = self.open[symbol]["qty"] = max(1, self.open[symbol]["qty"] - ev["qty"])
                self._enqueue(symbol, {"action": "resize", "quantity": left, "orderType": "market", "cancel": False},
                              ev["bot"], self.open[symbol]["contract"])
            elif ev["type"] == "trade_close" and symbol in self.open:
                pos = self.open.pop(symbol)
                self._enqueue(symbol, {"action": "exit", "cancel": True}, ev["bot"], pos["contract"])
        self._save()

    def flatten_all(self, symbols: list[str]) -> None:
        for symbol in set(symbols) | set(self.open):
            self._enqueue(symbol, {"action": "exit", "cancel": True}, "flatten all",
                          self.open.get(symbol, {}).get("contract"))
        self.open.clear()
        self.armed = False
        self._save()

    def _enqueue(self, symbol: str, msg: dict, reason: str, contract: Optional[str] = None) -> None:
        payload = {"ticker": contract or front_month(symbol), **msg, "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if self.queue is not None:
            self.queue.put_nowait((symbol, payload, reason))

    async def _worker(self) -> None:
        """Send orders one at a time, in order, so an exit can never overtake its entry."""
        while True:
            symbol, payload, reason = await self.queue.get()
            for url in self.webhooks:
                status, body = 0, ""
                for attempt in range(3):
                    try:
                        status, body = await asyncio.to_thread(self._post, url, payload)
                        if 200 <= status < 300:
                            break
                    except Exception as exc:   # network error: retry
                        status, body = 0, str(exc)
                    await asyncio.sleep(1 + attempt)
                ok = 200 <= status < 300
                self.sent += ok
                self.last_error = "" if ok else f"{payload['action']} {payload['ticker']}: HTTP {status} {body[:120]}"
                self._log(symbol, payload, reason, status, body)

    @staticmethod
    def _post(url: str, payload: dict) -> tuple[int, str]:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode(errors="replace")

    def _log(self, symbol: str, payload: dict, reason: str, status: int, body: str = "") -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        path = os.path.join(self.data_dir, "orders.csv")
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["sent_utc", "symbol", "ticker", "action", "quantity", "reason", "http_status", "response"])
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"), symbol, payload.get("ticker", ""),
                        payload.get("action"), payload.get("quantity", ""), reason, status, body[:200]])
