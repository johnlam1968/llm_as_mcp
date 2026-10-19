"""SSRF protection and timeout tests for ``base.py``.

These tests cover the fixes from MINI_AGENT_REVIEW_M3.md:

* **C1** — ``call_another_llm`` must reject ``base_url`` values that:
  - use a non-``https`` scheme
  - point at a loopback, link-local, or private IP literal
  - use the ``localhost`` hostname
* **A4 / H4** — ``call_another_llm`` must construct its ``httpx.AsyncClient``
  with ``timeout=30.0`` so a hung upstream cannot stall the MCP worker.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import Response


# ---------------------------------------------------------------------------
# C1: scheme allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://api.example.com/v1/chat/completions",
        "ftp://api.example.com/v1/chat/completions",
        "file:///etc/passwd",
        "gopher://api.example.com/",
        # No scheme at all.
        "api.example.com/v1/chat/completions",
    ],
)
async def test_call_another_llm_rejects_non_https_url(
    base_module, secret_dict, bad_url
):
    """Any non-https scheme must be rejected before any HTTP call is made."""
    base_module.secret_dict = secret_dict

    with pytest.raises(ValueError, match="scheme must be 'https'"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url=bad_url,
        )


# ---------------------------------------------------------------------------
# C1: loopback / link-local / private IP literal rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "blocked_url,description",
    [
        # Loopback (IPv4) — using https so the IP rule is the one that fires.
        ("https://127.0.0.1/v1/chat/completions", "IPv4 loopback"),
        ("https://127.0.0.53:53/v1", "127.0.0.53 (systemd-resolved stub)"),
        # AWS instance metadata
        (
            "https://169.254.169.254/latest/meta-data/",
            "AWS link-local metadata IP",
        ),
        # RFC1918 private ranges
        ("https://10.0.0.1/v1", "RFC1918 10.0.0.0/8"),
        ("https://10.255.255.255/v1", "RFC1918 10.0.0.0/8 upper bound"),
        ("https://172.16.0.1/v1", "RFC1918 172.16.0.0/12 lower bound"),
        ("https://172.31.255.255/v1", "RFC1918 172.16.0.0/12 upper bound"),
        ("https://192.168.0.1/v1", "RFC1918 192.168.0.0/16"),
        # IPv6 loopback
        ("https://[::1]/v1/chat/completions", "IPv6 loopback ::1"),
        # IPv6 link-local
        ("https://[fe80::1]/v1", "IPv6 link-local fe80::/10"),
        # IPv6 ULA
        ("https://[fc00::1]/v1", "IPv6 ULA fc00::/7"),
        ("https://[fd00::1]/v1", "IPv6 ULA fd00::/8 (subset of fc00::/7)"),
    ],
)
async def test_call_another_llm_rejects_blocked_ip_literal(
    base_module, secret_dict, blocked_url, description
):
    """Loopback / link-local / private IP literals must be rejected."""
    base_module.secret_dict = secret_dict

    with pytest.raises(ValueError, match="blocked network range"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url=blocked_url,
        )


async def test_call_another_llm_rejects_localhost_hostname(
    base_module, secret_dict
):
    """The hostname ``localhost`` must be rejected even though it isn't an IP literal."""
    base_module.secret_dict = secret_dict

    with pytest.raises(ValueError, match="loopback name"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url="https://localhost/v1/chat/completions",
        )


async def test_call_another_llm_rejects_http_loopback(base_module, secret_dict):
    """A request to an IPv4 loopback address must be rejected (IP rule, not scheme rule)."""
    base_module.secret_dict = secret_dict

    with pytest.raises(ValueError, match="blocked network range"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url="https://127.0.0.1:8080/v1/chat/completions",
        )


async def test_call_another_llm_rejects_aws_metadata_url(base_module, secret_dict):
    """The AWS instance metadata IP must be rejected (C1 specific example)."""
    base_module.secret_dict = secret_dict

    with pytest.raises(ValueError, match="blocked network range"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url="https://169.254.169.254/latest/meta-data/iam/security-credentials/",
        )


async def test_call_another_llm_rejects_private_rfc1918_url(
    base_module, secret_dict
):
    """A private RFC1918 IP must be rejected (C1 specific example)."""
    base_module.secret_dict = secret_dict

    with pytest.raises(ValueError, match="blocked network range"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url="https://10.0.0.1/admin",
        )


async def test_call_another_llm_does_not_make_http_call_when_url_rejected(
    base_module, secret_dict
):
    """If validation rejects the URL, no HTTP request must reach the network."""
    base_module.secret_dict = secret_dict

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(
            url__regex=r".*"
        ).mock(return_value=Response(200, json={"choices": []}))
        with pytest.raises(ValueError):
            await base_module.call_another_llm(
                persona="p",
                query="q",
                model="test-model-1",
                temperature=0.0,
                base_url="https://169.254.169.254/latest/meta-data/",
            )
        assert not route.called, (
            "SSRF guard must reject the URL before any HTTP request is made"
        )


# ---------------------------------------------------------------------------
# A4 / H4: timeout=30.0 on httpx.AsyncClient
# ---------------------------------------------------------------------------


async def test_call_another_llm_uses_30_second_timeout(base_module, secret_dict):
    """The outbound ``httpx.AsyncClient`` must be constructed with ``timeout=30.0``.

    We patch ``httpx.AsyncClient`` so we can capture the keyword arguments
    without making a real network request. The stub's ``.post()`` raises so
    the function bails out before it tries to ``raise_for_status()`` on a
    hand-built response.
    """
    base_module.secret_dict = secret_dict

    captured_kwargs: dict = {}

    class _StubClient:
        def __init__(self, *args, **kwargs):
            captured_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            # Raise a sentinel exception to short-circuit before the function
            # tries to interpret a fake response. We catch it below.
            raise httpx.HTTPError("stub: short-circuit")

    with patch.object(httpx, "AsyncClient", _StubClient):
        with pytest.raises(httpx.HTTPError, match="stub"):
            await base_module.call_another_llm(
                persona="p",
                query="q",
                model="test-model-1",
                temperature=0.0,
                base_url="https://api.example.com/v1/chat/completions",
            )

    assert "timeout" in captured_kwargs, (
        "call_another_llm must pass timeout=... to httpx.AsyncClient "
        f"(kwargs captured: {captured_kwargs!r})"
    )
    assert captured_kwargs["timeout"] == 30.0, (
        "timeout must be exactly 30.0 seconds "
        f"(got {captured_kwargs['timeout']!r})"
    )


async def test_call_another_llm_timeout_is_a_number_not_none(
    base_module, secret_dict
):
    """The timeout must be an explicit finite number, not None (the httpx default)."""
    base_module.secret_dict = secret_dict

    captured_kwargs: dict = {}

    class _StubClient:
        def __init__(self, *args, **kwargs):
            captured_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.HTTPError("stub: short-circuit")

    with patch.object(httpx, "AsyncClient", _StubClient):
        with pytest.raises(httpx.HTTPError, match="stub"):
            await base_module.call_another_llm(
                persona="p",
                query="q",
                model="test-model-1",
                temperature=0.0,
                base_url="https://api.example.com/v1/chat/completions",
            )

    timeout = captured_kwargs.get("timeout")
    assert timeout is not None, "timeout must not be None (httpx's default)"
    # httpx.Timeout objects are also acceptable as long as they're set.
    if hasattr(timeout, "connect"):
        # An httpx.Timeout object — confirm it has a finite value.
        assert (
            timeout.connect is not None
            or timeout.read is not None
            or timeout.write is not None
        )
    else:
        assert isinstance(timeout, (int, float)), (
            f"timeout must be a number, got {type(timeout).__name__}"
        )
        assert timeout > 0, f"timeout must be positive, got {timeout}"


# ---------------------------------------------------------------------------
# SSRF guard runs BEFORE secret_dict / api-key lookup
# ---------------------------------------------------------------------------


async def test_ssrf_check_runs_before_secret_dict_lookup(
    base_module, patched_secret_dict
):
    """Even with an empty ``secret_dict``, a bad URL must still raise the SSRF error."""
    patched_secret_dict(None)

    with pytest.raises(ValueError, match="scheme must be 'https'"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url="http://api.example.com/v1",
        )


async def test_validate_base_url_helper_directly(base_module):
    """The ``validate_base_url`` helper exposes the SSRF rules for direct testing."""
    # Allowed
    base_module.validate_base_url("https://api.openai.com/v1/chat/completions")
    base_module.validate_base_url("https://api.anthropic.com/v1/messages")

    # Disallowed — scheme
    with pytest.raises(ValueError, match="scheme must be 'https'"):
        base_module.validate_base_url("http://api.openai.com/v1/chat/completions")
    # Disallowed — IP literal (using https so the IP rule fires, not the scheme rule)
    with pytest.raises(ValueError, match="blocked network range"):
        base_module.validate_base_url("https://127.0.0.1/v1")
    with pytest.raises(ValueError, match="blocked network range"):
        base_module.validate_base_url("https://169.254.169.254/")
    with pytest.raises(ValueError, match="blocked network range"):
        base_module.validate_base_url("https://10.0.0.5/v1")
    with pytest.raises(ValueError, match="blocked network range"):
        base_module.validate_base_url("https://192.168.1.1/v1")
    # Disallowed — localhost hostname
    with pytest.raises(ValueError, match="loopback name"):
        base_module.validate_base_url("https://localhost/v1")
    # Disallowed — empty / malformed
    with pytest.raises(ValueError, match="must be a non-empty string"):
        base_module.validate_base_url("")
    with pytest.raises(ValueError, match="must include a host"):
        base_module.validate_base_url("https:///v1")