"""Single entry for workspace + config + project rules (P0-E1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from codegen.config import CodegenConfig, load_config, load_workspace_dotenv
from codegen.rules import load_project_rules
from codegen.workspace import resolve_workspace


@dataclass(frozen=True)
class BootstrapResult:
    """Resolved runtime inputs for an agent run (rules for model context when present)."""

    workspace: Path
    config: CodegenConfig
    """Full merged config; never log ``openai_api_key`` in clear text."""
    project_rules_text: str | None
    """Content of project rules file, or None if missing (P0-04)."""


def bootstrap(
    workspace: Path | None,
    config_path: Path | None,
) -> BootstrapResult:
    root = resolve_workspace(workspace)
    load_workspace_dotenv(root)
    cfg = load_config(workspace=root, config_path=config_path)
    rules = load_project_rules(root, cfg.agents_md)
    return BootstrapResult(workspace=root, config=cfg, project_rules_text=rules)
