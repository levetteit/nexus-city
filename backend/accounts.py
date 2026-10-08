"""Your Lucid accounts: each one tracked separately through the bots' trades.

The bots trade one strategy; TradersPost copies it to your accounts. They take the
same trades but sit in different places: one still in its evaluation, one funded
and close to a payout, one just synced after a payout. The book keeps a full
`PropAccount` for each (phase, balance, EOD drawdown, payout cycle) and feeds it
the P&L of every trade it was in.

Routing. If an account has its own TradersPost webhook (one TradersPost strategy
per account), new entries only go to accounts allowed to trade right now:
an evaluation that reached its target, an account that hit its daily stop or is
too close to its drawdown is skipped while the others keep trading. Adds, trims
and exits always follow the accounts that entered. Accounts without their own
webhook are assumed to copy every trade through NEXUS_TRADERSPOST_WEBHOOKS, and
the book only warns you when one of them should stop.

Saved to data/accounts.json (webhook URLs stay on the server, never sent to the app).
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone

from .persist import write_json_atomic
from .account import PropAccount

FIELDS = ("phase", "balance", "eod_high", "mll", "mll_locked", "best_day", "days", "profitable_days",
          "day_realized", "day_history", "cycle_days", "cycle_start", "payouts", "halted", "day_stop")


class Linked:
    def __init__(self, id: str, name: str, webhook: str = "", account: PropAccount | None = None) -> None:
        self.id, self.name, self.webhook = id, name, webhook
        self.account = account or PropAccount()
        self.warned: set[str] = set()   # alerts already sent today

    def can_enter(self) -> bool:
        a = self.account
        return a.can_trade and not a.goal_reached

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "webhook": self.webhook,
                "state": {k: getattr(self.account, k) for k in FIELDS}}

    @classmethod
    def from_json(cls, d: dict) -> "Linked":
        acc = PropAccount()
        for k, v in d.get("state", {}).items():
            if k in FIELDS:
                setattr(acc, k, [tuple(x) for x in v] if k == "day_history" else v)
        return cls(d["id"], d["name"], d.get("webhook", ""), acc)


class AccountBook:
    def __init__(self, data_dir: str) -> None:
        self.path = os.path.join(data_dir, "accounts.json")
        self.accounts: list[Linked] = []
        self.in_trade: dict[str, dict[str, int]] = {}   # bot id -> {account id: contracts} in its open trade
        self.bot_qty: dict[str, int] = {}                # bot id -> contracts the bot itself holds
        self.trade_pnl: dict[str, dict[str, float]] = {} # bot id -> {account id: P&L already banked by trims}
        self.last_add: dict[str, list[str]] = {}         # bot id -> webhooks that took its latest add
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.accounts = [Linked.from_json(d) for d in json.load(f)]

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        write_json_atomic(self.path, [a.to_json() for a in self.accounts], indent=1)

    def get(self, acc_id: str) -> Linked:
        for a in self.accounts:
            if a.id == acc_id:
                return a
        raise KeyError("no such account")

    # ---------------------------------------------------------------- managing accounts
    def add(self, name: str, phase: str, balance: float, mll: float, payouts: int = 0, cycle_days: int = 0,
            webhook: str = "") -> Linked:
        if webhook and not webhook.startswith("https://"):
            raise ValueError("the webhook must be an https:// URL from TradersPost")
        acc = Linked(secrets.token_hex(4), name.strip()[:40] or f"Account {len(self.accounts) + 1}", webhook.strip())
        acc.account.sync(phase, balance, mll, payouts, cycle_days)
        self.accounts.append(acc)
        self.save()
        return acc

    def remove(self, acc_id: str) -> None:
        self.accounts = [a for a in self.accounts if a.id != acc_id]
        for members in self.in_trade.values():
            members.pop(acc_id, None)
        self.save()

    def set_webhook(self, acc_id: str, webhook: str) -> None:
        if webhook and not webhook.startswith("https://"):
            raise ValueError("the webhook must be an https:// URL from TradersPost")
        self.get(acc_id).webhook = webhook.strip()
        self.save()

    # ---------------------------------------------------------------- following the bots
    def observe(self, engine, events: list[dict]) -> list[dict]:
        """Apply the tick's trades to every account, contract by contract. Returns alerts
        (passed, failed, payout ready, an account that must stop while the bots keep trading)."""
        out: list[dict] = []
        changed = False
        for ev in events:
            kind, bot = ev["type"], ev.get("bot")
            if kind == "trade_open":
                q = ev["qty"]
                # accounts with their own webhook only join when allowed and within their size budget;
                # copy-all accounts take every trade the shared strategy takes
                self.in_trade[bot] = {a.id: q for a in self.accounts
                                      if not a.webhook or (a.can_enter() and self._open_qty(a) + q <= a.account.max_micros)}
                self.bot_qty[bot], self.trade_pnl[bot], self.last_add[bot] = q, {}, []
            elif kind == "trade_add":
                add, members = ev["qty"], self.in_trade.get(bot, {})
                self.last_add[bot] = []
                for a in self._members(bot):
                    if not a.webhook or (a.account.can_trade and self._open_qty(a) + add <= a.account.max_micros):
                        members[a.id] += add
                        if a.webhook:
                            self.last_add[bot].append(a.webhook)
                self.bot_qty[bot] = ev["total"]
            elif kind == "trade_trim":
                per = ev["pnl"] / ev["qty"]
                members = self.in_trade.get(bot, {})
                for a in self._members(bot):
                    keep = min(members[a.id], ev["left"])
                    cut, members[a.id] = members[a.id] - keep, keep
                    if cut:
                        a.account.trimmed(bot, 0, round(per * cut, 2))
                        self.trade_pnl[bot][a.id] = self.trade_pnl[bot].get(a.id, 0) + per * cut
                self.bot_qty[bot] = ev["left"]
                changed = True
            elif kind == "trade_close":
                per = ev["pnl"] / max(1, self.bot_qty.get(bot) or 1)
                members = self.in_trade.get(bot, {})
                for a in self._members(bot):
                    pnl = round(per * members[a.id], 2)
                    a.account.closed(bot, "", pnl, pnl + self.trade_pnl.get(bot, {}).get(a.id, 0))
                    members[a.id] = 0   # flat; kept until the next entry: the router may still need it this tick
                changed = True
            elif kind == "new_session":
                for a in self.accounts:
                    out += self._roll(a)
                changed = True
        # open P&L, the drawdown and each account's own daily stop / cap / target
        bots_stopped = bool(engine.account.halted) or engine.account.phase == "failed"
        for a in self.accounts:
            unreal = 0.0
            for bid, b in engine.bots.items():
                q = self.in_trade.get(bid, {}).get(a.id, 0)
                if b.position and q:
                    unreal += b.position.pnl(engine.broker.mark(b.position, engine.market)) * q / b.position.qty
            was = a.account.phase
            reason = a.account.check(unreal)
            if a.account.phase == "failed" and was != "failed":
                out.append(self._alert(a, "failed", f"{a.name} touched its MLL: account failed"))
                changed = True
            elif reason and reason not in a.warned and not bots_stopped:   # the bots stopping for everyone needs no alert
                a.warned.add(reason)
                if a.webhook:
                    msg = f"{a.name}: {reason} · no new entries for this account today"
                else:   # we can't stop a copy-all account ourselves
                    msg = f"{a.name}: {reason} · it copies every trade: pause its TradersPost subscription for today"
                out.append(self._alert(a, "halt", msg))
        if changed:
            self.save()
        return out

    def _members(self, bot: str) -> list[Linked]:
        ids = self.in_trade.get(bot, {})
        return [a for a in self.accounts if ids.get(a.id)]

    def _open_qty(self, a: Linked) -> int:
        return sum(m.get(a.id, 0) for m in self.in_trade.values())

    def _roll(self, a: Linked) -> list[dict]:
        acc, out = a.account, []
        phase, could_pay = acc.phase, acc.payout_eligible
        acc.end_of_day()
        a.warned.clear()
        if phase == "evaluation" and acc.phase == "funded":
            out.append(self._alert(a, "passed", f"{a.name} PASSED its evaluation → funded"))
        if acc.payout_eligible and not could_pay:
            sug = f"suggested ${acc.safe_payout:,.0f}" if acc.safe_payout else "wait for more cushion"
            out.append(self._alert(a, "payout", f"{a.name}: payout #{len(acc.payouts) + 1} available, up to "
                                                f"${acc.payout_limit:,.0f} ({sug})"))
        return out

    @staticmethod
    def _alert(a: Linked, what: str, text: str) -> dict:
        return {"type": "acct_event", "account": a.id, "name": a.name, "what": what, "text": text}

    # ---------------------------------------------------------------- routing (execution.py asks these)
    def entry_targets(self, bot: str) -> list[str]:
        """Own-webhook accounts that joined this bot's new trade."""
        return [a.webhook for a in self._members(bot) if a.webhook]

    def add_targets(self, bot: str) -> list[str]:
        """Own-webhook accounts that took the bot's latest add (the rest stay at their size)."""
        return list(self.last_add.get(bot, []))

    def target_qty(self, bot: str) -> dict[str, int]:
        """Contracts each own-webhook account holds in this bot's trade right now."""
        members = self.in_trade.get(bot, {})
        return {a.webhook: members[a.id] for a in self._members(bot) if a.webhook}

    def urls(self) -> list[str]:
        return [a.webhook for a in self.accounts if a.webhook]

    # ---------------------------------------------------------------- view
    def status(self) -> dict:
        rows, ready = [], 0.0
        for a in self.accounts:
            s = a.account.snapshot()
            ready += s["safe_payout"]
            rows.append({"id": a.id, "name": a.name, "routed": bool(a.webhook), "can_enter": a.can_enter(),
                         **{k: s[k] for k in ("phase", "balance", "mll", "mll_locked", "day_pnl", "daily_stop", "halted",
                                              "target", "profit", "cycle_days", "payout_days", "payout_day_min",
                                              "cycle_net", "payout_eligible", "payout_limit", "safe_payout", "payouts",
                                              "max_payouts", "paid_out", "best_day", "consistency")},
                         "room": round(s["equity"] - s["mll"], 2)})
        return {"accounts": rows, "count": len(rows), "payouts_ready": round(ready, 2),
                "total_balance": round(sum(r["balance"] for r in rows), 2),
                "paid_out": round(sum(r["paid_out"] for r in rows), 2),
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
