"""HTTP(S) proxy environment checks for httpx/OpenAI client compatibility."""

from __future__ import annotations

import os

# httpx requires an explicit scheme; ``host:port`` alone raises UnsupportedProtocol.
_PROXY_ENV_KEYS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")


def _has_proxy_scheme(value: str) -> bool:
    v = value.strip().lower()
    return v.startswith(
        (
            "http://",
            "https://",
            "socks5://",
            "socks5h://",
            "socks4://",
        )
    )


def proxy_environment_error_message() -> str | None:
    """
    If ``HTTPS_PROXY`` / ``HTTP_PROXY`` / ``ALL_PROXY`` are set but not valid URL forms for httpx,
    return a clear error string; otherwise ``None``.

    Common mistake: ``HTTPS_PROXY=127.0.0.1:7890`` — must be ``http://127.0.0.1:7890``.
    """
    for key in _PROXY_ENV_KEYS:
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        if _has_proxy_scheme(raw):
            continue
        snippet = raw if len(raw) <= 100 else raw[:97] + "..."
        return (
            f"{key} must be a full URL with a scheme (e.g. http://127.0.0.1:7890), "
            f"not {snippet!r}. Unset {key} if you do not use a proxy."
        )
    return None
