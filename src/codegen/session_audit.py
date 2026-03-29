"""Session audit trail (P1-08, FR-SESS-4): ordered tool I/O for replay and debugging."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from codegen.console import redact_secrets_in_text
from codegen.observability import sanitize_args_for_log, tool_result_outcome

# Cap stored tool result JSON after redaction (replay-oriented, bounded size).
SESSION_AUDIT_RESULT_MAX_LEN = 256_000


def normalize_session_audit_path(raw: str | None) -> str | None:
    """Return ``None`` if off, else a non-empty path string (file append)."""
    if raw is None:
        return None
    s = raw.strip()
    return s or None


def truncate_for_audit(text: str, *, max_len: int = SESSION_AUDIT_RESULT_MAX_LEN) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class SessionAuditWriter:
    """
    Append one JSON object per line: run boundaries and per-tool records with monotonic ``seq``.
    """

    def __init__(
        self,
        fh: TextIO,
        *,
        trace_id: str,
        session_id: str,
    ) -> None:
        self._fh = fh
        self.trace_id = trace_id
        self.session_id = session_id
        self._seq = 0

    def _emit(self, event: str, **fields: Any) -> None:
        rec: dict[str, Any] = {
            "ts": _utc_ts(),
            "event": event,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            **fields,
        }
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()

    def run_start(
        self,
        *,
        workspace: str,
        model: str,
        task_preview: str,
        max_iterations: int,
        max_wall_clock_seconds: int,
        agent_mode: str,
        auto_approve_shell: bool,
    ) -> None:
        self._emit(
            "audit.run_start",
            workspace=workspace,
            model=model,
            task_preview=task_preview,
            max_iterations=max_iterations,
            max_wall_clock_seconds=max_wall_clock_seconds,
            agent_mode=agent_mode,
            auto_approve_shell=auto_approve_shell,
        )

    def tool_record(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        args_json: str,
        result_json: str,
        duration_ms: int,
    ) -> None:
        self._seq += 1
        outcome = tool_result_outcome(result_json)
        result_safe = truncate_for_audit(redact_secrets_in_text(result_json))
        self._emit(
            "audit.tool",
            seq=self._seq,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            args_sanitized=sanitize_args_for_log(args_json),
            result_sanitized=result_safe,
            duration_ms=duration_ms,
            **outcome,
        )

    def run_end(
        self,
        *,
        exit_code: int,
        stop_reason: str,
        iterations_used: int,
        tool_calls_count: int,
    ) -> None:
        self._emit(
            "audit.run_end",
            exit_code=exit_code,
            stop_reason=stop_reason,
            iterations_used=iterations_used,
            tool_calls_count=tool_calls_count,
        )


def open_session_audit(
    path: str,
    *,
    trace_id: str,
    session_id: str,
) -> tuple[SessionAuditWriter, Callable[[], None]]:
    """
    Open ``path`` for append (creating parent dirs) and return ``(writer, close)``.
    """
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    fh: TextIO = p.open("a", encoding="utf-8")
    return SessionAuditWriter(fh, trace_id=trace_id, session_id=session_id), fh.close
