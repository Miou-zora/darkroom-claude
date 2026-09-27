"""Integration tests on a real darktable-cli and a CC0 sample RAW.

Each test reproduces one pitfall of docs/pitfalls.md. If one fails, darktable changed
behaviour and the skills give wrong advice: fix the skill, not the test."""
import os, shutil, subprocess
import numpy as np
import pytest
from PIL import Image
import render, xmp

pytestmark = pytest.mark.darktable
SIZE = 400


@pytest.fixture
def rend(tmp_path, sample_raw, darktable_cli):
    """Render a sidecar text, return (result dict, pixel array)."""
    counter = iter(range(1000))

    def _render(sidecar_text, size=SIZE):
        i = next(counter)
        side = tmp_path / f"s{i}.xmp"; side.write_text(sidecar_text)
        out = str(tmp_path / f"r{i}.jpg")
        res = render.render(sample_raw, str(side), out, size)
        assert res["exit"] == 0 and res["written"], res
        return res, np.asarray(Image.open(out).convert("RGB")).astype(float)
    return _render


@pytest.fixture
def base(minimal_xmp):
    """One entry is needed: with an empty history darktable merges its auto presets."""
    return xmp.append(minimal_xmp, "exposure", 7, xmp.exposure_params(0.7))


def luma(a):
    return float((0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]).mean())


def test_baseline_loads_cleanly(rend, base):
    res, _ = rend(base)
    assert res["params_wrong"] == []
    assert "exposure" in res["modules_loaded"]
    assert "sigmoid" not in res["modules_loaded"], "auto presets were merged: fixture no longer deterministic"


@pytest.mark.pitfall("P7")
def test_render_is_deterministic(rend, base):
    _, a = rend(base)
    _, b = rend(base)
    assert np.abs(a - b).max() == 0


def test_exposure_acts(rend, base):
    _, a = rend(base)
    _, b = rend(xmp.append(base, "exposure", 7, xmp.exposure_params(1.7)))
    assert luma(b) > luma(a) * 1.15


@pytest.mark.pitfall("P4")
def test_exposure_field_order(rend, base):
    _, a = rend(base)
    # 0.5 in the `black` field must darken, 0.5 EV in `exposure` must brighten
    _, blk = rend(xmp.append(base, "exposure", 7, xmp.exposure_params(0.7, black=0.05)))
    _, ev = rend(xmp.append(base, "exposure", 7, xmp.exposure_params(1.2)))
    assert luma(blk) < luma(a) < luma(ev)


@pytest.mark.pitfall("P2")
def test_uppercase_hex_is_dropped_silently(rend, base):
    _, a = rend(base)
    x = xmp.append(base, "exposure", 7, xmp.exposure_params(2.0))
    lower = xmp.exposure_params(2.0).hex()
    upper = x.replace(f'darktable:params="{lower}"', f'darktable:params="{lower.upper()}"')
    assert upper != x
    res, b = rend(upper)
    assert "exposure" in res["params_wrong"]
    assert np.abs(a - b).max() == 0, "uppercase blob was applied: pitfall P2 no longer holds"


@pytest.mark.pitfall("P3")
def test_second_instance_needs_iop_order_list(rend, base, minimal_xmp):
    _, a = rend(base)
    two = xmp.append(base, "exposure", 7, xmp.exposure_params(1.5), multi_priority=1, multi_name="1")
    _, without = rend(two)
    assert np.abs(a - without).max() == 0, "second instance applied without iop_order_list"
    lst = open(os.path.join(os.path.dirname(__file__), "..", "tools", "iop_order_v4.txt")).read()
    lst = lst.replace("exposure,0", "exposure,0,exposure,1", 1)
    _, with_list = rend(xmp.with_iop_order_list(two, lst))
    assert luma(with_list) > luma(a) * 1.1


@pytest.mark.pitfall("P5")
def test_crop_edges_are_normalized(rend, base):
    res, full = rend(base, size=0)
    h, w = full.shape[:2]
    res, c = rend(xmp.append(base, "crop", 3, xmp.crop_params(0.25, 0.1, 0.75, 0.9)), size=0)
    ch, cw = c.shape[:2]
    assert abs(cw / w - 0.5) < 0.01 and abs(ch / h - 0.8) < 0.01


@pytest.mark.pitfall("P6")
def test_last_entry_wins(rend, base):
    x = xmp.append(base, "crop", 3, xmp.crop_params(0.0, 0.0, 0.5, 1.0))
    x = xmp.append(x, "crop", 3, xmp.crop_params(0.0, 0.0, 1.0, 0.5))
    _, c = rend(x, size=0)
    _, full = rend(base, size=0)
    assert abs(c.shape[1] / full.shape[1] - 1.0) < 0.01 and abs(c.shape[0] / full.shape[0] - 0.5) < 0.01


@pytest.mark.pitfall("P1")
def test_cli_never_overwrites(tmp_path, sample_raw, darktable_cli, base):
    side = tmp_path / "a.xmp"; side.write_text(base)
    out = tmp_path / "out.jpg"
    cmd = [darktable_cli, sample_raw, str(side), str(out), "--width", "200", "--height", "200",
           "--core", "--configdir", str(tmp_path / "conf"), "--library", ":memory:"]
    for _ in range(2):
        subprocess.run(cmd, capture_output=True, check=True)
    assert (tmp_path / "out_01.jpg").exists(), "darktable-cli now overwrites: render.py cleanup can go"
    # render.py removes the stale file first, so it never produces a suffixed copy
    render.render(sample_raw, str(side), str(out), 200)
    assert not (tmp_path / "out_02.jpg").exists()
