"""THROWAWAY (#31): the first darktable-cli run of a Windows job sometimes hangs after rawspeed init."""
import os, sys, subprocess, time, tempfile
sys.path.insert(0, "tools")
import render, xmp, dtenv

raw = os.environ["DARKROOM_SAMPLE"]
base = xmp.append(open("tests/fixtures/minimal.xmp", encoding="utf-8").read(), "exposure", 7, xmp.exposure_params(0.7))
work = tempfile.mkdtemp(prefix="dtdiag")
side = os.path.join(work, "s0.xmp"); open(side, "w", encoding="utf-8").write(base)


def run(label, tag, extra, timeout=100):
    out = os.path.join(work, tag + ".jpg")
    cmd = [render.cli(), raw, side, dtenv.out_arg(out), "--width", "400", "--height", "400"] + extra
    print(f"\n=== {label}\nCMD: {cmd}", flush=True)
    log = os.path.join(work, tag + ".log")
    t0 = time.time()
    with open(log, "wb") as f:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT)
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            rc = "TIMEOUT"
            ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                                 "Get-Process | Where-Object {$_.Name -match 'dark|Wer|conhost|fc-|OpenCL'} | "
                                 "Format-Table Name,Id,CPU,Threads,WS -AutoSize | Out-String -Width 200"],
                                capture_output=True, text=True).stdout
            print("processes during hang:\n", ps)
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    t = open(log, encoding="utf-8", errors="replace").read().splitlines()
    print(f"exit={rc} after {time.time() - t0:.1f}s, written={os.path.exists(out)}, {len(t)} log lines; tail:")
    print("\n".join(l[:240] for l in t[-70:]), flush=True)
    return rc


conf = os.path.join(work, "conf")
std = ["--core", "--configdir", conf, "--library", ":memory:", "--conf", "write_sidecar_files=never"]
a = run("A cold run, -d all", "a", std + ["-d", "all"])
b = run("B same again, no -d", "b", std)
c = run("C fresh config dir, --disable-opencl", "c", ["--core", "--configdir", os.path.join(work, "conf2"), "--library", ":memory:",
                                                      "--disable-opencl", "--conf", "write_sidecar_files=never"])
print("\nRESULT", a, b, c)
