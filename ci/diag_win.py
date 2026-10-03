"""THROWAWAY (#31): run darktable-cli by hand on the Windows runner, print everything."""
import os, sys, subprocess, time, tempfile, glob
sys.path.insert(0, "tools")
import render, xmp, dtenv

raw = os.environ["DARKROOM_SAMPLE"]
base = xmp.append(open("tests/fixtures/minimal.xmp", encoding="utf-8").read(), "exposure", 7, xmp.exposure_params(0.7))
work = tempfile.mkdtemp(prefix="dtdiag")
side = os.path.join(work, "s0.xmp"); open(side, "w", encoding="utf-8").write(base)
print("cli      :", render.cli())
print("CONF     :", render.CONF)
print("work     :", work, "cwd:", os.getcwd())
start = time.time()


def run(label, out, extra, timeout=60):
    if os.path.exists(out): os.remove(out)
    cmd = [render.cli(), raw, side, out, "--hq", "true", "--upscale", "false", "--apply-custom-presets", "false",
           "--width", "400", "--height", "400"] + extra
    print(f"\n=== {label}\nCMD: {cmd}", flush=True)
    so, se = os.path.join(work, label[0] + ".out"), os.path.join(work, label[0] + ".err")
    with open(so, "wb") as fo, open(se, "wb") as fe:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            rc = "TIMEOUT"
            print("tasklist during hang:", subprocess.run(["tasklist"], capture_output=True, text=True).stdout[-1500:])
            print("exists(out) during hang:", os.path.exists(out), "| listdir:", sorted(os.listdir(os.path.dirname(out) or ".")))
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    print("exit:", rc)
    for f in (so, se):
        t = open(f, encoding="utf-8", errors="replace").read().splitlines()
        print(f"{os.path.basename(f)} ({len(t)} lines) tail:", "\n".join(t[-25:]))
    print("exists(out):", os.path.exists(out), "| listdir:", sorted(os.listdir(os.path.dirname(out) or ".")), flush=True)


os.makedirs(render.CONF, exist_ok=True)
std = ["--core", "--configdir", render.CONF, "--library", ":memory:", "--conf", "write_sidecar_files=never", "-d", "params"]
run("A render.py args, backslash out", os.path.join(work, "a.jpg"), std)
run("B forward-slash out", os.path.join(work, "b.jpg").replace("\\", "/"), std)
run("C no --library :memory:", os.path.join(work, "c.jpg"), ["--core", "--configdir", render.CONF, "--conf", "write_sidecar_files=never"])
run("D no core options at all", os.path.join(work, "d.jpg"), [])
run("E out in cwd (relative)", "e.jpg", std)
run("F only configdir and library", os.path.join(work, "f.jpg"), ["--core", "--configdir", render.CONF, "--library", ":memory:"])

print("\n=== any image written since start, anywhere likely")
roots = {work, os.getcwd(), os.path.dirname(raw), tempfile.gettempdir(), os.path.expanduser("~"), "C:\\darktable", "C:\\dt"}
for root in roots:
    for p in glob.glob(os.path.join(root, "**", "*"), recursive=True):
        try:
            if os.path.isfile(p) and os.path.getmtime(p) >= start and p.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                print("FOUND", p, os.path.getsize(p))
        except OSError:
            pass
