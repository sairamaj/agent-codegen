"""Structured JSONL logging (P0-16)."""

from __future__ import annotations

import io
import json
from pathlib import Path

from codegen.config import CodegenConfig
from codegen.observability import (
    StructuredLogger,
    normalize_structured_log_destination,
    open_structured_logger,
    sanitize_args_for_log,
    tool_result_outcome,
)


def test_normalize_structured_log_destination() -> None:
    assert normalize_structured_log_destination(None) is None
    assert normalize_structured_log_destination("") is None
    assert normalize_structured_log_destination("  ") is None
    assert normalize_structured_log_destination("stderr") == "stderr"
    assert normalize_structured_log_destination("-") == "stderr"
    assert normalize_structured_log_destination("C:/tmp/log.jsonl") == "C:/tmp/log.jsonl"


def test_structured_logger_emit_trace_ids() -> None:
    buf = io.StringIO()
    log = StructuredLogger(
        trace_id="trace-1",
        session_id="session-1",
        write=buf.write,
    )
    log.emit("test.event", foo=1)
    line = buf.getvalue().strip()
    d = json.loads(line)
    assert d["event"] == "test.event"
    assert d["trace_id"] == "trace-1"
    assert d["session_id"] == "session-1"
    assert d["foo"] == 1
    assert "ts" in d


def test_sanitize_args_for_log_redacts() -> None:
    raw = '{"path": "x", "token": "sk-12345678901234567890"}'
    s = sanitize_args_for_log(raw)
    assert "12345678901234567890" not in s


def test_tool_result_outcome() -> None:
    assert tool_result_outcome('{"ok": true}')["outcome"] == "ok"
    r = tool_result_outcome('{"ok": false, "error": {"code": "PATH_OUTSIDE_WORKSPACE"}}')
    assert r["outcome"] == "error"
    assert r["error_code"] == "PATH_OUTSIDE_WORKSPACE"


def test_open_structured_logger_file(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b" / "out.jsonl"
    log, close = open_structured_logger(str(p))
    try:
        log.emit("x", n=1)
    finally:
        close()
    text = p.read_text(encoding="utf-8")
    d = json.loads(text.strip())
    assert d["event"] == "x"
    assert len(d["trace_id"]) == 36


def test_codegen_config_redacted_summary_structured_log() -> None:
    c = CodegenConfig(structured_log="stderr", openai_api_key="x")
    s = c.redacted_summary()
    assert s["structured_log"] == "stderr"
    c2 = CodegenConfig(structured_log=str(Path("/tmp/secret/codegen.log")), openai_api_key="x")
    assert c2.redacted_summary()["structured_log"] == "file:codegen.log"
