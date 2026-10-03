"""Platform lookups, run on every OS with sys.platform and subprocess mocked."""
import ntpath, sqlite3, subprocess, sys
import pytest
import dtenv, dbsync


class Done:
    def __init__(self, rc=0, out=""):
        self.returncode, self.stdout = rc, out


def fake_run(monkeypatch, result):
    calls = []
    def run(cmd, **kw):
        calls.append(cmd)
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_posix_uses_pgrep(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    calls = fake_run(monkeypatch, Done(0))
    assert dtenv.darktable_running() is True
    assert calls == [["pgrep", "-x", "darktable"]]
    fake_run(monkeypatch, Done(1))
    assert dtenv.darktable_running() is False


@pytest.mark.parametrize("out,expected", [
    ('"darktable.exe","4242","Console","1","310,000 K"\r\n', True),
    ('"Darktable.EXE","4242","Console","1","310,000 K"\n', True),
    ("INFO: No tasks are running which match the specified criteria.\r\n", False),
    ("INFO : Aucune tâche en service ne correspond aux critères spécifiés.\r\n", False),
    ('"darktable-cli.exe","77","Console","1","90,000 K"\r\n', False),
    ("", False),
])
def test_windows_uses_tasklist(monkeypatch, out, expected):
    monkeypatch.setattr(sys, "platform", "win32")
    calls = fake_run(monkeypatch, Done(0, out))
    assert dtenv.darktable_running() is expected
    assert calls[0][0] == "tasklist" and "IMAGENAME eq darktable.exe" in calls[0]


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_unreadable_process_list_counts_as_running(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    fake_run(monkeypatch, FileNotFoundError("no tasklist/pgrep"))
    assert dtenv.darktable_running() is True


def test_windows_tasklist_failure_counts_as_running(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    fake_run(monkeypatch, Done(1, ""))
    assert dtenv.darktable_running() is True


def test_config_dir(monkeypatch):
    monkeypatch.delenv("DARKTABLE_CONFIGDIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\a\AppData\Local")
    assert dtenv.config_dir() == r"C:\Users\a\AppData\Local\darktable"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert dtenv.config_dir().replace("\\", "/").endswith("/.config/darktable")
    monkeypatch.setenv("DARKTABLE_CONFIGDIR", "/x")
    assert dtenv.config_dir() == "/x"


def test_windows_cli_candidates(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(dtenv.shutil, "which", lambda name: None)  # which() itself branches on the platform
    monkeypatch.delenv("DARKTABLE_CLI", raising=False)
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.delenv("ProgramW6432", raising=False)
    assert r"C:\Program Files\darktable\bin\darktable-cli.exe" in dtenv.cli_candidates()


def test_windows_cache_dir(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\a\AppData\Local")
    assert dtenv.cache_dir() == r"C:\Users\a\AppData\Local"


def test_windows_folder_key_ignores_slash_and_case(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert dbsync.folder_key("C:/Users/A/Photos/") == dbsync.folder_key(r"c:\users\a\photos")
    assert dbsync.folder_key(r"C:\Users\A\Photos") != dbsync.folder_key(r"D:\Users\A\Photos")


def test_posix_folder_key_is_exact(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert dbsync.folder_key("/a/B") != dbsync.folder_key("/a/b")
    assert dbsync.folder_key("/a/b") == "/a/b"


def test_locate_matches_windows_style_folder(tmp_path, monkeypatch):
    """The DB holds the film roll folder in another case and with the other slash; on
    Windows that is still the same folder."""
    monkeypatch.setattr(sys, "platform", "win32")
    photos = tmp_path / "Photos"; photos.mkdir()
    side = photos / "A.ARW.xmp"; side.write_text("x")
    stored = ntpath.normpath(str(photos)).upper().replace("\\", "/")
    db = sqlite3.connect(":memory:")
    db.executescript("create table film_rolls (id integer primary key, folder varchar);"
                     "create table images (id integer primary key, film_id integer, filename varchar, version integer);")
    db.execute("insert into film_rolls values (1, ?)", (stored,))
    db.execute("insert into images values (7, 1, 'A.ARW', 0)")
    assert dbsync.locate(db, str(side))[0] == 7


def test_pid_alive_on_windows_reads_tasklist_and_never_signals(monkeypatch):
    import os
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "kill", lambda *a: pytest.fail("os.kill(pid, 0) is CTRL_C_EVENT on Windows"))
    calls = fake_run(monkeypatch, Done(0, '"darktable.exe","4242","Console","1","310,000 K"\r\n'))
    assert dtenv.pid_alive(4242) is True
    assert calls == [["tasklist", "/FI", "PID eq 4242", "/NH", "/FO", "CSV"]]
    fake_run(monkeypatch, Done(0, "INFO: No tasks are running which match the specified criteria.\r\n"))
    assert dtenv.pid_alive(4242) is False
    fake_run(monkeypatch, OSError("no tasklist"))
    assert dtenv.pid_alive(4242) is True  # fails closed


@pytest.mark.skipif(sys.platform == "win32", reason="posix probe")
def test_pid_alive_on_posix():
    import os
    assert dtenv.pid_alive(os.getpid()) is True
    assert dtenv.pid_alive(999999999) is False
