"""Post-edit verification hooks (P2-01, FR-VER-1–3)."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from codegen.config import CodegenConfig, CodegenConfigError, load_config
from codegen.console import make_console
from codegen.observability import tool_result_outcome
from codegen.tools_readonly import execute_tool
from codegen.verification_hooks import attach_verification_to_patch_result, run_verification_hooks


def test_run_verification_hooks_success(tmp_path: Path) -> None:
    results, ok = run_verification_hooks(
        tmp_path,
        [f'{__import__("sys").executable} -c "print(1)"'],
        timeout_seconds=30,
        max_output_bytes=4096,
        console=None,
    )
    assert ok is True
    assert len(results) == 1
    assert results[0]["ok"] is True
    assert results[0]["exit_code"] == 0
    assert "1" in results[0]["stdout"]


def test_run_verification_hooks_failure(tmp_path: Path) -> None:
    py = __import__("sys").executable
    results, ok = run_verification_hooks(
        tmp_path,
        [f'{py} -c "raise SystemExit(2)"'],
        timeout_seconds=30,
        max_output_bytes=4096,
        console=None,
    )
    assert ok is False
    assert results[0]["ok"] is False
    assert results[0]["exit_code"] == 2


def test_attach_verification_fail_policy() -> None:
    patch = json.dumps({"ok": True, "files": [{"path": "a.txt", "ok": True}]})
    hooks = [
        {
            "command": "x",
            "ok": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "e",
            "truncated_stdout": False,
            "truncated_stderr": False,
        }
    ]
    out = attach_verification_to_patch_result(
        patch,
        commands_were_configured=True,
        hook_results=hooks,
        verification_ok=False,
        policy="fail",
    )
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error"]["code"] == "VERIFICATION_FAILED"
    assert data["verification"]["ok"] is False
    assert data["verification"]["policy"] == "fail"


def test_attach_verification_warn_policy() -> None:
    patch = json.dumps({"ok": True, "files": []})
    hooks = [{"command": "x", "ok": False, "exit_code": 1, "stdout": "", "stderr": "", "truncated_stdout": False, "truncated_stderr": False}]
    out = attach_verification_to_patch_result(
        patch,
        commands_were_configured=True,
        hook_results=hooks,
        verification_ok=False,
        policy="warn",
    )
    data = json.loads(out)
    assert data["ok"] is True
    assert "error" not in data
    assert data["verification"]["ok"] is False


def test_execute_tool_apply_patch_runs_hooks_warn(tmp_path: Path) -> None:
    (tmp_path / "t.py").write_text("x=1\n", encoding="utf-8")
    cfg = CodegenConfig(
        verification_hooks=[f'{__import__("sys").executable} -c "raise SystemExit(5)"'],
        verification_failure="warn",
    )
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "t.py",
                        "hunks": [{"old_text": "x=1", "new_text": "x=2"}],
                    }
                ]
            }
        ),
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["verification"]["policy"] == "warn"
    assert data["verification"]["ok"] is False
    assert data["verification"]["hooks"][0]["exit_code"] == 5
    assert (tmp_path / "t.py").read_text() == "x=2\n"


def test_execute_tool_apply_patch_hooks_fail_policy(tmp_path: Path) -> None:
    (tmp_path / "t.py").write_text("a\n", encoding="utf-8")
    cfg = CodegenConfig(
        verification_hooks=[f'{__import__("sys").executable} -c "raise SystemExit(1)"'],
        verification_failure="fail",
    )
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {
                        "path": "t.py",
                        "hunks": [{"old_text": "a", "new_text": "b"}],
                    }
                ]
            }
        ),
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "VERIFICATION_FAILED"


def test_execute_tool_partial_patch_skips_hooks(tmp_path: Path) -> None:
    (tmp_path / "ok.txt").write_text("ok\n", encoding="utf-8")
    (tmp_path / "bad.txt").write_text("z\n", encoding="utf-8")
    cfg = CodegenConfig(
        verification_hooks=[f'{__import__("sys").executable} -c "raise SystemExit(99)"'],
        verification_failure="fail",
    )
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps(
            {
                "files": [
                    {"path": "ok.txt", "hunks": [{"old_text": "ok", "new_text": "OK"}]},
                    {"path": "bad.txt", "hunks": [{"old_text": "nope", "new_text": "x"}]},
                ]
            }
        ),
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is False
    assert "verification" not in data


def test_load_config_verification_from_toml(tmp_path: Path) -> None:
    (tmp_path / "codegen.toml").write_text(
        'verification_hooks = ["echo a"]\nverification_failure = "fail"\n',
        encoding="utf-8",
    )
    cfg = load_config(workspace=tmp_path)
    assert cfg.verification_hooks == ["echo a"]
    assert cfg.verification_failure == "fail"


def test_load_config_verification_hooks_env_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEGEN_VERIFICATION_HOOKS", '["whoami"]')
    cfg = load_config(workspace=tmp_path)
    assert cfg.verification_hooks == ["whoami"]


def test_load_config_verification_hooks_env_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEGEN_VERIFICATION_HOOKS", "not-json")
    with pytest.raises(CodegenConfigError, match="JSON"):
        load_config(workspace=tmp_path)


def test_tool_result_outcome_verification_failed() -> None:
    payload = {
        "ok": False,
        "error": {"code": "VERIFICATION_FAILED", "message": "x"},
        "files": [],
        "verification": {"ok": False, "policy": "fail", "hooks": []},
    }
    o = tool_result_outcome(json.dumps(payload))
    assert o["outcome"] == "error"
    assert o["error_code"] == "VERIFICATION_FAILED"


def test_console_stderr_style_for_hook_stderr(tmp_path: Path) -> None:
    py = __import__("sys").executable
    buf = StringIO()
    con = make_console(file=buf)
    run_verification_hooks(
        tmp_path,
        [f'{py} -c "import sys; print(\\"e\\", file=sys.stderr); raise SystemExit(1)"'],
        timeout_seconds=30,
        max_output_bytes=4096,
        console=con,
    )
    text = buf.getvalue()
    assert "e" in text
