"""Settings from the environment: NEXUS_* names, with the project's former STARNET_* names still honoured.

The project was called StarNet before it became Nexus City. Every setting is read here so a deployment that still
uses the old names keeps working unchanged:

    env("PASSWORD")   ->  NEXUS_PASSWORD, else STARNET_PASSWORD (deprecated), else the default

NEXUS_* wins when both are set. `legacy_names_in_use()` lists the old names a deployment still relies on
(names only, never values), so startup can say what is left to rename. See docs/MIGRATION_FROM_STARNET.md.
"""
from __future__ import annotations

import os
from typing import Optional

PREFIX = "NEXUS_"
LEGACY_PREFIX = "STARNET_"


def env(name: str, default: Optional[str] = None) -> Optional[str]:
    """The value of NEXUS_<name>, or of the deprecated STARNET_<name>, or `default`."""
    value = os.environ.get(PREFIX + name)
    if value is None:
        value = os.environ.get(LEGACY_PREFIX + name)
    return default if value is None else value


def set_env(name: str, value: str) -> None:
    """Set a setting for this process (under the current name, so it wins over a legacy value)."""
    os.environ[PREFIX + name] = value


def legacy_names_in_use() -> list[str]:
    """STARNET_* variables that are set with no NEXUS_* counterpart: what's left to rename."""
    return sorted(k for k in os.environ if k.startswith(LEGACY_PREFIX) and PREFIX + k[len(LEGACY_PREFIX):] not in os.environ)
