"""Tests for ``base.py``.

Covered:
    * ``call_another_llm`` happy path returns the assistant content.
    * ``call_another_llm`` raises ``ValueError`` when the requested model is
      absent from ``secret_dict``.
    * ``call_another_llm`` raises ``ValueError`` when ``secret_dict`` itself is
      falsy (``None`` / empty).
    * The ``mcp_tool`` decorator preserves the wrapped function's ``__name__``.

All HTTP traffic is mocked with ``respx`` so no real network calls are made.
pytest-asyncio is configured with ``asyncio_mode = auto`` (see ``pytest.ini``),
so every ``async def test_`` is automatically picked up as an async test.
"""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response


# ---------------------------------------------------------------------------
# call_another_llm: happy path
# ---------------------------------------------------------------------------


async def test_call_another_llm_happy_path_returns_content(base_module, secret_dict):
    """When the HTTP call succeeds, the assistant message content is returned."""
    # Belt-and-braces: ensure the module-level secret_dict matches our fixture.
    base_module.secret_dict = secret_dict

    fake_response_body = {
        "id": "chatcmpl-abc123",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello from the mocked LLM!",
                },
                "finish_reason": "stop",
            }
        ],
    }

    target_url = "https://api.example.com/v1/chat/completions"

    with respx.mock() as mock:
        route = mock.post(target_url).mock(
            return_value=Response(200, json=fake_response_body)
        )
        result = await base_module.call_another_llm(
            persona="You are a helpful assistant.",
            query="Say hello.",
            model="test-model-1",
            temperature=0.5,
            base_url=target_url,
        )

    assert result == "Hello from the mocked LLM!"
    assert route.called, "respx should have intercepted the POST request"

    # Verify the request payload shape sent to the API.
    sent = route.calls.last.request
    body = json.loads(sent.content)
    assert body["model"] == "test-model-1"
    assert body["messages"] == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say hello."},
    ]
    # The Authorization header should carry the API key looked up from secret_dict.
    assert sent.headers["Authorization"] == "Bearer fake-api-key-1"


# ---------------------------------------------------------------------------
# call_another_llm: error paths
# ---------------------------------------------------------------------------


async def test_call_another_llm_raises_when_model_missing_in_secret_dict(
    base_module, patched_secret_dict
):
    """If the requested model has no entry in ``secret_dict``, raise ValueError."""
    patched_secret_dict({"some-other-model": "key"})  # requested model absent

    with pytest.raises(ValueError, match="not found in secret_dict"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url="https://api.example.com/v1/chat/completions",
        )


async def test_call_another_llm_raises_when_secret_dict_is_none(
    base_module, patched_secret_dict
):
    """If ``secret_dict`` itself is falsy, raise ValueError before any HTTP call."""
    patched_secret_dict(None)

    with pytest.raises(ValueError, match="secret_dict is not set"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url="https://api.example.com/v1/chat/completions",
        )


async def test_call_another_llm_raises_when_model_key_is_empty_string(
    base_module, patched_secret_dict
):
    """An empty-string API key is treated as "not found" and raises."""
    patched_secret_dict({"test-model-1": ""})

    with pytest.raises(ValueError, match="not found in secret_dict"):
        await base_module.call_another_llm(
            persona="p",
            query="q",
            model="test-model-1",
            temperature=0.0,
            base_url="https://api.example.com/v1/chat/completions",
        )


# ---------------------------------------------------------------------------
# mcp_tool decorator
# ---------------------------------------------------------------------------


def test_mcp_tool_decorator_preserves_function_name(base_module):
    """The ``mcp_tool`` decorator must not rename the wrapped function.

    FastMCP's ``@server.tool`` decorator wraps functions in a ``Tool`` object,
    which is a known footgun for ``__name__``-based frameworks. This test
    guards against silent regressions where MCP loses the original callable's
    identity (used by some MCP clients for tool dispatch).
    """
    assert hasattr(base_module, "call_another_llm"), (
        "base.call_another_llm should be importable from the module"
    )
    assert base_module.call_another_llm.__name__ == "call_another_llm", (
        "mcp_tool must preserve the wrapped function's __name__ "
        f"(got {base_module.call_another_llm.__name__!r})"
    )
