"""Workspace root resolution and validation (FR-CTX-1)."""

from __future__ import annotations

from pathlib import Path


class WorkspaceError(Exception):
    """Invalid or inaccessible workspace root."""


def resolve_workspace(path: Path | None) -> Path:
    """
    Resolve workspace to an absolute, existing directory.

    If path is None, uses the current working directory.
    """
    root = (path or Path.cwd()).expanduser()
    try:
        resolved = root.resolve(strict=True)
    except FileNotFoundError as e:
        raise WorkspaceError(f"Workspace path does not exist: {root}") from e
    except OSError as e:
        raise WorkspaceError(f"Cannot access workspace path: {root} ({e})") from e
    if not resolved.is_dir():
        raise WorkspaceError(f"Workspace is not a directory: {resolved}")
    return resolved
