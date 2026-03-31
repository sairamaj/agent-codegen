"""MCP (Model Context Protocol) stdio clients: extra tools merged into the agent (P3-E1)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codegen.config import McpServerEntry

# Lazy imports for `mcp` — only when MCP servers are configured.
_mcp_types: Any = None


def _lazy_mcp():
    global _mcp_types
    if _mcp_types is None:
        import mcp.types as types
        from mcp.client.session import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        _mcp_types = types, ClientSession, StdioServerParameters, stdio_client
    return _mcp_types


_MAX_OPENAI_FN_LEN = 64
_MAX_TOOL_DEFS = 128


class McpStartupError(RuntimeError):
    """Raised when an MCP server fails during spawn/initialize/list_tools."""

    def __init__(
        self,
        *,
        server_name: str,
        command: str,
        args: list[str],
        cwd: str | None,
        phase: str,
        cause: BaseException,
    ) -> None:
        self.server_name = server_name
        self.command = command
        self.args = list(args)
        self.cwd = cwd
        self.phase = phase
        self.cause = cause
        msg = (
            f"MCP server '{server_name}' failed during {phase}: {cause}. "
            f"command={command!r} args={args!r} cwd={cwd!r}. "
            f"cause_chain={_exception_chain_text(cause)}"
        )
        super().__init__(msg)


def _exception_chain_text(exc: BaseException) -> str:
    parts: list[str] = []
    cur: BaseException | None = exc
    depth = 0
    while cur is not None and depth < 8:
        parts.append(f"{cur.__class__.__name__}: {cur}")
        cur = cur.__cause__
        depth += 1
    return " -> ".join(parts)


def _sanitize_component(s: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9]+", "_", (s or "").strip()).strip("_").lower()
    return t or "x"


def openai_tool_name_for_mcp(server_name: str, mcp_tool_name: str, used: set[str]) -> str:
    """Stable OpenAI function name: ``mcp__<server>__<tool>`` with collision handling."""
    a = _sanitize_component(server_name)
    b = _sanitize_component(mcp_tool_name)
    base = f"mcp__{a}__{b}"
    if len(base) <= _MAX_OPENAI_FN_LEN:
        name = base
    else:
        # Truncate middle; keep prefix for debugging
        name = base[: _MAX_OPENAI_FN_LEN - 6] + "__hash"
    if name not in used:
        used.add(name)
        return name
    i = 2
    while True:
        suffix = f"_{i}"
        cand = name[: _MAX_OPENAI_FN_LEN - len(suffix)] + suffix
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def mcp_tool_to_openai_definition(
    *,
    server_name: str,
    tool: Any,
    openai_name: str,
) -> dict[str, Any]:
    types, _, _, _ = _lazy_mcp()
    if not isinstance(tool, types.Tool):
        raise TypeError("expected mcp.types.Tool")
    desc = (tool.description or "").strip() or f"MCP tool {tool.name}"
    desc = f"[MCP server: {server_name}] {desc}"
    params: dict[str, Any]
    schema = tool.inputSchema
    if isinstance(schema, dict) and schema:
        params = schema
    else:
        params = {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": openai_name,
            "description": desc[:8000],
            "parameters": params,
        },
    }


def _serialize_call_tool_result(
    *,
    server_name: str,
    mcp_tool_name: str,
    result: Any,
) -> str:
    types, _, _, _ = _lazy_mcp()
    if not isinstance(result, types.CallToolResult):
        raise TypeError("expected CallToolResult")
    blocks: list[dict[str, Any]] = []
    for c in result.content:
        if hasattr(c, "model_dump"):
            blocks.append(c.model_dump(mode="json", exclude_none=True))
        else:
            blocks.append({"repr": str(c)})
    payload: dict[str, Any] = {
        "ok": not result.isError,
        "mcp": True,
        "server": server_name,
        "tool": mcp_tool_name,
        "content": blocks,
        "structuredContent": result.structuredContent,
    }
    if result.isError:
        text_parts = [b.get("text") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        msg = " ".join(str(t) for t in text_parts if t) or "MCP tool returned isError"
        payload["error"] = {"code": "MCP_TOOL_ERROR", "message": msg[:4000]}
    out = json.dumps(payload, ensure_ascii=False)
    if len(out) > 80_000:
        out = json.dumps(
            {
                "ok": payload["ok"],
                "mcp": True,
                "server": server_name,
                "tool": mcp_tool_name,
                "error": {"code": "MCP_RESULT_TOO_LARGE", "message": "Result truncated for context limits"},
                "truncated": True,
            },
            ensure_ascii=False,
        )
    return out


async def _list_all_tools(session: Any) -> list[Any]:
    types, _, _, _ = _lazy_mcp()
    all_tools: list[Any] = []
    cursor: str | None = None
    while True:
        if cursor is None:
            page = await session.list_tools()
        else:
            page = await session.list_tools(params=types.PaginatedRequestParams(cursor=cursor))
        all_tools.extend(page.tools)
        cursor = page.nextCursor
        if not cursor:
            break
    return all_tools


@dataclass
class McpRuntime:
    """
    Holds MCP stdio sessions for one agent run. Created via :func:`connect_mcp_runtime`.
    """

    _stack: AsyncExitStack
    _loop: asyncio.AbstractEventLoop | None = None
    _tool_to_server: dict[str, str] = field(default_factory=dict)
    _tool_to_mcp_name: dict[str, str] = field(default_factory=dict)
    _sessions: dict[str, Any] = field(default_factory=dict)
    openai_tool_definitions: list[dict[str, Any]] = field(default_factory=list)
    _owner_task: asyncio.Task[Any] | None = None
    _stop_event: asyncio.Event | None = None

    def is_mcp_tool(self, name: str) -> bool:
        return name in self._tool_to_mcp_name

    def call_tool_sync(self, openai_name: str, arguments: dict[str, Any]) -> str:
        """Invoke MCP ``tools/call`` on the right server (same asyncio loop as :func:`connect_mcp_runtime`)."""
        if self._loop is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": {"code": "MCP_INTERNAL", "message": "MCP event loop not initialized"},
                },
                ensure_ascii=False,
            )
        return self._loop.run_until_complete(self._call_tool_async(openai_name, arguments))

    async def _call_tool_async(self, openai_name: str, arguments: dict[str, Any]) -> str:
        server = self._tool_to_server.get(openai_name)
        mcp_name = self._tool_to_mcp_name.get(openai_name)
        if not server or not mcp_name:
            return json.dumps(
                {
                    "ok": False,
                    "error": {"code": "MCP_INTERNAL", "message": "Unknown MCP tool mapping"},
                },
                ensure_ascii=False,
            )
        session = self._sessions.get(server)
        if session is None:
            return json.dumps(
                {
                    "ok": False,
                    "error": {"code": "MCP_INTERNAL", "message": f"No session for server {server!r}"},
                },
                ensure_ascii=False,
            )
        try:
            result = await session.call_tool(mcp_name, arguments if arguments else None)
            return _serialize_call_tool_result(
                server_name=server,
                mcp_tool_name=mcp_name,
                result=result,
            )
        except Exception as e:
            return json.dumps(
                {
                    "ok": False,
                    "mcp": True,
                    "server": server,
                    "tool": mcp_name,
                    "error": {"code": "MCP_CALL_FAILED", "message": str(e)[:4000]},
                },
                ensure_ascii=False,
            )


async def _build_runtime(
    *,
    workspace: Path,
    servers: list[McpServerEntry],
    stack: AsyncExitStack,
) -> McpRuntime:
    """Initialize sessions and tool mappings inside the current task."""
    runtime = McpRuntime(_stack=stack, _loop=asyncio.get_running_loop())
    used_openai: set[str] = set()
    defs: list[dict[str, Any]] = []
    _, ClientSession, StdioServerParameters, stdio_client = _lazy_mcp()
    for srv in servers:
        cwd: str | Path | None = srv.cwd
        if cwd is not None and str(cwd).strip():
            p = Path(cwd).expanduser()
            if not p.is_absolute():
                p = (workspace / p).resolve()
            cwd = str(p)
        args = list(srv.args)
        try:
            params = StdioServerParameters(
                command=srv.command,
                args=args,
                env=dict(srv.env) if srv.env else None,
                cwd=cwd,
            )
            transport = await stack.enter_async_context(stdio_client(params))
        except Exception as e:
            raise McpStartupError(
                server_name=srv.name,
                command=srv.command,
                args=args,
                cwd=str(cwd) if cwd is not None else None,
                phase="spawn",
                cause=e,
            ) from e
        read, write = transport
        try:
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as e:
            raise McpStartupError(
                server_name=srv.name,
                command=srv.command,
                args=args,
                cwd=str(cwd) if cwd is not None else None,
                phase="initialize",
                cause=e,
            ) from e
        try:
            mcp_tools = await _list_all_tools(session)
        except Exception as e:
            raise McpStartupError(
                server_name=srv.name,
                command=srv.command,
                args=args,
                cwd=str(cwd) if cwd is not None else None,
                phase="list_tools",
                cause=e,
            ) from e
        if len(defs) + len(mcp_tools) > _MAX_TOOL_DEFS:
            raise ValueError(f"MCP tools exceed cap ({_MAX_TOOL_DEFS}); reduce servers or tools")
        runtime._sessions[srv.name] = session
        for t in mcp_tools:
            oname = openai_tool_name_for_mcp(srv.name, t.name, used_openai)
            runtime._tool_to_server[oname] = srv.name
            runtime._tool_to_mcp_name[oname] = t.name
            defs.append(mcp_tool_to_openai_definition(server_name=srv.name, tool=t, openai_name=oname))
    runtime.openai_tool_definitions = defs
    return runtime


async def connect_mcp_runtime(workspace: Path, servers: list[McpServerEntry]) -> McpRuntime:
    """Spawn stdio MCP servers, initialize sessions, and build OpenAI tool definitions."""
    if not servers:
        raise ValueError("connect_mcp_runtime requires at least one server entry")
    names = [s.name.strip() for s in servers]
    if len(set(names)) != len(names):
        raise ValueError("mcp_servers: duplicate server name")
    ready: asyncio.Future[McpRuntime] = asyncio.get_running_loop().create_future()
    stop_event = asyncio.Event()

    async def _owner() -> None:
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            runtime = await _build_runtime(workspace=workspace, servers=servers, stack=stack)
            runtime._owner_task = asyncio.current_task()
            runtime._stop_event = stop_event
            if not ready.done():
                ready.set_result(runtime)
            await stop_event.wait()
        except Exception as e:
            if not ready.done():
                ready.set_exception(e)
            raise
        finally:
            await stack.__aexit__(None, None, None)

    owner_task = asyncio.create_task(_owner(), name="mcp-runtime-owner")
    try:
        runtime = await ready
        runtime._owner_task = owner_task
        return runtime
    except Exception:
        stop_event.set()
        with contextlib.suppress(Exception):
            await owner_task
        raise


async def close_mcp_runtime(runtime: McpRuntime | None) -> None:
    if runtime is None:
        return
    if runtime._owner_task is not None and runtime._stop_event is not None:
        runtime._stop_event.set()
        await runtime._owner_task
        runtime._owner_task = None
        runtime._stop_event = None
        return
    await runtime._stack.__aexit__(None, None, None)
