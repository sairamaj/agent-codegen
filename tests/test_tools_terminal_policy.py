"""run_terminal_cmd policy and plan mode (P1-04, P1-05, P1-06, X-03)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from codegen.command_policy import command_policy_from_config
from codegen.config import CodegenConfig
from codegen.tool_dispatch import ToolDispatchContext
from codegen.tools_readonly import execute_tool


def test_run_terminal_cmd_echo(tmp_path: Path) -> None:
    cfg = CodegenConfig(
        openai_api_key="x",
        command_denylist=[],
        command_require_approval=[],
    )
    pol = command_policy_from_config(cfg)
    dispatch = ToolDispatchContext(
        agent_mode="execute",
        policy=pol,
        approval_callback=lambda _c: True,
    )
    raw = execute_tool(
        tmp_path,
        "run_terminal_cmd",
        json.dumps({"command": 'echo hello', "cwd": "."}),
        dispatch=dispatch,
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["exit_code"] == 0
    assert "hello" in (data.get("stdout") or "")


def test_denied_command_never_runs_subprocess(tmp_path: Path) -> None:
    cfg = CodegenConfig(
        openai_api_key="x",
        command_denylist=["*echo*"],
        command_require_approval=[],
    )
    pol = command_policy_from_config(cfg)
    dispatch = ToolDispatchContext(
        agent_mode="execute",
        policy=pol,
        approval_callback=lambda _c: True,
    )
    with patch("codegen.tools_terminal.subprocess.run") as mock_run:
        raw = execute_tool(
            tmp_path,
            "run_terminal_cmd",
            json.dumps({"command": "echo x"}),
            dispatch=dispatch,
            config=cfg,
        )
        mock_run.assert_not_called()
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "COMMAND_DENIED_BY_POLICY"


def test_plan_mode_blocks_shell(tmp_path: Path) -> None:
    cfg = CodegenConfig(openai_api_key="x")
    dispatch = ToolDispatchContext(agent_mode="plan", policy=command_policy_from_config(cfg))
    raw = execute_tool(
        tmp_path,
        "run_terminal_cmd",
        json.dumps({"command": "echo hi"}),
        dispatch=dispatch,
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "PLAN_MODE"


def test_plan_mode_blocks_patch(tmp_path: Path) -> None:
    cfg = CodegenConfig(openai_api_key="x")
    dispatch = ToolDispatchContext(agent_mode="plan", policy=command_policy_from_config(cfg))
    raw = execute_tool(
        tmp_path,
        "apply_patch",
        json.dumps({"files": []}),
        dispatch=dispatch,
        config=cfg,
    )
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "PLAN_MODE"


def test_approval_denied_skips_subprocess(tmp_path: Path) -> None:
    cfg = CodegenConfig(
        openai_api_key="x",
        command_denylist=[],
        command_require_approval=["*echo*"],
    )
    pol = command_policy_from_config(cfg)
    dispatch = ToolDispatchContext(
        agent_mode="execute",
        policy=pol,
        approval_callback=lambda _c: False,
    )
    with patch("codegen.tools_terminal.subprocess.run") as mock_run:
        raw = execute_tool(
            tmp_path,
            "run_terminal_cmd",
            json.dumps({"command": "echo no"}),
            dispatch=dispatch,
            config=cfg,
        )
        mock_run.assert_not_called()
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "COMMAND_APPROVAL_DENIED"
