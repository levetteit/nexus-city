"""End-of-day report: what every bot did today, why, and where the prop account stands.

Live mode follows the day as it trades. When the day rolls (18:00 ET, after the
16:45 flat), the report is saved to data/reports/YYYY-MM-DD.json. Once the
paper-vs-backtest replay (scorecard.py) has checked the day, the report is
pushed to your phone. Tap the notification to open the full report in the app.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from .backtest import trading_day


def _money(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}${abs(v):,.0f}"


class DayReports:
    def __init__(self, data_dir: str) -> None:
        self.dir = os.path.join(data_dir, "reports")
        self._day: dict | None = None

    # ---------------------------------------------------------------- following the day
    def start_day(self, engine, partial: bool = False) -> None:
        self._day = {"day": trading_day(engine.market.now), "partial": partial, "trades": [], "open": {},
                     "news": [], "halts": []}

    def observe(self, engine, events: list[dict]) -> dict | None:
        """Feed every tick's events. Returns the finished day's report when a new day starts."""
        if self._day is None:
            return None
        finished = None
        for ev in events:
            kind = ev["type"]
            if kind == "new_session":
                finished = self._finish(engine, ev)
                self.start_day(engine)
            elif kind == "trade_open":
                self._day["open"][ev["bot"]] = {"why": ev.get("note", ""), "adds": [], "trims": []}
            elif kind == "trade_add":
                self._day["open"].setdefault(ev["bot"], {"why": "", "adds": [], "trims": []})["adds"].append(ev.get("why", ""))
            elif kind == "trade_trim":
                self._day["open"].setdefault(ev["bot"], {"why": "", "adds": [], "trims": []})["trims"].append(
                    {"qty": ev["qty"], "price": ev["price"], "pnl": ev["pnl"]})
            elif kind == "trade_close":
                bot = engine.bots[ev["bot"]]
                t = bot.trades[-1]
                info = self._day["open"].pop(ev["bot"], {"why": "", "adds": [], "trims": []})
                persona = bot.cfg.persona or {}
                self._day["trades"].append({
                    "bot": bot.cfg.id, "name": bot.cfg.name, "handle": persona.get("handle", bot.cfg.name),
                    "side": "long" if t.contract.endswith("LONG") else "short", "qty": t.qty,
                    "entry": t.entry, "exit": t.exit, "pnl": ev.get("trade_pnl", t.pnl), "opened": t.opened_at,
                    "closed": t.closed_at, "why": info["why"], "adds": info["adds"], "trims": info.get("trims", []),
                    "exit_reason": t.reason})
            elif kind == "news_hold":
                self._day["news"].append(f"{ev['title']} {ev['at']}")
            elif kind == "account_halt":
                self._day["halts"].append(ev["reason"])
        return finished

    def _finish(self, engine, ev: dict) -> dict:
        d, acct = self._day, engine.account
        trades = d["trades"]
        day_pnl = acct.day_history[-1][1] if acct.day_history else round(sum(t["pnl"] for t in trades), 2)
        by_bot: dict[str, float] = {}
        for t in trades:
            by_bot[t["handle"]] = round(by_bot.get(t["handle"], 0) + t["pnl"], 2)
        a = acct.snapshot()
        return {
            "day": d["day"].isoformat(), "partial": d["partial"], "pnl": day_pnl,
            "trades": trades, "wins": sum(t["pnl"] > 0 for t in trades), "losses": sum(t["pnl"] <= 0 for t in trades),
            "by_bot": by_bot, "news": d["news"], "halts": d["halts"],
            "goal": acct.guards.daily_goal, "goal_hit": day_pnl >= acct.guards.daily_goal,
            "passed": bool(ev.get("phase_change")) and acct.phase == "funded",
            "account": {k: a[k] for k in ("phase", "balance", "profit", "target", "mll", "days",
                                          "profitable_days", "payout_days", "payout_eligible", "best_day",
                                          "consistency")},
            "room": round(acct.balance - acct.mll, 2),
            "check": None,
        }

    # ---------------------------------------------------------------- storage
    def save(self, report: dict) -> None:
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, f"{report['day']}.json"), "w") as f:
            json.dump(report, f, indent=1)

    def get(self, day: str) -> dict | None:
        try:
            date.fromisoformat(day)   # also keeps the path inside the reports folder
        except ValueError:
            return None
        path = os.path.join(self.dir, f"{day}.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def list(self, limit: int = 60) -> list[dict]:
        if not os.path.isdir(self.dir):
            return []
        out = []
        for name in sorted(os.listdir(self.dir), reverse=True)[:limit]:
            if name.endswith(".json"):
                r = self.get(name[:-5])
                if r:
                    out.append({"day": r["day"], "pnl": r["pnl"], "trades": len(r["trades"]), "wins": r["wins"],
                                "goal_hit": r["goal_hit"], "passed": r["passed"],
                                "check": r["check"]["verdict"] if r.get("check") else None})
        return out

    # ---------------------------------------------------------------- the push
    @staticmethod
    def message(r: dict, paper: dict | None = None, baseline: dict | None = None) -> tuple[str, str]:
        day = date.fromisoformat(r["day"]).strftime("%a %b %-d")
        n = len(r["trades"])
        title = f"📊 {day} · {_money(r['pnl'])} · {n} trade{'' if n == 1 else 's'}"
        if r["passed"]:
            title = f"🏆 PASSED the evaluation · {title}"
        lines = []
        if n:
            lines.append(f"{r['wins']}W {r['losses']}L" + (" · goal ✓" if r["goal_hit"] else ""))
        else:
            lines.append("no trades today" + (f" · news: {', '.join(r['news'])}" if r["news"] else ""))
        a = r["account"]
        if a["phase"] == "evaluation" and a["target"]:
            pct = max(0, min(100, round(100 * a["profit"] / a["target"])))
            lines.append(f"Eval {_money(a['profit'])} / ${a['target']:,.0f} ({pct}%) · ${r['room']:,.0f} room")
        else:
            lines.append(f"Funded {_money(a['profit'])} · {a['profitable_days']}/{a['payout_days']} payout days"
                         f" · ${r['room']:,.0f} room")
        c = r.get("check")
        if c:
            ok = c["verdict"] == "match"
            lines.append(f"Replay {'✅' if ok else '⚠️'} {c['matched']}/{max(c['live_trades'], c['replay_trades'])} trades matched"
                         + ("" if ok or not c["explained_by"] else f" ({c['explained_by'][0]})"))
        if n:
            best = max(r["trades"], key=lambda t: t["pnl"])
            why = re.sub(r" off [^+]*", " ", best["why"]).replace("  ", " ").strip()   # drop the zone prices
            lines.append(f"Best: {best['handle']} {_money(best['pnl'])} ({why or best['side']})")
        if paper and paper.get("days") and baseline:
            lines.append(f"Paper {paper['days']}d: {paper['profitable_day_pct']}% green (backtest {baseline['profitable_day_pct']}%)")
        return title, "\n".join(lines)
