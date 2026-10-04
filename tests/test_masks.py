"""Drawn masks: the `mask_points` layouts of tools/modules.json (`_masks`), checked against blobs
darktable wrote itself and against renders.

A mask in the wrong place is silent, so every geometry claim is a render: exposure +2 EV through
a drawn mask on the CC0 sample, minus the same render with the module off, and the changed region
is measured (bounding box, centroid, orientation). Positions are fractions of the image."""
import os, re, json, shutil, sqlite3, struct, subprocess, base64
import numpy as np
import pytest
from PIL import Image
import dtenv, render, xmp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = xmp.LAYOUTS["_masks"]
SHAPES = [k for k in M if not k.startswith("_") and k != "version"]
GID = 1001   # formid of the group the exposure points at
SIZE = 400
EV = 2.0


# --- helpers: pack by field name from modules.json, build masks_history, blend params ----------

def pack(shape, **fields):
    """One point of `shape` from named fields (missing ones are 0)."""
    L = M[shape]["fields"]
    bad = set(fields) - {f["name"] for f in L}
    assert not bad, f"{shape} has no field {bad}"
    return struct.pack("<" + "".join(f["type"] for f in L),
                       *[(int(fields.get(f["name"], 0)) if f["type"] == "i" else float(fields.get(f["name"], 0.0))) for f in L])


def unpack(shape, blob):
    L = M[shape]["fields"]; n = M[shape]["size"]
    assert len(blob) % n == 0, (shape, len(blob), n)
    fmt = "<" + "".join(f["type"] for f in L)
    return [dict(zip([f["name"] for f in L], struct.unpack_from(fmt, blob, i))) for i in range(0, len(blob), n)]


def form(fid, shape, points, name=None, num=0, version=None, src=bytes(8), nb=None, mask_type=None, enc=bytes.hex):
    """One `masks_history` <rdf:li>. `points` is a list of packed points (or raw bytes)."""
    blob = points if isinstance(points, bytes) else b"".join(points)
    nb = len(points) if nb is None and not isinstance(points, bytes) else nb
    return (f'\n     <rdf:li\n      darktable:mask_num="{num}"\n      darktable:mask_id="{fid}"\n'
            f'      darktable:mask_type="{mask_type if mask_type is not None else M[shape]["form"]}"\n'
            f'      darktable:mask_name="{name or shape + " #1"}"\n'
            f'      darktable:mask_version="{version if version is not None else M["version"]}"\n'
            f'      darktable:mask_points="{enc(blob)}"\n      darktable:mask_nb="{nb}"\n'
            f'      darktable:mask_src="{src.hex()}"/>')


def group(members, gid=GID, num=0, version=None):
    """members: (formid, state, opacity) tuples. First member 3 (use + show), then 3 + operator."""
    return form(gid, "group", [pack("group", formid=f, parentid=gid, state=s, opacity=o) for f, s, o in members],
                name="grp exposure", num=num, version=version)


def blend_params(mask_id, mask_mode=3, cst=4):
    """blendop v14 (420 B) of a neutral entry with a drawn mask: mask_mode at byte 0 (3 = enabled
    + drawn), blend_cst at byte 4 (4 = scene-referred RGB, what exposure blends in), mask_id at
    byte 24. Everything else is darktable's own neutral blob."""
    b = bytearray(xmp.decode_blob(xmp.NEUTRAL_BLEND))
    struct.pack_into("<I", b, 0, mask_mode)
    struct.pack_into("<I", b, 4, cst)
    struct.pack_into("<I", b, 24, mask_id)
    return bytes(b)


def with_masks(x, forms):
    block = "<darktable:masks_history>\n    <rdf:Seq>" + "".join(forms) + "\n    </rdf:Seq>\n   </darktable:masks_history>\n   "
    return x.replace("<darktable:history>", block + "<darktable:history>", 1)


def masked(minimal_xmp, forms, members=None, ev=EV, mask_mode=3, gid=GID, enabled=1, group_version=None):
    """Exposure `ev` through the group `gid`. By default the group holds the first form only."""
    if members is None:
        members = [(int(re.search(r'mask_id="(\d+)"', forms[0]).group(1)), 3, 1.0)]
    x = with_masks(minimal_xmp, list(forms) + ([group(members, gid, version=group_version)] if members else []))
    return xmp.append(x, "exposure", 7, xmp.exposure_params(ev), enabled=enabled, blendop=blend_params(gid, mask_mode).hex())


# --- measuring ---------------------------------------------------------------------------------

def region(a, base, thr=3):
    """Where the render moved: bbox, weighted centroid, principal axis angle (degrees, y down,
    so a positive angle leans clockwise on screen), share of pixels, all as image fractions."""
    d = np.abs(a - base).max(2)
    ys, xs = np.nonzero(d > thr)
    assert len(xs), "the mask changed nothing"
    H, W = d.shape; w = d[d > thr]
    cov = np.cov(np.vstack([xs, ys]), aweights=w)
    _, vec = np.linalg.eigh(cov)
    ang = float(np.degrees(np.arctan2(vec[1, 1], vec[0, 1])) % 180)
    return dict(x0=xs.min() / W, x1=xs.max() / W, y0=ys.min() / H, y1=ys.max() / H,
                cx=(xs * w).sum() / w.sum() / W, cy=(ys * w).sum() / w.sum() / H,
                angle=ang, share=len(xs) / d.size, mean=float(d.mean()), H=H, W=W)


def changed(a, base, thr=3):
    return int((np.abs(a - base).max(2) > thr).sum())


# --- fixtures ----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mrend(tmp_path_factory, sample_raw, darktable_cli):
    d = tmp_path_factory.mktemp("masks")
    counter = iter(range(10000))

    def _render(sidecar_text, size=SIZE, ok=True):
        i = next(counter)
        side = d / f"s{i}.xmp"; side.write_text(sidecar_text)
        out = str(d / f"r{i}.jpg")
        res = render.render(sample_raw, str(side), out, size)
        if not ok:
            return res, None
        assert res["exit"] == 0 and res["written"] and res["params_wrong"] == [], res
        return res, np.asarray(Image.open(out).convert("RGB")).astype(float)
    return _render


@pytest.fixture(scope="module")
def mx(minimal_xmp):
    return minimal_xmp


@pytest.fixture(scope="module")
def base(mrend, mx):
    """Same exposure entry, module off: what the image is where the mask does not act."""
    return mrend(xmp.append(mx, "exposure", 7, xmp.exposure_params(EV), enabled=0))[1]


@pytest.fixture(scope="module")
def everywhere(mrend, mx):
    """Exposure through no mask at all."""
    return mrend(xmp.append(mx, "exposure", 7, xmp.exposure_params(EV)))[1]


@pytest.fixture
def shot(mrend, mx, base):
    """shot(shape, points, **kw) -> region of the render that `masked` moved."""
    def _shot(shape, points, **kw):
        _, a = mrend(masked(mx, [form(555, shape, points)], **kw))
        return region(a, base), a
    return _shot


def close(v, want, tol=0.02):
    assert v == pytest.approx(want, abs=tol), (v, want)


# --- layout checks that need no darktable ------------------------------------------------------

def test_sizes_match_fields():
    assert SHAPES == ["ellipse", "circle", "path", "brush", "gradient", "group"]
    for s in SHAPES:
        assert M[s]["size"] == 4 * len(M[s]["fields"]) == struct.calcsize("<" + "".join(f["type"] for f in M[s]["fields"])), s


def authored():
    return json.load(open(os.path.join(ROOT, "tests", "fixtures", "darktable-authored-masks.json")))["forms"]


def base_shape(mask_type):
    """mask_type flags to shape name, ignoring CLONE (8) and NON_CLONE (128)."""
    t = int(mask_type) & ~(8 | 128)
    return {M[s]["form"]: s for s in SHAPES}[t]


def test_darktable_authored_blobs_follow_the_layout():
    """Blobs darktable wrote (its benchmark sidecar): nb * size bytes, and unpack then pack gives
    the same bytes, so no field is missing, reordered or retyped."""
    forms = authored()
    # the benchmark sidecar has no gradient: that layout rests on renders and the round trip below
    assert {base_shape(f["mask_type"]) for f in forms} == set(SHAPES) - {"gradient"}
    for f in forms:
        s = base_shape(f["mask_type"]); blob = xmp.decode_blob(f["mask_points"])
        assert int(f["mask_version"]) == M["version"]
        assert len(blob) == int(f["mask_nb"]) * M[s]["size"], f["mask_name"]
        assert b"".join(pack(s, **p) for p in unpack(s, blob)) == blob, f["mask_name"]


def test_darktable_authored_groups_link_children():
    """The group point order is formid, parentid, state, opacity: parentid is the group's own id."""
    g = next(f for f in authored() if f["mask_name"] == "grp retouch clone")
    pts = unpack("group", xmp.decode_blob(g["mask_points"]))
    assert [p["parentid"] for p in pts] == [int(g["mask_id"])] * 2
    assert [p["state"] for p in pts] == [3, 3 | 8] and [p["opacity"] for p in pts] == [1.0, 1.0]


# --- ellipse -----------------------------------------------------------------------------------

@pytest.mark.darktable
def test_ellipse_center_and_radii(shot):
    """Centre as image fractions; radii as fractions of min(width, height), a along x, b along y."""
    r, _ = shot("ellipse", [pack("ellipse", center_x=0.3, center_y=0.6, radius_a=0.15, radius_b=0.08, border=0.02)])
    short = min(r["W"], r["H"])
    close(r["cx"], 0.3, 0.01); close(r["cy"], 0.6, 0.01)
    hw = (r["x1"] - r["x0"]) / 2 * r["W"] / short; hh = (r["y1"] - r["y0"]) / 2 * r["H"] / short
    close(hw, 0.15 + 0.02, 0.02); close(hh, 0.08 + 0.02, 0.02)
    assert hw > hh * 1.5


@pytest.mark.darktable
def test_ellipse_rotation(shot):
    """90 degrees swaps the axes; a positive angle leans clockwise on screen."""
    e = lambda rot: [pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.2, radius_b=0.08, rotation=rot)]
    r0, r90, rp, rm = (shot("ellipse", e(v))[0] for v in (0, 90, 30, -30))
    assert (r0["x1"] - r0["x0"]) * r0["W"] > 1.8 * (r0["y1"] - r0["y0"]) * r0["H"]
    assert (r90["y1"] - r90["y0"]) * r90["H"] > 1.8 * (r90["x1"] - r90["x0"]) * r90["W"]
    assert 10 < rp["angle"] < 45 and 135 < rm["angle"] < 170, (rp["angle"], rm["angle"])


@pytest.mark.darktable
def test_ellipse_border_and_flags(shot, base):
    """flags 0: border is added to the radius. flags 1: border is a share of the radius (0.1 and
    0.5 give the same 0.15 outer radius), so the two renders are the same picture."""
    eq = lambda b, fl: [pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.1, radius_b=0.1, border=b, flags=fl)]
    (r_small, a_small), (r_eq, a_eq), (r_prop, a_prop) = (shot("ellipse", eq(b, fl)) for b, fl in ((0.001, 0), (0.05, 0), (0.5, 1)))
    assert changed(a_eq, base) > 1.4 * changed(a_small, base), "border did not widen the mask"
    assert np.abs(a_eq - a_prop).max() <= 1, "flags 1 is not a proportional border"


# --- circle, path, brush, gradient -------------------------------------------------------------

@pytest.mark.darktable
def test_circle_geometry(shot):
    r, _ = shot("circle", [pack("circle", center_x=0.3, center_y=0.4, radius=0.1, border=0.02)])
    short = min(r["W"], r["H"])
    close(r["cx"], 0.3, 0.01); close(r["cy"], 0.4, 0.01)
    close((r["x1"] - r["x0"]) / 2 * r["W"] / short, 0.12, 0.02)
    close((r["y1"] - r["y0"]) / 2 * r["H"] / short, 0.12, 0.02)


def rect(ctrl=0.0, border=0.01, state=2, pts=((0.3, 0.3), (0.7, 0.3), (0.7, 0.6), (0.3, 0.6))):
    out = []
    for x, y in pts:
        ox, oy = x - 0.5, y - 0.45; n = (ox * ox + oy * oy) ** 0.5
        c = (x + ctrl * ox / n, y + ctrl * oy / n)
        out.append(pack("path", corner_x=x, corner_y=y, ctrl1_x=c[0], ctrl1_y=c[1], ctrl2_x=c[0], ctrl2_y=c[1],
                        border_x=border, border_y=border, state=state))
    return out


@pytest.mark.darktable
def test_path_geometry(shot):
    """Four corners make a rectangle with straight edges when the control points sit on the corners."""
    r, _ = shot("path", rect())
    close(r["x0"], 0.3, 0.03); close(r["x1"], 0.7, 0.03); close(r["y0"], 0.3, 0.03); close(r["y1"], 0.6, 0.03)
    wide, _ = shot("path", rect(border=0.05))
    assert wide["x1"] - wide["x0"] > r["x1"] - r["x0"] + 0.02 and wide["y1"] - wide["y0"] > r["y1"] - r["y0"] + 0.02


@pytest.mark.darktable
def test_path_control_points(shot):
    """Control points pulled outward bulge the outline beyond the corners."""
    flat, _ = shot("path", rect())
    bulge, _ = shot("path", rect(ctrl=0.1))
    assert bulge["x1"] - bulge["x0"] > flat["x1"] - flat["x0"] + 0.05


def stroke(border=0.03, density=1.0, hardness=0.66, state=2):
    return [pack("brush", corner_x=x, corner_y=0.5, ctrl1_x=x, ctrl1_y=0.5, ctrl2_x=x, ctrl2_y=0.5,
                 border_x=border, border_y=border, density=density, hardness=hardness, state=state) for x in (0.2, 0.5, 0.8)]


@pytest.mark.darktable
def test_brush_geometry(shot):
    """A stroke through three nodes on one line is a band centred on the line; border sets its half width."""
    r, _ = shot("brush", stroke())
    close(r["cy"], 0.5, 0.01); close(r["x0"], 0.2, 0.05); close(r["x1"], 0.8, 0.05)
    wide, _ = shot("brush", stroke(border=0.06))
    assert (wide["y1"] - wide["y0"]) > 1.5 * (r["y1"] - r["y0"])


@pytest.mark.darktable
def test_brush_density_hardness(shot):
    ref, _ = shot("brush", stroke())
    thin, _ = shot("brush", stroke(density=0.5))
    hard, _ = shot("brush", stroke(hardness=1.0))
    soft, _ = shot("brush", stroke(hardness=0.1))
    assert thin["mean"] < ref["mean"] * 0.8
    assert soft["mean"] < ref["mean"] < hard["mean"]


def gradient(rot=0.0, ax=0.5, ay=0.5, comp=0.0, curv=0.0):
    return [pack("gradient", anchor_x=ax, anchor_y=ay, rotation=rot, compression=comp, curvature=curv, state=1)]


def halves(a, base):
    d = np.abs(a - base).max(2); H, W = d.shape
    return dict(top=d[:H // 2].mean(), bottom=d[H // 2:].mean(), left=d[:, :W // 2].mean(), right=d[:, W // 2:].mean())


@pytest.mark.darktable
def test_gradient_geometry(shot, base):
    """compression 0 is a hard edge: rotation 0 lights the top half, 90 the left, 180 the bottom,
    270 the right; the edge sits at the anchor."""
    for rot, lit, dark in ((0, "top", "bottom"), (90, "left", "right"), (180, "bottom", "top"), (270, "right", "left")):
        _, a = shot("gradient", gradient(rot))
        h = halves(a, base)
        assert h[lit] > 20 * max(h[dark], 0.1), (rot, h)
    rows = {}
    for ay in (0.25, 0.75):
        _, a = shot("gradient", gradient(0, ay=ay))
        d = np.abs(a - base).max(2).mean(1)
        rows[ay] = float((d > 10).mean())
    close(rows[0.25], 0.25, 0.05); close(rows[0.75], 0.75, 0.05)
    _, soft = shot("gradient", gradient(0, comp=1.0))
    assert halves(soft, base)["bottom"] > 5, "compression 1 should reach the lower half"


@pytest.mark.darktable
def test_gradient_curvature(shot, base):
    """Curvature bends the edge around the anchor: the edge row at the frame centre stays, the one
    at the side of the frame moves."""
    def edge_rows(a):
        d = np.abs(a - base).max(2) > 10; W = d.shape[1]
        return [float(d[:, x].mean()) for x in (W // 2, W // 8)]
    flat = edge_rows(shot("gradient", gradient(0))[1]); bent = edge_rows(shot("gradient", gradient(0, curv=0.5))[1])
    assert abs(bent[0] - flat[0]) < 0.02 and abs(bent[1] - flat[1]) > 0.05, (flat, bent)


# --- groups ------------------------------------------------------------------------------------

@pytest.mark.darktable
def test_group_opacity_and_state(mrend, mx, base, everywhere):
    """opacity scales the effect, bit 4 of state inverts the mask. State 0, 1 and 2 (use / show
    bits missing) still apply the mask: darktable's render does not read them."""
    e = form(555, "ellipse", [pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.2, radius_b=0.1, border=0.001)])
    run = lambda state=3, op=1.0: mrend(masked(mx, [e], members=[(555, state, op)]))[1]
    full, half, none = run(), run(op=0.5), run(op=0.0)
    assert np.abs(none - base).max() == 0
    assert 0.3 < np.abs(half - base).mean() / np.abs(full - base).mean() < 0.8
    inv = run(state=3 | 4)
    d_full, d_inv = np.abs(full - base).max(2) > 3, np.abs(inv - base).max(2) > 3
    H, W = d_full.shape
    assert d_full[H // 2, W // 2] and not d_inv[H // 2, W // 2] and d_inv[5, 5] and not d_full[5, 5]
    assert (d_full | d_inv).mean() > 0.95
    assert all(np.abs(run(state=s) - full).max() == 0 for s in (0, 1, 2))


@pytest.mark.darktable
def test_group_ops(mrend, mx, base):
    """Second member with union (8), intersection (16), difference (32) on two overlapping discs."""
    left = form(601, "ellipse", [pack("ellipse", center_x=0.4, center_y=0.5, radius_a=0.2, radius_b=0.2, border=0.001)])
    right = form(602, "ellipse", [pack("ellipse", center_x=0.6, center_y=0.5, radius_a=0.2, radius_b=0.2, border=0.001)])
    n = {}
    for op, name in ((8, "union"), (16, "inter"), (32, "diff")):
        _, a = mrend(masked(mx, [left, right], members=[(601, 3, 1.0), (602, 3 | op, 1.0)]))
        n[name] = changed(a, base)
    _, a = mrend(masked(mx, [left], members=[(601, 3, 1.0)]))
    n["left"] = changed(a, base)
    assert n["inter"] < 0.3 * n["union"] and n["union"] > 1.5 * n["left"]
    assert n["left"] * 0.4 < n["diff"] < n["left"] * 1.05, n


# --- where the mask lands ----------------------------------------------------------------------

@pytest.mark.darktable
def test_masks_follow_the_uncropped_input(mrend, mx):
    """Coordinates are fractions of what the module receives, before crop: cropping x to 0.1..0.9
    moves an ellipse at x 0.3 to (0.3 - 0.1) / 0.8 = 0.25 of the output."""
    e = form(555, "ellipse", [pack("ellipse", center_x=0.3, center_y=0.5, radius_a=0.1, radius_b=0.1, border=0.001)])
    def cropped(en):
        x = masked(mx, [e], enabled=en)
        return mrend(xmp.append(x, "crop", 3, xmp.crop_params(0.1, 0.0, 0.9, 1.0)))[1]
    r = region(cropped(1), cropped(0))
    close(r["cx"], 0.25, 0.01); close(r["cy"], 0.5, 0.01)


@pytest.mark.darktable
@pytest.mark.parametrize("name,want", [("ellipse #1", (0.1479, 0.7546)), ("circle #2", (0.9454, 0.4316)), ("ellipse #2", None),
                                       ("path #1", None), ("brush #1", None)])
def test_darktable_authored_masks_land_where_their_points_say(mrend, mx, base, name, want):
    """The blob darktable wrote, byte for byte (hex or gz), loads in 5.6 and lands on its own
    coordinates: centres for the discs, the node box for path and brush."""
    f = next(f for f in authored() if f["mask_name"] == name)
    s = base_shape(f["mask_type"]); blob = xmp.decode_blob(f["mask_points"])
    li = form(555, s, blob, name=name, mask_type=int(f["mask_type"]), nb=int(f["mask_nb"]), src=xmp.decode_blob(f["mask_src"]))
    _, a = mrend(masked(mx, [li]))
    r = region(a, base, thr=2)
    pts = unpack(s, blob)
    if want:
        close(r["cx"], want[0], 0.01); close(r["cy"], want[1], 0.01)
    elif s == "ellipse":
        p = pts[0]
        assert r["x1"] > 0.9 and p["center_x"] > 0.9 and r["y0"] < p["center_y"] < r["y1"] + 0.01
    else:
        xs = [p["corner_x"] for p in pts]; ys = [p["corner_y"] for p in pts]; b = pts[0]["border_x"]
        close(r["x0"], min(xs), b + 0.04); close(r["x1"], max(xs), b + 0.04)
        close(r["y0"], min(ys), b + 0.06); close(r["y1"], max(ys), b + 0.06)


@pytest.mark.darktable
def test_mask_manager_entry_as_darktable_writes_it(mrend, mx, base):
    """darktable compresses a history to one masks snapshot owned by a `mask_manager` entry at
    num 0 (module off, 4 zero bytes, modversion 2), every form at mask_num 0. That layout renders
    like the bare one: the entry is optional for the render and is what darktable itself writes."""
    e = form(555, "ellipse", [pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.2, radius_b=0.1, border=0.001)])
    x = with_masks(mx, [e, group([(555, 3, 1.0)])])
    x = xmp.append(x, "mask_manager", 2, bytes(4), enabled=0)
    x = xmp.append(x, "exposure", 7, xmp.exposure_params(EV), blendop=blend_params(GID).hex())
    res, a = mrend(x)
    assert "mask_manager" in res["modules_loaded"]
    _, bare = mrend(masked(mx, [e]))
    assert np.abs(a - bare).max() == 0


# --- pitfalls ----------------------------------------------------------------------------------

@pytest.mark.darktable
@pytest.mark.pitfall("P10")
def test_unresolved_mask_applies_to_the_whole_image(mrend, mx, everywhere, base):
    """A mask darktable cannot resolve is not an error: the module acts on the whole image. Seen for
    a group id with no row, mask_mode 2 (drawn bit without the enabled bit), blend_cst 0, and a
    mask_version darktable does not know (7). A group that lists a member with no row is the
    opposite failure: it selects nothing and the module does nothing."""
    e = form(555, "ellipse", [pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.1, radius_b=0.1)])
    cases = {"missing group": masked(mx, [e], gid=GID).replace(f'mask_id="{GID}"', 'mask_id="424242"'),
             "mask_mode 2": masked(mx, [e], mask_mode=2),
             "mask_version 7": masked(mx, [form(555, "ellipse", [pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.1, radius_b=0.1)], version=7)], group_version=7),
             "blend_cst 0": masked(mx, [e]).replace(blend_params(GID).hex(), blend_params(GID, cst=0).hex())}
    for name, x in cases.items():
        assert x != masked(mx, [e]), name
        res, a = mrend(x)
        assert np.abs(a - everywhere).max() == 0, f"{name}: the mask acted, darktable now rejects it"
    # a group whose member has no row selects nothing: the module does nothing at all
    _, nothing = mrend(masked(mx, [e], members=[(777, 3, 1.0)]))
    assert np.abs(nothing - base).max() == 0


@pytest.mark.darktable
@pytest.mark.pitfall("P11")
def test_uppercase_mask_points_crash_darktable(mrend, mx):
    """Uppercase hex in mask_points does not decode: darktable-cli segfaults and writes nothing
    (the same slip in `params` only drops the module, P2)."""
    e = form(555, "ellipse", [pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.1, radius_b=0.1)], enc=lambda b: b.hex().upper())
    res, _ = mrend(masked(mx, [e]), ok=False)
    assert not res["written"] and res["exit"] != 0, res


# --- the other side: darktable's own serializer and library.db ---------------------------------

def _forms_all_shapes():
    ell = pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.2, radius_b=0.08, rotation=30, border=0.5, flags=1)
    return [form(601, "ellipse", [ell]),
            form(602, "circle", [pack("circle", center_x=0.3, center_y=0.4, radius=0.1, border=0.02)]),
            form(603, "path", rect(state=1)),
            form(604, "brush", stroke()),
            form(605, "gradient", [pack("gradient", anchor_x=0.5, anchor_y=0.5, rotation=10, compression=0.5, steepness=0.1, curvature=0.2, state=1)])]


def _li_dicts(text):
    return [dict(re.findall(r'darktable:(\w+)="([^"]*)"', li)) for li in re.findall(r"<rdf:li\b(.*?)/>", text, re.S)]


@pytest.mark.darktable
def test_darktable_writes_back_the_same_forms(tmp_path, sample_raw, darktable_cli, mx):
    """Round trip through darktable's own XMP writer: the JPEG it exports carries masks_history
    serialized from its database. Every form comes back with the same ids, types, counts and bytes."""
    shapes = _forms_all_shapes()
    members = [(601, 3, 0.75)] + [(int(re.search(r'mask_id="(\d+)"', f).group(1)), 3 | 8, 0.75) for f in shapes[1:]]
    x = masked(mx, shapes, members=members)
    side = tmp_path / "a.xmp"; side.write_text(x)
    out = tmp_path / "o.jpg"
    r = subprocess.run([darktable_cli, sample_raw, str(side), dtenv.out_arg(out), "--width", "200", "--height", "200",
                        "--apply-custom-presets", "true", "--core", "--configdir", str(tmp_path / "conf"), "--library", ":memory:",
                        "--conf", "write_sidecar_files=never", "--conf", "plugins/lighttable/export/metadata_flags=2f"],
                       capture_output=True, text=True)
    assert out.exists(), r.stderr[-500:]
    d = out.read_bytes(); packet = d[d.index(b"<x:xmpmeta"):d.index(b"</x:xmpmeta>") + 12].decode()
    m = re.search(r"<darktable:masks_history>\s*<rdf:Seq>(.*?)</rdf:Seq>", packet, re.S)
    assert m, "darktable exported no masks_history"
    sent, got = _li_dicts("".join(shapes + [group(members)])), _li_dicts(m.group(1))
    assert len(got) == len(sent) == 6
    for s, g in zip(sent, got):
        for k in s:
            same = xmp.decode_blob(s[k]) == xmp.decode_blob(g[k]) if k in ("mask_points", "mask_src") else s[k] == g[k]
            assert same, (s["mask_name"], k, s[k][:40], g[k][:40])


@pytest.mark.darktable
def test_library_rows_match_the_layout(tmp_path, sample_raw, darktable_cli, mx, base):
    """library.db: darktable imports a sidecar into masks_history with the raw struct bytes. A
    render from rows rebuilt in Python (sidecar removed) equals the sidecar render, and a library
    with no rows applies the module to the whole image (P10)."""
    photos = tmp_path / "photos"; photos.mkdir()
    img = photos / "img.ARW"; shutil.copy(sample_raw, img)
    e_pts = [pack("ellipse", center_x=0.5, center_y=0.5, radius_a=0.2, radius_b=0.08, rotation=30, border=0.05)]
    x = masked(mx, [form(555, "ellipse", e_pts)])
    (photos / "img.ARW.xmp").write_text(x)
    conf = str(tmp_path / "conf")

    def cli(out, lib):
        if os.path.exists(out):
            os.remove(out)
        r = subprocess.run([darktable_cli, str(img), dtenv.out_arg(out), "--width", str(SIZE), "--height", str(SIZE), "--core",
                            "--configdir", conf, "--library", str(lib), "--conf", "write_sidecar_files=never"],
                           capture_output=True, text=True)
        assert os.path.exists(out), r.stderr[-500:]
        return np.asarray(Image.open(out).convert("RGB")).astype(float)

    lib = tmp_path / "library.db"
    from_sidecar = cli(tmp_path / "a.jpg", lib)                   # imports the image and its masks
    con = sqlite3.connect(lib)
    cols = [r[1] for r in con.execute("pragma table_info(masks_history)")]
    assert cols == ["imgid", "num", "formid", "form", "name", "version", "points", "points_count", "source"]
    rows = {r[0]: r for r in con.execute("select formid, form, name, version, points, points_count, source from masks_history")}
    assert set(rows) == {555, GID}
    assert rows[555][1] == 32 and rows[555][3] == 6 and rows[555][5] == 1 and bytes(rows[555][4]) == e_pts[0] and bytes(rows[555][6]) == bytes(8)
    assert rows[GID][1] == 4 and unpack("group", bytes(rows[GID][4])) == [dict(formid=555, parentid=GID, state=3, opacity=1.0)]
    # the sidecar goes away: only the rows drive the render
    os.rename(photos / "img.ARW.xmp", tmp_path / "side.xmp")
    assert np.abs(cli(tmp_path / "b.jpg", lib) - from_sidecar).max() == 0
    # rows rebuilt in Python
    lib2 = tmp_path / "lib2.db"; shutil.copy(lib, lib2)
    c2 = sqlite3.connect(lib2); imgid = c2.execute("select id from images").fetchone()[0]
    c2.execute("delete from masks_history")
    c2.executemany("insert into masks_history (imgid, num, formid, form, name, version, points, points_count, source) values (?,?,?,?,?,?,?,?,?)",
                   [(imgid, 0, 555, 32, "ellipse #1", 6, e_pts[0], 1, bytes(8)),
                    (imgid, 0, GID, 4, "grp exposure", 6, pack("group", formid=555, parentid=GID, state=3, opacity=1.0), 1, bytes(8))])
    c2.commit(); c2.close()
    assert np.abs(cli(tmp_path / "c.jpg", lib2) - from_sidecar).max() == 0
    # no rows: the whole image
    lib3 = tmp_path / "lib3.db"; shutil.copy(lib, lib3)
    c3 = sqlite3.connect(lib3); c3.execute("delete from masks_history"); c3.commit(); c3.close()
    nomask = cli(tmp_path / "d.jpg", lib3)
    assert np.abs(nomask - from_sidecar).mean() > 20
