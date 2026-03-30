"""CLI entry (P0-01 … P0-04, P0-E2 run)."""

from __future__ import annotations

import sys
from pathlib import Path
from collections.abc import Callable
from typing import Annotated, Any, Literal, Optional

import typer
from openai.types.chat import ChatCompletionMessageParam

from codegen import __version__
from codegen.agent_loop import AgentRunResult, run_agent_task
from codegen.bootstrap import bootstrap
from codegen.config import CodegenConfigError
from codegen.console import make_console
from codegen.observability import (
    new_trace_id,
    normalize_structured_log_destination,
    open_structured_logger,
)
from codegen.rules import rules_content_sha256
from codegen.session_audit import normalize_session_audit_path, open_session_audit
from codegen.session_persist import load_session, resolve_session_storage_path, save_session
from codegen.workspace import WorkspaceError

app = typer.Typer(
    name="codegen",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Workspace-scoped coding agent. Use ``codegen -w DIR run TASK`` or "
        "``codegen run TASK -w DIR``; use ``codegen run -i`` for an interactive task loop "
        "(same for ``info``).\n\n"
        "Run-only flags (``--mode plan|execute``, ``--yes``, ``-i``, …) are on the ``run`` subcommand — "
        "use ``codegen run --help`` to list them; they do not appear on this top-level help.\n\n"
        "Config: TOML file via --config, CODEGEN_CONFIG, or <workspace>/codegen.toml; "
        "optional .env under workspace or a parent dir (loaded before env merge). "
        "Keys: model, base_url, max_iterations, max_wall_clock_seconds, agents_md. "
        "Environment: OPENAI_API_KEY (secret, never printed), OPENAI_BASE_URL, OPENAI_MODEL, "
        "CODEGEN_MAX_ITERATIONS, CODEGEN_MAX_WALL_CLOCK_SECONDS, CODEGEN_AGENTS_MD, CODEGEN_CONFIG, "
        "CODEGEN_STRUCTURED_LOG, CODEGEN_SESSION_AUDIT, CODEGEN_COMMAND_ALLOWLIST, "
        "CODEGEN_COMMAND_DENYLIST, CODEGEN_COMMAND_REQUIRE_APPROVAL, CODEGEN_SHELL_TIMEOUT_SECONDS, "
        "CODEGEN_SHELL_MAX_OUTPUT_BYTES, CODEGEN_VERIFICATION_HOOKS, CODEGEN_VERIFICATION_FAILURE, "
        "CODEGEN_RESPECT_GITIGNORE, CODEGEN_SESSION_FILE, CODEGEN_MAX_HISTORY_CHARS."
    ),
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit(0)


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Annotated[
        Optional[Path],
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root directory; defaults to the current working directory.",
        ),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option(
            "--config",
            "-c",
            help="Path to codegen.toml (overrides CODEGEN_CONFIG and workspace discovery).",
        ),
    ] = None,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Increase verbosity (repeatable).",
        ),
    ] = 0,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Print version and exit.",
        ),
    ] = False,
) -> None:
    """Codegen CLI — global options only; ``codegen run --help`` for ``--mode``, ``--yes``, etc."""
    ctx.obj = {
        "workspace": workspace,
        "config": config,
        "verbose": verbose,
    }
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command("info")
def info_cmd(
    ctx: typer.Context,
    workspace: Annotated[
        Optional[Path],
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (overrides global ``-w`` when placed after ``info``).",
        ),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option(
            "--config",
            "-c",
            help="Config file (overrides global ``-c`` when placed after ``info``).",
        ),
    ] = None,
) -> None:
    """Show resolved workspace, config (secrets redacted), and whether project rules loaded."""
    console = make_console()
    workspace_arg, config_arg = _merged_workspace_config(ctx, workspace, config)
    o: dict[str, Any] = ctx.obj
    verbose: int = o["verbose"]

    try:
        result = bootstrap(workspace_arg, config_arg)
    except WorkspaceError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1) from e
    except CodegenConfigError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(2) from e

    # P0-02: workspace root logged once per run
    console.print("[muted]workspace:[/muted] ", end="")
    console.print(str(result.workspace))

    summary = result.config.redacted_summary()
    if verbose:
        console.print("[muted]config (redacted):[/muted]")
        console.print_json(data=summary)
    else:
        console.print("[muted]model:[/muted] ", end="")
        console.print(summary["model"])
        console.print("[muted]base_url:[/muted] ", end="")
        console.print(summary["base_url"] or "(default)")
        console.print("[muted]limits:[/muted] ", end="")
        console.print(
            f"max_iterations={summary['max_iterations']}, "
            f"max_wall_clock_seconds={summary['max_wall_clock_seconds']}"
        )
        console.print("[muted]agents_md:[/muted] ", end="")
        console.print(summary["agents_md"])
        console.print("[muted]OPENAI_API_KEY:[/muted] ", end="")
        console.print("set" if summary["openai_api_key_set"] else "not set")
        console.print("[muted]structured_log:[/muted] ", end="")
        console.print(summary["structured_log"] or "(off)")
        console.print("[muted]session_audit:[/muted] ", end="")
        console.print(summary["session_audit"] or "(off)")
        console.print("[muted]verification_hooks:[/muted] ", end="")
        n = summary["verification_hooks_count"]
        console.print(f"{n} configured" if n else "(none)")
        console.print("[muted]verification_failure:[/muted] ", end="")
        console.print(summary["verification_failure"])
        console.print("[muted]respect_gitignore:[/muted] ", end="")
        console.print("on" if summary["respect_gitignore"] else "off")
        console.print("[muted]session_file:[/muted] ", end="")
        console.print(summary["session_file"] or "(off)")
        console.print("[muted]max_history_chars:[/muted] ", end="")
        console.print(str(summary["max_history_chars"]))

    if result.project_rules_text is None:
        console.print("[muted]project rules:[/muted] ", end="")
        console.print("(not present)")
    else:
        n = len(result.project_rules_text)
        console.print("[muted]project rules:[/muted] ", end="")
        console.print(f"loaded ({n} characters)")


def _build_system_prompt(
    workspace_display: str,
    project_rules: str | None,
    *,
    agent_mode: Literal["plan", "execute"] = "execute",
    respect_gitignore: bool = True,
) -> str:
    tools_line = (
        "You have tools: read_file, list_dir, grep, apply_patch (structured edits), run_terminal_cmd. "
        "If the workspace config lists verification_hooks, they run automatically after a fully "
        "successful apply_patch; check the verification field in the tool result (policy fail vs warn). "
        if agent_mode == "execute"
        else "You have read-only tools: read_file, list_dir, grep. "
    )
    gi_line = (
        "list_dir and grep skip paths matched by workspace .gitignore files (configurable)."
        if respect_gitignore
        else "list_dir and grep do not apply .gitignore filtering (respect_gitignore is off)."
    )
    parts = [
        "You are Codegen, a workspace-scoped coding assistant.",
        f"Workspace root: {workspace_display}",
        tools_line + "Paths are relative to the workspace.",
        gi_line,
        "Prefer tools over guessing file contents.",
        "If the task is ambiguous or missing critical detail (which path, API version, scope, or "
        "expected behavior), ask a short clarifying question before using apply_patch or "
        "run_terminal_cmd for substantive changes.",
    ]
    if project_rules:
        parts.append("Project rules (follow when relevant):\n" + project_rules)
    return "\n\n".join(parts)


def _merged_workspace_config(
    ctx: typer.Context,
    workspace: Optional[Path],
    config: Optional[Path],
) -> tuple[Optional[Path], Optional[Path]]:
    """Subcommand ``-w``/``-c`` override the parent callback options."""
    o: dict[str, Any] = ctx.obj
    w = workspace if workspace is not None else o["workspace"]
    c = config if config is not None else o["config"]
    return w, c


def _interactive_repl_quit(line: str) -> bool:
    t = line.strip().lower()
    return t in ("exit", "quit", ":q")


@app.command("run")
def run_cmd(
    ctx: typer.Context,
    task: Annotated[
        Optional[str],
        typer.Argument(help="Task in natural language. Omit with --interactive to type tasks in the shell."),
    ] = None,
    workspace: Annotated[
        Optional[Path],
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (overrides global ``-w`` when placed after ``run``).",
        ),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option(
            "--config",
            "-c",
            help="Config file (overrides global ``-c`` when placed after ``run``).",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="plan = read-only tools; execute = apply_patch + run_terminal_cmd (subject to policy).",
        ),
    ] = "execute",
    auto_approve: Annotated[
        bool,
        typer.Option(
            "--yes",
            help="Auto-approve shell commands that would otherwise require a TTY prompt.",
        ),
    ] = False,
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            "-i",
            help="Prompt for tasks until you type exit or quit (requires a TTY).",
        ),
    ] = False,
    session: Annotated[
        Optional[str],
        typer.Option(
            "--session",
            help=(
                "Session backing store: path to a .json file, or a name stored under "
                "``.codegen/sessions/<name>.json`` in the workspace. Overrides CODEGEN_SESSION_FILE."
            ),
        ),
    ] = None,
) -> None:
    """Run the agent: OpenAI drives tools; output is streamed."""
    console = make_console()
    workspace_arg, config_arg = _merged_workspace_config(ctx, workspace, config)

    try:
        result = bootstrap(workspace_arg, config_arg)
    except WorkspaceError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(1) from e
    except CodegenConfigError as e:
        console.print(f"[error]{e}[/error]")
        raise typer.Exit(2) from e

    if mode not in ("plan", "execute"):
        console.print(f"[error]Invalid --mode {mode!r}; use plan or execute.[/error]")
        raise typer.Exit(2)
    agent_mode: Literal["plan", "execute"] = "plan" if mode == "plan" else "execute"

    task_stripped = (task or "").strip()
    if not interactive and not task_stripped:
        console.print(
            "[error]TASK is required unless you pass --interactive (-i).[/error]",
        )
        raise typer.Exit(2)

    system = _build_system_prompt(
        str(result.workspace),
        result.project_rules_text,
        agent_mode=agent_mode,
        respect_gitignore=result.config.respect_gitignore,
    )
    trace_id = new_trace_id()
    session_path = resolve_session_storage_path(
        workspace=result.workspace,
        session_arg=session,
        config_path=result.config.session_file,
    )
    persisted = load_session(session_path) if session_path is not None else None
    if persisted is not None:
        ws_saved = Path(persisted.workspace).resolve()
        if ws_saved != result.workspace.resolve():
            console.print(
                "[error]Session file workspace does not match current -w workspace.[/error]\n"
                f"[muted]Session has:[/muted] {ws_saved}\n"
                f"[muted]Current:[/muted] {result.workspace.resolve()}",
            )
            raise typer.Exit(2)
        history = persisted.transcript()
        session_id = persisted.session_id
    else:
        history = []
        session_id = trace_id
    log_dest = normalize_structured_log_destination(result.config.structured_log)
    audit_path = normalize_session_audit_path(result.config.session_audit)
    close_log: Callable[[], None] | None = None
    close_audit: Callable[[], None] | None = None
    structured_logger = None
    session_audit_writer = None
    if log_dest:
        structured_logger, close_log = open_structured_logger(
            log_dest, trace_id=trace_id, session_id=session_id
        )
    if audit_path:
        session_audit_writer, close_audit = open_session_audit(
            audit_path, trace_id=trace_id, session_id=session_id
        )

    rules_hash = rules_content_sha256(result.project_rules_text)
    run_verbose: int = int(ctx.obj.get("verbose", 0))

    def _persist_if_needed(out: AgentRunResult) -> None:
        if session_path is None or out.exit_code != 0:
            return
        save_session(
            session_path,
            session_id=session_id,
            workspace=result.workspace,
            messages=out.transcript_after_system,
            created_at=persisted.created_at if persisted else None,
        )

    def _run_one(user_message: str) -> AgentRunResult:
        nonlocal history
        out = run_agent_task(
            workspace=result.workspace,
            config=result.config,
            system_prompt=system,
            user_message=user_message,
            console=console,
            structured_logger=structured_logger,
            session_audit=session_audit_writer,
            agent_mode=agent_mode,
            auto_approve=auto_approve,
            prior_messages=history if history else None,
            verbose=run_verbose,
            project_rules_sha256=rules_hash,
        )
        if out.exit_code == 0 and out.transcript_after_system:
            history = list(out.transcript_after_system)
            _persist_if_needed(out)
        return out

    try:
        if not interactive:
            out = _run_one(task_stripped)
            raise typer.Exit(out.exit_code)

        if not sys.stdin.isatty() or not sys.stdout.isatty():
            console.print(
                "[error]Interactive mode requires a terminal (stdin and stdout must be TTYs).[/error]",
            )
            raise typer.Exit(2)

        console.print(
            "[muted]Interactive mode — each successful turn keeps conversation context for follow-ups. "
            "Enter tasks (or exit, quit, :q, or Ctrl+Z then Enter on Windows / Ctrl+D on Unix). "
            "Empty lines are skipped.[/muted]",
        )
        console.print()

        last_exit = 0
        pending: list[str] = []
        if task_stripped:
            pending.append(task_stripped)

        while True:
            if not pending:
                console.print("[muted]codegen>[/muted] ", end="")
                try:
                    line = input()
                except EOFError:
                    console.print()
                    break
                if _interactive_repl_quit(line):
                    break
                if not line.strip():
                    continue
                pending.append(line.strip())

            user_message = pending.pop(0)
            out = _run_one(user_message)
            last_exit = out.exit_code
            console.print()

        raise typer.Exit(last_exit)
    finally:
        if close_log is not None:
            close_log()
        if close_audit is not None:
            close_audit()


def run() -> None:
    """Console script entry (tests may call ``app()`` directly)."""
    app()


if __name__ == "__main__":
    run()
