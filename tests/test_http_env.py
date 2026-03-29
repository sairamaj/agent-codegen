"""http_env proxy URL validation."""

from __future__ import annotations

import pytest

from codegen.http_env import proxy_environment_error_message


def test_proxy_ok_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    assert proxy_environment_error_message() is None


def test_proxy_missing_scheme_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "127.0.0.1:7890")
    msg = proxy_environment_error_message()
    assert msg is not None
    assert "HTTPS_PROXY" in msg
    assert "http://" in msg


def test_proxy_socks5_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")
    assert proxy_environment_error_message() is None


def test_proxy_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    assert proxy_environment_error_message() is None
