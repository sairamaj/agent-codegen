"""Read-only tool execution tests (P0-09–P0-11)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codegen.config import CodegenConfig
from codegen.tools_readonly import execute_tool


def test_read_file_ok(tmp_path: Path) -> None:
    hi = tmp_path / "hi.txt"
    hi.write_text("line1\nline2\n", encoding="utf-8", newline="\n")
    raw = execute_tool(tmp_path, "read_file", json.dumps({"path": "hi.txt"}))
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["lines"] == ["line1", "line2"]
    assert data["truncated_bytes"] is False
    assert data["file_size_bytes"] == hi.stat().st_size


def test_read_file_byte_cap_truncation(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("x" * 5000, encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "read_file",
        json.dumps({"path": "big.txt", "max_bytes": 100}),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["truncated_bytes"] is True
    assert data["truncated"] is True
    assert data["bytes_read"] == 100


def test_read_file_line_limit_truncation(tmp_path: Path) -> None:
    lines = "\n".join(f"line{i}" for i in range(20))
    (tmp_path / "many.txt").write_text(lines, encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "read_file",
        json.dumps({"path": "many.txt", "offset": 0, "limit": 5}),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert len(data["lines"]) == 5
    assert data["truncated"] is True


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


def test_list_dir_truncated_entries(tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "list_dir",
        json.dumps({"path": ".", "depth": 1, "max_entries": 3}),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert len(data["entries"]) == 3
    assert data["truncated"] is True


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


def test_grep_max_matches_truncated(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hit\n" * 20, encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "grep",
        json.dumps({"pattern": "hit", "path": ".", "max_matches": 2}),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert len(data["matches"]) == 2
    assert data["truncated"] is True


def test_grep_bad_regex(tmp_path: Path) -> None:
    raw = execute_tool(tmp_path, "grep", json.dumps({"pattern": "((unclosed", "path": "."}))
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "BAD_REGEX"


def _try_symlink(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    """Raise OSError if the platform cannot create symlinks."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError:
        if os.name == "nt" and not os.environ.get("PROGRAMFILES"):
            pytest.skip("symlinks require elevated privileges or developer mode on Windows")
        raise


def test_grep_skips_symlink_escape_outside_workspace(tmp_path: Path) -> None:
    """P0-12: directory symlink to outside workspace must not be searched."""
    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret_outside", encoding="utf-8")
    link = tmp_path / "link_out"
    try:
        _try_symlink(link, outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available")

    (tmp_path / "safe.txt").write_text("safe_inside", encoding="utf-8")
    raw = execute_tool(
        tmp_path,
        "grep",
        json.dumps({"pattern": "secret", "path": "."}),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert not any("secret" in m.get("text", "") for m in data["matches"] if "outside" in m.get("path", ""))
    assert not any("secret_outside" in m.get("text", "") for m in data["matches"])


def test_list_dir_does_not_recurse_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside_ld_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "nested.txt").write_text("nested", encoding="utf-8")
    link = tmp_path / "link_out"
    try:
        _try_symlink(link, outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available")

    raw = execute_tool(
        tmp_path,
        "list_dir",
        json.dumps({"path": ".", "depth": 3, "max_entries": 50}),
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert not any("nested.txt" in e for e in data["entries"])


def test_grep_respects_gitignore_when_enabled(tmp_path: Path) -> None:
    """P2-02: ignored files are skipped when respect_gitignore is on."""
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("secret_word\n", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("secret_word here\n", encoding="utf-8")
    cfg = CodegenConfig(respect_gitignore=True)
    raw = execute_tool(
        tmp_path,
        "grep",
        json.dumps({"pattern": "secret_word", "path": "."}),
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is True
    paths = {m["path"] for m in data["matches"]}
    assert "visible.txt" in paths
    assert "ignored.txt" not in paths


def test_grep_includes_ignored_when_respect_gitignore_off(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("secret_word\n", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("x\n", encoding="utf-8")
    cfg = CodegenConfig(respect_gitignore=False)
    raw = execute_tool(
        tmp_path,
        "grep",
        json.dumps({"pattern": "secret_word", "path": "."}),
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is True
    paths = {m["path"] for m in data["matches"]}
    assert "ignored.txt" in paths


def test_list_dir_respects_gitignore_when_enabled(tmp_path: Path) -> None:
    """P2-02: ignored directories are omitted from listing."""
    (tmp_path / ".gitignore").write_text("build/\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    cfg = CodegenConfig(respect_gitignore=True)
    raw = execute_tool(tmp_path, "list_dir", json.dumps({"path": ".", "depth": 2}), config=cfg)
    data = json.loads(raw)
    assert data["ok"] is True
    assert not any(e == "build" or e.startswith("build/") for e in data["entries"])
    assert any(e == "src" or e.startswith("src/") for e in data["entries"])


def test_grep_nested_gitignore(tmp_path: Path) -> None:
    """Patterns in a subdirectory .gitignore apply to paths under that directory."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / ".gitignore").write_text("inner.txt\n", encoding="utf-8")
    (tmp_path / "pkg" / "inner.txt").write_text("needle\n", encoding="utf-8")
    (tmp_path / "pkg" / "outer.txt").write_text("needle\n", encoding="utf-8")
    cfg = CodegenConfig(respect_gitignore=True)
    raw = execute_tool(
        tmp_path,
        "grep",
        json.dumps({"pattern": "needle", "path": "pkg"}),
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is True
    paths = {m["path"] for m in data["matches"]}
    assert "pkg/outer.txt" in paths
    assert "pkg/inner.txt" not in paths


def test_read_file_symlink_to_outside_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"outside_rf_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = tmp_path / "link_file"
    try:
        _try_symlink(link, outside / "secret.txt")
    except OSError:
        pytest.skip("symlinks not available")

    raw = execute_tool(tmp_path, "read_file", json.dumps({"path": "link_file"}))
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"
