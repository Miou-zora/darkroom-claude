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
]


@pytest.mark.parametrize("tool,inp,expected", CASES)
def test_write_detection(tool, inp, expected):
    assert g.is_write(tool, inp) is expected


def run(monkeypatch, payload, running):
    monkeypatch.setattr(g, "darktable_running", lambda: running)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    return g.main()


@pytest.mark.pitfall("P9")
def test_blocks_sidecar_write_while_darktable_runs(monkeypatch, capsys):
    p = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/x/a.ARW.xmp"}})
    assert run(monkeypatch, p, True) == 2
    assert "darktable is running" in capsys.readouterr().err


def test_allows_write_when_darktable_closed(monkeypatch):
    p = json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/x/a.ARW.xmp"}})
    assert run(monkeypatch, p, False) == 0


def test_allows_reads_while_darktable_runs(monkeypatch):
    p = json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat a.ARW.xmp"}})
    assert run(monkeypatch, p, True) == 0


def test_ignores_malformed_payload(monkeypatch):
    assert run(monkeypatch, "not json", True) == 0
