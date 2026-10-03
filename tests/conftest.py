"""Shared fixtures. Records every test outcome with its pitfall markers into
$KPI_DIR/pytest-<suite>.json, read by ci/kpi.py."""
import json, os, sys, hashlib, shutil, urllib.request
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "hooks"))

# CC0 sample from raw.pixls.us (uploads are released into the public domain).
SAMPLE_URL = "https://raw.pixls.us/data/Sony/ILCE-7M3/_DSC0009.ARW"
SAMPLE_SHA256 = "250784580ea527442c09004417bb0eead484f2bf3ee8f9121a776ac65bb50d0f"


def pytest_configure(config):
    config.addinivalue_line("markers", "pitfall(id): the test reproduces pitfall `id` of docs/pitfalls.md")
    config.addinivalue_line("markers", "darktable: needs darktable-cli and the sample RAW")


_results = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    rep = (yield).get_result()
    if rep.when == "call" or (rep.when == "setup" and rep.outcome != "passed"):
        _results.append(dict(test=item.nodeid, outcome="skipped" if rep.skipped else rep.outcome,
                             pitfalls=[m.args[0] for m in item.iter_markers("pitfall")],
                             darktable=item.get_closest_marker("darktable") is not None))


def pytest_sessionfinish(session):
    d = os.environ.get("KPI_DIR")
    if d:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"pytest-{os.environ.get('KPI_SUITE', 'local')}.json"), "w") as f:
            json.dump(_results, f, indent=1)


@pytest.fixture(scope="session")
def minimal_xmp():
    return open(os.path.join(ROOT, "tests", "fixtures", "minimal.xmp")).read()


@pytest.fixture(scope="session")
def sample_raw(tmp_path_factory):
    """Sample RAW, from $DARKROOM_SAMPLE if set (CI cache), else downloaded and checked."""
    path = os.environ.get("DARKROOM_SAMPLE") or str(tmp_path_factory.mktemp("raw") / "sample.ARW")
    if not os.path.exists(path):
        try:
            urllib.request.urlretrieve(SAMPLE_URL, path)
        except OSError as e:
            pytest.skip(f"sample RAW unavailable: {e}")
    if hashlib.sha256(open(path, "rb").read()).hexdigest() != SAMPLE_SHA256:
        pytest.fail(f"sample RAW checksum mismatch: {path}")
    return path


@pytest.fixture(scope="session")
def darktable_cli():
    import render
    for c in render.CANDIDATES:
        if c and os.path.exists(c):
            return c
    pytest.skip("darktable-cli not found (set DARKTABLE_CLI)")


@pytest.fixture(scope="session")
def presets(tmp_path_factory, sample_raw, darktable_cli, minimal_xmp):
    """darktable's built-in presets, read from the data.db it writes into a throwaway config.
    Their blobs were written by darktable itself: the reference for layouts and a source of
    valid starting blobs. Returns preset(module, name=None) -> [(op_version, name, blob)]."""
    import sqlite3, subprocess
    import xmp
    d = tmp_path_factory.mktemp("dtpresets")
    side = d / "a.xmp"
    side.write_text(xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(0.7)))
    r = subprocess.run([darktable_cli, sample_raw, str(side), str(d / "o.jpg"), "--width", "100", "--height", "100",
                        "--core", "--configdir", str(d / "conf"), "--library", str(d / "library.db")],
                       capture_output=True)
    db = d / "conf" / "data.db"
    if not db.exists():
        pytest.fail(f"darktable wrote no data.db (exit {r.returncode})")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    def preset(module, name=None):
        rows = con.execute("select op_version, name, op_params from presets "
                           "where operation=? and op_params is not null order by name", (module,)).fetchall()
        rows = [(v, n.removeprefix("_builtin_"), bytes(b)) for v, n, b in rows
                if name is None or n.removeprefix("_builtin_") == name]
        return rows
    return preset
