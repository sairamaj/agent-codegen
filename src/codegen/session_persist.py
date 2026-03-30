"""Session persistence to disk (P2-04, FR-SESS-2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai.types.chat import ChatCompletionMessageParam

SESSION_SCHEMA_VERSION = 1


@dataclass
class PersistedSession:
    """On-disk session state (no system message; matches ``transcript_after_system``)."""

    schema_version: int
    session_id: str
    workspace: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]

    def transcript(self) -> list[ChatCompletionMessageParam]:
        return list(self.messages)  # type: ignore[return-value]


def normalize_session_file_path(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = raw.strip()
    return s or None


def resolve_session_storage_path(
    *,
    workspace: Path,
    session_arg: str | None,
    config_path: str | None,
) -> Path | None:
    """
    Resolve where to read/write session JSON.

    Precedence: explicit ``--session`` (``session_arg``) wins; else ``config_path``
    from config/env when set.

    - If the string looks like an absolute path or contains path separators / ends in
      ``.json``, it is treated as a filesystem path (relative paths are under cwd).
    - Otherwise it is a session **name** stored at
      ``<workspace>/.codegen/sessions/<name>.json``.
    """
    raw = (session_arg or "").strip() or (config_path or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    looks_like_path = p.is_absolute() or "/" in raw or "\\" in raw or raw.lower().endswith(".json")
    if looks_like_path:
        return p.resolve()
    safe = raw.replace("..", "_").replace("/", "_").replace("\\", "_")
    if not safe or safe.strip() != safe:
        safe = "default"
    return (workspace / ".codegen" / "sessions" / f"{safe}.json").resolve()


def load_session(path: Path) -> PersistedSession | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        ver = int(data["schema_version"])
        if ver != SESSION_SCHEMA_VERSION:
            return None
        return PersistedSession(
            schema_version=ver,
            session_id=str(data["session_id"]),
            workspace=str(data["workspace"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            messages=list(data["messages"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_session(
    path: Path,
    *,
    session_id: str,
    workspace: Path,
    messages: list[ChatCompletionMessageParam],
    created_at: str | None = None,
) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    path.parent.mkdir(parents=True, exist_ok=True)
    created = created_at or now
    if path.is_file():
        prev = load_session(path)
        if prev is not None:
            created = prev.created_at
    payload = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "workspace": str(workspace.resolve()),
        "created_at": created,
        "updated_at": now,
        "messages": [dict(m) for m in messages],  # type: ignore[arg-type]
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
