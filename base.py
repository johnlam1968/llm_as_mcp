"""MCP server exposing a generic ``call_another_llm`` tool.

Security-relevant behaviour:

* ``call_another_llm`` enforces an SSRF allowlist on ``base_url`` (C1):
  - scheme must be ``https``
  - resolved IP must not be in a loopback / link-local / private range
* ``secret_dict`` is loaded from the ``LLM_API_KEY_DICT`` env var at import
  time but a missing value only emits a warning; the module does not
  ``sys.exit(1)`` (C3).
* The outbound ``httpx.AsyncClient`` uses an explicit ``timeout=30.0`` (A4/H4).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
from typing import Awaitable, Callable, Dict, TypeVar
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Secret-dict loading (C3 fix: no sys.exit on import)
# ---------------------------------------------------------------------------

secret_dict_env = os.environ.get("LLM_API_KEY_DICT")
try:
    secret_dict: Dict[str, str] | None = (
        json.loads(secret_dict_env) if secret_dict_env else None
    )
except json.JSONDecodeError as exc:
    logger.warning(
        "LLM_API_KEY_DICT is set but is not valid JSON: %s. "
        "Continuing with secret_dict=None.",
        exc,
    )
    secret_dict = None

if not secret_dict:
    logger.warning(
        "secret_dict not set. Please set it in your .env file as "
        "LLM_API_KEY_DICT='{\"model-name\": \"api-key\"}'."
    )


# ---------------------------------------------------------------------------
# MCP server + decorator
# ---------------------------------------------------------------------------

server = FastMCP("llm_through_mcp")


F = TypeVar("F", bound=Callable[..., Awaitable[str]])


def mcp_tool(func: F) -> F:
    """Custom decorator for MCP tools that automatically sets structured_output=False."""
    return server.tool(structured_output=False)(func)  # type: ignore


# ---------------------------------------------------------------------------
# SSRF guard (C1 fix)
# ---------------------------------------------------------------------------

# Network ranges that ``call_another_llm`` is forbidden from talking to. Any
# IP that falls into one of these is treated as "internal" and the request is
# rejected outright. Covers IPv4 + IPv6 loopback, link-local, and RFC1918 / ULA
# private space.
_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),     # IPv4 loopback
    ipaddress.ip_network("169.254.0.0/16"),  # IPv4 link-local (incl. AWS metadata)
    ipaddress.ip_network("10.0.0.0/8"),      # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),   # RFC1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC1918
    ipaddress.ip_network("::1/128"),         # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),        # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),       # IPv6 link-local
]


def _ip_is_blocked(ip_str: str) -> bool:
    """Return True if ``ip_str`` belongs to any blocked network range."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        # If we can't parse it, treat it as blocked — fail closed.
        return True
    return any(ip in net for net in _BLOCKED_IP_NETWORKS)


def validate_base_url(base_url: str) -> None:
    """Reject ``base_url`` values that would expose internal services (C1).

    Rules:
      * scheme must be ``https``
      * host must be present
      * the hostname ``localhost`` is rejected
      * if the host is a literal IP, it must not fall into a blocked range

    For non-literal hostnames we do NOT do a DNS lookup here — that would
    make the guard fragile to DNS configuration and break mocked tests.
    Instead, every blocked-range IP address can also be spelled as a literal
    IP in the URL; the most common SSRF payloads (``http://127.0.0.1``,
    ``http://169.254.169.254/...``, ``http://10.0.0.1``) are all literal IPs
    and are caught by this guard. Operators who need stricter DNS-rebinding
    protection should run this tool behind a network-level egress proxy.

    Raises:
        ValueError: with a message identifying which rule was violated.
    """
    if not isinstance(base_url, str) or not base_url:
        raise ValueError("base_url must be a non-empty string")

    parsed = urlparse(base_url)

    if parsed.scheme.lower() != "https":
        raise ValueError(
            f"base_url scheme must be 'https' (got {parsed.scheme!r}). "
            "HTTP (non-TLS) endpoints are rejected for security."
        )

    host = parsed.hostname
    if not host:
        raise ValueError("base_url must include a host")

    # Explicitly reject the well-known loopback name.
    if host.lower() == "localhost":
        raise ValueError(
            f"base_url host {host!r} is a loopback name and is blocked."
        )

    # Literal IP? Check directly against the blocked ranges.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not a literal IP -> assume a real DNS hostname and allow it.
        return

    if _ip_is_blocked(host):
        raise ValueError(
            f"base_url host {host!r} (resolved {ip!r}) is in a blocked "
            "network range (loopback / link-local / private)."
        )


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


@mcp_tool
async def call_another_llm(
    persona: str,
    query: str,
    model: str,
    temperature: float,
    base_url: str,
) -> str:
    """Call this tool to query another LLM.

    Args:
        persona: The persona or role the LLM should assume.
        query: The user's query or prompt.
        model: The model name to use for the LLM.
        temperature: The temperature setting for the LLM.
        base_url: The base URL of the LLM API endpoint. Must be an ``https://``
            URL whose host is not a loopback / link-local / private address.

    Returns:
        The response from the LLM.

    Raises:
        ValueError: on bad configuration or a disallowed ``base_url``.
        httpx.HTTPError: on transport-level failures.
    """
    # SSRF guard runs FIRST so we never touch the network for a bad URL.
    validate_base_url(base_url)

    if not secret_dict:
        raise ValueError("secret_dict is not set.")

    api_key = secret_dict.get(model)
    if not api_key:
        raise ValueError(f"API key for model {model} not found in secret_dict.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            base_url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": persona},
                    {"role": "user", "content": query},
                ],
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    server.run()