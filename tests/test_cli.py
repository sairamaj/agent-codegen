"""CLI smoke tests (P0-01)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("typer", reason="Install the package (pip install -e .) to run CLI subprocess tests.")

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + prev if prev else "")
    return subprocess.run(
        [sys.executable, "-m", "codegen", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_help_exits_zero() -> None:
    r = _run("--help")
    assert r.returncode == 0
    out = r.stdout + r.stderr
    assert "--workspace" in out
    assert "--config" in out
    assert "--verbose" in out


def test_no_args_shows_help() -> None:
    r = _run()
    assert r.returncode == 0
    out = r.stdout + r.stderr
    assert "Usage" in out or "codegen" in out


def test_version() -> None:
    r = _run("--version")
    assert r.returncode == 0
    assert (r.stdout + r.stderr).strip()


def test_info_ok(tmp_path: Path) -> None:
    r = _run("-w", str(tmp_path), "info")
    assert r.returncode == 0
    out = (r.stdout + r.stderr).replace("\\", "/")
    assert str(tmp_path.resolve()).replace("\\", "/") in out
    assert "not present" in out or "loaded" in out


def test_info_bad_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    r = _run("-w", str(missing), "info")
    assert r.returncode == 1


def test_run_help() -> None:
    r = _run("run", "--help")
    assert r.returncode == 0
    out = r.stdout + r.stderr
    assert "run" in out.lower()
    assert "--workspace" in out or "-w" in out


def test_mcp_check_help() -> None:
    r = _run("mcp-check", "--help")
    assert r.returncode == 0
    out = r.stdout + r.stderr
    assert "mcp-check" in out.lower()
    assert "--workspace" in out or "-w" in out


def test_mcp_check_without_servers(tmp_path: Path) -> None:
    r = _run("-w", str(tmp_path), "mcp-check")
    assert r.returncode == 2
    out = (r.stdout + r.stderr).lower()
    assert "no mcp servers configured" in out


def test_run_accepts_workspace_after_task(tmp_path: Path) -> None:
    """``-w`` after ``run`` must be recognized (not a global-only option)."""
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + prev if prev else "")
    r = subprocess.run(
        [sys.executable, "-m", "codegen", "run", "hello", "-w", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    out = r.stdout + r.stderr
    assert "No such option" not in out
    assert r.returncode == 2
    assert "OPENAI_API_KEY" in out or "not set" in out.lower()


def test_run_requires_task_without_interactive(tmp_path: Path) -> None:
    r = _run("-w", str(tmp_path), "run")
    assert r.returncode == 2
    out = r.stdout + r.stderr
    assert "TASK" in out or "interactive" in out.lower()


def test_run_interactive_requires_tty(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + prev if prev else "")
    r = subprocess.run(
        [sys.executable, "-m", "codegen", "-w", str(tmp_path), "run", "-i"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 2
    out = r.stdout + r.stderr
    assert "TTY" in out or "terminal" in out.lower() or "stdin" in out.lower()


def test_system_prompt_includes_clarifying_question_guidance() -> None:
    """P1-09 (FR-TASK-3): model is instructed to ask before substantive edits when ambiguous."""
    import codegen.cli as cli_mod

    for mode in ("plan", "execute"):
        text = cli_mod._build_system_prompt("/workspace", None, agent_mode=mode)
        assert "clarifying" in text.lower()
