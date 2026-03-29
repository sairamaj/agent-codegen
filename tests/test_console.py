"""Console semantics and redaction (P0-E4)."""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest

from codegen.console import (
    TOOL_ARGS_DISPLAY_MAX_LEN,
    format_user_task_preview,
    make_console,
    redact_secrets_in_text,
    redact_tool_args_display,
)


def test_redact_openai_sk() -> None:
    s = '{"key":"sk-123456789012345678901234567890"}'
    out = redact_secrets_in_text(s)
    assert "sk-123456789012345678901234567890" not in out
    assert "[redacted]" in out


def test_redact_bearer() -> None:
    s = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    out = redact_secrets_in_text(s)
    assert "eyJ" not in out
    assert "Bearer [redacted]" in out


def test_redact_json_secret_keys() -> None:
    s = '{"api_key": "supersecret", "path": "ok"}'
    out = redact_secrets_in_text(s)
    assert "supersecret" not in out
    assert '"api_key": "[redacted]"' in out or '"[redacted]"' in out
    assert "ok" in out


def test_redact_tool_args_truncates() -> None:
    long_arg = "x" * (TOOL_ARGS_DISPLAY_MAX_LEN + 50)
    out = redact_tool_args_display(long_arg)
    assert len(out) == TOOL_ARGS_DISPLAY_MAX_LEN
    assert out.endswith("…")


def test_format_user_task_preview_truncates() -> None:
    t = "a" * 600
    out = format_user_task_preview(t, max_len=100)
    assert len(out) == 100
    assert out.endswith("…")


def test_make_console_file_is_plain_text() -> None:
    buf = io.StringIO()
    c = make_console(file=buf)
    c.print("[error]oops[/error]")
    out = buf.getvalue()
    assert "\x1b" not in out
    assert "oops" in out


class _FakeTTYStdout(io.StringIO):
    def isatty(self) -> bool:  # noqa: D102
        return True


def test_no_color_env_disables_ansi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    buf = _FakeTTYStdout()
    with patch("codegen.console.sys.stdout", buf):
        c = make_console()
        c.print("[error]hello[/error]")
    assert "\x1b" not in buf.getvalue()
    assert "hello" in buf.getvalue()
