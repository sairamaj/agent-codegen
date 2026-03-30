"""Project rules (P0-04)."""

from pathlib import Path

from codegen.rules import load_project_rules, resolve_rules_path, rules_content_sha256


def test_load_missing_agents_md(tmp_path: Path) -> None:
    assert load_project_rules(tmp_path, "AGENTS.md") is None


def test_load_present_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
    text = load_project_rules(tmp_path, "AGENTS.md")
    assert text == "# Rules\n"


def test_relative_path_under_workspace(tmp_path: Path) -> None:
    sub = tmp_path / "docs"
    sub.mkdir()
    (sub / "rules.md").write_text("x", encoding="utf-8")
    assert load_project_rules(tmp_path, "docs/rules.md") == "x"


def test_rules_content_sha256() -> None:
    assert rules_content_sha256(None) is None
    h = rules_content_sha256("hello")
    assert h is not None and len(h) == 64


def test_resolve_absolute(tmp_path: Path) -> None:
    f = tmp_path / "r.md"
    f.write_text("z", encoding="utf-8")
    p = resolve_rules_path(tmp_path, str(f))
    assert p == f.resolve()
