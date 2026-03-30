"""Workspace .gitignore handling for list_dir and grep (P2-02, FR-CTX-5)."""

from __future__ import annotations

from pathlib import Path

from pathspec import PathSpec


class GitignoreMatcher:
    """
    Git-style ignore checks using ``.gitignore`` files under the workspace.

    Patterns in ``ROOT/.gitignore`` apply to paths relative to the workspace root;
    patterns in ``ROOT/a/.gitignore`` apply to paths relative to ``a/``, matching
    git's nested ignore semantics.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self._spec_cache: dict[str, PathSpec | None] = {}

    def _spec_for_directory(self, dir_abs: Path) -> PathSpec | None:
        key = str(dir_abs.resolve())
        if key in self._spec_cache:
            return self._spec_cache[key]
        gi = dir_abs / ".gitignore"
        if not gi.is_file():
            self._spec_cache[key] = None
            return None
        try:
            text = gi.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._spec_cache[key] = None
            return None
        lines = text.splitlines()
        spec = PathSpec.from_lines("gitignore", lines)
        self._spec_cache[key] = spec
        return spec

    def is_ignored(self, path: Path) -> bool:
        """
        Return True if ``path`` is under ``workspace`` and ignored by an applicable
        ``.gitignore``. Uses logical (non-resolved) relative paths so symlinks keep
        their workspace names.
        """
        try:
            rel = path.relative_to(self.workspace)
        except ValueError:
            return True
        if not rel.parts:
            return False
        rel_posix = rel.as_posix()
        parts = rel.parts
        for i in range(len(parts)):
            dir_abs = self.workspace if i == 0 else self.workspace.joinpath(*parts[:i])
            remainder = rel_posix if i == 0 else "/".join(parts[i:])
            spec = self._spec_for_directory(dir_abs)
            if spec is None:
                continue
            if spec.match_file(remainder):
                return True
            # Patterns like ``build/`` match the directory itself only with a trailing slash.
            if path.is_dir() and remainder:
                if spec.match_file(remainder + "/"):
                    return True
        return False
