"""run_terminal_cmd tool (P1-04, FR-TOOL-6)."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codegen.command_policy import CommandPolicy, PolicyVerdict
from codegen.observability import StructuredLogger, sanitize_args_for_log
from codegen.workspace_paths import PathOutsideWorkspaceError, resolve_under_workspace
from rich.console import Console

RUN_TERMINAL_CMD_TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_terminal_cmd",
        "description": (
            "Run a shell command with working directory under the workspace. "
            "Output and stderr are captured; exit code is returned. "
            "Subject to policy (allow/deny/approval). Use for builds and tests."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command line (platform shell: cmd on Windows, sh -c style on Unix).",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory relative to workspace (default \".\").",
                },
            },
            "required": ["command"],
        },
    },
}


def _tool_error(code: str, message: str) -> str:
    return json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False)


def run_terminal_cmd(
    workspace: Path,
    args: dict[str, Any],
    *,
    policy: CommandPolicy,
    timeout_seconds: int,
    max_output_bytes: int,
    approval_callback: Callable[[str], bool] | None,
    console: Console | None = None,
    structured_logger: StructuredLogger | None = None,
) -> str:
    """Execute shell command under workspace; policy and approval applied here."""
    cmd = args.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return _tool_error("INVALID_ARGUMENT", "run_terminal_cmd requires non-empty string command")
    cwd_rel = args.get("cwd", ".")
    if not isinstance(cwd_rel, str):
        return _tool_error("INVALID_ARGUMENT", "cwd must be a string")
    try:
        cwd_path = resolve_under_workspace(workspace, cwd_rel)
    except PathOutsideWorkspaceError as e:
        return _tool_error("PATH_OUTSIDE_WORKSPACE", str(e))
    if not cwd_path.is_dir():
        return _tool_error("NOT_FOUND", f"Not a directory: {cwd_rel}")

    outcome = policy.evaluate(cmd)
    if outcome.verdict == PolicyVerdict.DENY:
        reason = outcome.reason or "command blocked by policy"
        if console is not None:
            console.print(f"[error]Command blocked by policy: {reason}[/error]")
        return _tool_error("COMMAND_DENIED_BY_POLICY", reason)
    if outcome.verdict == PolicyVerdict.REQUIRE_APPROVAL:
        preview = sanitize_args_for_log(json.dumps({"command": cmd}, ensure_ascii=False))
        if structured_logger is not None:
            structured_logger.emit("approval.request", tool="run_terminal_cmd", command_preview=preview)
        if approval_callback is None:
            return _tool_error(
                "APPROVAL_REQUIRED",
                "This command requires approval but no approval handler is configured.",
            )
        if not approval_callback(cmd):
            if structured_logger is not None:
                structured_logger.emit(
                    "approval.decision",
                    tool="run_terminal_cmd",
                    decision="denied",
                    command_preview=preview,
                )
            if console is not None:
                console.print("[muted]Approval denied; command not run.[/muted]")
            return _tool_error("COMMAND_APPROVAL_DENIED", "User denied approval for this command.")
        if structured_logger is not None:
            structured_logger.emit(
                "approval.decision",
                tool="run_terminal_cmd",
                decision="approved",
                command_preview=preview,
            )

    try:
        completed = subprocess.run(
            cmd,
            shell=True,
            cwd=os.fspath(cwd_path),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return _tool_error(
            "TIMEOUT",
            f"Command exceeded timeout of {timeout_seconds}s (process terminated).",
        )
    except OSError as e:
        return _tool_error("IO_ERROR", f"Failed to run command: {e}")

    def clip(s: str) -> tuple[str, bool]:
        if len(s.encode("utf-8")) <= max_output_bytes:
            return s, False
        raw = s.encode("utf-8")[:max_output_bytes].decode("utf-8", errors="replace")
        return raw + "\n… [truncated]", True

    out, trunc_out = clip(completed.stdout or "")
    err, trunc_err = clip(completed.stderr or "")
    payload: dict[str, Any] = {
        "ok": True,
        "exit_code": completed.returncode,
        "stdout": out,
        "stderr": err,
        "truncated_stdout": trunc_out,
        "truncated_stderr": trunc_err,
        "cwd": cwd_rel.replace("\\", "/"),
    }
    return json.dumps(payload, ensure_ascii=False)
