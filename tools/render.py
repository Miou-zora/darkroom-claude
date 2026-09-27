#!/usr/bin/env python3
"""Render a RAW with a sidecar through darktable-cli, then measure the result.

    python3 render.py RAW XMP OUT.jpg [--size 1080] [--phone]

- Isolated config dir and in-memory library: never touches the user's library.db.
- OUT is deleted first: darktable-cli never overwrites, it writes OUT_01.jpg next
  to it, and a tuning loop would silently keep measuring the old file.
- `-d params` is parsed: any "params WRONG" line means a module was dropped.
- --phone also writes OUT.phone.png at 390 px wide, the size of a feed post on a phone.

Prints one JSON line: size, luminance percentiles (Rec.709, 0 to 1), clipped share.
"""
import os, sys, json, shutil, subprocess, argparse
import numpy as np
from PIL import Image

CANDIDATES = [os.environ.get("DARKTABLE_CLI", ""),
              "/Applications/darktable.app/Contents/MacOS/darktable-cli",
              shutil.which("darktable-cli") or ""]
CONF = os.path.join(os.path.expanduser(os.environ.get("XDG_CACHE_HOME", "~/.cache")),
                    "darkroom-claude", "dtconf")


def cli():
    for c in CANDIDATES:
        if c and os.path.exists(c):
            return c
    sys.exit("darktable-cli not found: set DARKTABLE_CLI")


def render(raw, xmp, out, size=1080, height=None):
    if not out.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
        sys.exit("OUT must be an image path")
    if os.path.abspath(out) in (os.path.abspath(raw), os.path.abspath(xmp)):
        sys.exit("OUT would overwrite an input")
    if os.path.exists(out):
        os.remove(out)
    os.makedirs(CONF, exist_ok=True)
    cmd = [cli(), raw, xmp, out, "--hq", "true", "--upscale", "false",
           "--apply-custom-presets", "false"]
    if size:
        cmd += ["--width", str(size), "--height", str(height or size)]
    cmd += ["--core", "--configdir", CONF, "--library", ":memory:",
            "--conf", "write_sidecar_files=never", "-d", "params"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    log = r.stdout + r.stderr
    return dict(exit=r.returncode, params_ok=log.count("params ok"),
                params_wrong=log.lower().count("params wrong"), written=os.path.exists(out))


def stats(path):
    im = Image.open(path).convert("RGB"); a = np.asarray(im).astype(float)
    L = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]) / 255
    p = np.percentile(L, [1, 5, 50, 95, 99.5])
    return dict(size=list(im.size), p1=round(p[0], 3), p5=round(p[1], 3), p50=round(p[2], 3),
                p95=round(p[3], 3), p995=round(p[4], 3),
                clipped_pct=round(float((a.max(2) >= 254).mean() * 100), 3))


def phone(path, width=390):
    im = Image.open(path); im = im.resize((width, round(width * im.height / im.width)), Image.LANCZOS)
    out = os.path.splitext(path)[0] + ".phone.png"; im.save(out); return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw"); ap.add_argument("xmp"); ap.add_argument("out")
    ap.add_argument("--size", type=int, default=1080, help="bounding box, 0 = full resolution")
    ap.add_argument("--height", type=int, help="bounding box height, defaults to --size")
    ap.add_argument("--phone", action="store_true")
    a = ap.parse_args()
    res = render(a.raw, a.xmp, a.out, a.size, a.height)
    if res["written"]:
        res.update(stats(a.out))
        if a.phone:
            res["phone"] = phone(a.out)
    print(json.dumps(res))
    return 0 if res["written"] and res["params_wrong"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
