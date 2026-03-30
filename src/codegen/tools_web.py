"""Optional HTTP GET tool (P2-07, FR-TOOL-8)."""

from __future__ import annotations

import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from codegen.config import CodegenConfig

WEB_FETCH_TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": (
            "HTTP GET a public URL (https or http) and return response body as text. "
            "Subject to size and time limits; truncation is explicit in the result. "
            "Use for public documentation or version metadata — not for secrets or internal URLs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute URL with http:// or https:// scheme.",
                },
            },
            "required": ["url"],
        },
    },
}

_MAX_REDIRECTS = 5


def _tool_error(code: str, message: str) -> str:
    return json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False)


def _host_resolves_to_public(hostname: str) -> tuple[bool, str]:
    """
    Reject loopback, link-local, private, multicast, and reserved IPs (SSRF mitigation).

    Hostname is validated after URL parse; bracketed IPv6 literals are supported.
    """
    if not hostname:
        return False, "empty host"
    host = hostname.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    low = host.lower()
    if low == "localhost" or low.endswith(".localhost"):
        return False, "localhost is not allowed"

    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "address is not a public endpoint"
        return True, ""
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError as e:
        return False, f"DNS resolution failed: {e}"
    if not infos:
        return False, "no addresses resolved for host"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "host resolves to a non-public address"
    return True, ""


def _validate_request_url(url: str) -> tuple[bool, str]:
    """Ensure scheme/host and that the host is not an obvious SSRF target."""
    try:
        parsed = urlparse(url)
    except ValueError as e:
        return False, f"invalid URL: {e}"
    if parsed.scheme not in ("http", "https"):
        return False, "only http:// and https:// URLs are allowed"
    if not parsed.netloc:
        return False, "URL must include a host"
    ok, reason = _host_resolves_to_public(parsed.hostname or "")
    if not ok:
        return False, reason
    return True, ""


def _validate_redirect_chain(response: httpx.Response) -> tuple[bool, str]:
    """After a completed request, ensure every hop stayed on allowed schemes and hosts."""
    chain = list(response.history) + [response]
    for r in chain:
        u = str(r.url)
        ok, reason = _validate_request_url(u)
        if not ok:
            return False, f"redirect target rejected: {reason}"
    return True, ""


def web_fetch(args: dict[str, Any], config: CodegenConfig) -> str:
    """
    Perform a bounded HTTP GET. Returns JSON for the model.

    ``config.web_fetch_enabled`` must be true (caller also gates tool registration).
    """
    if not config.web_fetch_enabled:
        return _tool_error("WEB_FETCH_DISABLED", "web_fetch is disabled; set web_fetch_enabled in config.")

    url = args.get("url")
    if not isinstance(url, str) or not url.strip():
        return _tool_error("INVALID_ARGUMENT", "web_fetch requires a non-empty string url")

    url = url.strip()
    ok, reason = _validate_request_url(url)
    if not ok:
        return _tool_error("URL_NOT_ALLOWED", reason)

    max_bytes = config.web_fetch_max_bytes
    timeout = float(config.web_fetch_timeout_seconds)

    truncated = False
    buf = bytearray()
    final_status: int | None = None
    final_ct: str | None = None

    try:
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            limits=limits,
            max_redirects=_MAX_REDIRECTS,
        ) as client:
            with client.stream("GET", url) as response:
                ok_chain, chain_reason = _validate_redirect_chain(response)
                if not ok_chain:
                    return _tool_error("REDIRECT_REJECTED", chain_reason)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    return _tool_error(
                        "HTTP_ERROR",
                        f"HTTP {e.response.status_code} for {url}",
                    )
                final_status = response.status_code
                final_ct = response.headers.get("content-type", "")
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    need = max_bytes - len(buf)
                    if need <= 0:
                        truncated = True
                        break
                    take = chunk[:need]
                    buf.extend(take)
                    if len(chunk) > need:
                        truncated = True
                        break
    except httpx.TimeoutException:
        return _tool_error("TIMEOUT", f"Request exceeded {config.web_fetch_timeout_seconds}s timeout.")
    except httpx.RequestError as e:
        return _tool_error("REQUEST_FAILED", str(e))

    body = bytes(buf)
    text = body.decode("utf-8", errors="replace")
    _max_tool_json_chars = 80_000

    def _truncate_payload(s: str) -> tuple[str, bool]:
        if len(s) <= _max_tool_json_chars:
            return s, False
        return s[:_max_tool_json_chars] + "\n… [truncated]", True

    payload: dict[str, Any] = {
        "ok": True,
        "url": url,
        "status_code": final_status,
        "content_type": final_ct or "",
        "bytes_read": len(body),
        "truncated": truncated,
        "truncation_note": (
            f"Response body capped at {max_bytes} bytes; set web_fetch_max_bytes to raise the limit."
            if truncated
            else ""
        ),
        "text": text,
    }
    out = json.dumps(payload, ensure_ascii=False)
    out, json_trunc = _truncate_payload(out)
    if json_trunc:
        payload["truncated"] = True
        note = payload.get("truncation_note") or ""
        payload["truncation_note"] = (note + " " if note else "") + "Tool JSON hit global character cap."
        out = json.dumps(payload, ensure_ascii=False)
        out, _ = _truncate_payload(out)
    return out
