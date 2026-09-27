#!/usr/bin/env python3
"""Align darktable's library.db on edited XMP sidecars. Dry run by default.

    python3 dbsync.py SIDECAR.xmp [...]                      report only
    python3 dbsync.py SIDECAR.xmp [...] --write              apply (darktable must be closed)
      --accept-divergent  also rewrite rows where the DB and the XMP disagree
      --allow-delete      also delete DB rows beyond the XMP history

Why: for an image already in the library, darktable trusts library.db over the
sidecar and rewrites the sidecar from the DB on open and on close. A hand-edited
XMP is therefore lost unless the DB carries the same history.

This writes to darktable's internal database, whose schema is not a public API.
Every --write backs the DB up first, runs in one transaction and ends with
PRAGMA integrity_check. Tested against darktable 5.6.
"""
import os, re, sys, time, shutil, sqlite3, subprocess, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xmp import entries, history_end, decode_blob

GDATETIME_EPOCH_OFFSET = 62135596800  # images.change_timestamp: microseconds since year 1


def library_path():
    base = os.environ.get("DARKTABLE_CONFIGDIR", os.path.expanduser("~/.config/darktable"))
    return os.path.join(base, "library.db")


def darktable_running():
    return subprocess.run(["pgrep", "-x", "darktable"], capture_output=True).returncode == 0


def locate(db, sidecar):
    """Sidecar path -> (imgid, filename, version). NAME.EXT.xmp is version 0,
    NAME_01.EXT.xmp is version 1 of NAME.EXT."""
    folder, base = os.path.split(os.path.abspath(sidecar))
    raw = base[:-4]
    m = re.match(r"^(.*)_(\d{2})(\.[^.]+)$", raw)
    version = 0
    if m and not os.path.exists(os.path.join(folder, raw)):
        raw, version = m.group(1) + m.group(3), int(m.group(2))
    row = db.execute("select i.id from images i join film_rolls f on f.id = i.film_id "
                     "where f.folder = ? and i.filename = ? and i.version = ?",
                     (folder, raw, version)).fetchone()
    return (row[0] if row else None), raw, version


def row(e):
    return (int(e["num"]), int(e["modversion"]), e["operation"], decode_blob(e["params"]),
            int(e["enabled"]), decode_blob(e["blendop_params"]), int(e["blendop_version"]),
            int(e["multi_priority"]), e["multi_name"], int(e.get("multi_name_hand_edited", "0")))


COLS = ("num, module, operation, op_params, enabled, blendop_params, blendop_version, "
        "multi_priority, multi_name, multi_name_hand_edited")


def plan(db, sidecar):
    iid, raw, version = locate(db, sidecar)
    if iid is None:
        return dict(sidecar=sidecar, error=f"{raw} (version {version}) not found in library.db")
    x = open(sidecar).read()
    ents = [row(e) for e in entries(x)]
    have = db.execute(f"select {COLS} from history where imgid = ? order by num", (iid,)).fetchall()
    diverge = [h[0] for h, e in zip(have, ents) if tuple(h) != e]
    lst = re.search(r'darktable:iop_order_list="([^"]*)"', x)
    return dict(sidecar=sidecar, imgid=iid, x=x, ents=ents, have=have, diverge=diverge,
                insert=ents[len(have):], delete=[h[0] for h in have[len(ents):]],
                history_end=history_end(x), iop_list=lst.group(1) if lst else None)


def report(p):
    if "error" in p:
        return f"{p['sidecar']}: ERROR {p['error']}"
    ops = lambda rows: ", ".join(f"{r[0]}:{r[2]}" for r in rows) or "none"
    return (f"{os.path.basename(p['sidecar'])} imgid {p['imgid']}: DB {len(p['have'])} rows, "
            f"XMP {len(p['ents'])}; insert [{ops(p['insert'])}]; delete {p['delete'] or 'none'}; "
            f"divergent {p['diverge'] or 'none'}")


def apply(db, p):
    iid = p["imgid"]
    for k in p["diverge"]:
        e = p["ents"][k]
        db.execute("update history set module=?, operation=?, op_params=?, enabled=?, blendop_params=?, "
                   "blendop_version=?, multi_priority=?, multi_name=?, multi_name_hand_edited=? "
                   "where imgid=? and num=?", e[1:] + (iid, k))
    for k in p["delete"]:
        db.execute("delete from history where imgid=? and num=?", (iid, k))
    for e in p["insert"]:
        db.execute(f"insert into history (imgid, {COLS}) values (?,?,?,?,?,?,?,?,?,?,?)", (iid,) + e)
    db.execute("update images set history_end=?, change_timestamp=? where id=?",
               (p["history_end"], int((time.time() + GDATETIME_EPOCH_OFFSET) * 1e6), iid))
    if p["iop_list"]:
        if db.execute("select 1 from module_order where imgid=?", (iid,)).fetchone():
            db.execute("update module_order set iop_list=? where imgid=?", (p["iop_list"], iid))
        else:
            v = int(re.search(r'darktable:iop_order_version="(\d+)"', p["x"]).group(1))
            db.execute("insert into module_order (imgid, version, iop_list) values (?,?,?)",
                       (iid, v, p["iop_list"]))
    db.execute("delete from history_hash where imgid=?", (iid,))  # darktable recomputes it


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sidecars", nargs="+")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--accept-divergent", action="store_true")
    ap.add_argument("--allow-delete", action="store_true")
    a = ap.parse_args()
    path = library_path()
    db = sqlite3.connect(path)
    plans = [plan(db, s) for s in a.sidecars]
    for p in plans:
        print(report(p))
    blockers = [p["sidecar"] for p in plans if "error" in p]
    blockers += [p["sidecar"] for p in plans if p.get("diverge") and not a.accept_divergent]
    blockers += [p["sidecar"] for p in plans if p.get("delete") and not a.allow_delete]
    if not a.write:
        print("dry run: nothing written" + (f"; would refuse: {blockers}" if blockers else ""))
        return 0
    if blockers:
        print(f"refused, nothing written: {blockers}"); return 1
    if darktable_running():
        print("refused: darktable is running and would overwrite the DB and sidecars on close"); return 1
    backup = f"{path}-darkroom-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup); print(f"backup: {backup}")
    try:
        for p in plans:
            apply(db, p)
        db.commit()
    except Exception:
        db.rollback(); raise
    check = db.execute("pragma integrity_check").fetchone()[0]
    print(f"committed; integrity_check: {check}")
    return 0 if check == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
