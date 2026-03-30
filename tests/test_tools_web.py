"""web_fetch tool (P2-07, FR-TOOL-8)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from codegen.config import CodegenConfig
from codegen.tools_readonly import execute_tool, tool_definitions_for_mode
from codegen.tools_web import web_fetch


def _cfg(**kwargs: object) -> CodegenConfig:
    base: dict = {"web_fetch_enabled": True, "openai_api_key": "x"}
    base.update(kwargs)
    return CodegenConfig.model_validate(base)


def test_tool_not_registered_without_config_flag() -> None:
    cfg = CodegenConfig(web_fetch_enabled=False)
    defs = tool_definitions_for_mode("execute", config=cfg)
    names = [d["function"]["name"] for d in defs]
    assert "web_fetch" not in names


def test_tool_registered_when_enabled_plan_and_execute() -> None:
    cfg = CodegenConfig(web_fetch_enabled=True)
    for mode in ("plan", "execute"):
        defs = tool_definitions_for_mode(mode, config=cfg)
        names = [d["function"]["name"] for d in defs]
        assert "web_fetch" in names


def test_execute_tool_disabled_returns_error(tmp_path: Path) -> None:
    cfg = CodegenConfig(web_fetch_enabled=False)
    raw = execute_tool(tmp_path, "web_fetch", json.dumps({"url": "https://example.com"}), config=cfg)
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "WEB_FETCH_DISABLED"


def test_blocks_localhost() -> None:
    raw = web_fetch({"url": "http://localhost/foo"}, _cfg())
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "URL_NOT_ALLOWED"


def test_blocks_loopback_ip() -> None:
    raw = web_fetch({"url": "http://127.0.0.1/"}, _cfg())
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "URL_NOT_ALLOWED"


def test_blocks_non_http_scheme() -> None:
    raw = web_fetch({"url": "file:///etc/passwd"}, _cfg())
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "URL_NOT_ALLOWED"


def test_mock_http_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, content=b"hello", headers={"content-type": "text/plain"})

    transport = httpx.MockTransport(handler)
    RealClient = httpx.Client

    def client_with_transport(*args: object, **kwargs: object) -> httpx.Client:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return RealClient(*args, **kwargs)

    monkeypatch.setattr("codegen.tools_web.httpx.Client", client_with_transport)

    raw = web_fetch({"url": "https://example.com/doc"}, _cfg())
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["text"] == "hello"
    assert data["bytes_read"] == 5
    assert data["truncated"] is False
    assert data["status_code"] == 200


def test_mock_http_truncates_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    transport = httpx.MockTransport(handler)
    RealClient = httpx.Client

    def client_with_transport(*args: object, **kwargs: object) -> httpx.Client:
        kwargs = dict(kwargs)
        kwargs["transport"] = transport
        return RealClient(*args, **kwargs)

    monkeypatch.setattr("codegen.tools_web.httpx.Client", client_with_transport)

    raw = web_fetch({"url": "https://example.com/big"}, _cfg(web_fetch_max_bytes=1024))
    data = json.loads(raw)
    assert data["ok"] is True
    assert data["bytes_read"] == 1024
    assert data["truncated"] is True
    assert "1024 bytes" in data.get("truncation_note", "")


@patch("codegen.tools_web.socket.getaddrinfo", return_value=[])
def test_dns_failure(mock_gai: object) -> None:
    raw = web_fetch({"url": "https://does-not-exist.invalid-tld-xyz/"}, _cfg())
    data = json.loads(raw)
    assert data["ok"] is False
    assert data["error"]["code"] == "URL_NOT_ALLOWED"
