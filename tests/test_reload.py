"""tools/reload.py: unit tests with a fake darktable, then integration tests (marked darktable)
on four edit shapes, checked against dbsync.py --write and against a render from the sidecar.
Everything runs in a throwaway config dir (DARKTABLE_CONFIGDIR), never ~/.config/darktable."""
import hashlib, os, re, shutil, sqlite3, subprocess, sys
import numpy as np
import pytest
from PIL import Image
import dbsync, dtenv, reload, render, xmp
from test_dbsync import SCHEMA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRST_RUN = ["--conf", "lua/luarc/darktable_first_run_complete=TRUE"]


# ---- unit: no darktable needed -------------------------------------------------------------

@pytest.fixture
def fake(tmp_path, monkeypatch, minimal_xmp):
    """A library with image 10 = photos/A.ARW and image 11 = photos/B.ARW, and A's sidecar."""
    conf = tmp_path / "conf"; conf.mkdir()
    photos = tmp_path / "photos"; photos.mkdir()
    db = sqlite3.connect(conf / "library.db"); db.executescript(SCHEMA)
    db.execute("insert into film_rolls values (1, ?)", (str(photos),))
    db.execute("insert into images values (10, 1, 'A.ARW', 0, 0, -1)")
    db.execute("insert into images values (11, 1, 'B.ARW', 0, 0, -1)")
    db.commit(); db.close()
    for n in ("A.ARW", "B.ARW"):
        (photos / n).write_bytes(b"raw")
    side = photos / "A.ARW.xmp"
    side.write_text(xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(1.0)))
    monkeypatch.setenv("DARKTABLE_CONFIGDIR", str(conf))
    monkeypatch.setattr(dbsync, "darktable_running", lambda: False)
    calls = []
    monkeypatch.setattr(reload, "run_lua", lambda c, host, sc: calls.append(host) or (0, []))
    return dict(side=str(side), photos=photos, conf=conf, calls=calls)


def test_no_reload_ok_line_is_failure(fake, capsys):
    """A skipped --luacmd exits 0 and prints nothing: that must not read as success."""
    assert reload.main([fake["side"]]) == 1
    assert "no 'RELOAD ok'" in capsys.readouterr().out
    assert fake["calls"] == [str(fake["photos"] / "B.ARW")]  # default host is the other image


def test_not_in_library_is_failure(fake, monkeypatch, capsys):
    monkeypatch.setattr(reload, "run_lua", lambda c, h, sc: (0, [f"RELOAD NOT_IN_LIBRARY {sc[0]}"]))
    assert reload.main([fake["side"]]) == 1
    assert "no 'RELOAD ok'" in capsys.readouterr().out


def test_ok_line_but_db_differs_is_failure(fake, monkeypatch, capsys):
    """Lua says ok, the DB still lacks the history: the dbsync.plan() check must catch it."""
    monkeypatch.setattr(reload, "run_lua", lambda c, h, sc: (0, [f"RELOAD ok {sc[0]}"]))
    assert reload.main([fake["side"]]) == 1
    assert "differs from the sidecar" in capsys.readouterr().out


def test_refuses_while_darktable_runs(fake, monkeypatch, capsys):
    monkeypatch.setattr(dbsync, "darktable_running", lambda: True)
    assert reload.main([fake["side"]]) == 1
    assert fake["calls"] == [] and not list(fake["conf"].glob("library.db-darkroom-*"))


def test_refuses_locked_library(fake, capsys):
    (fake["conf"] / "library.db.lock").write_text(f"{os.getpid()}\0")  # a live pid, NUL terminated like darktable writes it
    assert reload.main([fake["side"]]) == 1
    assert fake["calls"] == []


def test_stale_lock_is_ignored(fake):
    (fake["conf"] / "library.db.lock").write_text("999999999\n")
    reload.main([fake["side"]])
    assert len(fake["calls"]) == 1


def test_backup_is_made_before_the_run(fake):
    reload.main([fake["side"]])
    assert len(list(fake["conf"].glob("library.db-darkroom-*"))) == 1


# ---- integration ---------------------------------------------------------------------------

def dt(conf, raw, out, size=8, sidecars="never", from_db=False):
    """One darktable-cli run on the library of conf. from_db: history read from the library."""
    if os.path.exists(out):
        os.remove(out)
    lib = os.path.join(conf, "library.db")
    cmd = [render.cli(), raw, dtenv.out_arg(out), "--hq", "true", "--upscale", "false", "--apply-custom-presets", "false",
           "--width", str(size), "--height", str(size)]
    if from_db:
        cmd += ["--library", lib]  # CLI option, so before --core
    cmd += ["--core", "--configdir", conf, "--library", lib, "--conf", f"write_sidecar_files={sidecars}", *FIRST_RUN]
    return subprocess.run(cmd, capture_output=True, text=True)


def dump(conf, imgid):
    """History rows (blobs as short sha1), history_end and module_order of one image."""
    db = sqlite3.connect(os.path.join(conf, "library.db"))
    db.create_function("sha", 1, lambda b: hashlib.sha1(b or b"").hexdigest()[:8])
    q = lambda s: db.execute(s, (imgid,)).fetchall()
    return dict(
        history=q("select num, module, operation, sha(op_params), enabled, sha(blendop_params), blendop_version, "
                  "multi_priority, multi_name, multi_name_hand_edited from history where imgid=? order by num"),
        history_end=q("select history_end from images where id=?"),
        module_order=q("select version, iop_list from module_order where imgid=?"))


def li_block(x, num):
    return re.search(rf'<rdf:li\b[^>]*darktable:num="{num}"[^>]*/>', x, re.S).group(0)


SCENARIOS = {
    "append": lambda x: xmp.append(xmp.append(x, "exposure", 7, xmp.exposure_params(1.7)),
                                   "crop", 3, xmp.crop_params(0.1, 0.1, 0.9, 0.9)),
    # an existing entry edited in place (what a hand edit of a sidecar often looks like)
    "inplace": lambda x: x.replace(li_block(x, 8), re.sub(r'darktable:params="[^"]*"',
                                   f'darktable:params="{xmp.exposure_params(2.0).hex()}"', li_block(x, 8))),
    # pitfall P3: a second exposure instance only exists with an explicit iop_order_list
    "multi": lambda x: xmp.with_iop_order_list(
        xmp.append(x, "exposure", 7, xmp.exposure_params(1.5), multi_priority=1, multi_name="1"),
        open(os.path.join(ROOT, "tools", "iop_order_v4.txt")).read().strip().replace("exposure,0", "exposure,0,exposure,1", 1)),
    # sidecar shorter than the DB history: last entry dropped
    "shorter": lambda x: re.sub(r'darktable:history_end="\d+"', 'darktable:history_end="10"',
                                x.replace(li_block(x, 10), "")),
}


@pytest.fixture(scope="module")
def world(tmp_path_factory, sample_raw, darktable_cli):
    """A library where darktable itself imported A (sidecar written at import) and a host image B."""
    w = tmp_path_factory.mktemp("reload")
    raw, host = str(w / "photos" / "A.ARW"), str(w / "host" / "B.ARW")
    for p in (raw, host):
        os.makedirs(os.path.dirname(p)); shutil.copy(sample_raw, p)
    conf = str(w / "conf0"); os.makedirs(conf)
    for p in (raw, host):  # A first: it must get image id 1
        r = dt(conf, p, str(w / "o.jpg"), sidecars="on import")
        assert os.path.exists(str(w / "o.jpg")), r.stdout + r.stderr
    side = raw + ".xmp"
    assert os.path.exists(side)
    ids = sqlite3.connect(os.path.join(conf, "library.db")).execute("select id, filename from images").fetchall()
    assert ids == [(1, "A.ARW"), (2, "B.ARW")], ids
    return dict(w=w, raw=raw, host=host, side=side, conf0=conf, base=open(side).read())


def pixels(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(float)


def library_render(world, conf, name):
    """Render A from the library alone: the sidecar is moved away so only the DB can drive it."""
    out = str(world["w"] / f"{name}.jpg")
    os.rename(world["side"], world["side"] + ".hidden")
    try:
        dt(conf, world["raw"], out, size=400, from_db=True)
    finally:
        os.rename(world["side"] + ".hidden", world["side"])
    return pixels(out)


@pytest.mark.darktable
@pytest.mark.parametrize("scenario", list(SCENARIOS))
def test_reload_matches_sidecar_and_dbsync(world, scenario, monkeypatch):
    w = world
    edited = SCENARIOS[scenario](w["base"])
    open(w["side"], "w").write(edited)
    ref_out = str(w["w"] / f"{scenario}-ref.jpg")
    assert render.render(w["raw"], w["side"], ref_out, 400)["written"]
    confs = {v: str(w["w"] / f"{scenario}-{v}") for v in ("lua", "dbsync")}
    for c in confs.values():
        shutil.copytree(w["conf0"], c)
    monkeypatch.setattr(dbsync, "darktable_running", lambda: False)  # isolated config: a GUI elsewhere is no risk

    monkeypatch.setenv("DARKTABLE_CONFIGDIR", confs["lua"])
    assert reload.main([w["side"]]) == 0  # default host: image B
    monkeypatch.setenv("DARKTABLE_CONFIGDIR", confs["dbsync"])
    monkeypatch.setattr(sys, "argv", ["dbsync.py", w["side"], "--write", "--accept-divergent", "--allow-delete"])
    assert dbsync.main() == 0

    lua, ds = dump(confs["lua"], 1), dump(confs["dbsync"], 1)
    assert len(lua["history"]) == len(xmp.entries(edited))
    assert lua["history_end"] == [(xmp.history_end(edited),)]
    assert lua["history"] == ds["history"]
    assert lua["history_end"] == ds["history_end"]
    assert lua["module_order"] == ds["module_order"]
    if scenario == "multi":
        assert "exposure,1" in lua["module_order"][0][1]
    diff = np.abs(library_render(w, confs["lua"], f"{scenario}-lua") - pixels(ref_out)).max()
    assert diff == 0, f"render from the reloaded library differs from the sidecar render: {diff}"


@pytest.mark.darktable
def test_untouched_library_renders_differently(world, monkeypatch):
    """Calibration of the test above: without reload the library render must not match the sidecar."""
    w = world
    open(w["side"], "w").write(SCENARIOS["append"](w["base"]))
    ref_out = str(w["w"] / "control-ref.jpg")
    render.render(w["raw"], w["side"], ref_out, 400)
    c = str(w["w"] / "control"); shutil.copytree(w["conf0"], c)
    assert np.abs(library_render(w, c, "control") - pixels(ref_out)).max() > 0


@pytest.mark.darktable
def test_sidecar_not_in_library_fails(world, monkeypatch, capsys):
    """Sidecar of an image the library does not know: Lua prints NOT_IN_LIBRARY, the tool fails."""
    c = str(world["w"] / "notin"); shutil.copytree(world["conf0"], c)
    stray = world["w"] / "nowhere" / "Z.ARW.xmp"; stray.parent.mkdir(exist_ok=True)
    stray.write_text(world["base"])
    monkeypatch.setattr(dbsync, "darktable_running", lambda: False)
    monkeypatch.setenv("DARKTABLE_CONFIGDIR", c)
    assert reload.main([str(stray)]) == 1
    assert "NOT_IN_LIBRARY" in capsys.readouterr().out
