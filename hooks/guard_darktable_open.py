#!/usr/bin/env python3
"""PreToolUse hook: block writes to darktable sidecars or library.db while darktable runs.

darktable trusts library.db over the sidecar for images already in the library and
rewrites the sidecar from the DB when it opens and closes an image. A sidecar edited
while darktable is open is overwritten without warning.

Reads the hook payload on stdin. Exit 2 blocks the tool call and shows stderr to Claude.
Reads (cat, grep, python reading a file) are never blocked.
"""
import json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from dtenv import darktable_running  # pgrep, or tasklist on Windows

WRITE_BASH = re.compile(
    r"(dbsync\.py[^|;&]*--write)"                                   # our own DB sync
    r"|(sqlite3[^|;&]*library\.db[^|;&]*\b(insert|update|delete|replace)\b)"
    r"|((\bcp\b|\bmv\b|\btee\b|sed\s+-i|>)[^|;&]*\.xmp\b)", re.I)

# Python writing a sidecar or the DB: inline (-c, heredoc) or a script file read from disk.
PYTHON = re.compile(r"\bpython[\d.]*\b")
PY_SCRIPT = re.compile(r"\bpython[\d.]*\s+(?:-[^\s;&|<>]+\s+)*([^\s;&|<>'\"-][^\s;&|<>'\"]*\.py)\b")
PY_TARGET = re.compile(r"(?<!tools)\.xmp\b(?![ \t]+import)|library\.db", re.I)  # tools.xmp is the module
PY_WRITE = re.compile(
    r"open\([^)]*['\"][rbt]*[wax+][rbtwax+]*['\"]"                    # open(..., 'w'|'a'|'wb'|'r+')
    r"|\.write_(text|bytes)\(|(?<!stdout)(?<!stderr)\.write\("          # Path.write_text, ET tree.write
    r"|shutil\.(copy\w*|move)\(|os\.(replace|rename)\("
    r"|\.executescript\(|\b(insert\s+into|update\s+\w+\s+set|delete\s+from|replace\s+into)\b", re.I)
OUR_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools") + os.sep


def python_writes(cmd, cwd):
    """Heuristic: python code that names a sidecar or library.db and has a write signal.
    Covers inline code and a script file named in the command (written first, run later)."""
    if not PYTHON.search(cmd):
        return False
    text = cmd
    for name in PY_SCRIPT.findall(cmd):
        path = os.path.abspath(os.path.join(cwd, os.path.expanduser(name)))
        if path.startswith(OUR_TOOLS):
            continue  # our tools are covered by their own flags (dbsync.py --write)
        try:
            text += "\n" + open(path, errors="replace").read()
        except OSError:
            pass
    return bool(PY_TARGET.search(text) and PY_WRITE.search(text))


def is_write(tool, inp, cwd=None):
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path", "")
        return path.endswith(".xmp") or path.endswith("library.db")
    if tool == "Bash":
        cmd = inp.get("command", "")
        return bool(WRITE_BASH.search(cmd)) or python_writes(cmd, cwd or os.getcwd())
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if is_write(payload.get("tool_name", ""), payload.get("tool_input", {}) or {}, payload.get("cwd")) and darktable_running():
        print("darkroom-claude: darktable is running. It rewrites sidecars from library.db when it "
              "opens or closes an image, so this write would be lost or would corrupt the history. "
              "Ask the user to quit darktable, then check again (`pgrep -x darktable`, or `tasklist` "
              "on Windows) right before writing.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
