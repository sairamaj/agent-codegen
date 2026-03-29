"""End-to-end bootstrap."""

from pathlib import Path

from codegen.bootstrap import bootstrap


def test_bootstrap_with_rules(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    r = bootstrap(tmp_path, None)
    assert r.workspace == tmp_path.resolve()
    assert r.project_rules_text == "rules"
