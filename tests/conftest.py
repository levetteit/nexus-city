import gzip
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# the app's files go to a throwaway directory, never ./data (session key, station records, logs)
import tempfile  # noqa: E402
os.environ.setdefault("NEXUS_DATA_DIR", tempfile.mkdtemp(prefix="nexus-test-data-"))


@pytest.fixture(scope="session")
def real_data(tmp_path_factory):
    """5 real trading days (Sep 14-18 2026) of MNQ and MES 1-minute candles."""
    from backend.backtest import load_csv
    d = tmp_path_factory.mktemp("candles")
    data = {}
    for sym in ("MNQ", "MES"):
        path = d / f"{sym}_1m.csv"
        with gzip.open(os.path.join(ROOT, "tests", "fixtures", f"{sym}_1m.csv.gz"), "rb") as src, open(path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        data[sym] = load_csv(str(path))
    return data


# ---------------------------------------------------------------- no real network in tests
# Every external service is faked in the tests themselves. This guard makes sure of it: a test that tries to open a
# connection to anything but this machine fails loudly instead of quietly posting, emailing, trading or paying.
# Tests that are meant to reach a real service are marked @pytest.mark.live and only run with NEXUS_LIVE_TESTS=1.
import socket  # noqa: E402

_real_connect = socket.socket.connect
_LOCAL = ("127.", "::1", "localhost", "0.0.0.0")


def _guarded_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and not host.startswith(_LOCAL) and self.family != getattr(socket, "AF_UNIX", -1):
        raise RuntimeError(f"tests must not use the network (tried to reach {host}); fake the connector "
                           "or mark the test @pytest.mark.live")
    return _real_connect(self, address)


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        if os.environ.get("NEXUS_LIVE_TESTS") != "1":
            pytest.skip("live test: set NEXUS_LIVE_TESTS=1 to run it against real services")
        return
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)   # a local proxy would otherwise carry requests past the guard
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)


_real_getaddrinfo = socket.getaddrinfo


def _guarded_getaddrinfo(host, *args, **kwargs):
    if isinstance(host, str) and host and not host.startswith(_LOCAL) and host != "testserver":
        raise RuntimeError(f"tests must not use the network (tried to resolve {host}); fake the connector "
                           "or mark the test @pytest.mark.live")
    return _real_getaddrinfo(host, *args, **kwargs)
