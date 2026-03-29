"""TTY-aware console: semantic colors (P0-E4), NO_COLOR and non-TTY safe.

Four primary semantic styles (streams) for scanning:

- **user** — the human task / input
- **assistant** — model reply (streaming)
- **tool** — tool name and compact arg summary
- **error** — failures and API errors

Secondary: **warn**, **muted** (labels, limits, truncation hints).
"""

from __future__ import annotations

import os
import re
import sys
from typing import TextIO

from rich.console import Console
from rich.theme import Theme

CODEGEN_THEME = Theme(
    {
        "user": "bold cyan",
        "assistant": "green",
        "tool": "magenta",
        "error": "bold red",
        "warn": "yellow",
        "muted": "dim",
    }
)

# Tool arg summary on one line; longer payloads are truncated after redaction.
TOOL_ARGS_DISPLAY_MAX_LEN = 200

_SK_PATTERN = re.compile(r"\bsk-[a-zA-Z0-9]{10,}\b")
_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9._\-~+/=]+", re.I)
# JSON string values for common secret keys (double-quoted JSON).
_JSON_SECRET_PAIR = re.compile(
    r'("(?:api[_-]?key|token|password|secret|authorization)"\s*:\s*)("[^"]*")',
    re.I,
)


def env_no_color() -> bool:
    return os.environ.get("NO_COLOR", "").strip() not in ("", "0", "false", "False")


def stdout_is_tty() -> bool:
    return sys.stdout.isatty()


def redact_secrets_in_text(text: str) -> str:
    """Best-effort redaction for display-only strings (tool arg summaries, logs)."""
    t = _SK_PATTERN.sub("[redacted]", text)
    t = _BEARER_PATTERN.sub("Bearer [redacted]", t)

    def _hide_value(m: re.Match[str]) -> str:
        return f'{m.group(1)}"[redacted]"'

    t = _JSON_SECRET_PAIR.sub(_hide_value, t)
    return t


def format_user_task_preview(task: str, *, max_len: int = 480) -> str:
    """Single-line preview of the user task for console headers."""
    s = task.replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def redact_tool_args_display(
    arguments: str,
    *,
    max_len: int = TOOL_ARGS_DISPLAY_MAX_LEN,
) -> str:
    """Redact secrets, collapse whitespace, then truncate for one-line tool summaries."""
    t = redact_secrets_in_text(arguments)
    t = t.replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def make_console(
    *,
    force_color: bool | None = None,
    file: TextIO | None = None,
) -> Console:
    """Rich console: styling on TTY when ``NO_COLOR`` is unset; plain output otherwise.

    If ``file`` is set (e.g. ``StringIO`` for tests), output is never colorized.
    """
    if file is not None:
        return Console(
            theme=CODEGEN_THEME,
            file=file,
            force_terminal=False,
            no_color=True,
            highlight=False,
            width=120,
        )
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
