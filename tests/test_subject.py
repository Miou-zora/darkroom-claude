"""tools/subject.py: unit tests on synthetic frames with a known subject box."""
import json, subprocess, sys, os
import numpy as np
import pytest
from PIL import Image, ImageFilter
import subject

W, H = 600, 400


def frame(path, box, color=(220, 40, 40), blur=0):
    """Noisy grey background (std ~6) with a coloured rectangle at box = x0, y0, x1, y1."""
    rng = np.random.default_rng(0)
    a = np.clip(rng.normal(110, 6, (H, W, 1)), 0, 255).repeat(3, 2)
    x0, y0, x1, y1 = box
    a[y0:y1, x0:x1] = color
    im = Image.fromarray(a.astype("uint8"))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    im.save(path)
    return str(path)


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy)


@pytest.mark.parametrize("truth", [(60, 50, 200, 190), (380, 220, 560, 370), (250, 150, 350, 250)])
def test_box_follows_the_subject(tmp_path, truth):
    # three positions: a locator that returns the frame centre or a fixed box fails two of them
    res = subject.locate(frame(tmp_path / "f.png", truth))
    assert res["size"] == [W, H]
    assert iou(res["box"], truth) > 0.85, res
    cx, cy = (truth[0] + truth[2]) / 2 / W, (truth[1] + truth[3]) / 2 / H
    assert abs(res["center_pct"][0] - cx) < 0.03 and abs(res["center_pct"][1] - cy) < 0.03


def test_share_and_pct_agree_with_box(tmp_path):
    res = subject.locate(frame(tmp_path / "f.png", (100, 100, 400, 300)))
    assert res["width_share"] == pytest.approx(0.5, abs=0.04)
    assert res["height_share"] == pytest.approx(0.5, abs=0.04)
    assert res["box"][0] == pytest.approx(res["box_pct"][0] * W, abs=1)


def test_soft_edged_subject(tmp_path):
    # macro style: the subject edge is blurred, the box must still sit on it
    truth = (150, 90, 330, 300)
    res = subject.locate(frame(tmp_path / "f.png", truth, blur=6))
    assert iou(res["box"], truth) > 0.75, res


def test_flat_frame_has_no_subject(tmp_path):
    Image.new("RGB", (W, H), (120, 120, 120)).save(tmp_path / "flat.png")
    with pytest.raises(ValueError):
        subject.locate(str(tmp_path / "flat.png"))


def test_cli_prints_json(tmp_path):
    p = frame(tmp_path / "f.png", (60, 50, 200, 190))
    out = subprocess.run([sys.executable, subject.__file__, p], capture_output=True, text=True)
    assert out.returncode == 0 and set(json.loads(out.stdout)) >= {"box", "box_pct", "width_share"}


def test_stray_speck_does_not_widen_the_box(tmp_path):
    # a small bright speck far from the subject must not stretch the box across the frame
    p = frame(tmp_path / "f.png", (60, 50, 200, 190))
    im = Image.open(p); im.paste((255, 255, 0), (530, 330, 560, 360)); im.save(p)
    assert iou(subject.locate(p)["box"], (60, 50, 200, 190)) > 0.85
