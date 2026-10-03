"""tools/sheet.py: contact sheet layout on generated images."""
import json, subprocess, sys, os
import numpy as np
import pytest
from PIL import Image
import sheet

COLORS = [(220, 40, 40), (40, 200, 60), (50, 80, 230), (230, 200, 40)]


def imgs(tmp_path, n, size=(800, 600)):
    paths = []
    for i in range(n):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", size, COLORS[i % 4]).save(p)
        paths.append(str(p))
    return paths


def test_grid_places_each_image_in_its_cell(tmp_path):
    out, cols, rows, cell = sheet.sheet(imgs(tmp_path, 4), cell=200, cols=2)
    assert (cols, rows, cell) == (2, 2, 200)
    # 4:3 images at 200 px wide are 150 tall; each cell has a label strip above the image
    assert out.size == (10 + 2 * 210, 10 + 2 * (sheet.LABEL_H + 150 + 10))
    for i, color in enumerate(COLORS):
        x = sheet.GAP + (i % 2) * 210 + 100
        y = sheet.GAP + (i // 2) * (sheet.LABEL_H + 150 + 10) + sheet.LABEL_H + 75
        assert out.getpixel((x, y)) == color
    # labels are drawn: the strip above the first image is not all background
    strip = np.asarray(out.crop((10, 10, 210, 10 + sheet.LABEL_H)))
    assert (strip != np.array(sheet.BG)).any()


def test_phone_is_390_wide_whatever_the_source(tmp_path):
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    Image.new("RGB", (1080, 1350), COLORS[0]).save(a)
    Image.new("RGB", (3000, 2000), COLORS[1]).save(b)
    out, cols, rows, cell = sheet.sheet([a, b], cell=999, cols=2, phone=True)
    assert cell == 390
    assert out.size[0] == 10 + 2 * 400
    # tallest image sets the row: 1080x1350 -> 390x488
    assert out.size[1] == 10 + sheet.LABEL_H + 488 + 10


def test_pairs_are_one_per_row_before_then_after(tmp_path):
    out, cols, rows, _ = sheet.sheet(imgs(tmp_path, 4), cell=100, pairs=True, cols=5)
    assert (cols, rows) == (2, 2)
    y = sheet.GAP + sheet.LABEL_H + 37
    assert out.getpixel((sheet.GAP + 50, y)) == COLORS[0]       # row 0 before
    assert out.getpixel((sheet.GAP + 110 + 50, y)) == COLORS[1]  # row 0 after


def test_pairs_need_an_even_count(tmp_path):
    with pytest.raises(ValueError, match="even"):
        sheet.sheet(imgs(tmp_path, 3), pairs=True)


def test_cli_writes_the_sheet_and_prints_json(tmp_path):
    out = tmp_path / "s.png"
    tool = os.path.join(os.path.dirname(__file__), "..", "tools", "sheet.py")
    r = subprocess.run([sys.executable, tool, *imgs(tmp_path, 3), "--out", str(out), "--phone"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout)
    assert Image.open(out).size == tuple(info["size"]) and info["cell_width"] == 390
