"""Integration tests on a real darktable-cli and a CC0 sample RAW.

Each test reproduces one pitfall of docs/pitfalls.md. If one fails, darktable changed
behaviour and the skills give wrong advice: fix the skill, not the test."""
import json, os, shutil, subprocess, sys, time
import numpy as np
import pytest
from PIL import Image
import dtenv, render, xmp

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
    cmd = [darktable_cli, sample_raw, str(side), dtenv.out_arg(out), "--width", "200", "--height", "200",
           "--core", "--configdir", str(tmp_path / "conf"), "--library", ":memory:"]
    for _ in range(2):
        subprocess.run(cmd, capture_output=True, check=True)
    assert (tmp_path / "out_01.jpg").exists(), "darktable-cli now overwrites: render.py cleanup can go"
    # render.py removes the stale file first, so it never produces a suffixed copy
    render.render(sample_raw, str(side), str(out), 200)
    assert not (tmp_path / "out_02.jpg").exists()


# Field confirmation (tools/modules.json): change one field of a default instance, check the
# render moves the expected way. The module must load, or darktable dropped the blob.

def chroma(a):
    return float((a.max(2) - a.min(2)).mean())


def luma_spread(a):
    return float((0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]).std())


def with_module(base, module, version, **fields):
    blob = xmp.default_params(module, version)
    for name, value in fields.items():
        blob = xmp.set_field(blob, module, version, name, value)
    return xmp.append(base, module, version, blob)


def render_module(rend, base, module, version, **fields):
    res, a = rend(with_module(base, module, version, **fields))
    assert res["params_wrong"] == [] and module in res["modules_loaded"], res
    return a


def test_colorbalancergb_saturation_global(rend, base):
    lo, mid, hi = (chroma(render_module(rend, base, "colorbalancergb", 5, saturation_global=v))
                   for v in (-0.5, 0.0, 0.5))
    assert lo < mid * 0.9 and hi > mid * 1.05


def test_colorbalancergb_vibrance(rend, base):
    mid = chroma(render_module(rend, base, "colorbalancergb", 5, vibrance=0.0))
    hi = chroma(render_module(rend, base, "colorbalancergb", 5, vibrance=0.8))
    assert hi > mid * 1.03


def test_colorbalancergb_contrast(rend, base):
    lo, mid, hi = (luma_spread(render_module(rend, base, "colorbalancergb", 5, contrast=v))
                   for v in (-0.5, 0.0, 0.5))
    assert lo < mid * 0.95 and hi > mid * 1.05


def test_sigmoid_contrast(rend, base):
    lo, hi = (luma_spread(render_module(rend, base, "sigmoid", 3, middle_grey_contrast=v))
              for v in (1.0, 2.5))
    assert hi > lo * 1.05


def test_sigmoid_skew(rend, base):
    neg, mid, pos = (luma(render_module(rend, base, "sigmoid", 3, contrast_skewness=v))
                     for v in (-0.5, 0.0, 0.5))
    assert neg < mid * 0.99 and pos > mid * 1.01


def hf_detail(a):
    """Mean absolute difference to a blurred copy: the small-scale contrast bilat acts on."""
    from PIL import ImageFilter
    im = Image.fromarray(a.mean(2).astype("uint8"))
    return float(np.abs(np.asarray(im).astype(float) - np.asarray(im.filter(ImageFilter.GaussianBlur(4)))).mean())


def test_bilat_detail(rend, base):
    """`midtone`, the next field, also changes small-scale contrast, and more at the low end
    (detail 0: 0.85 of the default render, midtone 0: 0.47; detail 1: 1.43, midtone 1: 1.07).
    The ratios tell the two apart, so a swapped offset fails here."""
    lo, mid, hi = (hf_detail(render_module(rend, base, "bilat", 3, detail=v)) for v in (0.0, 0.25, 1.0))
    assert 0.7 < lo / mid < 0.95 and hi / mid > 1.25, (lo / mid, hi / mid)


def percentiles(a):
    return np.percentile(0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2], [5, 10, 25, 50, 75, 95])


def test_toneequal_bands_follow_tonal_order(rend, base, presets):
    """Bands sit at -4 (shadows), -3 (midtones), -2 (highlights), -1 EV (whites). Raising one
    lifts the pixels around its EV first: the percentile that rises most moves up the tonal
    scale from midtones to highlights to whites. A layout off by one field would break the order."""
    _, _, blob = presets("toneequal", "compress shadows/highlights | EIGF | soft")[0]
    for name in ("noise", "ultra_deep_blacks", "deep_blacks", "blacks", "shadows", "midtones", "highlights",
                 "whites", "speculars", "contrast_boost", "exposure_boost"):
        blob = xmp.set_field(blob, "toneequal", 2, name, 0.0)

    def render_band(**fields):
        b = blob
        for k, v in fields.items():
            b = xmp.set_field(b, "toneequal", 2, k, v)
        res, a = rend(xmp.append(base, "toneequal", 2, b))
        assert res["params_wrong"] == [] and "toneequal" in res["modules_loaded"], res
        return percentiles(a)

    neutral = render_band()
    peak = {band: int(np.argmax(render_band(**{band: 1.0}) - neutral)) for band in ("midtones", "highlights", "whites")}
    assert peak["midtones"] < peak["highlights"] < peak["whites"], peak


PRESET_MODULES = ("exposure", "sigmoid", "colorbalancergb", "toneequal", "bilat", "colorequal", "channelmixerrgb")


@pytest.mark.parametrize("module", PRESET_MODULES)
def test_preset_blobs_match_layout(presets, module):
    """darktable's own presets are the reference: same version, same byte size as modules.json.
    If this fails after a darktable upgrade, the layout changed and the table is out of date."""
    layout = xmp.LAYOUTS[module]
    rows = [(v, n, b) for v, n, b in presets(module) if v == layout["version"]]
    assert rows, f"no {module} v{layout['version']} preset: the current version moved"
    assert [n for _, n, b in rows if len(b) != layout["size"]] == []


def test_preset_fields_hold_plausible_values(presets):
    """A field read at the wrong offset gives a denormal float or a huge int. Ranges are
    generous; they pin the offsets of fields no render test confirms."""
    def each(module):
        v = xmp.LAYOUTS[module]["version"]
        rows = [(n, lambda f, b=b: xmp.get_field(b, module, v, f)) for ver, n, b in presets(module) if ver == v]
        assert rows, module
        return rows
    for n, g in each("colorbalancergb"):
        assert g("grey_fulcrum") == pytest.approx(0.1845) and g("mask_grey_fulcrum") == pytest.approx(0.1845), n
        assert g("shadows_weight") == pytest.approx(1.0) and g("highlights_weight") == pytest.approx(1.0), n
        assert g("saturation_formula") in (0, 1), n
    for n, g in each("sigmoid"):
        assert g("display_white_target") == pytest.approx(100.0) and g("display_black_target") == pytest.approx(0.0152), n
        assert g("color_processing") in (0, 1) and g("base_primaries") in range(5), n
    for n, g in each("toneequal"):
        assert all(-4 <= g(b) <= 4 for b in ("noise", "blacks", "shadows", "midtones", "highlights", "speculars")), n
        assert 0 < g("smoothing") < 10 and 0 < g("feathering") <= 10000 and 1 <= g("iterations") <= 10, n
        assert g("details") in range(5), n
    for n, g in each("bilat"):
        assert g("mode") in (0, 1) and 0 <= g("detail") <= 2 and 0 <= g("midtone") <= 1, n
    for n, g in each("colorequal"):
        assert g("use_filter") in (0, 1) and 0 <= g("threshold") < 1, n
        colors = ("red", "orange", "yellow", "green", "cyan", "blue", "lavender", "magenta")
        assert all(0.1 < g(f"sat_{c}") < 5 and 0.1 < g(f"bright_{c}") < 5 and abs(g(f"hue_{c}")) < 180 for c in colors), n
    for n, g in each("channelmixerrgb"):
        assert g("version") == 2 and 0.2 < g("x") < 0.5 and 0.2 < g("y") < 0.5, n
        assert 1000 < g("temperature") < 25000 and g("illum_fluo") in range(10) and g("illum_led") in range(10), n


def test_subject_box_on_a_real_render(rend, base, tmp_path):
    """The sample is a landscape with no single subject: composite one of known position on the
    darktable render, then check subject.py finds it through real texture and JPEG noise."""
    import subject
    from PIL import ImageDraw
    res, a = rend(base, 800)
    h, w = a.shape[:2]
    truth = (int(w * .55), int(h * .45), int(w * .85), int(h * .85))
    im = Image.fromarray(a.astype("uint8")); ImageDraw.Draw(im).ellipse(truth, fill=(30, 60, 230))
    p = str(tmp_path / "subject.jpg"); im.save(p)
    box = subject.locate(p)["box"]
    # contains the subject, give or take a few px of blur, without swallowing the frame
    assert box[0] <= truth[0] + 8 and box[1] <= truth[1] + 8 and box[2] >= truth[2] - 8 and box[3] >= truth[3] - 8, box
    assert (box[2] - box[0]) * (box[3] - box[1]) < 1.5 * (truth[2] - truth[0]) * (truth[3] - truth[1]), box


# crop ratio_n / ratio_d. In an export pipeline darktable trims the crop to a multiple of the
# ratio on each side (modify_roi_out in src/iop/crop.c): the long side d goes with the long
# side of the crop, the short side n with the short one. 0/0 is freehand and trims nothing. The
# sign of ratio_d only flips the orientation shown in the GUI, which an export cannot observe.

def crop_dims(rend, base, edges, n=0, d=0):
    res, a = rend(xmp.append(base, "crop", 3, xmp.crop_params(*edges, ratio_n=n, ratio_d=d)), size=0)
    assert res["params_wrong"] == [] and "crop" in res["modules_loaded"], res
    return a.shape[1], a.shape[0]


def trimmed(w, h, n, d):
    aw, ah = (d, n) if w >= h else (n, d)
    return w - w % aw, h - h % ah


LANDSCAPE = (0.1, 0.1, 0.7, 0.5993)
PORTRAIT = (0.1, 0.1, 0.4, 0.9)


def test_crop_ratio_trims_to_the_ratio(rend, base):
    """One test for both fields (a parametrized id would not match the `test` of modules.json).
    Swapping n and d, or the landscape and portrait crops, trims the other side."""
    for edges, n, d in [(LANDSCAPE, 4, 5), (LANDSCAPE, 5, 4), (LANDSCAPE, 2, 3), (PORTRAIT, 4, 5), (PORTRAIT, 5, 4)]:
        w0, h0 = crop_dims(rend, base, edges)
        w, h = crop_dims(rend, base, edges, n, d)
        assert (w, h) == trimmed(w0, h0, n, d), (edges, n, d, (w0, h0), (w, h))
        assert (w, h) != (w0, h0), f"ratio {n}/{d} had no effect on {edges}: pick other edges"


def test_crop_ratio_sign_does_not_change_the_export(rend, base):
    assert crop_dims(rend, base, LANDSCAPE, 4, -5) == crop_dims(rend, base, LANDSCAPE, 4, 5)


def test_crop_aspect_gives_the_requested_aspect(rend, base):
    _, full = rend(base, size=0)
    h, w = full.shape[:2]
    top, bottom = 0.05, 0.95
    right = (bottom - top) * h * 0.8 / w
    cw, ch = crop_dims(rend, base, (0.0, top, right, bottom), 4, 5)
    assert cw % 4 == 0 and ch % 5 == 0 and abs(cw / ch - 0.8) < 0.002, (cw, ch)


@pytest.mark.skipif(sys.platform != "win32", reason="darktable.exe and tasklist: the Windows process check")
def test_hook_blocks_sidecar_write_while_real_darktable_exe_runs(tmp_path, darktable_cli):
    """#9: the PreToolUse hook against a real darktable.exe process, no mocked process list."""
    exe = os.path.join(os.path.dirname(darktable_cli), "darktable.exe")
    if not os.path.exists(exe):
        pytest.skip("darktable.exe not installed next to darktable-cli")
    hook = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks", "guard_darktable_open.py")
    payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "DSC1.ARW.xmp")}})

    def hook_rc():
        return subprocess.run([sys.executable, hook], input=payload, capture_output=True, text=True).returncode

    assert hook_rc() == 0, "no darktable.exe yet: the write must pass"
    p = subprocess.Popen([exe, "--configdir", str(tmp_path / "conf"), "--library", ":memory:"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if dtenv.darktable_running():
                break
            time.sleep(1)
        assert dtenv.darktable_running(), "darktable.exe never showed up in tasklist"
        assert hook_rc() == 2
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
