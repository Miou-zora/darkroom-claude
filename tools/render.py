#!/usr/bin/env python3
"""Render a RAW with a sidecar through darktable-cli, then measure the result.

    python3 render.py RAW XMP OUT.jpg [--size 1080] [--phone]

- Isolated config dir and in-memory library: never touches the user's library.db.
- OUT is deleted first: darktable-cli never overwrites, it writes OUT_01.jpg next
  to it, and a tuning loop would silently keep measuring the old file.
- `-d params` is parsed per module: `params_wrong` lists modules whose blob failed to
  decode (those are dropped from the render). Exit code 1 if any.
- --phone also writes OUT.phone.png at 390 px wide, the size of a feed post on a phone.

Prints one JSON line: size, luminance percentiles (Rec.709, 0 to 1), clipped share.
"""
import os, re, sys, json, shutil, subprocess, argparse
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtenv

CANDIDATES = dtenv.cli_candidates()
CONF = os.path.join(dtenv.cache_dir(), "darkroom-claude", "dtconf")
TIMEOUT = int(os.environ.get("DARKROOM_RENDER_TIMEOUT", 600))  # seconds


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
    cmd = [cli(), raw, xmp, dtenv.out_arg(out), "--hq", "true", "--upscale", "false",
           "--apply-custom-presets", "false"]
    if size:
        cmd += ["--width", str(size), "--height", str(height or size)]
    cmd += ["--core", "--configdir", CONF, "--library", ":memory:",
            "--conf", "write_sidecar_files=never", "-d", "params"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
        code, log = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:  # a hung darktable-cli (crash dialog on Windows) must not hang the caller
        code, log = -1, "".join(x.decode("utf-8", "replace") if isinstance(x, bytes) else x or "" for x in (e.stdout, e.stderr))
        log += "\nTIMEOUT after %ss" % TIMEOUT
        if sys.platform == "win32":  # THROWAWAY (#31)
            log += "\n" + subprocess.run(["tasklist"], capture_output=True, text=True).stdout
    loaded, wrong = parse_params_log(log)
    res = dict(exit=code, modules_loaded=loaded, params_wrong=wrong, written=os.path.exists(out))
    if not res["written"]:
        res["log_tail"] = log[-1500:]  # darktable-cli says why, or where it wrote instead
    return res


def parse_params_log(log):
    """darktable -d params prints, per history module, a 'blendop v.N' line and a
    'params v.N' line. Only 'params ... params WRONG' means a blob failed to decode.
    'blendop v. 0 ... WRONG' is normal for modules without blending (rawprepare, gamma...)."""
    loaded, wrong, cur = [], [], None
    for line in log.splitlines():
        m = re.search(r"successfully loaded module (\w+) from history", line)
        if m:
            cur = m.group(1); loaded.append(cur); continue
        m = re.search(r"^\s*params v\. \d+:\s+version \w+\s+params (\w+)", line)
        if m and cur and m.group(1).upper() == "WRONG":
            wrong.append(cur)
    return loaded, wrong


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
    return 0 if res["written"] and not res["params_wrong"] else 1


if __name__ == "__main__":
    sys.exit(main())
