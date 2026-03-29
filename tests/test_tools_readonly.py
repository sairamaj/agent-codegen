"""Read-only tool execution tests."""

import json
from pathlib import Path

from codegen.tools_readonly import execute_tool


def test_read_file_ok(tmp_path: Path) -> None:
    (tmp_path / "hi.txt").write_text("line1\nline2\n", encoding="utf-8")
    raw = execute_tool(tmp_path, "read_file", json.dumps({"path": "hi.txt"}))
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["lines"] == ["line1", "line2"]


def test_read_file_error_json(tmp_path: Path) -> None:
    raw = execute_tool(tmp_path, "read_file", json.dumps({"path": "nope.txt"}))
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "NOT_FOUND"


def test_structured_error_bad_path(tmp_path: Path) -> None:
    raw = execute_tool(tmp_path, "read_file", json.dumps({"path": "../../etc/passwd"}))
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"


def test_list_dir_top_level(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")
    raw = execute_tool(tmp_path, "list_dir", json.dumps({"path": ".", "depth": 1}))
    data = json.loads(raw)
    assert data["ok"] is True
    names = {p.split("/")[-1] for p in data["entries"]}
    assert "a" in names and "b.txt" in names


def test_grep_matches(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "grep",
        json.dumps({"pattern": "def foo", "path": "src", "max_matches": 10}),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert len(data["matches"]) >= 1
