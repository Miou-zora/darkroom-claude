#!/usr/bin/env python3
"""Contact sheet of renders, labelled, to compare candidates in one image.

    python3 sheet.py IMG... --out sheet.png [--phone] [--pairs] [--cols N] [--cell PX]

Grid, in the order given, each cell labelled with the file name. Images keep their aspect ratio
and are resized to the same width (`--cell`, default 480).
  --phone  every image is 390 px wide, the width of a phone feed (overrides --cell).
  --pairs  before/after: the images are read two by two (before1 after1 before2 after2 ...), one pair
           per row, labelled "before" and "after" above the file name. Needs an even count.
Prints one JSON line: out, size, cols, rows, cell_width.
"""
import sys, json, argparse
from PIL import Image, ImageDraw, ImageFont

PHONE = 390
GAP, LABEL_H, BG, FG = 10, 22, (24, 24, 24), (235, 235, 235)


def font():
    try:
        return ImageFont.load_default(size=14)
    except TypeError:  # Pillow < 10.1: fixed-size bitmap font
        return ImageFont.load_default()


def sheet(paths, cell=480, cols=3, pairs=False, phone=False):
    if phone:
        cell = PHONE
    if pairs:
        if len(paths) % 2:
            raise ValueError(f"--pairs needs an even number of images, got {len(paths)}")
        cols = 2
    ims = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        ims.append(im.resize((cell, max(1, round(im.height * cell / im.width))), Image.LANCZOS))
    labels = [p.replace("\\", "/").rsplit("/", 1)[-1] for p in paths]
    if pairs:
        labels = [f"{'before' if i % 2 == 0 else 'after'}: {n}" for i, n in enumerate(labels)]
    cols = max(1, min(cols, len(ims)))
    rows = [ims[i:i + cols] for i in range(0, len(ims), cols)]
    row_h = [LABEL_H + max(im.height for im in r) for r in rows]
    W = GAP + cols * (cell + GAP)
    H = GAP + sum(h + GAP for h in row_h)
    out = Image.new("RGB", (W, H), BG)
    d, f, y = ImageDraw.Draw(out), font(), GAP
    for r, row in enumerate(rows):
        for c, im in enumerate(row):
            x = GAP + c * (cell + GAP)
            d.text((x, y + 3), labels[r * cols + c], fill=FG, font=f)
            out.paste(im, (x, y + LABEL_H))
        y += row_h[r] + GAP
    return out, cols, len(rows), cell


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--phone", action="store_true")
    ap.add_argument("--pairs", action="store_true")
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--cell", type=int, default=480)
    a = ap.parse_args()
    try:
        out, cols, rows, cell = sheet(a.images, a.cell, a.cols, a.pairs, a.phone)
    except (ValueError, OSError) as e:
        print(json.dumps(dict(error=str(e)))); return 1
    out.save(a.out)
    print(json.dumps(dict(out=a.out, size=list(out.size), cols=cols, rows=rows, cell_width=cell)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
