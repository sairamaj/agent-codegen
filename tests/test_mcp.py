"""MCP integration (P3-E1): tool naming, dispatch, and observability fields."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from mcp.types import Tool

from codegen.config import CodegenConfig
from codegen.mcp_runtime import McpRuntime, mcp_tool_to_openai_definition, openai_tool_name_for_mcp
from codegen.observability import tool_context_debug_fields
from codegen.tools_readonly import execute_tool, tool_definitions_for_mode


def test_openai_tool_name_collision() -> None:
    used: set[str] = set()
    a = openai_tool_name_for_mcp("srv", "tool", used)
    b = openai_tool_name_for_mcp("srv", "tool", used)
    assert a != b
    assert a.startswith("mcp__")


def test_mcp_tool_to_openai_definition() -> None:
    t = Tool(
        name="alpha",
        description="desc",
        inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
    )
    d = mcp_tool_to_openai_definition(server_name="myserver", tool=t, openai_name="mcp__myserver__alpha")
    assert d["type"] == "function"
    assert d["function"]["name"] == "mcp__myserver__alpha"
    assert "myserver" in d["function"]["description"]


class _FakeMcpRuntime:
    """Minimal stand-in for :class:`codegen.mcp_runtime.McpRuntime` in unit tests."""

    def __init__(self) -> None:
        oname = "mcp__demo__ping"
        self.openai_tool_definitions = [
            {
                "type": "function",
                "function": {
                    "name": oname,
                    "description": "test",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        self._mcp_names = {oname}

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._mcp_names

    def call_tool_sync(self, openai_name: str, arguments: dict[str, object]) -> str:
        return json.dumps(
            {
                "ok": True,
                "mcp": True,
                "server": "demo",
                "tool": "ping",
                "content": [{"type": "text", "text": "pong"}],
            },
            ensure_ascii=False,
        )


def test_tool_definitions_include_mcp(tmp_path: Path) -> None:
    fake = _FakeMcpRuntime()
    cfg = CodegenConfig()
    defs = tool_definitions_for_mode("plan", config=cfg, mcp_runtime=cast(McpRuntime, fake))
    names = [d["function"]["name"] for d in defs if d.get("type") == "function"]
    assert "mcp__demo__ping" in names


def test_execute_tool_mcp_route(tmp_path: Path) -> None:
    fake = _FakeMcpRuntime()
    raw = execute_tool(
        tmp_path,
        "mcp__demo__ping",
        "{}",
        mcp_runtime=cast(McpRuntime, fake),
    )
    d = json.loads(raw)
    assert d.get("ok") is True
    assert d.get("mcp") is True


def test_observability_mcp_fields() -> None:
    raw = json.dumps(
        {"ok": True, "mcp": True, "server": "demo", "tool": "ping"},
        ensure_ascii=False,
    )
    f = tool_context_debug_fields("mcp__demo__ping", raw)
    assert f.get("context_mcp_server") == "demo"
    assert f.get("context_mcp_tool") == "ping"
