#!/usr/bin/env python3
"""Apply a darktable style (data.db) to XMP sidecars, and prove every module acts.

    python3 apply_style.py STYLE SIDECAR.xmp [...]               render proof, report only
    python3 apply_style.py STYLE SIDECAR.xmp [...] --write       also write the sidecars
      --exclude op,op   style modules to leave out (default: temperature,exposure,rawprepare,
                        the image-specific ones; --exclude '' keeps everything)
      --exposure EV     append an exposure entry after the style, to tune per image
      --data-db PATH    default $DARKTABLE_CONFIGDIR/data.db or ~/.config/darktable/data.db
      --no-verify       skip the render proof (no RAW or no darktable-cli)

Copies each kept style_items row (params, blend params with parametric masks, multi_priority,
multi_name) as a new history entry. If the style holds a second instance of a module, adds an
iop_order_list naming it: without one darktable ignores the instance silently (P3).

Proof: renders the sidecar with the style, then once more per module without that module. A
zero pixel difference means the module did nothing (dropped blob, ignored instance, masked
out): reported as an error and the sidecar is not written. The style is read read-only.
"""
import os, re, sys, time, shutil, sqlite3, tempfile, argparse
from pathlib import Path
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xmp, render
from dbsync import darktable_running

DEFAULT_EXCLUDE = ("temperature", "exposure", "rawprepare")
IOP_V4 = open(os.path.join(HERE, "iop_order_v4.txt")).read().strip()


def data_db_path():
    return os.path.join(os.environ.get("DARKTABLE_CONFIGDIR", os.path.expanduser("~/.config/darktable")), "data.db")


def load_style(db_path, name):
    """style_items rows of the style called `name`, in order. `module` is the module version."""
    db = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    ids = db.execute("select id from styles where name = ?", (name,)).fetchall()
    if len(ids) != 1:
        raise ValueError(f"style {name!r}: {len(ids)} matches in {db_path}, expected 1")
    rows = db.execute("select operation, module, op_params, enabled, blendop_params, blendop_version, "
                      "multi_priority, multi_name from style_items where styleid = ? order by num", ids[0])
    return [dict(op=op, version=v, params=bytes(p), enabled=en, multi_priority=mp, multi_name=mn or "",
                 blend=bytes(bl).hex() if bl is not None else xmp.NEUTRAL_BLEND,
                 blend_version=bv if bl is not None else 14)
            for op, v, p, en, bl, bv, mp, mn in rows]


def with_instances(x, items):
    """Add the second (third...) instances the style carries to the sidecar's iop_order_list,
    starting from the bundled v4 list when the sidecar has none."""
    extra = sorted({(i["op"], i["multi_priority"]) for i in items if i["multi_priority"] > 0}, key=lambda t: t[1])
    if not extra:
        return x
    m = re.search(r'darktable:iop_order_list="([^"]*)"', x)
    if m:
        lst = m.group(1)
    elif 'darktable:iop_order_version="4"' in x:
        lst = IOP_V4
    else:
        raise ValueError("style has a second instance but the sidecar has no iop_order_list "
                         "and is not iop_order_version 4: no list to extend")
    t = lst.split(",")
    pairs = [(t[k], t[k + 1]) for k in range(0, len(t), 2)]
    for op, mp in extra:
        if (op, str(mp)) in pairs:
            continue
        at = [k for k, p in enumerate(pairs) if p[0] == op]
        if not at:
            raise ValueError(f"{op} is not in the iop_order_list: cannot place its instance {mp}")
        pairs.insert(at[-1] + 1, (op, str(mp)))
    return xmp.with_iop_order_list(x, ",".join(f"{a},{b}" for a, b in pairs))


def add(x, items, ev=None, skip=None):
    """Sidecar text with the style appended; `skip` = (operation, multi_priority) left out."""
    out = with_instances(x, items)
    for i in items:
        if (i["op"], i["multi_priority"]) != skip:
            out = xmp.append(out, i["op"], i["version"], i["params"], enabled=i["enabled"],
                             multi_priority=i["multi_priority"], multi_name=i["multi_name"],
                             blendop=i["blend"], blendop_version=i["blend_version"])
    if ev is not None and skip != ("exposure", 0):
        out = xmp.append(out, "exposure", 7, xmp.exposure_params(ev))
    return out


def raw_for(sidecar):
    """NAME.EXT.xmp -> NAME.EXT, or NAME.EXT for a duplicate NAME_01.EXT.xmp."""
    raw = sidecar[:-4]
    if os.path.exists(raw):
        return raw
    m = re.match(r"^(.*)_\d{2}(\.[^.]+)$", raw)
    return m.group(1) + m.group(2) if m and os.path.exists(m.group(1) + m.group(2)) else None


def prove(raw, x, items, ev, size=600):
    """Errors found by rendering: a module with zero pixel diff when left out, or a blob that
    darktable could not decode. Empty list = every added module acts."""
    with tempfile.TemporaryDirectory() as tmp:
        def px(text, tag):
            side, out = os.path.join(tmp, tag + ".xmp"), os.path.join(tmp, tag + ".jpg")
            open(side, "w").write(text)
            res = render.render(raw, side, out, size)
            if res["exit"] != 0 or not res["written"]:
                raise RuntimeError(f"darktable-cli failed on {tag}: {res}")
            return res, np.asarray(Image.open(out).convert("RGB")).astype(int)
        res, full = px(add(x, items, ev), "full")
        errors = [f"{op}: params blob did not decode (dropped by darktable)" for op in res["params_wrong"]]
        keys = [(i["op"], i["multi_priority"]) for i in items if i["enabled"]] + ([("exposure", 0)] if ev is not None else [])
        for k, (op, mp) in enumerate(dict.fromkeys(keys)):
            _, without = px(add(x, items, ev, skip=(op, mp)), f"no{k}")
            if np.abs(full - without).max() == 0:
                errors.append(f"{op} (instance {mp}): zero pixel difference with and without it, it does nothing")
        return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("style"); ap.add_argument("sidecars", nargs="+")
    ap.add_argument("--exclude", default=",".join(DEFAULT_EXCLUDE))
    ap.add_argument("--exposure", type=float, metavar="EV")
    ap.add_argument("--data-db", default=data_db_path())
    ap.add_argument("--size", type=int, default=600, help="render bounding box for the proof")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    exclude = {e for e in a.exclude.split(",") if e}
    items = [i for i in load_style(a.data_db, a.style) if i["op"] not in exclude]
    if not items:
        print(f"style {a.style!r} has nothing left after excluding {sorted(exclude)}"); return 1
    print(f"style {a.style!r}: " + ", ".join(f"{i['op']}{'#' + str(i['multi_priority']) if i['multi_priority'] else ''}"
                                             f"{'' if i['enabled'] else ' (off)'}" for i in items)
          + (f"; excluded {sorted(exclude)}" if exclude else ""))
    if a.write and darktable_running():
        print("refused: darktable is running and would overwrite the sidecars on close"); return 1
    failed = 0
    for s in a.sidecars:
        x = open(s).read()
        try:
            new = add(x, items, a.exposure)
            raw = None if a.no_verify else raw_for(s)
            if not a.no_verify and not raw:
                errors = ["RAW not found next to the sidecar: cannot prove the modules act (--no-verify to skip)"]
            else:
                errors = [] if a.no_verify else prove(raw, x, items, a.exposure, a.size)
        except (ValueError, RuntimeError) as e:
            errors, new = [str(e)], None
        name = os.path.basename(s)
        if errors:
            failed += 1
            print(f"{name}: ERROR, not written")
            for e in errors:
                print(f"  {e}")
        elif a.write:
            backup = f"{s}-darkroom-{time.strftime('%Y%m%d-%H%M%S')}"
            shutil.copy2(s, backup); open(s, "w").write(new)
            print(f"{name}: written{'' if a.no_verify else ', every module proven by render'} (backup {backup})")
        else:
            print(f"{name}: ok{'' if a.no_verify else ', every module proven by render'}; dry run, nothing written")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
