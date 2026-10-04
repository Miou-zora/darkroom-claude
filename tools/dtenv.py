"""Platform-dependent lookups shared by the tools and the PreToolUse hook.

    darktable_running()  is darktable open right now (pgrep on macOS/Linux, tasklist on Windows)
    config_dir()         darktable's config directory (holds library.db)
    cache_dir()          where our own throwaway darktable config lives
    out_arg(path)        an output path as darktable-cli must receive it
    cli_candidates()     where darktable-cli may be, best guess first

Keep this file free of imports from the rest of the repo: the hook loads it by path.
"""
import ntpath, os, shutil, subprocess, sys


def _win():
    return sys.platform == "win32"


def darktable_running():
    """True when a darktable GUI process exists. Fails closed: if the process list cannot
    be read, answer True, because a wrong False lets a write be clobbered silently."""
    try:
        if _win():
            # tasklist exits 0 with or without a match, so the output decides. darktable-cli.exe
            # does not match "darktable.exe".
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq darktable.exe", "/NH", "/FO", "CSV"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            return r.returncode != 0 or "darktable.exe" in r.stdout.lower()
        return subprocess.run(["pgrep", "-x", "darktable"], capture_output=True).returncode == 0
    except OSError:
        return True


def pid_alive(pid):
    """True when a process with this pid exists. os.kill(pid, 0) is not a probe on Windows:
    signal 0 is CTRL_C_EVENT there and interrupts the target. Fails closed like darktable_running."""
    try:
        if _win():
            r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            return r.returncode != 0 or f'"{int(pid)}"' in r.stdout
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True  # exists, owned by someone else
    except ProcessLookupError:
        return False
    except OSError:
        return True


def out_arg(path):
    """Output path for darktable-cli. On Windows it runs the path through its variable expansion,
    which eats backslashes: `C:\\tmp\\a.jpg` is written as `C:tmpa.jpg`, relative to the cwd of drive
    C:, and the file is not where the caller looks. Forward slashes survive. Input and config
    paths are not expanded and may keep backslashes."""
    return str(path).replace("\\", "/") if _win() else str(path)


def config_dir():
    env = os.environ.get("DARKTABLE_CONFIGDIR")
    if env:
        return env
    if _win():
        return ntpath.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local"), "darktable")
    return os.path.expanduser("~/.config/darktable")


def cache_dir():
    if _win():
        return os.environ.get("LOCALAPPDATA") or ntpath.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.expanduser(os.environ.get("XDG_CACHE_HOME", "~/.cache"))


def cli_candidates():
    c = [os.environ.get("DARKTABLE_CLI", ""),
         "/Applications/darktable.app/Contents/MacOS/darktable-cli"]
    if _win():
        c += [ntpath.join(os.environ[v], "darktable", "bin", "darktable-cli.exe")
              for v in ("ProgramFiles", "ProgramW6432") if os.environ.get(v)]
    return c + [shutil.which("darktable-cli") or ""]
