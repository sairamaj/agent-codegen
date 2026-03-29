"""Agent loop tests with mocked OpenAI client."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from codegen.agent_loop import run_agent_task
from codegen.console import make_console
from codegen.config import CodegenConfig


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
