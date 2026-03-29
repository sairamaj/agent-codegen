"""Configuration: TOML file + environment (NFR-PRIV, requirements §7.3)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import tomllib
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator


class CodegenConfigError(Exception):
    """Invalid configuration file or merged settings."""


class CodegenConfig(BaseModel):
    """
    Merged configuration after file + environment.

    Precedence (later wins): defaults < TOML file < discovered ``.env`` (via
    ``load_workspace_dotenv``) < process environment variables.

    Documented environment variables:
    - OPENAI_API_KEY — API secret (never printed by the CLI).
    - OPENAI_BASE_URL — optional API base URL.
    - OPENAI_MODEL — optional model name override.
    - CODEGEN_CONFIG — path to TOML config file when --config is not passed.
    """

    model: str = Field(default="gpt-4o-mini", description="OpenAI model id.")
    base_url: str | None = Field(default=None, description="Optional OpenAI API base URL.")
    max_iterations: int = Field(default=25, ge=1, le=10_000)
    max_wall_clock_seconds: int = Field(default=600, ge=1, le=86_400)
    agents_md: str = Field(
        default="AGENTS.md",
        description="Project rules file path, relative to workspace or absolute.",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="Set via OPENAI_API_KEY only; kept for downstream client use.",
    )

    @field_validator("base_url")
    @classmethod
    def strip_base_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        s = v.strip()
        return s or None

    def redacted_summary(self) -> dict[str, Any]:
        """Safe dict for logging / `codegen info` (no secrets)."""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "max_iterations": self.max_iterations,
            "max_wall_clock_seconds": self.max_wall_clock_seconds,
            "agents_md": self.agents_md,
            "openai_api_key_set": bool(self.openai_api_key),
        }


def _read_toml_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise CodegenConfigError(f"Cannot read config file {path}: {e}") from e
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise CodegenConfigError(f"Invalid TOML in {path}: {e}") from e
    if not isinstance(data, dict):
        raise CodegenConfigError(f"Config root must be a table in {path}")
    return data


def _find_default_config_file(workspace: Path) -> Path | None:
    for name in ("codegen.toml", ".codegen.toml"):
        candidate = workspace / name
        if candidate.is_file():
            return candidate
    return None


def _find_dotenv_path(workspace: Path) -> Path | None:
    """
    Find ``.env`` starting at the workspace directory, walking up to the drive root.

    Closest file to the workspace wins (``pkg/.env`` before ``repo/.env``).
    """
    cur = workspace.resolve()
    for _ in range(256):
        candidate = cur / ".env"
        if candidate.is_file():
            return candidate
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def load_workspace_dotenv(workspace: Path) -> None:
    """
    Load a discovered ``.env`` into the process environment if one exists.

    The file is searched from ``workspace`` upward (so a ``.env`` in a parent
    folder still applies when the workspace is a subdirectory). Does not
    override variables already set in the environment. Uses UTF-8 with BOM
    stripped (``utf-8-sig``) for Windows-friendly files.

    Call before ``load_config`` so merged settings see these values.
    """
    path = _find_dotenv_path(workspace)
    if path is not None:
        load_dotenv(dotenv_path=path, override=False, encoding="utf-8-sig")


def resolve_config_file_path(
    *,
    workspace: Path,
    config_path: Path | None,
) -> Path | None:
    """Return path to TOML to load, or None if no file should be read."""
    if config_path is not None:
        p = config_path.expanduser()
        if not p.is_file():
            raise CodegenConfigError(f"Config file not found: {p}")
        return p.resolve()
    env_path = os.environ.get("CODEGEN_CONFIG", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if not p.is_file():
            raise CodegenConfigError(f"CODEGEN_CONFIG points to missing file: {p}")
        return p.resolve()
    return _find_default_config_file(workspace)


def load_config(
    *,
    workspace: Path,
    config_path: Path | None = None,
) -> CodegenConfig:
    """
    Load configuration from optional TOML plus environment overlays.

    ``bootstrap`` loads a ``.env`` (see ``_find_dotenv_path``) before this;
    existing process env vars still win over ``.env`` entries.

    TOML keys (all optional): model, base_url, max_iterations, max_wall_clock_seconds, agents_md.
    """
    file_data: dict[str, Any] = {}
    resolved = resolve_config_file_path(workspace=workspace, config_path=config_path)
    if resolved is not None:
        file_data = _read_toml_file(resolved)

    merged: dict[str, Any] = {**file_data}

    if (m := os.environ.get("OPENAI_MODEL", "").strip()):
        merged["model"] = m
    if (u := os.environ.get("OPENAI_BASE_URL", "").strip()):
        merged["base_url"] = u
    if (k := os.environ.get("OPENAI_API_KEY", "").strip()):
        merged["openai_api_key"] = k

    for key in ("max_iterations", "max_wall_clock_seconds"):
        env_key = f"CODEGEN_{key.upper()}"
        raw = os.environ.get(env_key, "").strip()
        if raw:
            try:
                merged[key] = int(raw)
            except ValueError as e:
                raise CodegenConfigError(f"{env_key} must be an integer, got {raw!r}") from e

    if (p := os.environ.get("CODEGEN_AGENTS_MD", "").strip()):
        merged["agents_md"] = p

    try:
        return CodegenConfig.model_validate(merged)
    except ValidationError as e:
        raise CodegenConfigError(_format_validation_error(e)) from e


def _format_validation_error(e: ValidationError) -> str:
    parts: list[str] = []
    for err in e.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "config"
        parts.append(f"{loc}: {err['msg']}")
    return "Invalid configuration: " + "; ".join(parts)
