"""Command policy (P1-05)."""

from __future__ import annotations

from codegen.command_policy import (
    CommandPolicy,
    PolicyVerdict,
    command_policy_from_config,
    default_denylist,
)
from codegen.config import CodegenConfig


def test_denylist_wins_over_allow() -> None:
    pol = CommandPolicy(
        allowlist=("echo*",),
        denylist=("*bad*",),
        require_approval=(),
    )
    assert pol.evaluate("echo bad").verdict == PolicyVerdict.DENY


def test_allowlist_restricts() -> None:
    pol = CommandPolicy(
        allowlist=("pytest*",),
        denylist=(),
        require_approval=(),
    )
    assert pol.evaluate("pytest -q").verdict == PolicyVerdict.ALLOW
    assert pol.evaluate("python -m pytest").verdict == PolicyVerdict.DENY


def test_require_approval_after_passes_deny_and_allow() -> None:
    pol = CommandPolicy(
        allowlist=(),
        denylist=(),
        require_approval=("*push*",),
    )
    assert pol.evaluate("git push").verdict == PolicyVerdict.REQUIRE_APPROVAL


def test_command_policy_from_config_uses_defaults_when_none() -> None:
    cfg = CodegenConfig()
    pol = command_policy_from_config(cfg)
    assert pol.denylist == default_denylist()
    assert pol.evaluate("curl https://x").verdict == PolicyVerdict.DENY


def test_empty_explicit_denylist_in_config() -> None:
    cfg = CodegenConfig(command_denylist=[])
    pol = command_policy_from_config(cfg)
    assert pol.denylist == ()
    assert pol.evaluate("curl https://x").verdict != PolicyVerdict.DENY
