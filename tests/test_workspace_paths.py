"""Workspace path boundary tests."""

from pathlib import Path

import pytest

from codegen.workspace_paths import (
    PathOutsideWorkspaceError,
    resolved_path_is_under_workspace,
    resolve_under_workspace,
)


def test_resolve_simple(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    p = resolve_under_workspace(tmp_path, "a.txt")
    assert p == f.resolve()


def test_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideWorkspaceError):
        resolve_under_workspace(tmp_path, "..")


def test_rejects_absolute_outside(tmp_path: Path) -> None:
    import sys

    outside = Path("C:/Windows") if sys.platform == "win32" else Path("/usr")
    if not outside.exists():
        pytest.skip("system anchor path not present")
    with pytest.raises(PathOutsideWorkspaceError):
        resolve_under_workspace(tmp_path, str(outside))


def test_resolved_path_is_under_workspace_direct(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert resolved_path_is_under_workspace(tmp_path, f) is True


def test_resolved_path_is_under_workspace_rejects_escape(tmp_path: Path) -> None:
    import os

    outside = tmp_path.parent / f"outside_{tmp_path.name}"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "bad"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available")
    assert resolved_path_is_under_workspace(tmp_path, link) is False
