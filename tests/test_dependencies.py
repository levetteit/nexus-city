"""The lockfile that Docker and CI install pins every direct dependency, exactly."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _names(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"([A-Za-z0-9_.-]+)(\[[^\]]*\])?\s*(.*)", line)
        out[m.group(1).lower().replace("_", "-")] = m.group(3)
    return out


def test_every_direct_dependency_is_pinned_in_the_lock():
    direct = _names((ROOT / "requirements.txt").read_text())
    locked = _names((ROOT / "requirements.lock").read_text())
    for name in direct:
        assert name in locked, f"{name} is missing from requirements.lock: regenerate it (docs/DEVELOPMENT.md)"
    assert all(spec.startswith("==") for spec in locked.values()), "every locked version must be exact"


def test_python_version_is_pinned_for_docker_and_ci():
    assert (ROOT / ".python-version").read_text().strip() == "3.12"
    assert "python:3.12" in (ROOT / "Dockerfile").read_text()
    assert "requirements.lock" in (ROOT / "Dockerfile").read_text()
