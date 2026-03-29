"""TTY-aware console: colors when appropriate, NO_COLOR safe."""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.theme import Theme

CODEGEN_THEME = Theme(
    {
        "user": "bold cyan",
        "assistant": "default",
        "tool": "magenta",
        "error": "bold red",
        "warn": "yellow",
        "muted": "dim",
    }
)


def env_no_color() -> bool:
    return os.environ.get("NO_COLOR", "").strip() not in ("", "0", "false", "False")


def stdout_is_tty() -> bool:
    return sys.stdout.isatty()


def make_console(*, force_color: bool | None = None) -> Console:
    """Rich console that disables styling when not a TTY or when NO_COLOR is set."""
    if force_color is True:
        return Console(theme=CODEGEN_THEME, force_terminal=True, highlight=False)
    if force_color is False:
        return Console(theme=CODEGEN_THEME, force_terminal=False, no_color=True, highlight=False)
    no_color = env_no_color()
    use_color = stdout_is_tty() and not no_color
    return Console(
        theme=CODEGEN_THEME,
        force_terminal=use_color,
        no_color=not use_color,
        highlight=False,
    )
