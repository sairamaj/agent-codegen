"""Context for tool execution (plan vs execute, policy, approvals)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from rich.console import Console

from codegen.command_policy import CommandPolicy
from codegen.observability import StructuredLogger


@dataclass
class ToolDispatchContext:
    """Passed into ``execute_tool`` for policy and mode checks."""

    agent_mode: Literal["plan", "execute"] = "execute"
    policy: CommandPolicy | None = None
    approval_callback: Callable[[str], bool] | None = None
    console: Console | None = None
    structured_logger: StructuredLogger | None = None
    #: Global -v count from CLI; used for context trace lines after tools (P2-03).
    verbose: int = 0
