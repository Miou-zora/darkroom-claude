"""apply_style against a throwaway data.db with the styles / style_items schema of darktable 5.6.
Never touches the user's data.db or sidecars: everything lives in tmp_path."""
import os, re, shutil, sqlite3, sys, zlib
import numpy as np
import pytest
from PIL import Image
import apply_style, render, xmp

SCHEMA = """
create table styles (id integer primary key, name varchar, description varchar, iop_list varchar);
create table style_items (styleid integer, num integer, module integer, operation varchar(256),
                          op_params blob, enabled integer, blendop_params blob, blendop_version integer,
                          multi_priority integer, multi_name varchar(256), multi_name_hand_edited integer);
"""
NEUTRAL = xmp.decode_blob(xmp.NEUTRAL_BLEND)
MASKED = bytes(range(256)) + bytes(range(164))  # stands for a 420 byte blend blob with a parametric mask


def blob(module, version, **fields):
    b = xmp.default_params(module, version)
    for k, v in fields.items():
        b = xmp.set_field(b, module, version, k, v)
    return b


def make_db(path, items, name="Macro", iop_list=None):
    """items: (operation, version, params, enabled, blend, blend_version, multi_priority, multi_name)"""
    db = sqlite3.connect(path); db.executescript(SCHEMA)
    db.execute("insert into styles values (1, ?, '', ?)", (name, iop_list))
    for n, (op, v, p, en, bl, bv, mp, mn) in enumerate(items):
        db.execute("insert into style_items values (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)", (n, v, op, p, en, bl, bv, mp, mn))
    db.commit(); db.close()
    return str(path)


SIGMOID = blob("sigmoid", 3, middle_grey_contrast=2.5)
CBRGB0 = blob("colorbalancergb", 5, saturation_global=0.5)
CBRGB1 = blob("colorbalancergb", 5, contrast=0.5)
ITEMS = [("rawprepare", 1, b"\x00" * 4, 1, NEUTRAL, 14, 0, ""),
         ("temperature", 3, b"\x01" * 4, 1, NEUTRAL, 14, 0, ""),
         ("exposure", 7, xmp.exposure_params(1.0), 1, NEUTRAL, 14, 0, ""),
         ("sigmoid", 3, SIGMOID, 1, MASKED, 13, 0, "tone"),
         ("colorbalancergb", 5, CBRGB0, 1, NEUTRAL, 14, 0, ""),
         ("colorbalancergb", 5, CBRGB1, 1, MASKED, 14, 1, "second")]


@pytest.fixture
def style_db(tmp_path):
    return make_db(tmp_path / "data.db", ITEMS)


@pytest.fixture
def base(minimal_xmp):
    return xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(0.7))


def kept(db, exclude=apply_style.DEFAULT_EXCLUDE):
    return [i for i in apply_style.load_style(db, "Macro") if i["op"] not in exclude]


def test_copies_modules_and_blend_params(style_db, base):
    x = apply_style.add(base, kept(style_db))
    new = xmp.entries(x)[1:]
    assert [(e["operation"], e["multi_priority"], e["multi_name"]) for e in new] == [
        ("sigmoid", "0", "tone"), ("colorbalancergb", "0", ""), ("colorbalancergb", "1", "second")]
    assert [xmp.decode_blob(e["params"]) for e in new] == [SIGMOID, CBRGB0, CBRGB1]
    assert [xmp.decode_blob(e["blendop_params"]) for e in new] == [MASKED, NEUTRAL, MASKED]
    assert [e["blendop_version"] for e in new] == ["13", "14", "14"]
    assert [e["modversion"] for e in new] == ["3", "5", "5"]
    assert xmp.history_end(x) == 4


def test_image_specific_modules_excluded_by_default(style_db):
    assert [i["op"] for i in kept(style_db)] == ["sigmoid", "colorbalancergb", "colorbalancergb"]
    assert [i["op"] for i in kept(style_db, exclude=())] == [i[0] for i in ITEMS]
    assert [i["op"] for i in kept(style_db, exclude=("sigmoid",))][:2] == ["rawprepare", "temperature"]


def test_exposure_is_appended_last(style_db, base):
    x = apply_style.add(base, kept(style_db), ev=1.7)
    last = xmp.entries(x)[-1]
    assert last["operation"] == "exposure" and xmp.decode_blob(last["params"]) == xmp.exposure_params(1.7)


@pytest.mark.pitfall("P3")
def test_second_instance_adds_iop_order_list(style_db, base):
    x = apply_style.add(base, kept(style_db))
    lst = re.search(r'darktable:iop_order_list="([^"]*)"', x).group(1)
    assert "colorbalancergb,0,colorbalancergb,1," in lst
    assert lst == apply_style.IOP_V4  # the bundled list already names this instance: nothing to add


def test_instance_missing_from_the_list_is_inserted_after_the_first(tmp_path, base):
    items = apply_style.load_style(make_db(tmp_path / "d.db", [
        ("sigmoid", 3, SIGMOID, 1, NEUTRAL, 14, 0, ""), ("sigmoid", 3, SIGMOID, 1, NEUTRAL, 14, 1, "")]), "Macro")
    lst = re.search(r'darktable:iop_order_list="([^"]*)"', apply_style.add(base, items)).group(1)
    assert "sigmoid,0,sigmoid,1," in lst and lst.replace(",sigmoid,1", "", 1) == apply_style.IOP_V4


def test_no_second_instance_leaves_the_list_alone(style_db, base):
    x = apply_style.add(base, [i for i in kept(style_db) if i["multi_priority"] == 0])
    assert "iop_order_list" not in x


def test_existing_list_is_extended_not_replaced(style_db, base):
    mine = apply_style.IOP_V4.replace("sigmoid,0", "sigmoid,0,sigmoid,1", 1)
    x = apply_style.add(xmp.with_iop_order_list(base, mine), kept(style_db))
    lst = re.search(r'darktable:iop_order_list="([^"]*)"', x).group(1)
    assert "sigmoid,0,sigmoid,1" in lst and "colorbalancergb,0,colorbalancergb,1" in lst


def test_second_instance_without_any_list_to_extend(style_db, base):
    with pytest.raises(ValueError, match="iop_order_version 4"):
        apply_style.add(base.replace('iop_order_version="4"', 'iop_order_version="3"'), kept(style_db))


def test_unknown_or_ambiguous_style(style_db):
    with pytest.raises(ValueError, match="0 matches"):
        apply_style.load_style(style_db, "Nope")
    db = sqlite3.connect(style_db); db.execute("insert into styles values (2, 'Macro', '', null)"); db.commit()
    with pytest.raises(ValueError, match="2 matches"):
        apply_style.load_style(style_db, "Macro")


def test_style_db_is_opened_read_only(style_db):
    before = open(style_db, "rb").read()
    apply_style.load_style(style_db, "Macro")
    assert open(style_db, "rb").read() == before


# The proof, with a fake renderer: brightness = sum over active entries of a per-module weight,
# except modules in DEAD, which darktable would accept and then ignore.

DEAD = set()


def fake_render(raw, side, out, size=600, height=None):
    x = open(side).read()
    last = {}
    for e in xmp.entries(x):
        last[(e["operation"], e["multi_priority"])] = e
    inst1_ok = "iop_order_list" in x
    v = 10
    for (op, mp), e in last.items():
        if op in DEAD or (mp != "0" and not inst1_ok) or e["enabled"] != "1":
            continue
        v += len(op) * 3 + int(mp) * 5 + zlib.crc32(e["params"].encode()) % 97
    Image.fromarray(np.full((8, 8, 3), v % 250, np.uint8)).save(out, format="PNG")
    return dict(exit=0, modules_loaded=[], params_wrong=[], written=True)


@pytest.fixture
def faked(monkeypatch):
    DEAD.clear()
    monkeypatch.setattr(render, "render", fake_render)
    monkeypatch.setattr(apply_style, "darktable_running", lambda: False)


def test_prove_passes_when_every_module_acts(faked, style_db, base):
    assert apply_style.prove("raw.ARW", base, kept(style_db), 1.7) == []


def test_zero_diff_is_an_error(faked, style_db, base):
    DEAD.add("sigmoid")
    errors = apply_style.prove("raw.ARW", base, kept(style_db), None)
    assert len(errors) == 1 and "sigmoid" in errors[0] and "zero pixel difference" in errors[0]


def test_ignored_second_instance_is_an_error(faked, style_db, base, monkeypatch):
    monkeypatch.setattr(apply_style, "with_instances", lambda x, items: x)
    errors = apply_style.prove("raw.ARW", base, kept(style_db), None)
    assert len(errors) == 1 and "colorbalancergb (instance 1)" in errors[0]


def test_disabled_item_is_copied_but_not_required_to_act(faked, tmp_path, base):
    items = ITEMS[3:4] + [("bilat", 3, blob("bilat", 3), 0, NEUTRAL, 14, 0, "")]
    items = apply_style.load_style(make_db(tmp_path / "d.db", items), "Macro")
    assert apply_style.prove("raw.ARW", base, items, None) == []
    assert xmp.entries(apply_style.add(base, items))[-1]["enabled"] == "0"


@pytest.fixture
def photo(tmp_path, base):
    raw = tmp_path / "A.ARW"; raw.write_bytes(b"raw")
    side = tmp_path / "A.ARW.xmp"; side.write_text(base)
    return str(side)


def run(monkeypatch, style_db, *args):
    monkeypatch.setattr(sys, "argv", ["apply_style.py", "Macro", *args, "--data-db", style_db])
    return apply_style.main()


def test_dry_run_writes_nothing(faked, style_db, photo, monkeypatch):
    before = open(photo).read()
    assert run(monkeypatch, style_db, photo) == 0
    assert open(photo).read() == before


def test_write_backs_up_and_appends(faked, style_db, photo, monkeypatch, tmp_path):
    before = open(photo).read()
    assert run(monkeypatch, style_db, photo, "--write", "--exposure", "1.2") == 0
    backups = [p for p in os.listdir(tmp_path) if p.startswith("A.ARW.xmp-darkroom-")]
    assert len(backups) == 1 and open(tmp_path / backups[0]).read() == before
    ops = [e["operation"] for e in xmp.entries(open(photo).read())]
    assert ops == ["exposure", "sigmoid", "colorbalancergb", "colorbalancergb", "exposure"]


def test_zero_diff_blocks_the_write_and_fails(faked, style_db, photo, monkeypatch, capsys):
    DEAD.add("colorbalancergb")
    before = open(photo).read()
    assert run(monkeypatch, style_db, photo, "--write") == 1
    assert open(photo).read() == before
    assert "zero pixel difference" in capsys.readouterr().out


def test_missing_raw_is_an_error_unless_no_verify(faked, style_db, photo, monkeypatch, tmp_path):
    os.remove(tmp_path / "A.ARW")
    assert run(monkeypatch, style_db, photo) == 1
    assert run(monkeypatch, style_db, photo, "--no-verify") == 0


def test_write_refused_while_darktable_runs(faked, style_db, photo, monkeypatch):
    monkeypatch.setattr(apply_style, "darktable_running", lambda: True)
    before = open(photo).read()
    assert run(monkeypatch, style_db, photo, "--write") == 1
    assert open(photo).read() == before


# Integration: real darktable-cli.

@pytest.fixture
def real_photo(tmp_path, sample_raw, darktable_cli, base, monkeypatch):
    monkeypatch.setattr(apply_style, "darktable_running", lambda: False)  # only tmp_path is written
    raw = tmp_path / "A.ARW"; shutil.copy(sample_raw, raw)  # a symlink is not a file darktable-cli can open on Windows
    side = tmp_path / "A.ARW.xmp"; side.write_text(base)
    return str(side)


@pytest.mark.darktable
@pytest.mark.pitfall("P3")
def test_style_with_second_instance_renders_both(real_photo, style_db, monkeypatch):
    """The sidecar written by apply_style carries the iop_order_list, and darktable applies
    instance 1: proven by render, for every module of the style."""
    assert run(monkeypatch, style_db, real_photo, "--write", "--size", "300") == 0
    x = open(real_photo).read()
    assert "colorbalancergb,0,colorbalancergb,1," in x
    assert apply_style.prove(os.path.splitext(real_photo)[0], x, [], None, 300) == []  # sidecar still renders


@pytest.mark.darktable
def test_zero_diff_on_a_real_render_is_an_error(real_photo, style_db, monkeypatch, capsys):
    """Without the iop_order_list darktable ignores instance 1 with exit code 0: the proof must see it."""
    monkeypatch.setattr(apply_style, "with_instances", lambda x, items: x)
    before = open(real_photo).read()
    assert run(monkeypatch, style_db, real_photo, "--write", "--size", "300") == 1
    assert open(real_photo).read() == before
    out = capsys.readouterr().out
    assert "colorbalancergb (instance 1)" in out and "zero pixel difference" in out
