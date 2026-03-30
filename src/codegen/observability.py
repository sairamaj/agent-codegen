"""Structured JSON lines logging (P0-16, NFR-OBS-1/2)."""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from codegen.console import redact_secrets_in_text

# Cap logged tool argument JSON after redaction (audit without huge lines).
TOOL_ARGS_LOG_MAX_LEN = 4096


def sanitize_args_for_log(raw_json: str, *, max_len: int = TOOL_ARGS_LOG_MAX_LEN) -> str:
    """Redact secrets and truncate for structured logs."""
    t = redact_secrets_in_text(raw_json)
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def new_trace_id() -> str:
    """Opaque id for one CLI invocation (also used as session_id in Phase 0)."""
    return str(uuid.uuid4())


def normalize_structured_log_destination(raw: str | None) -> str | None:
    """
    Return ``None`` (off), ``\"stderr\"``, or a non-empty filesystem path string.

    Accepts ``\"-\"`` as alias for stderr (common CLI convention).
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    low = s.lower()
    if low in ("stderr", "-", "console"):
        return "stderr"
    return s


def tool_result_outcome(result_json: str) -> dict[str, Any]:
    """Summarize tool JSON result for logs (no large payloads)."""
    try:
        d = json.loads(result_json)
    except json.JSONDecodeError:
        return {"outcome": "invalid_json"}
    if not isinstance(d, dict):
        return {"outcome": "ok"}
    if d.get("ok") is False:
        err = d.get("error")
        code = "unknown"
        if isinstance(err, dict) and isinstance(err.get("code"), str):
            code = err["code"]
        return {"outcome": "error", "error_code": code}
    return {"outcome": "ok"}


# Cap paths listed in structured logs (P2-03, FR-CTX-8).
_CONTEXT_PATHS_LOG_MAX = 32


def tool_context_debug_fields(tool_name: str, result_json: str) -> dict[str, Any]:
    """
    Compact fields describing which workspace paths/snippets shaped tool output.

    Emitted on ``tool.complete`` for successful read_file / list_dir / grep.
    """
    try:
        d = json.loads(result_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(d, dict) or d.get("ok") is not True:
        return {}

    if tool_name == "read_file":
        path = d.get("path")
        lines = d.get("lines")
        n = len(lines) if isinstance(lines, list) else 0
        paths = [path] if isinstance(path, str) else []
        return {
            "context_paths": paths[:_CONTEXT_PATHS_LOG_MAX],
            "context_path_count": len(paths),
            "context_line_snippets": n,
        }

    if tool_name == "list_dir":
        path = d.get("path")
        entries = d.get("entries")
        n = len(entries) if isinstance(entries, list) else 0
        paths = [path] if isinstance(path, str) else []
        return {
            "context_paths": paths[:_CONTEXT_PATHS_LOG_MAX],
            "context_path_count": len(paths),
            "context_entries_listed": n,
        }

    if tool_name == "grep":
        matches = d.get("matches")
        if not isinstance(matches, list):
            return {}
        unique_paths: list[str] = []
        for m in matches:
            if not isinstance(m, dict):
                continue
            p = m.get("path")
            if isinstance(p, str) and p not in unique_paths:
                unique_paths.append(p)
        log_paths = unique_paths[:_CONTEXT_PATHS_LOG_MAX]
        return {
            "context_paths": log_paths,
            "context_path_count": len(unique_paths),
            "context_match_snippets": len(matches),
        }

    if tool_name == "web_fetch":
        url = d.get("url")
        if isinstance(url, str) and url:
            u = url if len(url) <= 200 else url[:197] + "..."
            return {
                "context_paths": [u],
                "context_path_count": 1,
                "context_web_fetch_bytes": int(d.get("bytes_read") or 0),
            }

    return {}


class StructuredLogger:
    """Append one JSON object per line; each record includes ``trace_id`` and ``session_id``."""

    def __init__(
        self,
        *,
        trace_id: str,
        session_id: str,
        write: Callable[[str], None],
    ) -> None:
        self.trace_id = trace_id
        self.session_id = session_id
        self._write = write

    def emit(self, event: str, **fields: Any) -> None:
        rec: dict[str, Any] = {
            "ts": _utc_ts(),
            "event": event,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            **fields,
        }
        self._write(json.dumps(rec, ensure_ascii=False) + "\n")


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def open_structured_logger(
    destination: str,
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
) -> tuple[StructuredLogger, Callable[[], None]]:
    """
    Open a logger writing to stderr or append to a file.

    Returns ``(logger, close)`` — ``close`` is a no-op for stderr; for files it closes the handle.
    When ``trace_id`` / ``session_id`` are omitted, new UUIDs are generated (and match each other).
    """
    dest = normalize_structured_log_destination(destination)
    if dest is None:
        raise ValueError("structured log destination is empty")
    tid = trace_id or new_trace_id()
    sid = session_id or tid
    if dest == "stderr":

        def _write(s: str) -> None:
            sys.stderr.write(s)

        return StructuredLogger(trace_id=tid, session_id=sid, write=_write), lambda: None

    path = Path(dest).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fh: TextIO = path.open("a", encoding="utf-8")

    def _close() -> None:
        fh.close()

    return (
        StructuredLogger(trace_id=tid, session_id=sid, write=fh.write),
        _close,
    )
