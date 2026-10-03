import io, json, sys
import pytest
import guard_darktable_open as g

CASES = [
    ("Bash", {"command": 'cp "/a/tmp/DSC1.xmp" "/p/DSC1.ARW.xmp"'}, True),
    ("Bash", {"command": "mv new.xmp /p/DSC1.ARW.xmp"}, True),
    ("Bash", {"command": "sed -i '' s/a/b/ x.ARW.xmp"}, True),
    ("Bash", {"command": "cat edited.txt > /p/DSC1.ARW.xmp"}, True),
    ("Bash", {"command": "python3 tools/dbsync.py /p/a.xmp --write"}, True),
    ("Bash", {"command": 'sqlite3 ~/.config/darktable/library.db "update images set history_end=3"'}, True),
    ("Bash", {"command": 'sqlite3 ~/.config/darktable/library.db "delete from history where imgid=1"'}, True),
    ("Write", {"file_path": "/p/DSC1.ARW.xmp"}, True),
    ("Edit", {"file_path": "/p/DSC1.ARW.xmp"}, True),
    ("Bash", {"command": "cat /p/DSC1.ARW.xmp"}, False),
    ("Bash", {"command": "grep operation /p/DSC1.ARW.xmp | head"}, False),
    ("Bash", {"command": "python3 tools/dbsync.py /p/a.xmp"}, False),
    ("Bash", {"command": 'sqlite3 ~/.config/darktable/library.db "select * from images"'}, False),
    ("Bash", {"command": "python3 tools/xmp.py show a.xmp > out.txt"}, False),
    ("Edit", {"file_path": "/p/notes.md"}, False),
    ("Read", {"file_path": "/p/DSC1.ARW.xmp"}, False),
    # python writing a sidecar or the DB, inline
    ("Bash", {"command": "python3 -c \"open('/p/a.ARW.xmp','w').write(x)\""}, True),
    ("Bash", {"command": "python3 -c \"open('/p/a.ARW.xmp', mode='a').write(x)\""}, True),
    ("Bash", {"command": "python3 -c \"open('/p/a.ARW.xmp','wb').write(x)\""}, True),
    ("Bash", {"command": "python3 -c \"import pathlib; pathlib.Path('/p/a.xmp').write_text(x)\""}, True),
    ("Bash", {"command": "python3 -c \"import shutil; shutil.copy('t.xmp','/p/a.ARW.xmp')\""}, True),
    ("Bash", {"command": "python3 - <<'EOF'\nimport sqlite3\nc=sqlite3.connect('library.db')\nc.execute('update images set history_end=3')\nEOF"}, True),
    ("Bash", {"command": "python3 - <<'EOF'\nfrom tools import xmp\nx=xmp.append(open('a.xmp').read(), e)\nopen('a.xmp','w').write(x)\nEOF"}, True),
    # python reading, or touching neither a sidecar nor the DB
    ("Bash", {"command": "python3 -c \"print(open('/p/a.ARW.xmp').read())\""}, False),
    ("Bash", {"command": "python3 -c \"print(open('/p/a.ARW.xmp','rb').read())\""}, False),
    ("Bash", {"command": "python3 -c \"import sqlite3; sqlite3.connect('library.db').execute('select * from images')\""}, False),
    ("Bash", {"command": "python3 -c \"open('notes.txt','w').write('x')\""}, False),
    ("Bash", {"command": "python3 -c \"from tools.xmp import entries; open('out.txt','w').write('x')\""}, False),
    ("Bash", {"command": "echo \"open('a.xmp','w')\" > snippet.txt"}, False),
]


@pytest.mark.parametrize("tool,inp,expected", CASES)
def test_write_detection(tool, inp, expected):
    assert g.is_write(tool, inp) is expected


@pytest.mark.parametrize("body,expected", [
    ("import sys\nopen(sys.argv[1], 'w').write(x)\n", True),   # path only on the command line
    ("print(open(sys.argv[1]).read())\n", False),
    ("open('out.txt', 'w').write('x')\n", True),   # known false positive: xmp on the command line + any write
])
def test_script_run_later(tmp_path, body, expected):
    (tmp_path / "edit.py").write_text(body)
    cmd = "python3 edit.py /p/a.ARW.xmp"
    assert g.is_write("Bash", {"command": cmd}, str(tmp_path)) is expected


def test_script_with_xmp_inside(tmp_path):
    (tmp_path / "edit.py").write_text("open('/p/a.ARW.xmp', 'w').write(x)\n")
    assert g.is_write("Bash", {"command": "python3 edit.py"}, str(tmp_path)) is True
    assert g.is_write("Bash", {"command": "python3 missing.py"}, str(tmp_path)) is False


def test_our_tools_are_not_scanned(monkeypatch, tmp_path):
    t = tmp_path / "tools"
    t.mkdir()
    (t / "x.py").write_text("open('a.xmp', 'w').write(x)\n")
    monkeypatch.setattr(g, "OUR_TOOLS", str(t) + "/")
    assert g.is_write("Bash", {"command": f"python3 {t}/x.py"}, str(tmp_path)) is False


def run(monkeypatch, payload, running):
    monkeypatch.setattr(g, "darktable_running", lambda: running)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    return g.main()


@pytest.mark.pitfall("P9")
def test_blocks_sidecar_write_while_darktable_runs(monkeypatch, capsys):
    p = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/x/a.ARW.xmp"}})
    assert run(monkeypatch, p, True) == 2
    assert "darktable is running" in capsys.readouterr().err


def test_blocks_python_sidecar_write_while_darktable_runs(monkeypatch, capsys):
    cmd = "python3 -c \"open('/x/a.ARW.xmp','w').write(s)\""
    p = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "/x"})
    assert run(monkeypatch, p, True) == 2
    assert run(monkeypatch, p, False) == 0


def test_allows_write_when_darktable_closed(monkeypatch):
    p = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/x/a.ARW.xmp"}})
    assert run(monkeypatch, p, False) == 0


def test_allows_reads_while_darktable_runs(monkeypatch):
    p = json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat a.ARW.xmp"}})
    assert run(monkeypatch, p, True) == 0


def test_ignores_malformed_payload(monkeypatch):
    assert run(monkeypatch, "not json", True) == 0


def test_blocks_windows_sidecar_write_while_darktable_exe_runs(monkeypatch, capsys):
    """End to end on the Windows path: backslash path, real tasklist parsing, mocked process list."""
    import subprocess
    monkeypatch.setattr(sys, "platform", "win32")
    out = "\"darktable.exe\",\"4242\",\"Console\",\"1\",\"310,000 K\"\r\n"
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: type("R", (), {"returncode": 0, "stdout": out})())
    p = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "C:\\Users\\a\\Pictures\\DSC1.ARW.xmp"}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(p))
    assert g.main() == 2
    assert "darktable is running" in capsys.readouterr().err
