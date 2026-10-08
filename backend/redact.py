"""Keep secrets out of error messages, logs and anything shown in the app.

`redact(text)` removes the values of every secret setting (anything whose name says TOKEN, SECRET, PASSWORD,
KEY or WEBHOOK, under its NEXUS_, STARNET_ or third-party name) and common credential shapes (access_token=...,
Bearer ..., Stripe/Anthropic keys, TradersPost webhook paths). It is applied where outside text becomes our
text: connector errors, the order router's errors and log, the station's last error, and printed log lines.
"""
from __future__ import annotations

import os
import re

SECRET_WORDS = ("TOKEN", "SECRET", "PASSWORD", "KEY", "WEBHOOK")
MASK = "[redacted]"
MIN_LEN = 8   # shorter values (flags, small numbers) are not treated as secrets
PATTERNS = [
    re.compile(r"(access_token=)[^&\s\"']+", re.I),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.I),
    re.compile(r"()\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"()\bwhsec_[A-Za-z0-9]{8,}"),
    re.compile(r"()\bsk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(traderspost\.io/)[^\s\"']+", re.I),
]


def secret_values() -> list[str]:
    vals = set()
    for name, value in os.environ.items():
        if any(w in name.upper() for w in SECRET_WORDS) and value and len(value.strip()) >= MIN_LEN:
            vals.add(value.strip())
            vals.update(v.strip() for v in value.split(",") if len(v.strip()) >= MIN_LEN)   # comma-separated lists
    return sorted(vals, key=len, reverse=True)


def redact(text) -> str:
    """`text` with secret values and credential-looking strings masked. Safe on any input."""
    s = "" if text is None else str(text)
    for v in secret_values():
        if v in s:
            s = s.replace(v, MASK)
    for p in PATTERNS:
        s = p.sub(lambda m: m.group(1) + MASK, s)
    return s
