"""Session audit NDJSON (P1-08, FR-SESS-4)."""

from __future__ import annotations

import io
import json
from pathlib import Path

from codegen.session_audit import (
    SessionAuditWriter,
    normalize_session_audit_path,
    open_session_audit,
    truncate_for_audit,
)


def test_normalize_session_audit_path() -> None:
    assert normalize_session_audit_path(None) is None
    assert normalize_session_audit_path("") is None
    assert normalize_session_audit_path("  ") is None
    assert normalize_session_audit_path(" C:/tmp/a.jsonl ") == "C:/tmp/a.jsonl"


def test_truncate_for_audit() -> None:
    assert truncate_for_audit("ab", max_len=10) == "ab"
    t = truncate_for_audit("abcdef", max_len=4)
    assert t.endswith("…")
    assert len(t) == 4


def test_session_audit_tool_seq_and_json(tmp_path: Path) -> None:
    p = tmp_path / "audit.jsonl"
    w, close = open_session_audit(str(p), trace_id="t1", session_id="s1")
    try:
        w.run_start(
            workspace="/w",
            model="m",
            task_preview="tp",
            max_iterations=3,
            max_wall_clock_seconds=60,
            agent_mode="execute",
            auto_approve_shell=False,
        )
        w.tool_record(
            tool_call_id="c1",
            tool_name="read_file",
            args_json='{"path":"a.txt"}',
            result_json='{"ok":true,"content":"hi"}',
            duration_ms=5,
        )
        w.tool_record(
            tool_call_id="c2",
            tool_name="list_dir",
            args_json="{}",
            result_json='{"ok":false,"error":{"code":"X"}}',
            duration_ms=1,
        )
        w.run_end(
            exit_code=0,
            stop_reason="stop",
            iterations_used=2,
            tool_calls_count=2,
        )
    finally:
        close()

    lines = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert [x["event"] for x in lines] == [
        "audit.run_start",
        "audit.tool",
        "audit.tool",
        "audit.run_end",
    ]
    assert lines[0]["trace_id"] == "t1"
    assert lines[1]["seq"] == 1 and lines[1]["tool_name"] == "read_file"
    assert lines[1]["outcome"] == "ok"
    assert lines[2]["seq"] == 2 and lines[2]["outcome"] == "error"
    assert lines[3]["tool_calls_count"] == 2


def test_stringio_writer() -> None:
    buf = io.StringIO()
    w = SessionAuditWriter(buf, trace_id="a", session_id="b")
    w.tool_record(
        tool_call_id="x",
        tool_name="grep",
        args_json="{}",
        result_json="{}",
        duration_ms=0,
    )
    d = json.loads(buf.getvalue().strip())
    assert d["event"] == "audit.tool"
    assert d["seq"] == 1
