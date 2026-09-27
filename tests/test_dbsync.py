"""dbsync against a throwaway library.db with the columns darktable 5.6 uses.
Never touches the user's database: DARKTABLE_CONFIGDIR points to tmp_path."""
import os, sqlite3, sys
import pytest
import dbsync, xmp

SCHEMA = """
create table film_rolls (id integer primary key, folder varchar);
create table images (id integer primary key, film_id integer, filename varchar, version integer,
                     history_end integer, change_timestamp integer);
create table history (imgid integer, num integer, module integer, operation varchar(256),
                      op_params blob, enabled integer, blendop_params blob, blendop_version integer,
                      multi_priority integer, multi_name varchar(256), multi_name_hand_edited integer);
create table module_order (imgid integer primary key, version integer, iop_list varchar);
create table history_hash (imgid integer primary key, basic_hash blob, auto_hash blob, current_hash blob);
"""


@pytest.fixture
def lib(tmp_path, monkeypatch, minimal_xmp):
    conf = tmp_path / "conf"; conf.mkdir()
    photos = tmp_path / "photos"; photos.mkdir()
    db = sqlite3.connect(conf / "library.db"); db.executescript(SCHEMA)
    db.execute("insert into film_rolls values (1, ?)", (str(photos),))
    db.execute("insert into images values (10, 1, 'A.ARW', 0, 0, -1)")
    db.execute("insert into images values (11, 1, 'A.ARW', 1, 0, -1)")
    db.execute("insert into history_hash (imgid) values (10)")
    db.commit(); db.close()
    (photos / "A.ARW").write_bytes(b"raw")
    monkeypatch.setenv("DARKTABLE_CONFIGDIR", str(conf))
    monkeypatch.setattr(dbsync, "darktable_running", lambda: False)
    x = xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(1.0))
    x = xmp.append(x, "crop", 3, xmp.crop_params(0.1, 0.1, 0.9, 0.9))
    side = photos / "A.ARW.xmp"; side.write_text(x)
    return dict(conf=conf, photos=photos, side=str(side), db=conf / "library.db")


def run(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["dbsync.py", *args])
    return dbsync.main()


def rows(lib, imgid=10):
    db = sqlite3.connect(lib["db"])
    return db.execute("select num, operation from history where imgid=? order by num", (imgid,)).fetchall()


def test_locate_version_suffix(lib):
    db = sqlite3.connect(lib["db"])
    assert dbsync.locate(db, lib["side"])[0] == 10
    dup = os.path.join(lib["photos"], "A_01.ARW.xmp")
    open(dup, "w").write(open(lib["side"]).read())
    assert dbsync.locate(db, dup)[0] == 11


def test_dry_run_writes_nothing(lib, monkeypatch):
    before = open(lib["db"], "rb").read()
    assert run(monkeypatch, lib["side"]) == 0
    assert open(lib["db"], "rb").read() == before


def test_write_inserts_and_backs_up(lib, monkeypatch, capsys):
    assert run(monkeypatch, lib["side"], "--write") == 0
    assert rows(lib) == [(0, "exposure"), (1, "crop")]
    db = sqlite3.connect(lib["db"])
    assert db.execute("select history_end from images where id=10").fetchone()[0] == 2
    assert db.execute("select count(*) from history_hash where imgid=10").fetchone()[0] == 0
    assert db.execute("select change_timestamp from images where id=10").fetchone()[0] > 6e16
    assert any(f.startswith("library.db-darkroom-") for f in os.listdir(lib["conf"]))
    assert "integrity_check: ok" in capsys.readouterr().out


def test_second_run_is_aligned(lib, monkeypatch, capsys):
    run(monkeypatch, lib["side"], "--write"); capsys.readouterr()
    run(monkeypatch, lib["side"])
    assert "insert [none]; delete none; divergent none" in capsys.readouterr().out


def test_refuses_divergent_rows_unless_accepted(lib, monkeypatch):
    run(monkeypatch, lib["side"], "--write")
    db = sqlite3.connect(lib["db"])
    db.execute("update history set op_params=? where imgid=10 and num=0", (xmp.exposure_params(0.3),))
    db.commit(); db.close()
    assert run(monkeypatch, lib["side"], "--write") == 1
    assert run(monkeypatch, lib["side"], "--write", "--accept-divergent") == 0
    db = sqlite3.connect(lib["db"])
    assert db.execute("select op_params from history where imgid=10 and num=0").fetchone()[0] == xmp.exposure_params(1.0)


def test_refuses_deletions_unless_allowed(lib, monkeypatch, minimal_xmp):
    run(monkeypatch, lib["side"], "--write")
    shorter = xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(1.0))
    open(lib["side"], "w").write(shorter)
    assert run(monkeypatch, lib["side"], "--write") == 1
    assert run(monkeypatch, lib["side"], "--write", "--allow-delete") == 0
    assert rows(lib) == [(0, "exposure")]


def test_refuses_when_darktable_runs(lib, monkeypatch):
    monkeypatch.setattr(dbsync, "darktable_running", lambda: True)
    assert run(monkeypatch, lib["side"], "--write") == 1
    assert rows(lib) == []


def test_refuses_unknown_image_and_writes_nothing(lib, monkeypatch, tmp_path):
    other = tmp_path / "photos" / "B.ARW.xmp"; other.write_text(open(lib["side"]).read())
    assert run(monkeypatch, lib["side"], str(other), "--write") == 1
    assert rows(lib) == []


def test_writes_module_order_when_sidecar_has_list(lib, monkeypatch):
    x = xmp.with_iop_order_list(open(lib["side"]).read(), "exposure,0,crop,0")
    open(lib["side"], "w").write(x)
    run(monkeypatch, lib["side"], "--write")
    db = sqlite3.connect(lib["db"])
    assert db.execute("select version, iop_list from module_order where imgid=10").fetchone() == (4, "exposure,0,crop,0")
