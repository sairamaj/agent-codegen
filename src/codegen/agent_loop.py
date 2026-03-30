"""OpenAI chat loop with tools, streaming, and task limits (P0-E2)."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from rich.console import Console

from codegen.command_policy import command_policy_from_config
from codegen.config import CodegenConfig
from codegen.history_compaction import compact_prior_messages, estimate_messages_chars
from codegen.http_env import proxy_environment_error_message
from codegen.console import format_user_task_preview, redact_secrets_in_text, redact_tool_args_display
from codegen.observability import (
    StructuredLogger,
    sanitize_args_for_log,
    tool_context_debug_fields,
    tool_result_outcome,
)
from codegen.session_audit import SessionAuditWriter
from codegen.tool_dispatch import ToolDispatchContext
from codegen.tools_readonly import execute_tool, tool_definitions_for_mode


@dataclass(frozen=True)
class ToolCallRecord:
    """One executed tool call (for tests / logging)."""

    name: str
    arguments: str
    result: str



@dataclass
class AgentRunResult:
    """Outcome of a single agent run."""

    exit_code: int
    iterations_used: int
    stop_reason: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    #: Messages after the system prompt (user / assistant / tool), for multi-turn CLI sessions.
    transcript_after_system: list[ChatCompletionMessageParam] = field(default_factory=list)


def prompt_for_command_approval(console: Console, command: str) -> bool:
    """TTY y/n gate for policy-approved sensitive commands (P1-07)."""
    if not sys.stdin.isatty():
        return False
    console.print("[warn]This command requires approval:[/warn]")
    console.print(f"  {command}", style="muted")
    console.print("[muted]Allow? [y/N]:[/muted] ", end="")
    try:
        line = input().strip().lower()
    except EOFError:
        return False
    return line in ("y", "yes")


def _context_trace_line(tool_name: str, fields: dict[str, Any]) -> str | None:
    """One-line summary for -v (P2-03); returns None when nothing to show."""
    if not fields:
        return None
    paths = fields.get("context_paths") or []
    if tool_name == "read_file":
        n = int(fields.get("context_line_snippets", 0))
        p = paths[0] if paths else "?"
        return f"read_file → {n} line(s) from {p}"
    if tool_name == "list_dir":
        n = int(fields.get("context_entries_listed", 0))
        p = paths[0] if paths else "?"
        return f"list_dir → {n} entr(y/ies) under {p}"
    if tool_name == "grep":
        m = int(fields.get("context_match_snippets", 0))
        u = int(fields.get("context_path_count", 0))
        return f"grep → {m} match snippet(s) across {u} file(s)"
    if tool_name == "web_fetch":
        b = int(fields.get("context_web_fetch_bytes", 0))
        paths = fields.get("context_paths") or []
        u = paths[0] if paths else "?"
        return f"web_fetch → {b} byte(s) from {u}"
    return None


def _approval_callback_for_run(*, auto_approve: bool, console: Console) -> Callable[[str], bool]:
    if auto_approve:
        return lambda _cmd: True
    return lambda cmd: prompt_for_command_approval(console, cmd)


def _http_timeout_seconds(cfg: CodegenConfig) -> float:
    """Bound a single HTTP call; keep below task wall clock."""
    return float(min(120, max(30, cfg.max_wall_clock_seconds)))


def _api_error_stop_reason(exc: APIError) -> str:
    if isinstance(exc, APITimeoutError):
        return "api_timeout"
    if isinstance(exc, APIConnectionError):
        return "api_connection"
    return "api_error"


def _exception_chain_contains_unsupported_protocol(root: BaseException) -> bool:
    cur: BaseException | None = root
    while cur is not None:
        if isinstance(cur, httpx.UnsupportedProtocol):
            return True
        cur = cur.__cause__
    return False


def _print_openai_api_error(console: Console, exc: APIError, *, config: CodegenConfig) -> None:
    """User-visible detail for API failures (connection issues are often opaque as 'Connection error.')."""
    console.print()
    if isinstance(exc, APITimeoutError):
        console.print("[error]OpenAI request timed out before a response was received.[/error]")
        console.print(
            "[muted]Try again, check network latency, or raise the client timeout "
            f"(currently {_http_timeout_seconds(config):.0f}s, derived from max_wall_clock_seconds).[/muted]"
        )
        return
    if isinstance(exc, APIConnectionError):
        console.print("[error]Could not reach the OpenAI API (connection failed).[/error]")
        base = (config.base_url or "").strip() or "https://api.openai.com/v1 (default)"
        console.print(f"[muted]Effective base URL:[/muted] {base}")
        cause = exc.__cause__
        if cause is not None:
            console.print(f"[muted]Underlying error:[/muted] {cause!r}")
        bad_proto = _exception_chain_contains_unsupported_protocol(exc)
        if bad_proto:
            console.print(
                "[muted]This often means HTTPS_PROXY, HTTP_PROXY, or ALL_PROXY is set to a host:port "
                "without a scheme. Use a full URL, e.g. [bold]http://127.0.0.1:7890[/bold]. "
                "Or unset those variables if you do not need a proxy.[/muted]"
            )
            console.print(
                "[muted]OPENAI_BASE_URL must also include https:// or http:// if you set it.[/muted]"
            )
        msg = str(exc).strip()
        if msg and msg.lower() not in ("connection error.", "connection error"):
            console.print(f"[muted]Detail:[/muted] {msg}")
        if not bad_proto:
            console.print(
                "[muted]Check: outbound HTTPS allowed; VPN/firewall/proxy; OPENAI_BASE_URL typo; "
                "set HTTPS_PROXY/HTTP_PROXY to a full URL if your network requires a proxy.[/muted]"
            )
        return
    console.print(f"[error]OpenAI API error: {exc}[/error]")


def _merge_tool_delta(
    tool_calls_by_index: dict[int, dict[str, Any]],
    delta_tool_calls: list[Any] | None,
) -> None:
    if not delta_tool_calls:
        return
    for tc in delta_tool_calls:
        idx = tc.index
        if idx not in tool_calls_by_index:
            tool_calls_by_index[idx] = {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
        if getattr(tc, "id", None):
            tool_calls_by_index[idx]["id"] = tc.id
        fn = getattr(tc, "function", None)
        if fn is not None:
            if getattr(fn, "name", None):
                tool_calls_by_index[idx]["function"]["name"] = fn.name
            if getattr(fn, "arguments", None):
                tool_calls_by_index[idx]["function"]["arguments"] += fn.arguments


def run_agent_task(
    *,
    workspace: Path,
    config: CodegenConfig,
    system_prompt: str,
    user_message: str,
    console: Console,
    client: OpenAI | None = None,
    structured_logger: StructuredLogger | None = None,
    session_audit: SessionAuditWriter | None = None,
    agent_mode: Literal["plan", "execute"] = "execute",
    auto_approve: bool = False,
    prior_messages: Sequence[ChatCompletionMessageParam] | None = None,
    verbose: int = 0,
    project_rules_sha256: str | None = None,
) -> AgentRunResult:
    """
    Run the model with tools until a final assistant message or a limit.

    Streams assistant text to ``console`` (P0-07). Enforces ``max_iterations`` and
    ``max_wall_clock_seconds`` (P0-06). Tool failures are JSON strings (P0-08).
    ``agent_mode=plan`` exposes only read-only tools (P1-06); ``execute`` adds patch + shell.
    Optional ``session_audit`` appends per-run NDJSON (P1-08) with ordered tool records.
    Pass ``prior_messages`` (must not include the system message) to continue a conversation;
    ``transcript_after_system`` on the result is the full suffix to pass as the next
    ``prior_messages`` after a successful turn.

    ``verbose >= 1`` prints a short context trace after read-only tools (P2-03).
    ``project_rules_sha256`` is emitted on ``run.start`` for audit metadata (P2-06).
    """
    if not (config.openai_api_key or "").strip():
        console.print("[error]OPENAI_API_KEY is not set.[/error]")
        return AgentRunResult(exit_code=2, iterations_used=0, stop_reason="missing_api_key")

    proxy_err = proxy_environment_error_message()
    if proxy_err is not None:
        console.print(f"[error]{proxy_err}[/error]")
        return AgentRunResult(exit_code=2, iterations_used=0, stop_reason="invalid_proxy_env")

    console.print("[muted]user[/muted] ", end="")
    console.print(format_user_task_preview(user_message), style="user")
    console.print()
    if agent_mode == "plan":
        console.print(
            "[warn]Mode: plan — read-only tools only (no apply_patch or run_terminal_cmd).[/warn]"
        )
        console.print()

    tool_dispatch = ToolDispatchContext(
        agent_mode=agent_mode,
        policy=command_policy_from_config(config),
        approval_callback=_approval_callback_for_run(auto_approve=auto_approve, console=console),
        console=console,
        structured_logger=structured_logger,
        verbose=verbose,
    )

    tools_for_run = tool_definitions_for_mode(agent_mode, config=config)

    own_client = client is None
    if client is None:
        client = OpenAI(
            api_key=config.openai_api_key,
            base_url=config.base_url or None,
            timeout=_http_timeout_seconds(config),
        )

    prior = list(prior_messages) if prior_messages else []
    prior_chars_before = estimate_messages_chars(prior)
    prior_compact, did_compact = compact_prior_messages(
        prior,
        max_chars=config.max_history_chars,
    )
    # API messages may use compacted prior; transcript retains full history for resume (P2-04/05).
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        *prior_compact,
        {"role": "user", "content": user_message},
    ]
    transcript_full: list[ChatCompletionMessageParam] = [
        *prior,
        {"role": "user", "content": user_message},
    ]

    def _finish(
        exit_code: int,
        stop_reason: str,
        *,
        iterations_used: int,
    ) -> AgentRunResult:
        if structured_logger is not None:
            structured_logger.emit(
                "run.end",
                exit_code=exit_code,
                stop_reason=stop_reason,
                iterations_used=iterations_used,
            )
        if session_audit is not None and audit_started:
            session_audit.run_end(
                exit_code=exit_code,
                stop_reason=stop_reason,
                iterations_used=iterations_used,
                tool_calls_count=len(all_records),
            )
        return AgentRunResult(
            exit_code=exit_code,
            iterations_used=iterations_used,
            stop_reason=stop_reason,
            tool_calls=all_records,
            transcript_after_system=deepcopy(transcript_full),
        )

    all_records: list[ToolCallRecord] = []
    iterations = 0
    audit_started = False
    task_preview = redact_secrets_in_text(format_user_task_preview(user_message))
    if structured_logger is not None:
        structured_logger.emit(
            "run.start",
            workspace=str(workspace),
            model=config.model,
            task_preview=task_preview,
            max_iterations=config.max_iterations,
            max_wall_clock_seconds=config.max_wall_clock_seconds,
            agent_mode=agent_mode,
            auto_approve_shell=auto_approve,
            project_rules_sha256=project_rules_sha256,
            max_history_chars=config.max_history_chars,
        )
        if did_compact:
            structured_logger.emit(
                "history.compact",
                prior_chars_before=prior_chars_before,
                prior_chars_after=estimate_messages_chars(prior_compact),
                max_history_chars=config.max_history_chars,
            )
    if session_audit is not None:
        session_audit.run_start(
            workspace=str(workspace),
            model=config.model,
            task_preview=task_preview,
            max_iterations=config.max_iterations,
            max_wall_clock_seconds=config.max_wall_clock_seconds,
            agent_mode=agent_mode,
            auto_approve_shell=auto_approve,
        )
        audit_started = True

    deadline = time.monotonic() + float(config.max_wall_clock_seconds)

    try:
        while True:
            if time.monotonic() >= deadline:
                console.print()
                console.print(
                    "[warn]Stopped: max wall-clock time exceeded "
                    f"({config.max_wall_clock_seconds}s).[/warn]"
                )
                return _finish(1, "max_wall_clock", iterations_used=iterations)
            if iterations >= config.max_iterations:
                console.print()
                console.print(
                    "[warn]Stopped: max iterations reached "
                    f"({config.max_iterations}).[/warn]"
                )
                return _finish(1, "max_iterations", iterations_used=iterations)

            iterations += 1
            if structured_logger is not None:
                structured_logger.emit("model.iteration", iteration=iterations)
            tool_calls_by_index: dict[int, dict[str, Any]] = {}
            finish_reason: str | None = None

            try:
                stream = client.chat.completions.create(
                    model=config.model,
                    messages=messages,
                    tools=tools_for_run,
                    tool_choice="auto",
                    stream=True,
                    parallel_tool_calls=True,
                )
            except APIError as e:
                _print_openai_api_error(console, e, config=config)
                return _finish(1, _api_error_stop_reason(e), iterations_used=iterations)

            assistant_content_parts: list[str] = []
            try:
                for chunk in stream:
                    if time.monotonic() >= deadline:
                        console.print()
                        console.print("[warn]Stopped: max wall-clock time exceeded during streaming.[/warn]")
                        return _finish(1, "max_wall_clock", iterations_used=iterations)
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    delta = choice.delta
                    if delta.content:
                        assistant_content_parts.append(delta.content)
                        console.print(delta.content, end="", style="assistant")
                    _merge_tool_delta(tool_calls_by_index, delta.tool_calls)
            except APIError as e:
                _print_openai_api_error(console, e, config=config)
                return _finish(1, _api_error_stop_reason(e), iterations_used=iterations)

            if assistant_content_parts:
                console.print()

            assistant_text = "".join(assistant_content_parts) if assistant_content_parts else None
            tool_calls_list = [tool_calls_by_index[i] for i in sorted(tool_calls_by_index.keys())]

            if tool_calls_list:
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_text if assistant_text else None,
                    "tool_calls": tool_calls_list,
                }
                messages.append(assistant_msg)  # type: ignore[arg-type]
                transcript_full.append(assistant_msg)  # type: ignore[arg-type]

                for tc in tool_calls_list:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    raw_args = fn.get("arguments") or "{}"
                    tid = tc.get("id") or ""
                    arg_summary = redact_tool_args_display(raw_args)
                    console.print("[tool]›[/tool] ", end="")
                    console.print(name, style="tool", end=" ")
                    console.print(arg_summary, style="muted")
                    if structured_logger is not None:
                        structured_logger.emit(
                            "tool.start",
                            tool_name=name,
                            args_sanitized=sanitize_args_for_log(raw_args),
                        )
                    t_tool = time.monotonic()
                    result = execute_tool(
                        workspace,
                        name,
                        raw_args,
                        dispatch=tool_dispatch,
                        config=config,
                    )
                    duration_ms = int((time.monotonic() - t_tool) * 1000)
                    outcome = tool_result_outcome(result)
                    ctx_dbg = tool_context_debug_fields(name, result)
                    if structured_logger is not None:
                        structured_logger.emit(
                            "tool.complete",
                            tool_name=name,
                            duration_ms=duration_ms,
                            **outcome,
                            **ctx_dbg,
                        )
                    if tool_dispatch.verbose >= 1:
                        line = _context_trace_line(name, ctx_dbg)
                        if line:
                            console.print(f"[muted]context[/muted] {line}")
                    if session_audit is not None:
                        session_audit.tool_record(
                            tool_call_id=tid,
                            tool_name=name,
                            args_json=raw_args,
                            result_json=result,
                            duration_ms=duration_ms,
                        )
                    all_records.append(ToolCallRecord(name=name, arguments=raw_args, result=result))
                    tool_msg: ChatCompletionMessageParam = {
                        "role": "tool",
                        "tool_call_id": tid,
                        "content": result,
                    }
                    messages.append(tool_msg)
                    transcript_full.append(tool_msg)
                continue

            # Final assistant turn (or stop without tools) — keep in transcript for follow-up turns.
            final_asst: ChatCompletionMessageParam = {"role": "assistant", "content": assistant_text}
            messages.append(final_asst)
            transcript_full.append(final_asst)
            return _finish(0, finish_reason or "stop", iterations_used=iterations)
    finally:
        if own_client:
            client.close()
