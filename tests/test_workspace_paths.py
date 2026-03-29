"""Workspace path boundary tests."""

from pathlib import Path

import pytest

from codegen.workspace_paths import PathOutsideWorkspaceError, resolve_under_workspace


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
