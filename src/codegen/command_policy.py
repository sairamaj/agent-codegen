"""Shell command policy: allowlist / denylist / require approval (P1-05, FR-TOOL-7)."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PolicyVerdict(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class PolicyOutcome:
    verdict: PolicyVerdict
    reason: str | None = None


def _norm(s: str) -> str:
    return " ".join(s.strip().split())


def _matches_any(patterns: list[str], command: str) -> bool:
    cmd = _norm(command).lower()
    for raw in patterns:
        p = raw.strip()
        if not p:
            continue
        pat = p.lower()
        if fnmatch.fnmatch(cmd, pat):
            return True
    return False


@dataclass(frozen=True)
class CommandPolicy:
    """
    Evaluate a shell command string (as passed to ``run_terminal_cmd``).

    Order: **denylist** first (never runs), then **allowlist** (if non-empty,
    command must match at least one pattern), then **require_approval** for
    sensitive operations that may proceed after user confirmation.
    """

    allowlist: tuple[str, ...]
    denylist: tuple[str, ...]
    require_approval: tuple[str, ...]

    def evaluate(self, command: str) -> PolicyOutcome:
        if not command or not command.strip():
            return PolicyOutcome(PolicyVerdict.DENY, "empty command")

        if _matches_any(list(self.denylist), command):
            return PolicyOutcome(PolicyVerdict.DENY, "matched command_denylist pattern")

        if self.allowlist and not _matches_any(list(self.allowlist), command):
            return PolicyOutcome(PolicyVerdict.DENY, "did not match any command_allowlist pattern")

        if _matches_any(list(self.require_approval), command):
            return PolicyOutcome(PolicyVerdict.REQUIRE_APPROVAL, "matched require_approval pattern")

        return PolicyOutcome(PolicyVerdict.ALLOW, None)


def default_denylist() -> tuple[str, ...]:
    """Conservative defaults: destructive and obvious network fetchers."""
    return (
        "*rm -rf*",
        "*curl*",
        "*wget*",
        "*Invoke-WebRequest*",
        "*iwr *",
    )


def default_require_approval() -> tuple[str, ...]:
    """Sensitive operations that proceed only after explicit approval."""
    return (
        "*git push*",
        "*git reset --hard*",
        "*npm publish*",
        "*twine*upload*",
        "*rm *",
        "*del *",
        "*Remove-Item*",
    )


def command_policy_from_config(cfg: Any) -> CommandPolicy:
    """Build policy from merged config (``None`` lists use built-in defaults)."""
    deny = tuple(cfg.command_denylist) if cfg.command_denylist is not None else default_denylist()
    req = (
        tuple(cfg.command_require_approval)
        if cfg.command_require_approval is not None
        else default_require_approval()
    )
    return CommandPolicy(
        allowlist=tuple(cfg.command_allowlist),
        denylist=deny,
        require_approval=req,
    )

