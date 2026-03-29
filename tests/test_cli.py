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
