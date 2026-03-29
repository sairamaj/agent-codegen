"""Agent loop tests with mocked OpenAI client."""

from __future__ import annotations

import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIConnectionError

from codegen.agent_loop import run_agent_task
from codegen.console import make_console
from codegen.config import CodegenConfig
from codegen.session_audit import open_session_audit


class _FakeStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Any:
        return iter(self._chunks)


class _FakeChoice:
    def __init__(self, delta: Any, finish_reason: str | None = None) -> None:
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, delta: Any, finish_reason: str | None = None) -> None:
        self.choices = [_FakeChoice(delta, finish_reason)]


class _FakeDelta:
    def __init__(
        self,
        content: str | None = None,
        tool_calls: list[Any] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeFn:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCallDelta:
    def __init__(self, index: int, call_id: str, name: str, arg_fragment: str) -> None:
        self.index = index
        self.id = call_id
        self.function = _FakeFn(name, arg_fragment)


def test_tool_round_trip_then_text(tmp_path: Path) -> None:
    cfg = CodegenConfig(
        model="gpt-4o-mini",
        openai_api_key="sk-test",
        max_iterations=5,
        max_wall_clock_seconds=60,
    )
    client = MagicMock()

    stream1 = _FakeStream(
        [
            _FakeChunk(_FakeDelta(content="Thinking ")),
            _FakeChunk(_FakeDelta(content="…")),
            _FakeChunk(
                _FakeDelta(
                    tool_calls=[
                        _FakeToolCallDelta(
                            0,
                            "call_1",
                            "list_dir",
                            '{"path": ".", "depth": 1, "max_entries": 10}',
                        )
                    ]
                ),
                finish_reason="tool_calls",
            ),
        ]
    )
    stream2 = _FakeStream(
        [
            _FakeChunk(_FakeDelta(content="Done.")),
            _FakeChunk(_FakeDelta(), finish_reason="stop"),
        ]
    )

    client.chat.completions.create.side_effect = [stream1, stream2]

    console = make_console(force_color=False)
    out = run_agent_task(
        workspace=tmp_path,
        config=cfg,
        system_prompt="test",
        user_message="list files",
        console=console,
        client=client,
    )

    assert out.exit_code == 0
    assert out.iterations_used == 2
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0].name == "list_dir"
    tr = out.transcript_after_system
    assert tr[0] == {"role": "user", "content": "list files"}
    assert tr[-1]["role"] == "assistant"


def test_prior_messages_second_turn_sent_to_api(tmp_path: Path) -> None:
    """Interactive-style memory: prior transcript is prepended before the new user message."""
    cfg = CodegenConfig(
        model="gpt-4o-mini",
        openai_api_key="sk-test",
        max_iterations=5,
        max_wall_clock_seconds=60,
    )
    client = MagicMock()
    stream1 = _FakeStream(
        [
            _FakeChunk(_FakeDelta(content="Hi.")),
            _FakeChunk(_FakeDelta(), finish_reason="stop"),
        ]
    )
    stream2 = _FakeStream(
        [
            _FakeChunk(_FakeDelta(content="Ack.")),
            _FakeChunk(_FakeDelta(), finish_reason="stop"),
        ]
    )
    api_message_snapshots: list[Any] = []
    stream_q = [stream1, stream2]

    def _capture_create(**kwargs: Any) -> Any:
        api_message_snapshots.append(deepcopy(kwargs["messages"]))
        return stream_q.pop(0)

    client.chat.completions.create.side_effect = _capture_create
    console = make_console(force_color=False)
    out1 = run_agent_task(
        workspace=tmp_path,
        config=cfg,
        system_prompt="sys",
        user_message="first",
        console=console,
        client=client,
    )
    assert out1.exit_code == 0
    tr = out1.transcript_after_system
    assert tr[0]["role"] == "user" and tr[0]["content"] == "first"
    assert tr[-1]["role"] == "assistant"

    out2 = run_agent_task(
        workspace=tmp_path,
        config=cfg,
        system_prompt="sys",
        user_message="second",
        console=console,
        client=client,
        prior_messages=tr,
    )
    assert out2.exit_code == 0
    assert len(api_message_snapshots) == 2
    msgs = api_message_snapshots[1]
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1]["role"] == "user" and msgs[1]["content"] == "first"
    assert msgs[-1] == {"role": "user", "content": "second"}


def test_session_audit_ordered_tool_records(tmp_path: Path) -> None:
    """P1-08: NDJSON audit lists tools in order with args and truncated results."""
    cfg = CodegenConfig(
        model="gpt-4o-mini",
        openai_api_key="sk-test",
        max_iterations=5,
        max_wall_clock_seconds=60,
    )
    client = MagicMock()
    stream1 = _FakeStream(
        [
            _FakeChunk(
                _FakeDelta(
                    tool_calls=[
                        _FakeToolCallDelta(
                            0,
                            "call_a",
                            "list_dir",
                            '{"path": ".", "depth": 1, "max_entries": 10}',
                        )
                    ]
                ),
                finish_reason="tool_calls",
            ),
        ]
    )
    stream2 = _FakeStream(
        [
            _FakeChunk(_FakeDelta(), finish_reason="stop"),
        ]
    )
    client.chat.completions.create.side_effect = [stream1, stream2]

    audit_path = tmp_path / "audit.jsonl"
    writer, close = open_session_audit(str(audit_path), trace_id="trace-x", session_id="sess-x")
    try:
        out = run_agent_task(
            workspace=tmp_path,
            config=cfg,
            system_prompt="test",
            user_message="list files",
            console=make_console(force_color=False),
            client=client,
            session_audit=writer,
        )
    finally:
        close()

    assert out.exit_code == 0

    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert events[0]["event"] == "audit.run_start"
    assert events[0]["trace_id"] == "trace-x"
    tools = [e for e in events if e["event"] == "audit.tool"]
    assert len(tools) == 1
    assert tools[0]["seq"] == 1
    assert tools[0]["tool_call_id"] == "call_a"
    assert tools[0]["tool_name"] == "list_dir"
    assert "args_sanitized" in tools[0] and "result_sanitized" in tools[0]
    assert events[-1]["event"] == "audit.run_end"
    assert events[-1]["tool_calls_count"] == 1


def test_api_connection_error_reports_stop_reason(tmp_path: Path) -> None:
    """Connection failures surface as api_connection with a clearer console message."""
    cfg = CodegenConfig(
        model="gpt-4o-mini",
        openai_api_key="sk-test",
        max_iterations=5,
        max_wall_clock_seconds=60,
        base_url="https://api.openai.com/v1",
    )
    client = MagicMock()
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    client.chat.completions.create.side_effect = APIConnectionError(request=req)

    buf = io.StringIO()
    console = make_console(file=buf)
    out = run_agent_task(
        workspace=tmp_path,
        config=cfg,
        system_prompt="test",
        user_message="hi",
        console=console,
        client=client,
    )
    assert out.stop_reason == "api_connection"
    text = buf.getvalue()
    assert "Could not reach" in text or "connection" in text.lower()
    assert "api.openai.com" in text or "Base URL" in text


def test_invalid_proxy_env_exits_before_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "127.0.0.1:9999")
    cfg = CodegenConfig(
        model="gpt-4o-mini",
        openai_api_key="sk-test",
        max_iterations=5,
        max_wall_clock_seconds=60,
    )
    client = MagicMock()
    buf = io.StringIO()
    console = make_console(file=buf)
    out = run_agent_task(
        workspace=tmp_path,
        config=cfg,
        system_prompt="x",
        user_message="y",
        console=console,
        client=client,
    )

    assert out.stop_reason == "invalid_proxy_env"
    assert out.exit_code == 2
    assert client.chat.completions.create.call_count == 0
    assert "HTTPS_PROXY" in buf.getvalue()


def test_missing_api_key(tmp_path: Path) -> None:
    cfg = CodegenConfig(openai_api_key=None)
    console = make_console(force_color=False)
    out = run_agent_task(
        workspace=tmp_path,
        config=cfg,
        system_prompt="x",
        user_message="y",
        console=console,
        client=MagicMock(),
    )
    assert out.exit_code == 2
    assert out.stop_reason == "missing_api_key"


def test_run_prints_user_line_and_redacts_tool_args(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    cfg = CodegenConfig(
        model="gpt-4o-mini",
        openai_api_key="sk-test",
        max_iterations=5,
        max_wall_clock_seconds=60,
    )
    client = MagicMock()
    secret = "sk-123456789012345678901234567890"
    stream1 = _FakeStream(
        [
            _FakeChunk(
                _FakeDelta(
                    tool_calls=[
                        _FakeToolCallDelta(
                            0,
                            "call_1",
                            "read_file",
                            f'{{"path": "a.txt", "note": "{secret}"}}',
                        )
                    ]
                ),
                finish_reason="tool_calls",
            ),
        ]
    )
    stream2 = _FakeStream(
        [
            _FakeChunk(_FakeDelta(content="Ok."), finish_reason="stop"),
        ]
    )
    client.chat.completions.create.side_effect = [stream1, stream2]

    buf = io.StringIO()
    console = make_console(file=buf)
    task = "Do the thing"
    run_agent_task(
        workspace=tmp_path,
        config=cfg,
        system_prompt="test",
        user_message=task,
        console=console,
        client=client,
    )
    text = buf.getvalue()
    assert task in text
    assert secret not in text
    assert "read_file" in text
