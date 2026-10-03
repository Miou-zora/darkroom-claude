#!/usr/bin/env python3
"""EXPERIMENTAL. Three ways to push a hand-edited sidecar into a library.db, compared on the DB
rows they leave and on the pixels rendered from the DB:

  lua     image:apply_sidecar (reload_sidecars.lua) in a darktable-cli process fed another image
  dbsync  tools/dbsync.py --write --accept-divergent --allow-delete
  cli     plain `darktable-cli A.ARW`: its own import re-reads A's sidecar (no Lua involved)
  none    control, nothing done

    python3 experiment.py RAW [WORKDIR]

Everything happens in WORKDIR (default $TMPDIR/lua-reload). Never touches ~/.config/darktable.
"""
import os, re, sys, time, shutil, sqlite3, subprocess, tempfile, hashlib
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import xmp, render  # noqa: E402

LUA = os.path.join(ROOT, "tools", "reload_sidecars.lua")  # promoted to tools/ (#20)
MINIMAL = os.path.join(ROOT, "tests", "fixtures", "minimal.xmp")
# luacmd is skipped by darktable on a config whose Lua first run has not completed
FIRST_RUN = ["--conf", "lua/luarc/darktable_first_run_complete=TRUE"]


def dt(conf, raw, out, extra=(), env=None, size=8, sidecars="never", from_db=False):
    """One darktable-cli run. from_db: history read from the library (CLI option, so before --core)."""
    if os.path.exists(out):
        os.remove(out)
    lib = os.path.join(conf, "library.db")
    cmd = [render.cli(), raw, out, "--hq", "true", "--upscale", "false", "--apply-custom-presets", "false",
           "--width", str(size), "--height", str(size)]
    if from_db:
        cmd += ["--library", lib]
    cmd += ["--core", "--configdir", conf, "--library", lib, "--conf", f"write_sidecar_files={sidecars}",
            *FIRST_RUN, *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, **(env or {})})
    return r.stdout + r.stderr


def dump(conf):
    """Image 1 only (image 2, if any, is the dummy host of the Lua run). Blobs shown as short sha1."""
    db = sqlite3.connect(os.path.join(conf, "library.db"))
    db.create_function("sha", 1, lambda b: hashlib.sha1(b or b"").hexdigest()[:8])
    q = lambda s: db.execute(s).fetchall()
    return dict(
        history=q("select num, module, operation, sha(op_params), enabled, sha(blendop_params), blendop_version, "
                  "multi_priority, multi_name, multi_name_hand_edited from history where imgid=1 order by num"),
        history_end=q("select history_end from images where id=1"),
        module_order=q("select version, iop_list from module_order where imgid=1"),
        history_hash=q("select count(*) from history_hash where imgid=1"),
        timestamp_set=q("select change_timestamp > 0 from images where id=1"))


def li_block(x, num):
    return re.search(rf'<rdf:li\b[^>]*darktable:num="{num}"[^>]*/>', x, re.S).group(0)


SCENARIOS = {
    "append": lambda x: xmp.append(xmp.append(x, "exposure", 7, xmp.exposure_params(1.7)),
                                   "crop", 3, xmp.crop_params(0.1, 0.1, 0.9, 0.9)),
    # edit an existing entry in place (what a hand edit of a sidecar often looks like)
    "inplace": lambda x: x.replace(li_block(x, 8), re.sub(r'darktable:params="[^"]*"',
                                   f'darktable:params="{xmp.exposure_params(2.0).hex()}"', li_block(x, 8))),
    # pitfall P3: a second exposure instance, which only exists with an explicit iop_order_list
    "multi": lambda x: xmp.with_iop_order_list(
        xmp.append(x, "exposure", 7, xmp.exposure_params(1.5), multi_priority=1, multi_name="1"),
        open(os.path.join(ROOT, "tools", "iop_order_v4.txt")).read().strip().replace("exposure,0", "exposure,0,exposure,1", 1)),
    # sidecar shorter than the DB history: last entry dropped
    "shorter": lambda x: re.sub(r'darktable:history_end="\d+"', 'darktable:history_end="10"',
                                x.replace(li_block(x, 10), "")),
}


def pixels(path):
    return np.asarray(Image.open(path).convert("RGB")).astype(float)


def main():
    raw_src = sys.argv[1]
    work = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.environ.get("TMPDIR", tempfile.gettempdir()), "lua-reload")
    shutil.rmtree(work, ignore_errors=True)
    photos = os.path.join(work, "photos"); os.makedirs(photos)
    host_dir = os.path.join(work, "host"); os.makedirs(host_dir)
    raw = os.path.join(photos, "A.ARW"); shutil.copy(raw_src, raw)
    host = os.path.join(host_dir, "B.ARW"); shutil.copy(raw_src, host)
    side = raw + ".xmp"

    # library with A imported by darktable itself, which writes the sidecar at import
    c0 = os.path.join(work, "conf0"); os.makedirs(c0)
    dt(c0, raw, os.path.join(work, "o.jpg"), sidecars="on import")
    base = open(side).read()
    d0 = dump(c0)
    print(f"import: {len(d0['history'])} rows, history_end {d0['history_end']}, sidecar {len(xmp.entries(base))} entries\n")

    for name, edit in SCENARIOS.items():
        edited = edit(base)
        open(side, "w").write(edited)
        print(f"=== scenario {name}: sidecar {len(xmp.entries(edited))} entries, history_end {xmp.history_end(edited)}")
        ref = os.path.join(work, f"{name}-ref.jpg"); render.render(raw, side, ref, 400)
        R = pixels(ref)
        conf, D = {}, {}
        for v in ("lua", "dbsync", "cli", "none"):
            conf[v] = os.path.join(work, f"{name}-{v}"); shutil.copytree(c0, conf[v])
        log = dt(conf["lua"], host, os.path.join(work, "h.jpg"), ["--luacmd", f'dofile("{LUA}")'],
                 env={"DARKROOM_SIDECARS": side})
        lua_lines = [l for l in log.splitlines() if l.startswith("RELOAD") or "LUA ERROR" in l]
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "dbsync.py"), side, "--write",
                            "--accept-divergent", "--allow-delete"], capture_output=True, text=True,
                           env={**os.environ, "DARKTABLE_CONFIGDIR": conf["dbsync"]})
        dt(conf["cli"], raw, os.path.join(work, "c.jpg"))
        print("lua log   :", lua_lines)
        print("dbsync log:", r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr.strip())
        # sidecar hidden while rendering from the library: only the DB can drive the render
        os.rename(side, side + ".hidden")
        for v in conf:
            D[v] = dump(conf[v])
            out = os.path.join(work, f"{name}-{v}.jpg"); dt(conf[v], raw, out, size=400, from_db=True)
            diff = np.abs(pixels(out) - R).max()
            print(f"{v:<7} rows {len(D[v]['history']):>2} history_end {D[v]['history_end'][0][0]:>2} "
                  f"hash rows {D[v]['history_hash'][0][0]} | render vs sidecar reference: max diff {diff:.0f}")
        os.rename(side + ".hidden", side)
        for v in ("lua", "cli"):
            for k in D["dbsync"]:
                if D[v][k] != D["dbsync"][k]:
                    print(f"  {v} != dbsync on {k}: {D[v][k] if k != 'history' else 'rows differ'} vs {D['dbsync'][k] if k != 'history' else ''}")
        print()
    extras(work, c0, raw, host, base)


def extras(work, c0, raw, host, base):
    """Side questions, each on its own copy of the library."""
    side = raw + ".xmp"
    edited = SCENARIOS["append"](base)
    open(side, "w").write(edited)
    print("=== extra 1: sidecar rewritten by apply_sidecar?")
    for mode in ("never", "on import", "after edit"):
        c = os.path.join(work, f"x1-{mode.replace(' ', '_')}"); shutil.copytree(c0, c)
        before = open(side, "rb").read()
        dt(c, host, os.path.join(work, "h.jpg"), ["--luacmd", f'dofile("{LUA}")'], env={"DARKROOM_SIDECARS": side},
           sidecars=mode)
        after = open(side, "rb").read()
        print(f"write_sidecar_files={mode:<10} sidecar unchanged: {before == after}, entries {len(xmp.entries(after.decode()))}")
        open(side, "wb").write(before)

    print("=== extra 2: library locked by a running darktable-cli?")
    c = os.path.join(work, "x2"); shutil.copytree(c0, c)
    first = subprocess.Popen([render.cli(), host, os.path.join(work, "slow.jpg"), "--core", "--configdir", c,
                              "--library", os.path.join(c, "library.db"), *FIRST_RUN],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    log = dt(c, host, os.path.join(work, "h2.jpg"), ["--luacmd", f'dofile("{LUA}")'], env={"DARKROOM_SIDECARS": side})
    first.wait()
    print("second instance, same library:", [l.strip() for l in log.splitlines()
                                               if re.search(r"lock|RELOAD|LUA ERROR|already|rror", l)][:4] or "no output")

    print("=== extra 3: two images in one run, plus a path not in the library")
    c = os.path.join(work, "x3"); shutil.copytree(c0, c)
    raw2 = os.path.join(os.path.dirname(raw), "A2.ARW"); shutil.copy(raw, raw2)
    open(side, "w").write(base)
    dt(c, raw2, os.path.join(work, "o2.jpg"), sidecars="on import")
    base2 = open(raw2 + ".xmp").read()
    open(side, "w").write(edited); open(raw2 + ".xmp", "w").write(SCENARIOS["inplace"](base2))
    paths = [side, raw2 + ".xmp", os.path.join(work, "nowhere", "Z.ARW.xmp")]
    log = dt(c, host, os.path.join(work, "h3.jpg"), ["--luacmd", f'dofile("{LUA}")'],
             env={"DARKROOM_SIDECARS": "\n".join(paths)})
    print("\n".join(l for l in log.splitlines() if l.startswith("RELOAD")))
    db = sqlite3.connect(os.path.join(c, "library.db"))
    print("rows per image:", db.execute("select imgid, count(*) from history group by imgid").fetchall())


if __name__ == "__main__":
    main()
