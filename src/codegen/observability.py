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


def open_structured_logger(destination: str) -> tuple[StructuredLogger, Callable[[], None]]:
    """
    Open a logger writing to stderr or append to a file.

    Returns ``(logger, close)`` — ``close`` is a no-op for stderr; for files it closes the handle.
    """
    dest = normalize_structured_log_destination(destination)
    if dest is None:
        raise ValueError("structured log destination is empty")
    tid = new_trace_id()
    sid = tid
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
