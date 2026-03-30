"""
Project rules loading (FR-RULE-1, P0-04).

Precedence (FR-RULE-2): session overrides and user-global rule files are not implemented yet.
For P0-E1, only the configured project file (default ``AGENTS.md`` under the workspace) is loaded;
the agent loop should inject ``project_rules_text`` ahead of the user task when it is not None.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def rules_content_sha256(text: str | None) -> str | None:
    """SHA-256 hex digest of project rules for audit metadata (P2-06, FR-RULE-3)."""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_rules_path(workspace: Path, agents_md: str) -> Path:
    """Resolve configured rules path: absolute if already absolute, else under workspace."""
    p = Path(agents_md).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (workspace / p).resolve()


def load_project_rules(workspace: Path, agents_md: str) -> str | None:
    """
    Load project rules text if the file exists.

    If the file is missing, returns None (no error). If it exists but is not a file,
    returns None to avoid failing runs when misconfigured as a directory name.
    """
    path = resolve_rules_path(workspace, agents_md)
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
