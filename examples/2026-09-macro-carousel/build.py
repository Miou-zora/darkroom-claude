"""Reference script from the session that produced this plugin (8-photo macro carousel,
September 2026). Kept as a worked example, not as a tool: photo names, crops and exposure
values are specific to that shoot. Comments are in French.

    PHOTO_DIR=/path/to/raws python3 build.py '{"00968":1.4}' [names]

Expects untouched sidecar copies in ./originals/ and writes candidates to ./tmpxmp/ and ./out/.
"""
"""Construit les XMP du carrousel dans tmpxmp/, rend et mesure. N'ecrit rien dans 08:2026."""
import sys, os, struct, sqlite3, subprocess, json
import numpy as np
from PIL import Image
S = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, S)
sys.path.insert(0, os.path.join(S, "..", "..", "tools"))
from xmp import *

D  = os.environ["PHOTO_DIR"]            # folder holding the RAW files and their sidecars
DT = "/Applications/darktable.app/Contents/MacOS/darktable-cli"

# Ratio naturel par photo (Instagram accepte 1,91:1 a 4:5). None = pas de crop ajoute :
# on garde le recadrage du photographe s'il existe (823 4:3, 846 ~5:4, 954 3:2), sinon plein cadre 3:2.
# 01103 : portrait 2:3 hors limites Instagram, donc 4:5 serre sur la sauterelle.
KLP = 4024 / 6048                # portrait : largeur / hauteur de l'entree du crop
W45 = 0.8 / KLP                  # 4:5 portrait : largeur = hauteur * W45
CROPS = {n: None for n in ("00823", "00846", "00871", "00954", "00968", "01014", "01033")}
CROPS["01103"] = (0.42 - 0.14*W45, 0.373, 0.42 + 0.14*W45, 0.653)
# 2026-09-27 : lisibilite sur telephone (~400 px d'affichage). Meme ratio, cadre resserre.
# largeur normalisee = hauteur normalisee * ratio * 4024/6048
K = 4024 / 6048
def box(cx, cy, h, ratio):
    w = h * ratio * K
    return (cx - w/2, cy - h/2, cx + w/2, cy + h/2)
CROPS["00846"] = box(0.48, 0.50, 0.60, 1080/910)    # etait 0,235-0,985 : punaise 20 % -> 23 % larg., 58 % haut.
CROPS["00871"] = box(0.50, 0.505, 0.78, 1.5)      # fleur (y 0,15) et bas des ailes (0,87) dans le cadre         # pieride 25 % -> 40 %
CROPS["00968"] = box(0.50, 0.48, 0.80, 1.5)         # nacre 54 % -> 67 %
CROPS["01014"] = box(0.46, 0.48, 0.50, 1.5)         # criquet 30 % -> 64 %
for n, c in CROPS.items():
    if c: assert 0 <= c[0] < c[2] <= 1 and 0 <= c[1] < c[3] <= 1, (n, c)

STYLE_OPS = ("sigmoid", "colorbalancergb", "denoiseprofile", "diffuse")
VIERGES = ("00968", "01014", "01103")

def style_items():
    db = sqlite3.connect(os.path.expanduser("~/.config/darktable/data.db"))
    q = ("select operation, op_params, blendop_params, multi_priority, multi_name from style_items "
         "where styleid=(select id from styles where name='Macro-base2') order by num")
    mods = {"sigmoid": 3, "colorbalancergb": 5, "denoiseprofile": 12, "diffuse": 2}
    return [(op, mods[op], p, bl, mp, mn) for op, p, bl, mp, mn in db.execute(q) if op in STYLE_OPS]

def exposure_params(ev):
    # mode manuel, black, exposure, deflicker percentile, deflicker target, compensate bias, _
    return struct.pack("<i4fii", 0, -0.000244140625, ev, 50.0, -4.0, 1, 1)

def build(n, ev=None):
    x = open(f"{S}/originals/DSC{n}.ARW.xmp").read()   # untouched copies of the sidecars
    if n in VIERGES:
        for op, mv, p, bl, mp, mn in style_items():
            x = append(x, op, mv, p, multi_priority=mp, multi_name=mn, blendop=bl.hex())
        x = append(x, "exposure", 7, exposure_params(ev))
        # sans iop_order_list, la 2e instance de colorbalancergb est ignoree en
        # silence (params ok, ecart nul). Liste v4 reprise de DSC01033, doublons retires.
        assert "iop_order_list" not in x
        IOP = open(os.path.join(S, "..", "..", "tools", "iop_order_v4.txt")).read()
        x = x.replace('darktable:iop_order_version="4"',
                      f'darktable:iop_order_version="4"\n   darktable:iop_order_list="{IOP}"', 1)
    if CROPS[n]:
        x = append(x, "crop", 3, crop_params(*CROPS[n]))
    out = f"{S}/tmpxmp/DSC{n}.xmp"; open(out, "w").write(x)
    return out

def render(n, xmp, out, size=1080):
    # darktable-cli n'ecrase jamais : il ecrit out_01.jpg a cote, et on mesurerait l'ancien
    assert out.startswith(S + "/")
    if os.path.exists(out): os.remove(out)
    r = subprocess.run([DT, f"{D}/DSC{n}.ARW", xmp, out, "--width", str(size), "--height", str(size),
                        "--hq", "true", "--apply-custom-presets", "false",
                        "--core", "--configdir", f"{S}/dtconf", "--library", ":memory:", "-d", "params"],
                       capture_output=True, text=True)
    log = r.stdout + r.stderr
    return r.returncode, log.count("params ok"), log.lower().count("wrong")

def stats(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(float)
    L = (0.2126*a[..., 0] + 0.7152*a[..., 1] + 0.0722*a[..., 2]) / 255
    p = np.percentile(L, [1, 50, 99.5])
    return dict(size=Image.open(path).size, p1=round(p[0], 3), p50=round(p[1], 3), p995=round(p[2], 3),
                clip=round(float((a.max(2) >= 254).mean()*100), 3))

if __name__ == "__main__":
    evs = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    os.makedirs(f"{S}/out", exist_ok=True)
    for n in sys.argv[2].split(",") if len(sys.argv) > 2 else CROPS:
        xmp = build(n, evs.get(n))
        rc, ok, bad = render(n, xmp, f"{S}/out/DSC{n}.jpg")
        print(n, f"ev {evs.get(n)}", f"exit {rc} params ok {ok} wrong {bad}", stats(f"{S}/out/DSC{n}.jpg"), flush=True)
