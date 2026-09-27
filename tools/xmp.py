#!/usr/bin/env python3
"""Read and append darktable history entries in an XMP sidecar.

    python3 xmp.py show  photo.ARW.xmp         decoded history, one line per entry
    python3 xmp.py check photo.ARW.xmp         history_end vs entry count, iop_order_list

As a module: entries(), history_end(), append(), decode_blob(), crop_params(),
exposure_params(), with_iop_order_list().

Existing entries are never modified: darktable keeps the last entry of each
(operation, multi_priority) pair, so a change is always a new entry.
"""
import re, struct, base64, zlib, sys

# Neutral blend parameters (blendop_version 14), taken from a crop entry written by darktable 5.6.
NEUTRAL_BLEND = "gz11eJxjYIAACQYYOOHEgAZY0QWAgBGLGANDgz0Ej1Q+dcF/IADRAGpyHQU="


def decode_blob(s):
    """XMP blob to raw bytes. Either lowercase hex, or 'gz' + 2 digits + base64(zlib)."""
    if s.startswith("gz"):
        return zlib.decompress(base64.b64decode(s[4:]))
    return bytes.fromhex(s)


def entries(x):
    m = re.search(r"<darktable:history>\s*<rdf:Seq>(.*?)</rdf:Seq>", x, re.S)
    if not m:
        return []
    return [dict(re.findall(r'darktable:(\w+)="([^"]*)"', li))
            for li in re.findall(r"<rdf:li\b(.*?)/>", m.group(1), re.S)]


def history_end(x):
    return int(re.search(r'darktable:history_end="(\d+)"', x).group(1))


def append(x, operation, modversion, params, enabled=1, multi_priority=0,
           multi_name="", blendop=NEUTRAL_BLEND):
    """Append one history entry. `params` are raw bytes, written as lowercase hex:
    uppercase hex is decoded as garbage and the module is silently dropped."""
    ents, end = entries(x), history_end(x)
    if end != len(ents):
        raise ValueError(f"history_end {end} != {len(ents)} entries: the history was "
                         "truncated in darktable (undo); refusing to append after it")
    li = (f'\n     <rdf:li\n'
          f'      darktable:num="{end}"\n'
          f'      darktable:operation="{operation}"\n'
          f'      darktable:enabled="{enabled}"\n'
          f'      darktable:modversion="{modversion}"\n'
          f'      darktable:params="{params.hex()}"\n'
          f'      darktable:multi_name="{multi_name}"\n'
          f'      darktable:multi_name_hand_edited="0"\n'
          f'      darktable:multi_priority="{multi_priority}"\n'
          f'      darktable:blendop_version="14"\n'
          f'      darktable:blendop_params="{blendop}"/>')
    i = x.index("</rdf:Seq>", x.index("<darktable:history>"))
    x = x[:i].rstrip() + li + "\n    " + x[i:]
    return x.replace(f'darktable:history_end="{end}"', f'darktable:history_end="{end + 1}"', 1)


def with_iop_order_list(x, iop_list):
    """A second instance of a module (multi_priority 1) is silently ignored unless the
    sidecar carries an explicit iop_order_list that contains it."""
    if "darktable:iop_order_list=" in x:
        return re.sub(r'darktable:iop_order_list="[^"]*"', f'darktable:iop_order_list="{iop_list}"', x, count=1)
    m = re.search(r'darktable:iop_order_version="\d+"', x)
    if not m:
        raise ValueError("no iop_order_version in sidecar")
    return x[:m.end()] + f'\n   darktable:iop_order_list="{iop_list}"' + x[m.end():]


def crop_params(left, top, right, bottom, ratio_n=0, ratio_d=0):
    """crop v3. Edges are normalized to the module input, i.e. after flip and ashift."""
    return struct.pack("<4f2i", left, top, right, bottom, ratio_n, ratio_d)


def exposure_params(ev, black=-0.000244140625):
    """exposure v7: int mode, float black, float exposure, float deflicker percentile,
    float deflicker target, int compensate camera bias, int (unused here)."""
    return struct.pack("<i4fii", 0, black, ev, 50.0, -4.0, 1, 1)


def _floats(b):
    n = len(b) // 4
    return [round(v, 4) for v in struct.unpack(f"<{n}f", b[:n * 4])]


def main(argv):
    if len(argv) != 3 or argv[1] not in ("show", "check"):
        print("usage: xmp.py show|check SIDECAR.xmp"); return 2
    x = open(argv[2]).read()
    ents, end = entries(x), history_end(x)
    if argv[1] == "check":
        lst = re.search(r'darktable:iop_order_list="([^"]*)"', x)
        multi = sorted({e["operation"] for e in ents if e.get("multi_priority", "0") != "0"})
        print(f"entries {len(ents)}, history_end {end}, "
              f"{'OK' if end == len(ents) else 'TRUNCATED (entries after history_end are inactive)'}")
        print(f"iop_order_list: {'present' if lst else 'absent'}; multi-instance modules: {multi or 'none'}")
        if multi and not lst:
            print("WARNING: multi-instance modules without iop_order_list are ignored at render time")
        return 0
    for e in ents:
        b = decode_blob(e["params"])
        print(f'{e["num"]:>3} {e["operation"]:<18} v{e["modversion"]:<3} '
              f'{"on " if e["enabled"] == "1" else "off"} mp{e.get("multi_priority", "0")} '
              f'{len(b):>4}B {_floats(b)[:10]}')
    print(f"history_end {end} / {len(ents)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
