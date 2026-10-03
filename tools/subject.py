#!/usr/bin/env python3
"""Locate the main subject on a render, to frame a crop from a measurement and not by eye.

    python3 subject.py RENDER.jpg

Saliency without a model: distance of each pixel to the median colour of the frame (the
background is the bulk of the pixels), on a downscaled, slightly blurred copy. The subject is the
region above half the peak distance. Fits a subject that differs in colour or tone from its
surroundings (macro, bokeh background); a subject the same colour as its background is not found,
look at the render instead.

Prints one JSON line, all in the render's own coordinates:
  size, box [x0, y0, x1, y1] in px, box_pct (same, 0 to 1), center_pct, width_share, height_share.
Exit code 1 if the frame has no contrast to find a subject in.
"""
import sys, json
import numpy as np
from PIL import Image, ImageFilter

WORK = 256  # long side of the working copy; the box is scaled back to the render


def main_blob(sal, mask):
    """The 4-connected blob of `mask` with the highest summed saliency, as a boolean mask.
    Grown from the peak of what is left, by repeated dilation: no scipy needed."""
    left, best, best_sum = mask.copy(), None, -1.0
    while left.any():
        seed = np.zeros_like(mask); seed[np.unravel_index(np.argmax(sal * left), mask.shape)] = True
        while True:
            p = np.pad(seed, 1)
            grown = (seed | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]) & mask
            if (grown == seed).all():
                break
            seed = grown
        if sal[seed].sum() > best_sum:
            best, best_sum = seed, sal[seed].sum()
        left &= ~seed
    return best


def locate(path):
    im = Image.open(path).convert("RGB"); W, H = im.size
    k = WORK / max(W, H)
    small = im.resize((max(1, round(W * k)), max(1, round(H * k))), Image.LANCZOS)
    a = np.asarray(small.filter(ImageFilter.GaussianBlur(1.5))).astype(float)
    sal = np.linalg.norm(a - np.median(a.reshape(-1, 3), axis=0), axis=2)
    if sal.max() < 8:  # under ~3% of full scale: noise, not a subject
        raise ValueError("no contrast: nothing to locate")
    ys, xs = np.nonzero(main_blob(sal, sal >= 0.5 * sal.max()))
    # ponytail: the blob with the most total saliency wins, so a thin or split subject can lose to a
    # bright patch of sky; upgrade to a real segmentation if that bites. 0.5 percentile trim drops
    # the stray pixels the blur leaves at the edge.
    x0, x1 = np.percentile(xs, [0.5, 99.5]); y0, y1 = np.percentile(ys, [0.5, 99.5])
    sw, sh = small.size
    box_pct = [x0 / sw, y0 / sh, (x1 + 1) / sw, (y1 + 1) / sh]
    box = [int(np.floor(box_pct[0] * W)), int(np.floor(box_pct[1] * H)),
           int(np.ceil(box_pct[2] * W)), int(np.ceil(box_pct[3] * H))]
    r = lambda v: round(float(v), 3)
    return dict(size=[W, H], box=box, box_pct=[r(v) for v in box_pct],
                center_pct=[r((box_pct[0] + box_pct[2]) / 2), r((box_pct[1] + box_pct[3]) / 2)],
                width_share=r(box_pct[2] - box_pct[0]), height_share=r(box_pct[3] - box_pct[1]))


def main():
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        sys.exit(__doc__)
    try:
        print(json.dumps(locate(sys.argv[1])))
    except ValueError as e:
        print(json.dumps(dict(error=str(e)))); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
