"""Workspace resolution (P0-02)."""

from pathlib import Path

import pytest

from codegen.workspace import WorkspaceError, resolve_workspace


def test_resolve_workspace_uses_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    w = resolve_workspace(None)
    assert w == tmp_path.resolve()


def test_resolve_workspace_explicit(tmp_path: Path) -> None:
    d = tmp_path / "proj"
    d.mkdir()
    w = resolve_workspace(d)
    assert w == d.resolve()


def test_resolve_workspace_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    with pytest.raises(WorkspaceError, match="does not exist"):
        resolve_workspace(missing)


def test_resolve_workspace_not_dir(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="not a directory"):
        resolve_workspace(f)
