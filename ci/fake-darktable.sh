#!/bin/bash
# Stand-in for a running darktable, so evals/ can exercise hooks/guard_darktable_open.py.
# The hook runs `pgrep -x darktable`; a copy of `sleep` named `darktable` satisfies it.
#   ci/fake-darktable.sh start | stop
# Linux (CI) only: macOS refuses to run a copied system binary.
set -eu
DIR="${TMPDIR:-/tmp}/darkroom-fake-darktable"
case "${1:-}" in
  start)
    mkdir -p "$DIR"
    cp "$(command -v sleep)" "$DIR/darktable"
    "$DIR/darktable" 3600 &
    echo $! > "$DIR/pid"
    sleep 0.5
    pgrep -x darktable > /dev/null || { echo "fake darktable did not start" >&2; exit 1; }
    echo "fake darktable running (pid $(cat "$DIR/pid"))" ;;
  stop)
    [ -f "$DIR/pid" ] && kill "$(cat "$DIR/pid")" 2> /dev/null || true
    rm -rf "$DIR" ;;
  *) echo "usage: $0 start|stop" >&2; exit 2 ;;
esac
