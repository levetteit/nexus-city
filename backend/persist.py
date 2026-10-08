"""Crash-safe file writes and reads for the app's JSON state and its append-only JSONL logs.

* `write_json_atomic` writes to a temporary file in the same directory, flushes it to disk, then renames it over the
  old file. A crash leaves either the old version or the new one, never a half-written file.
* `repair_jsonl_tail` handles the one way an append-only log can break: a crash in the middle of an append leaves a
  last line without its newline. The torn bytes are moved aside to `<file>.torn-<time>` (kept for review, never
  silently dropped), so the next append starts on a clean line instead of gluing itself to the fragment.
* `read_jsonl` reads every complete line and skips (and counts) any that don't parse, so one bad line can never stop
  the app from starting.

See docs/PERSISTENCE.md.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Optional


def write_json_atomic(path: str, obj: Any, **dump_kwargs) -> None:
    """Replace `path` with `obj` as JSON, atomically and durably."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f, **dump_kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):   # only when something failed before the rename
            try:
                os.remove(tmp)
            except OSError:
                pass


def repair_jsonl_tail(path: str) -> Optional[str]:
    """If the log's last line was cut off by a crash, move the fragment aside. Returns where it went, or None."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size == 0:
        return None
    with open(path, "rb+") as f:
        f.seek(-1, os.SEEK_END)
        if f.read(1) == b"\n":
            return None
        f.seek(0)
        data = f.read()
        cut = data.rfind(b"\n") + 1   # 0 when the whole file is one torn line
        aside = f"{path}.torn-{int(time.time())}"
        with open(aside, "wb") as out:
            out.write(data[cut:])
        f.truncate(cut)
    return aside


def read_jsonl(path: str) -> tuple[list[dict], int]:
    """(records, bad_lines): every complete line that parses as JSON; lines that don't are skipped and counted."""
    if not os.path.exists(path):
        return [], 0
    out, bad = [], 0
    with open(path) as f:
        for line in f:
            if not line.strip():
                continue
            if not line.endswith("\n"):   # a torn last line (repair_jsonl_tail moves these aside)
                bad += 1
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                bad += 1
    return out, bad
