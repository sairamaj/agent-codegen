"""CLI entry (P0-01 … P0-04, P0-E2 run)."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Annotated, Any, Optional

import typer

from codegen import __version__
from codegen.agent_loop import run_agent_task
from codegen.bootstrap import bootstrap
from codegen.config import CodegenConfigError
from codegen.console import make_console
from codegen.observability import normalize_structured_log_destination, open_structured_logger
from codegen.workspace import WorkspaceError

app = typer.Typer(
    name="codegen",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Workspace-scoped coding agent. Use ``codegen -w DIR run TASK`` or "
        "``codegen run TASK -w DIR`` (same for ``info``).\n\n"
        "Config: TOML file via --config, CODEGEN_CONFIG, or <workspace>/codegen.toml; "
        "optional .env under workspace or a parent dir (loaded before env merge). "
        "Keys: model, base_url, max_iterations, max_wall_clock_seconds, agents_md. "
        "Environment: OPENAI_API_KEY (secret, never printed), OPENAI_BASE_URL, OPENAI_MODEL, "
        "CODEGEN_MAX_ITERATIONS, CODEGEN_MAX_WALL_CLOCK_SECONDS, CODEGEN_AGENTS_MD, CODEGEN_CONFIG, "
        "CODEGEN_STRUCTURED_LOG."
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
    """Codegen CLI — Phase 0 read-only agent (see ``codegen run``)."""
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

    if result.project_rules_text is None:
        console.print("[muted]project rules:[/muted] ", end="")
        console.print("(not present)")
    else:
        n = len(result.project_rules_text)
        console.print("[muted]project rules:[/muted] ", end="")
        console.print(f"loaded ({n} characters)")


def _build_system_prompt(workspace_display: str, project_rules: str | None) -> str:
    parts = [
        "You are Codegen, a workspace-scoped coding assistant.",
        f"Workspace root: {workspace_display}",
        "You have tools: read_file, list_dir, grep, apply_patch (structured edits). "
        "Paths are relative to the workspace.",
        "Prefer tools over guessing file contents.",
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


@app.command("run")
def run_cmd(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(help="Task in natural language.")],
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
) -> None:
    """Run the agent: OpenAI drives read-only tools; output is streamed."""
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

    system = _build_system_prompt(str(result.workspace), result.project_rules_text)
    log_dest = normalize_structured_log_destination(result.config.structured_log)
    close_log: Callable[[], None] | None = None
    structured_logger = None
    if log_dest:
        structured_logger, close_log = open_structured_logger(log_dest)
    try:
        out = run_agent_task(
            workspace=result.workspace,
            config=result.config,
            system_prompt=system,
            user_message=task,
            console=console,
            structured_logger=structured_logger,
        )
    finally:
        if close_log is not None:
            close_log()
    raise typer.Exit(out.exit_code)


def run() -> None:
    """Console script entry (tests may call ``app()`` directly)."""
    app()


if __name__ == "__main__":
    run()
