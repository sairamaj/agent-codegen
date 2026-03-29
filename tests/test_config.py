"""Configuration merge and validation (P0-03)."""

from pathlib import Path

import pytest

from codegen.config import CodegenConfigError, load_config, resolve_config_file_path


def test_load_defaults(tmp_path: Path) -> None:
    cfg = load_config(workspace=tmp_path)
    assert cfg.model == "gpt-4o-mini"
    assert cfg.base_url is None
    assert cfg.openai_api_key is None


def test_load_from_toml(tmp_path: Path) -> None:
    (tmp_path / "codegen.toml").write_text(
        'model = "gpt-4o"\nbase_url = "https://example.com/v1"\nmax_iterations = 10\n',
        encoding="utf-8",
    )
    cfg = load_config(workspace=tmp_path)
    assert cfg.model == "gpt-4o"
    assert cfg.base_url == "https://example.com/v1"
    assert cfg.max_iterations == 10


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "codegen.toml").write_text('model = "from-file"\n', encoding="utf-8")
    monkeypatch.setenv("OPENAI_MODEL", "from-env")
    cfg = load_config(workspace=tmp_path)
    assert cfg.model == "from-env"


def test_openai_api_key_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    cfg = load_config(workspace=tmp_path)
    assert cfg.openai_api_key == "secret-key"


def test_redacted_summary_hides_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    cfg = load_config(workspace=tmp_path)
    s = cfg.redacted_summary()
    assert s["openai_api_key_set"] is True
    assert "openai_api_key" not in s


def test_invalid_toml(tmp_path: Path) -> None:
    (tmp_path / "codegen.toml").write_text("not[[toml", encoding="utf-8")
    with pytest.raises(CodegenConfigError, match="Invalid TOML"):
        load_config(workspace=tmp_path)


def test_invalid_field(tmp_path: Path) -> None:
    (tmp_path / "codegen.toml").write_text("max_iterations = 0\n", encoding="utf-8")
    with pytest.raises(CodegenConfigError, match="Invalid configuration"):
        load_config(workspace=tmp_path)


def test_base_url_requires_scheme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "api.openai.com/v1")
    with pytest.raises(CodegenConfigError, match="base_url|https"):
        load_config(workspace=tmp_path)


def test_explicit_config_path(tmp_path: Path) -> None:
    other = tmp_path / "other.toml"
    other.write_text('model = "x"\n', encoding="utf-8")
    cfg = load_config(workspace=tmp_path, config_path=other)
    assert cfg.model == "x"


def test_missing_explicit_config(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(CodegenConfigError, match="not found"):
        load_config(workspace=tmp_path, config_path=missing)


def test_codegen_config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "via-env.toml"
    p.write_text('model = "envfile"\n', encoding="utf-8")
    monkeypatch.setenv("CODEGEN_CONFIG", str(p))
    cfg = load_config(workspace=tmp_path)
    assert cfg.model == "envfile"


def test_invalid_codegen_max_iterations_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEGEN_MAX_ITERATIONS", "nope")
    with pytest.raises(CodegenConfigError, match="integer"):
        load_config(workspace=tmp_path)


def test_resolve_config_file_path_none_when_no_file(tmp_path: Path) -> None:
    assert resolve_config_file_path(workspace=tmp_path, config_path=None) is None


def test_session_audit_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEGEN_SESSION_AUDIT", str(tmp_path / "a.jsonl"))
    cfg = load_config(workspace=tmp_path)
    assert cfg.session_audit == str(tmp_path / "a.jsonl")
    assert cfg.redacted_summary()["session_audit"] == "file:a.jsonl"
