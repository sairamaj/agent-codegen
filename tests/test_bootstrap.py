"""End-to-end bootstrap."""

import os
from pathlib import Path

import pytest

from codegen.bootstrap import bootstrap


def test_bootstrap_with_rules(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    r = bootstrap(tmp_path, None)
    assert r.workspace == tmp_path.resolve()
    assert r.project_rules_text == "rules"


def test_bootstrap_loads_workspace_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    (tmp_path / ".env").write_text("OPENAI_MODEL=gpt-from-dotenv\n", encoding="utf-8")
    try:
        r = bootstrap(tmp_path, None)
        assert r.config.model == "gpt-from-dotenv"
    finally:
        os.environ.pop("OPENAI_MODEL", None)


def test_bootstrap_loads_dotenv_from_parent_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-parent\n", encoding="utf-8")
    nested = tmp_path / "sub" / "nested"
    nested.mkdir(parents=True)
    try:
        r = bootstrap(nested, None)
        assert r.config.openai_api_key == "sk-from-parent"
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
