"""Resolve paths strictly under workspace root (FR-CTX-1)."""

from __future__ import annotations

from pathlib import Path


class PathOutsideWorkspaceError(Exception):
    """Path escapes the workspace (traversal, symlink, or absolute outside root)."""


def resolve_under_workspace(workspace: Path, relative_path: str) -> Path:
    """
    Resolve ``relative_path`` to an absolute path that must stay under ``workspace``.

    Uses :meth:`~pathlib.Path.resolve` so symlinks cannot escape the workspace.
    """
    root = workspace.expanduser().resolve(strict=True)
    rel = (relative_path or ".").strip() or "."
    if Path(rel).is_absolute():
        candidate = Path(rel).resolve()
    else:
        candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as e:
        raise PathOutsideWorkspaceError(
            f"Path is outside workspace: {relative_path!r} (resolved to {candidate})"
        ) from e
    return candidate
