#!/usr/bin/env python3
"""Reload edited XMP sidecars into darktable's library through its Lua API.

    python3 reload.py SIDECAR.xmp [...] [--host IMAGE]

Default way to make darktable take a hand-edited sidecar (darktable must be closed). It runs
reload_sidecars.lua (`image:apply_sidecar`, Lua API 9.5.0 or newer) inside a headless
darktable-cli, so darktable writes library.db itself and no schema is involved. Fallback for an
older darktable or a build without Lua: dbsync.py.

- Refuses while darktable runs or the library is locked, backs library.db up first.
- darktable-cli always needs an image to export: --host (default: another image of the library)
  is exported at 8 px to a temp folder and thrown away.
- Success needs a `RELOAD ok` line per sidecar. The exit code proves nothing: darktable skips
  --luacmd on a config whose Lua first run is not done, and exits 0.
- Then checks with dbsync.plan() (dry run): the DB must hold exactly the sidecar's history.

Config dir: $DARKTABLE_CONFIGDIR, default ~/.config/darktable (same as dbsync.py).
"""
import os, sys, time, shutil, sqlite3, argparse, tempfile, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbsync, render
from dtenv import pid_alive

LUA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reload_sidecars.lua")
TIMEOUT = 600


def library_locked(conf):
    """darktable keeps library.db.lock with its pid (NUL terminated) while it owns the library."""
    try:
        pid = int(open(os.path.join(conf, "library.db.lock")).read().strip("\0 \n"))
    except (OSError, ValueError, IndexError):
        return False
    return pid_alive(pid)


def default_host(db, sidecars):
    """First library image whose file exists and which is not one of the images to reload."""
    for folder, name in db.execute("select f.folder, i.filename from images i join film_rolls f "
                                   "on f.id = i.film_id order by i.id"):
        path = os.path.join(folder, name)
        if os.path.exists(path) and path + ".xmp" not in sidecars:
            return path


def run_lua(conf, host, sidecars):
    """One darktable-cli run hosting the Lua script. Returns (exit code, output lines)."""
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [render.cli(), host, os.path.join(tmp, "host.jpg"), "--width", "8", "--height", "8",
               "--core", "--configdir", conf, "--library", os.path.join(conf, "library.db"),
               "--conf", "write_sidecar_files=never",
               "--conf", "lua/luarc/darktable_first_run_complete=TRUE",
               "--luacmd", f"dofile([==[{LUA}]==])"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT,
                           env={**os.environ, "DARKROOM_SIDECARS": "\n".join(sidecars)})
    return r.returncode, (r.stdout + r.stderr).splitlines()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sidecars", nargs="+")
    ap.add_argument("--host", help="image darktable-cli exports to host the run (default: another library image)")
    a = ap.parse_args(argv)
    sidecars = [os.path.abspath(s) for s in a.sidecars]
    missing = [s for s in sidecars if not os.path.exists(s)]
    if missing or any("\n" in s for s in sidecars):
        print(f"refused: missing sidecar or newline in path: {missing}"); return 1
    lib = dbsync.library_path()
    conf = os.path.dirname(lib)
    if not os.path.exists(lib):
        print(f"refused: no library at {lib}"); return 1
    if dbsync.darktable_running() or library_locked(conf):
        print("refused: darktable is running or holds the library; it would overwrite the DB and sidecars on close")
        return 1
    db = sqlite3.connect(lib)
    host = a.host or default_host(db, sidecars)
    db.close()
    if not host:
        print("refused: no other image in the library to host the run, pass --host"); return 1
    backup = f"{lib}-darkroom-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(lib, backup); print(f"backup: {backup}")

    code, lines = run_lua(conf, host, sidecars)
    results = [l.split(" ", 2) for l in lines if l.startswith("RELOAD ")]
    ok = {r[2] for r in results if r[1] == "ok"}
    for l in lines:
        if l.startswith("RELOAD ") or "LUA ERROR" in l:
            print(l)
    bad = [s for s in sidecars if s not in ok]
    if bad:
        print(f"FAILED: no 'RELOAD ok' for {bad} (darktable-cli exit {code}). Library backup: {backup}")
        return 1

    db = sqlite3.connect(lib)
    plans = [dbsync.plan(db, s) for s in sidecars]
    drift = [p["sidecar"] for p in plans if "error" in p or p["insert"] or p["delete"] or p["diverge"]
             or db.execute("select history_end from images where id=?", (p["imgid"],)).fetchone()[0] != p["history_end"]]
    for p in plans:
        print(dbsync.report(p))
    if drift:
        print(f"FAILED: library differs from the sidecar after reload: {drift}. Library backup: {backup}")
        return 1
    print(f"reloaded and verified: {len(sidecars)} sidecar(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
