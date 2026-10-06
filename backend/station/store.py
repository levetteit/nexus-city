"""Durable station records and the audit trail.

Every collection lives in one JSON file under data/station/. Every change also appends one line to
events.jsonl (who, what, why, when), which is never rewritten: it is the station's audit log, and the
feed the Command Board and the 3D station animate from.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

COLLECTIONS = ("ventures", "agents", "tasks", "approvals", "opportunities", "missions", "routines", "actions", "leads",
               "products")
SINGULAR = {"opportunities": "opportunity"}
PREFIX = {"ventures": "V", "agents": "A", "tasks": "T", "approvals": "AP", "opportunities": "OP",
          "missions": "M", "routines": "R", "actions": "X", "leads": "L", "products": "PR"}

# Venture lifecycle (the export's canonical order, plus the two end states)
STAGES = ("research", "validate", "approved", "build", "launch", "operate", "measure", "optimize", "scale",
          "paused", "killed")
AGENT_STATES = ("WORKING", "THINKING", "WAITING", "COMPLETED", "ON BREAK", "BENCHED")
TASK_STATES = ("queued", "blocked", "running", "done", "failed", "waiting_owner", "cancelled")
SEVERITIES = ("INFO", "OPPORTUNITY", "ACTION NEEDED", "WARNING", "CRITICAL", "WAITING FOR OWNER")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, data_dir: str) -> None:
        self.dir = os.path.join(data_dir, "station")
        os.makedirs(self.dir, exist_ok=True)
        self.lock = threading.RLock()
        self.data: dict[str, dict[str, dict]] = {}
        self.counters: dict[str, int] = {}
        for name in COLLECTIONS:
            path = os.path.join(self.dir, f"{name}.json")
            self.data[name] = {}
            if os.path.exists(path):
                with open(path) as f:
                    self.data[name] = {r["id"]: r for r in json.load(f)}
        cpath = os.path.join(self.dir, "counters.json")
        if os.path.exists(cpath):
            with open(cpath) as f:
                self.counters = json.load(f)
        self.events_path = os.path.join(self.dir, "events.jsonl")

    # ---------------------------------------------------------------- records
    def all(self, name: str) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.data[name].values()]

    def get(self, name: str, rid: str) -> Optional[dict]:
        with self.lock:
            r = self.data[name].get(rid)
            return dict(r) if r else None

    def find(self, name: str, **match) -> list[dict]:
        return [r for r in self.all(name) if all(r.get(k) == v for k, v in match.items())]

    def create(self, name: str, record: dict, by: str, why: str = "") -> dict:
        with self.lock:
            n = self.counters.get(name, 0) + 1
            while not record.get("id") and f"{PREFIX[name]}-{n:03d}" in self.data[name]:
                n += 1   # a seeded record already took this number
            self.counters[name] = n
            rid = record.get("id") or f"{PREFIX[name]}-{n:03d}"
            rec = {**record, "id": rid, "created_at": now_iso(), "updated_at": now_iso()}
            self.data[name][rid] = rec
            self._save(name)
            self._save_counters()
            self.event(f"{SINGULAR.get(name, name[:-1])}.created", by, why or rec.get("name") or rec.get("title") or rid, ref=rid,
                       data={k: rec[k] for k in ("name", "title", "stage", "status", "role") if k in rec})
            return dict(rec)

    def update(self, name: str, rid: str, changes: dict, by: str, why: str = "", kind: Optional[str] = None) -> dict:
        with self.lock:
            rec = self.data[name][rid]
            before = {k: rec.get(k) for k in changes}
            rec.update(changes)
            rec["updated_at"] = now_iso()
            self._save(name)
            diff = {k: [before[k], changes[k]] for k in changes if before[k] != changes[k] and not isinstance(changes[k], (list, dict))}
            self.event(kind or f"{SINGULAR.get(name, name[:-1])}.updated", by, why, ref=rid, data=diff or None)
            return dict(rec)

    # ---------------------------------------------------------------- audit log
    def event(self, kind: str, by: str, summary: str, ref: Optional[str] = None, data: Any = None,
              severity: str = "INFO") -> dict:
        ev = {"at": now_iso(), "kind": kind, "by": by, "summary": summary, "severity": severity}
        if ref:
            ev["ref"] = ref
        if data:
            ev["data"] = data
        with self.lock, open(self.events_path, "a") as f:
            f.write(json.dumps(ev, default=str) + "\n")
        return ev

    def events(self, limit: int = 100, kinds: Optional[tuple] = None) -> list[dict]:
        if not os.path.exists(self.events_path):
            return []
        with self.lock, open(self.events_path) as f:
            lines = f.readlines()
        out = []
        for line in reversed(lines):
            ev = json.loads(line)
            if kinds is None or ev["kind"].startswith(kinds):
                out.append(ev)
                if len(out) >= limit:
                    break
        return out

    # ---------------------------------------------------------------- files
    def _save(self, name: str) -> None:
        path = os.path.join(self.dir, f"{name}.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(list(self.data[name].values()), f, indent=1, default=str)
        os.replace(tmp, path)

    def _save_counters(self) -> None:
        with open(os.path.join(self.dir, "counters.json"), "w") as f:
            json.dump(self.counters, f)

    def save_doc(self, name: str, doc: Any) -> None:
        """A free-form document (routine outputs, ULTRON's reports) under data/station/docs/."""
        d = os.path.join(self.dir, "docs")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        tmp = f"{path}.{threading.get_ident()}.tmp"   # write, then swap: a reader never sees a half-written file
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=1, default=str)
        os.replace(tmp, path)

    def load_doc(self, name: str) -> Optional[Any]:
        path = os.path.join(self.dir, "docs", name)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def list_docs(self, prefix: str, limit: int = 20) -> list[str]:
        d = os.path.join(self.dir, "docs")
        if not os.path.isdir(d):
            return []
        return sorted((n for n in os.listdir(d) if n.startswith(prefix) and n.endswith(".json")), reverse=True)[:limit]
