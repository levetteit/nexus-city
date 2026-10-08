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
from typing import Any, Callable, Optional, Protocol

from ..persist import repair_jsonl_tail, write_json_atomic

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


class StationStore(Protocol):
    """What the station needs from storage. `Store` (JSON files + JSONL audit log) implements it today; a future
    PostgresStore would implement the same methods (docs/PERSISTENCE.md). Records are plain dicts; every change
    writes an audit event."""

    lock: Any

    def all(self, name: str) -> list[dict]: ...
    def get(self, name: str, rid: str) -> Optional[dict]: ...
    def find(self, name: str, **match) -> list[dict]: ...
    def create(self, name: str, record: dict, by: str, why: str = "") -> dict: ...
    def update(self, name: str, rid: str, changes: dict, by: str, why: str = "", kind: Optional[str] = None) -> dict: ...
    def event(self, kind: str, by: str, summary: str, ref: Optional[str] = None, data: Any = None,
              severity: str = "INFO") -> dict: ...
    def events(self, limit: int = 100, kinds: Optional[tuple] = None) -> list[dict]: ...
    def save_doc(self, name: str, doc: Any) -> None: ...
    def load_doc(self, name: str) -> Optional[Any]: ...
    def update_doc(self, name: str, change: Callable[[Any], Any]) -> Any: ...


class Store:
    """The JSON-file implementation of StationStore: one file per collection, rewritten atomically on each change,
    plus the append-only audit log events.jsonl. Thread-safe through one re-entrant lock."""

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
        torn = repair_jsonl_tail(self.events_path)   # a crash mid-append: set the fragment aside, keep the log clean
        self._events: list[dict] = []                 # the audit log, parsed once and then read incrementally
        self._events_offset = 0
        self.bad_event_lines = 0
        if torn:
            self.event("storage.repaired", "station", f"audit log: a line cut off by a crash was moved to {os.path.basename(torn)}",
                       severity="WARNING")

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

    def _read_new_events(self) -> None:
        """Parse only what was appended since the last read (whole lines only; bad lines are skipped and counted)."""
        try:
            size = os.path.getsize(self.events_path)
        except OSError:
            return
        if size < self._events_offset:   # the file was replaced or rotated: start over
            self._events, self._events_offset = [], 0
        if size == self._events_offset:
            return
        with open(self.events_path, "rb") as f:
            f.seek(self._events_offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1      # leave a line that's still being written for next time
        for line in chunk[:end].splitlines():
            if not line.strip():
                continue
            try:
                self._events.append(json.loads(line))
            except ValueError:
                self.bad_event_lines += 1
        self._events_offset += end

    def events(self, limit: int = 100, kinds: Optional[tuple] = None) -> list[dict]:
        """The newest `limit` events (optionally only kinds starting with `kinds`), newest first."""
        with self.lock:
            self._read_new_events()
            out = []
            for ev in reversed(self._events):
                if kinds is None or str(ev.get("kind", "")).startswith(kinds):
                    out.append(dict(ev))
                    if len(out) >= limit:
                        break
            return out

    # ---------------------------------------------------------------- files
    def _save(self, name: str) -> None:
        write_json_atomic(os.path.join(self.dir, f"{name}.json"), list(self.data[name].values()), indent=1, default=str)

    def _save_counters(self) -> None:
        write_json_atomic(os.path.join(self.dir, "counters.json"), self.counters)

    def save_doc(self, name: str, doc: Any) -> None:
        """A free-form document (routine outputs, ULTRON's reports) under data/station/docs/."""
        d = os.path.join(self.dir, "docs")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with self.lock:   # write, then swap: a reader never sees a half-written file
            write_json_atomic(path, doc, indent=1, default=str)

    def update_doc(self, name: str, change: Callable[[Any], Any]) -> Any:
        """Read-modify-write a document under the store's lock, so two threads can't overwrite each other's change
        (e.g. an opt-out arriving while the dispatch worker records a send). `change` returns the new document."""
        with self.lock:
            doc = change(self.load_doc(name))
            self.save_doc(name, doc)
            return doc

    def load_doc(self, name: str) -> Optional[Any]:
        path = os.path.join(self.dir, "docs", name)
        with self.lock:
            if not os.path.exists(path):
                return None
            with open(path) as f:
                return json.load(f)

    def list_docs(self, prefix: str, limit: int = 20) -> list[str]:
        d = os.path.join(self.dir, "docs")
        if not os.path.isdir(d):
            return []
        return sorted((n for n in os.listdir(d) if n.startswith(prefix) and n.endswith(".json")), reverse=True)[:limit]


JSONStore = Store   # the name the persistence docs use
