"""OpenAI chat loop with tools, streaming, and task limits (P0-E2)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import APIError, OpenAI
from openai.types.chat import ChatCompletionMessageParam
from rich.console import Console

from codegen.config import CodegenConfig
from codegen.console import format_user_task_preview, redact_secrets_in_text, redact_tool_args_display
from codegen.observability import StructuredLogger, sanitize_args_for_log, tool_result_outcome
from codegen.tools_readonly import TOOL_DEFINITIONS, execute_tool


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


def _http_timeout_seconds(cfg: CodegenConfig) -> float:
    """Bound a single HTTP call; keep below task wall clock."""
    return float(min(120, max(30, cfg.max_wall_clock_seconds)))


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
) -> AgentRunResult:
    """
    Run the model with read-only tools until a final assistant message or a limit.

    Streams assistant text to ``console`` (P0-07). Enforces ``max_iterations`` and
    ``max_wall_clock_seconds`` (P0-06). Tool failures are JSON strings (P0-08).
    """
    if not (config.openai_api_key or "").strip():
        console.print("[error]OPENAI_API_KEY is not set.[/error]")
        return AgentRunResult(exit_code=2, iterations_used=0, stop_reason="missing_api_key")

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
        return AgentRunResult(
            exit_code=exit_code,
            iterations_used=iterations_used,
            stop_reason=stop_reason,
            tool_calls=all_records,
        )

    console.print("[muted]user[/muted] ", end="")
    console.print(format_user_task_preview(user_message), style="user")
    console.print()

    own_client = client is None
    if client is None:
        client = OpenAI(
            api_key=config.openai_api_key,
            base_url=config.base_url or None,
            timeout=_http_timeout_seconds(config),
        )

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    if structured_logger is not None:
        task_preview = redact_secrets_in_text(format_user_task_preview(user_message))
        structured_logger.emit(
            "run.start",
            workspace=str(workspace),
            model=config.model,
            task_preview=task_preview,
            max_iterations=config.max_iterations,
            max_wall_clock_seconds=config.max_wall_clock_seconds,
        )

    deadline = time.monotonic() + float(config.max_wall_clock_seconds)
    all_records: list[ToolCallRecord] = []
    iterations = 0

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
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    stream=True,
                    parallel_tool_calls=True,
                )
            except APIError as e:
                console.print()
                console.print(f"[error]OpenAI API error: {e}[/error]")
                return _finish(1, "api_error", iterations_used=iterations)

            assistant_content_parts: list[str] = []
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
                    result = execute_tool(workspace, name, raw_args)
                    duration_ms = int((time.monotonic() - t_tool) * 1000)
                    if structured_logger is not None:
                        outcome = tool_result_outcome(result)
                        structured_logger.emit(
                            "tool.complete",
                            tool_name=name,
                            duration_ms=duration_ms,
                            **outcome,
                        )
                    all_records.append(ToolCallRecord(name=name, arguments=raw_args, result=result))
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tid,
                            "content": result,
                        }
                    )
                continue

            # Final assistant turn (or stop without tools)
            if assistant_text is not None:
                # already printed while streaming
                pass
            return _finish(0, finish_reason or "stop", iterations_used=iterations)
    finally:
        if own_client:
            client.close()
