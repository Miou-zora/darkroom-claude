#!/usr/bin/env python3
"""PreToolUse hook: block writes to darktable sidecars or library.db while darktable runs.

darktable trusts library.db over the sidecar for images already in the library and
rewrites the sidecar from the DB when it opens and closes an image. A sidecar edited
while darktable is open is overwritten without warning.

Reads the hook payload on stdin. Exit 2 blocks the tool call and shows stderr to Claude.
Reads (cat, grep, python reading a file) are never blocked.
"""
import json, re, subprocess, sys

WRITE_BASH = re.compile(
    r"(dbsync\.py[^|;&]*--write)"                                   # our own DB sync
    r"|(sqlite3[^|;&]*library\.db[^|;&]*\b(insert|update|delete|replace)\b)"
    r"|((\bcp\b|\bmv\b|\btee\b|sed\s+-i|>)[^|;&]*\.xmp\b)", re.I)


def darktable_running():
    return subprocess.run(["pgrep", "-x", "darktable"], capture_output=True).returncode == 0


def is_write(tool, inp):
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path", "")
        return path.endswith(".xmp") or path.endswith("library.db")
    if tool == "Bash":
        return bool(WRITE_BASH.search(inp.get("command", "")))
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if is_write(payload.get("tool_name", ""), payload.get("tool_input", {}) or {}) and darktable_running():
        print("darkroom-claude: darktable is running. It rewrites sidecars from library.db when it "
              "opens or closes an image, so this write would be lost or would corrupt the history. "
              "Ask the user to quit darktable, then check again with `pgrep -x darktable` right "
              "before writing.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
