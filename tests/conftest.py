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
