"""CLI entry (P0-01, P0-02, P0-03, P0-04)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Optional

import typer

from codegen import __version__
from codegen.bootstrap import bootstrap
from codegen.config import CodegenConfigError
from codegen.console import make_console
from codegen.workspace import WorkspaceError

app = typer.Typer(
    name="codegen",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Workspace-scoped coding agent. Global options apply to subcommands.\n\n"
        "Config: TOML file via --config, CODEGEN_CONFIG, or <workspace>/codegen.toml. "
        "Keys: model, base_url, max_iterations, max_wall_clock_seconds, agents_md. "
        "Environment: OPENAI_API_KEY (secret, never printed), OPENAI_BASE_URL, OPENAI_MODEL, "
        "CODEGEN_MAX_ITERATIONS, CODEGEN_MAX_WALL_CLOCK_SECONDS, CODEGEN_AGENTS_MD."
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
    """Codegen CLI — Phase 0 read-only agent (tools and loop in later stories)."""
    ctx.obj = {
        "workspace": workspace,
        "config": config,
        "verbose": verbose,
    }
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


@app.command("info")
def info_cmd(ctx: typer.Context) -> None:
    """Show resolved workspace, config (secrets redacted), and whether project rules loaded."""
    console = make_console()
    o: dict[str, Any] = ctx.obj
    workspace_arg: Path | None = o["workspace"]
    config_arg: Path | None = o["config"]
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

    if result.project_rules_text is None:
        console.print("[muted]project rules:[/muted] ", end="")
        console.print("(not present)")
    else:
        n = len(result.project_rules_text)
        console.print("[muted]project rules:[/muted] ", end="")
        console.print(f"loaded ({n} characters)")


def run() -> None:
    """Console script entry (tests may call ``app()`` directly)."""
    app()


if __name__ == "__main__":
    run()
