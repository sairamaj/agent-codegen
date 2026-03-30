"""Post-edit verification hooks after successful apply_patch (P2-01, FR-VER-1–3)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from rich.console import Console

from codegen.console import redact_secrets_in_text


def run_verification_hooks(
    workspace: Path,
    commands: list[str],
    *,
    timeout_seconds: int,
    max_output_bytes: int,
    console: Console | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """
    Run each shell command with cwd ``workspace`` (in order).

    Returns ``(hook_results, all_ok)`` where ``all_ok`` is True only if every hook exited 0.
    Each result dict: command, exit_code, ok, stdout, stderr, truncated_stdout, truncated_stderr,
    and optional error message for spawn failures.
    """
    results: list[dict[str, Any]] = []
    all_ok = True

    def clip(s: str) -> tuple[str, bool]:
        if len(s.encode("utf-8")) <= max_output_bytes:
            return s, False
        raw = s.encode("utf-8")[:max_output_bytes].decode("utf-8", errors="replace")
        return raw + "\n… [truncated]", True

    for cmd in commands:
        cmd_stripped = cmd.strip()
        if not cmd_stripped:
            results.append(
                {
                    "command": cmd,
                    "ok": False,
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "truncated_stdout": False,
                    "truncated_stderr": False,
                    "error": "empty command",
                }
            )
            all_ok = False
            continue

        display_cmd = redact_secrets_in_text(cmd_stripped)
        if console is not None:
            console.print("[tool]verify[/tool] ", end="")
            console.print(display_cmd, style="tool")

        try:
            completed = subprocess.run(
                cmd_stripped,
                shell=True,
                cwd=os.fspath(workspace),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            all_ok = False
            payload = {
                "command": cmd_stripped,
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "truncated_stdout": False,
                "truncated_stderr": False,
                "error": f"exceeded timeout of {timeout_seconds}s",
            }
            results.append(payload)
            if console is not None:
                console.print(
                    f"[error]verify failed (timeout {timeout_seconds}s):[/error] {display_cmd}"
                )
            continue
        except OSError as e:
            all_ok = False
            payload = {
                "command": cmd_stripped,
                "ok": False,
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "truncated_stdout": False,
                "truncated_stderr": False,
                "error": str(e),
            }
            results.append(payload)
            if console is not None:
                console.print(f"[error]verify failed to run:[/error] {e}")
            continue

        out, trunc_out = clip(completed.stdout or "")
        err, trunc_err = clip(completed.stderr or "")
        hook_ok = completed.returncode == 0
        if not hook_ok:
            all_ok = False

        results.append(
            {
                "command": cmd_stripped,
                "ok": hook_ok,
                "exit_code": completed.returncode,
                "stdout": out,
                "stderr": err,
                "truncated_stdout": trunc_out,
                "truncated_stderr": trunc_err,
            }
        )

        if console is not None:
            if out.strip():
                console.print(out.rstrip(), style="muted")
            if err.strip():
                console.print(err.rstrip(), style="stderr")
            if not hook_ok:
                console.print(f"exit {completed.returncode}", style="error")

    return results, all_ok


def attach_verification_to_patch_result(
    patch_result_json: str,
    *,
    commands_were_configured: bool,
    hook_results: list[dict[str, Any]],
    verification_ok: bool,
    policy: Literal["fail", "warn"],
) -> str:
    """Merge verification into apply_patch JSON; may set top-level ok=false when policy is fail."""
    try:
        data = json.loads(patch_result_json)
    except json.JSONDecodeError:
        return patch_result_json
    if not isinstance(data, dict):
        return patch_result_json

    if not commands_were_configured:
        return patch_result_json

    data["verification"] = {
        "ok": verification_ok,
        "policy": policy,
        "hooks": hook_results,
    }

    patch_ok = data.get("ok") is True
    if patch_ok and policy == "fail" and not verification_ok:
        data["ok"] = False
        failed = [h.get("command", "") for h in hook_results if not h.get("ok")]
        preview = "; ".join(failed[:3])
        if len(failed) > 3:
            preview += "; …"
        data["error"] = {
            "code": "VERIFICATION_FAILED",
            "message": (
                "Post-edit verification hook(s) failed (policy=fail). "
                f"See verification.hooks for stdout/stderr. Commands: {preview or '(see hooks)'}"
            ),
        }

    return json.dumps(data, ensure_ascii=False)
