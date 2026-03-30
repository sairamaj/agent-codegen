"""Workspace tools: read-only (P0-E3) + apply_patch (P1-01) + run_terminal_cmd (P1-E2)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from codegen.command_policy import CommandPolicy, command_policy_from_config
from codegen.config import CodegenConfig
from codegen.gitignore_filter import GitignoreMatcher
from codegen.tools_patch import APPLY_PATCH_TOOL_DEFINITION, apply_patch
from codegen.tools_terminal import RUN_TERMINAL_CMD_TOOL_DEFINITION, run_terminal_cmd
from codegen.tools_web import WEB_FETCH_TOOL_DEFINITION, web_fetch
from codegen.tool_dispatch import ToolDispatchContext
from codegen.verification_hooks import attach_verification_to_patch_result, run_verification_hooks
from codegen.workspace_paths import (
    PathOutsideWorkspaceError,
    resolved_path_is_under_workspace,
    resolve_under_workspace,
)

# OpenAI Chat Completions `tools=[{"type":"function","function":{...}}]` entries (read-only).
_READONLY_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a UTF-8 text file under the workspace. "
                "Use offset/limit to read a slice of lines when the file is large."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to workspace root.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "0-based starting line index (optional).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to return (optional).",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": (
                            "Maximum bytes read from disk before decoding (default 262144). "
                            "Truncation is indicated in the result."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories under a path with depth and entry limits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory relative to workspace root (use '.' for root).",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Max depth below the directory (default 1).",
                    },
                    "max_entries": {
                        "type": "integer",
                        "description": "Maximum entries to list (default 200).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search file contents with a Python regex (limited matches). "
                "Scope is relative to workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression."},
                    "path": {
                        "type": "string",
                        "description": "File or directory relative to workspace (default '.').",
                    },
                    "max_matches": {
                        "type": "integer",
                        "description": "Maximum matches to return (default 50).",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]


def tool_definitions_for_mode(
    mode: Literal["plan", "execute"],
    *,
    config: CodegenConfig | None = None,
) -> list[dict[str, Any]]:
    """Plan mode exposes only read-only tools; execute adds patch + shell.

    Optional ``web_fetch`` is registered when ``config.web_fetch_enabled`` is true (P2-07).
    """
    defs = list(_READONLY_TOOL_DEFINITIONS)
    if config is not None and config.web_fetch_enabled:
        defs.append(WEB_FETCH_TOOL_DEFINITION)
    if mode == "execute":
        defs.append(APPLY_PATCH_TOOL_DEFINITION)
        defs.append(RUN_TERMINAL_CMD_TOOL_DEFINITION)
    return defs


# Backward compatibility: full toolset (execute mode), no optional web_fetch.
TOOL_DEFINITIONS: list[dict[str, Any]] = tool_definitions_for_mode("execute", config=None)

_DEFAULT_READ_LINES = 500
_DEFAULT_READ_MAX_BYTES = 262_144  # 256 KiB
_DEFAULT_LIST_DEPTH = 1
_DEFAULT_LIST_MAX = 200
_DEFAULT_GREP_MAX = 50
_MAX_TOOL_JSON_CHARS = 80_000


def _gitignore_matcher(workspace: Path, config: CodegenConfig | None) -> GitignoreMatcher | None:
    if config is None or not config.respect_gitignore:
        return None
    return GitignoreMatcher(workspace)


def _tool_error(code: str, message: str) -> str:
    return json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False)


def _truncate_payload(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_TOOL_JSON_CHARS:
        return text, False
    return text[: _MAX_TOOL_JSON_CHARS] + "\n… [truncated]", True


def _read_file(workspace: Path, args: dict[str, Any]) -> str:
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        return _tool_error("INVALID_ARGUMENT", "read_file requires non-empty string path")
    offset = args.get("offset", 0)
    limit = args.get("limit", _DEFAULT_READ_LINES)
    max_bytes = args.get("max_bytes", _DEFAULT_READ_MAX_BYTES)
    try:
        off = int(offset) if offset is not None else 0
        lim = int(limit) if limit is not None else _DEFAULT_READ_LINES
        max_b = int(max_bytes) if max_bytes is not None else _DEFAULT_READ_MAX_BYTES
    except (TypeError, ValueError):
        return _tool_error("INVALID_ARGUMENT", "offset, limit, and max_bytes must be integers")
    if off < 0 or lim < 1:
        return _tool_error("INVALID_ARGUMENT", "offset must be >= 0 and limit >= 1")
    if max_b < 1:
        return _tool_error("INVALID_ARGUMENT", "max_bytes must be >= 1")
    try:
        target = resolve_under_workspace(workspace, path)
    except PathOutsideWorkspaceError as e:
        return _tool_error("PATH_OUTSIDE_WORKSPACE", str(e))
    if not target.is_file():
        return _tool_error("NOT_FOUND", f"Not a file: {path}")
    try:
        file_size = target.stat().st_size
    except OSError as e:
        return _tool_error("IO_ERROR", f"Cannot stat file: {e}")
    truncated_bytes = file_size > max_b
    try:
        with open(target, "rb") as f:
            raw = f.read(max_b)
    except OSError as e:
        return _tool_error("IO_ERROR", f"Cannot read file: {e}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _tool_error("ENCODING", "File is not valid UTF-8; binary or other encoding.")
    lines = text.splitlines()
    end = min(len(lines), off + lim)
    slice_lines = lines[off:end]
    truncated_lines = end < len(lines) or off > 0 or len(slice_lines) >= lim
    payload = {
        "ok": True,
        "path": path,
        "offset": off,
        "lines": slice_lines,
        "total_lines": len(lines),
        "file_size_bytes": file_size,
        "bytes_read": len(raw),
        "truncated": truncated_bytes or truncated_lines,
        "truncated_bytes": truncated_bytes,
    }
    out = json.dumps(payload, ensure_ascii=False)
    out, _ = _truncate_payload(out)
    return out


def _list_dir(
    workspace: Path,
    args: dict[str, Any],
    *,
    gitignore: GitignoreMatcher | None,
) -> str:
    path = args.get("path")
    if not isinstance(path, str):
        return _tool_error("INVALID_ARGUMENT", "list_dir requires string path")
    depth = args.get("depth", _DEFAULT_LIST_DEPTH)
    max_entries = args.get("max_entries", _DEFAULT_LIST_MAX)
    try:
        d = int(depth) if depth is not None else _DEFAULT_LIST_DEPTH
        cap = int(max_entries) if max_entries is not None else _DEFAULT_LIST_MAX
    except (TypeError, ValueError):
        return _tool_error("INVALID_ARGUMENT", "depth and max_entries must be integers")
    if d < 1 or cap < 1:
        return _tool_error("INVALID_ARGUMENT", "depth and max_entries must be >= 1")
    try:
        target = resolve_under_workspace(workspace, path)
    except PathOutsideWorkspaceError as e:
        return _tool_error("PATH_OUTSIDE_WORKSPACE", str(e))
    if not target.is_dir():
        return _tool_error("NOT_FOUND", f"Not a directory: {path}")
    entries: list[str] = []
    truncated = False

    def walk(current: Path, current_depth: int) -> str | None:
        nonlocal truncated
        if current_depth > d:
            return None
        try:
            names = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError as e:
            return _tool_error("IO_ERROR", str(e))
        for child in names:
            if len(entries) >= cap:
                truncated = True
                return None
            if gitignore is not None and gitignore.is_ignored(child):
                continue
            rel = child.relative_to(workspace)
            entries.append(str(rel).replace("\\", "/"))
            if child.is_dir() and current_depth < d:
                if not resolved_path_is_under_workspace(workspace, child):
                    continue
                err = walk(child, current_depth + 1)
                if err is not None:
                    return err
            if len(entries) >= cap:
                truncated = True
                return None
        return None

    err = walk(target, 1)
    if err is not None:
        return err
    payload = {"ok": True, "path": path, "entries": entries, "truncated": truncated}
    out = json.dumps(payload, ensure_ascii=False)
    out, _ = _truncate_payload(out)
    return out


def _grep_collect_files(
    workspace: Path,
    scope: Path,
    gitignore: GitignoreMatcher | None,
) -> list[Path]:
    """Text files under scope, skipping symlink escapes and optional gitignore."""

    out: list[Path] = []

    def walk(dir_path: Path) -> None:
        if not resolved_path_is_under_workspace(workspace, dir_path):
            return
        if gitignore is not None and gitignore.is_ignored(dir_path):
            return
        try:
            names = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for child in names:
            if not resolved_path_is_under_workspace(workspace, child):
                continue
            if gitignore is not None and gitignore.is_ignored(child):
                continue
            if child.is_file():
                out.append(child)
            elif child.is_dir():
                walk(child)

    if scope.is_file():
        if gitignore is None or not gitignore.is_ignored(scope):
            return [scope]
        return []
    if scope.is_dir():
        walk(scope)
        return out
    return []


def _grep(
    workspace: Path,
    args: dict[str, Any],
    *,
    gitignore: GitignoreMatcher | None,
) -> str:
    pattern = args.get("pattern")
    path = args.get("path", ".")
    max_matches = args.get("max_matches", _DEFAULT_GREP_MAX)
    if not isinstance(pattern, str) or not pattern:
        return _tool_error("INVALID_ARGUMENT", "grep requires non-empty pattern string")
    if not isinstance(path, str):
        return _tool_error("INVALID_ARGUMENT", "path must be a string")
    try:
        cap = int(max_matches) if max_matches is not None else _DEFAULT_GREP_MAX
    except (TypeError, ValueError):
        return _tool_error("INVALID_ARGUMENT", "max_matches must be an integer")
    if cap < 1:
        return _tool_error("INVALID_ARGUMENT", "max_matches must be >= 1")
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return _tool_error("BAD_REGEX", str(e))
    try:
        scope = resolve_under_workspace(workspace, path)
    except PathOutsideWorkspaceError as e:
        return _tool_error("PATH_OUTSIDE_WORKSPACE", str(e))
    matches: list[dict[str, Any]] = []
    truncated = False

    def scan_file(fp: Path) -> None:
        nonlocal truncated
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line) is None:
                continue
            rel = str(fp.relative_to(workspace)).replace("\\", "/")
            matches.append({"path": rel, "line": i, "text": line[:500]})
            if len(matches) >= cap:
                truncated = True
                return

    if scope.is_file():
        files = _grep_collect_files(workspace, scope, gitignore)
        for fp in files:
            scan_file(fp)
    elif scope.is_dir():
        files = _grep_collect_files(workspace, scope, gitignore)
        for fp in sorted(files, key=lambda p: p.as_posix().lower()):
            scan_file(fp)
            if truncated:
                break
    else:
        return _tool_error("NOT_FOUND", f"Path not found: {path}")

    payload = {"ok": True, "pattern": pattern, "matches": matches, "truncated": truncated}
    out = json.dumps(payload, ensure_ascii=False)
    out, _ = _truncate_payload(out)
    return out


def _permissive_shell_policy() -> CommandPolicy:
    """Tests / callers that omit dispatch: shell allowed without deny/approval rules."""
    return CommandPolicy(allowlist=(), denylist=(), require_approval=())


def execute_tool(
    workspace: Path,
    name: str,
    arguments_json: str,
    *,
    dispatch: ToolDispatchContext | None = None,
    config: CodegenConfig | None = None,
) -> str:
    """Run a tool by name; always returns a string (JSON object) for the model."""
    ctx = dispatch or ToolDispatchContext()
    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            return _tool_error("INVALID_ARGUMENT", "Tool arguments must be a JSON object")
    except json.JSONDecodeError as e:
        return _tool_error("INVALID_JSON", f"Invalid tool arguments JSON: {e}")

    if ctx.agent_mode == "plan" and name in ("apply_patch", "run_terminal_cmd"):
        return _tool_error(
            "PLAN_MODE",
            "This tool is disabled in plan mode (read-only). Use execute mode to apply patches or run shell.",
        )

    gi = _gitignore_matcher(workspace, config)

    if name == "read_file":
        return _read_file(workspace, args)
    if name == "list_dir":
        return _list_dir(workspace, args, gitignore=gi)
    if name == "grep":
        return _grep(workspace, args, gitignore=gi)
    if name == "web_fetch":
        if config is None or not config.web_fetch_enabled:
            return _tool_error(
                "WEB_FETCH_DISABLED",
                "web_fetch is disabled; set web_fetch_enabled in config (or CODEGEN_WEB_FETCH_ENABLED=true).",
            )
        return web_fetch(args, config)
    if name == "apply_patch":
        raw = apply_patch(workspace, args)
        if config is None or not config.verification_hooks:
            return raw
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if not isinstance(parsed, dict) or parsed.get("ok") is not True:
            return raw
        hook_results, verification_ok = run_verification_hooks(
            workspace,
            config.verification_hooks,
            timeout_seconds=config.shell_timeout_seconds,
            max_output_bytes=config.shell_max_output_bytes,
            console=ctx.console,
        )
        return attach_verification_to_patch_result(
            raw,
            commands_were_configured=True,
            hook_results=hook_results,
            verification_ok=verification_ok,
            policy=config.verification_failure,
        )
    if name == "run_terminal_cmd":
        if ctx.policy is not None:
            pol = ctx.policy
        elif config is not None:
            pol = command_policy_from_config(config)
        else:
            pol = _permissive_shell_policy()
        timeout = config.shell_timeout_seconds if config is not None else 120
        max_out = config.shell_max_output_bytes if config is not None else 32_768
        return run_terminal_cmd(
            workspace,
            args,
            policy=pol,
            timeout_seconds=timeout,
            max_output_bytes=max_out,
            approval_callback=ctx.approval_callback,
            console=ctx.console,
            structured_logger=ctx.structured_logger,
        )
    return _tool_error("UNKNOWN_TOOL", f"Unknown tool: {name}")
