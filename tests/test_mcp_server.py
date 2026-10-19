"""Tests for ``mcp_server.py``.

Covered:
    * ``call_llm`` happy path returns the assistant content.
    * ``call_llm`` returns an error string when ``OPENROUTER_API_KEY`` is missing.
    * ``call_llm`` returns an error string when the upstream HTTP call raises.
    * ``list_available_models`` returns the formatted list of models.
    * ``list_available_models`` returns an error string when the upstream HTTP
      call raises.
    * The ``mcp_tool`` decorator preserves the wrapped function's ``__name__``.

All HTTP traffic is mocked with ``respx`` so no real network calls are made.
pytest-asyncio is configured with ``asyncio_mode = auto`` (see ``pytest.ini``),
so every ``async def test_`` is automatically picked up as an async test.
"""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response, TimeoutException


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


# ---------------------------------------------------------------------------
# call_llm: happy path
# ---------------------------------------------------------------------------


async def test_call_llm_happy_path_returns_content(mcp_server_module, patched_openrouter_key):
    """When the HTTP call succeeds, the assistant message content is returned."""
    patched_openrouter_key("fake-openrouter-key")

    fake_response_body = {
        "id": "gen-abc123",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hi! I'm a mocked model.",
                },
                "finish_reason": "stop",
            }
        ],
    }

    with respx.mock() as mock:
        route = mock.post(OPENROUTER_URL).mock(
            return_value=Response(200, json=fake_response_body)
        )
        result = await mcp_server_module.call_llm(
            persona="You are a helpful assistant.",
            query="Say hi.",
            model="google/gemini-2.0-flash-001",
            temperature=0.7,
        )

    assert result == "Hi! I'm a mocked model."
    assert route.called

    sent = route.calls.last.request
    body = json.loads(sent.content)
    assert body["model"] == "google/gemini-2.0-flash-001"
    assert body["messages"] == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say hi."},
    ]
    assert body["temperature"] == 0.7
    assert sent.headers["Authorization"] == "Bearer fake-openrouter-key"


# ---------------------------------------------------------------------------
# call_llm: missing API key
# ---------------------------------------------------------------------------


async def test_call_llm_returns_error_when_openrouter_api_key_missing(
    mcp_server_module, patched_openrouter_key
):
    """When ``OPENROUTER_API_KEY`` is unset, return a friendly error string."""
    patched_openrouter_key(None)

    # No respx mock needed: the function must short-circuit before any HTTP call.
    result = await mcp_server_module.call_llm(
        persona="p",
        query="q",
        model="google/gemini-2.0-flash-001",
    )

    assert isinstance(result, str)
    assert "OPENROUTER_API_KEY not found" in result


async def test_call_llm_returns_error_when_openrouter_api_key_empty_string(
    mcp_server_module, patched_openrouter_key
):
    """An empty-string API key is also "missing" and should produce the same error."""
    patched_openrouter_key("")

    result = await mcp_server_module.call_llm(
        persona="p",
        query="q",
        model="google/gemini-2.0-flash-001",
    )

    assert isinstance(result, str)
    assert "OPENROUTER_API_KEY not found" in result


# ---------------------------------------------------------------------------
# call_llm: upstream error -> friendly string (not an exception)
# ---------------------------------------------------------------------------


async def test_call_llm_returns_error_string_on_http_error(
    mcp_server_module, patched_openrouter_key
):
    """An HTTP error response is converted to an error string, not raised."""
    patched_openrouter_key("fake-openrouter-key")

    with respx.mock() as mock:
        mock.post(OPENROUTER_URL).mock(
            return_value=Response(500, json={"error": "boom"})
        )
        result = await mcp_server_module.call_llm(
            persona="p",
            query="q",
            model="google/gemini-2.0-flash-001",
        )

    assert isinstance(result, str)
    assert "Agent Error" in result


async def test_call_llm_returns_error_string_on_timeout(
    mcp_server_module, patched_openrouter_key
):
    """A timeout from httpx is converted to an error string, not raised."""
    patched_openrouter_key("fake-openrouter-key")

    with respx.mock() as mock:
        mock.post(OPENROUTER_URL).mock(side_effect=TimeoutException("slow"))
        result = await mcp_server_module.call_llm(
            persona="p",
            query="q",
            model="google/gemini-2.0-flash-001",
        )

    assert isinstance(result, str)
    assert "Agent Error" in result


# ---------------------------------------------------------------------------
# list_available_models: formatted output
# ---------------------------------------------------------------------------


async def test_list_available_models_returns_formatted_list(mcp_server_module):
    """The function should return one formatted line per model."""
    fake_response_body = {
        "data": [
            {
                "id": "anthropic/claude-3.5-sonnet",
                "name": "Claude 3.5 Sonnet",
                "context_length": 200000,
            },
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
                "context_length": 128000,
            },
            {
                "id": "meta-llama/llama-3.1-70b-instruct",
                "name": "Llama 3.1 70B Instruct",
                "context_length": 131072,
            },
        ],
    }

    with respx.mock() as mock:
        route = mock.get(OPENROUTER_MODELS_URL).mock(
            return_value=Response(200, json=fake_response_body)
        )
        result = await mcp_server_module.list_available_models()

    assert route.called

    # Output should contain the header plus one line per model, in order.
    lines = result.splitlines()
    assert lines[0] == "Available OpenRouter Models:"
    assert (
        "- ID: anthropic/claude-3.5-sonnet | Name: Claude 3.5 Sonnet | Context: 200000"
        in lines
    )
    assert (
        "- ID: openai/gpt-4o | Name: GPT-4o | Context: 128000"
        in lines
    )
    assert (
        "- ID: meta-llama/llama-3.1-70b-instruct | Name: Llama 3.1 70B Instruct | Context: 131072"
        in lines
    )
    assert len(lines) == 4  # 1 header + 3 model lines


async def test_list_available_models_limits_to_top_50(mcp_server_module):
    """The implementation caps output at 50 models to save context."""
    fake_models = [
        {"id": f"model-{i}", "name": f"Model {i}", "context_length": 1000 + i}
        for i in range(75)
    ]
    fake_response_body = {"data": fake_models}

    with respx.mock() as mock:
        mock.get(OPENROUTER_MODELS_URL).mock(
            return_value=Response(200, json=fake_response_body)
        )
        result = await mcp_server_module.list_available_models()

    lines = result.splitlines()
    # 1 header + 50 model lines
    assert len(lines) == 51
    assert "model-0" in result
    assert "model-49" in result
    assert "model-50" not in result


async def test_list_available_models_handles_empty_data(mcp_server_module):
    """An empty ``data`` array should yield just the header line."""
    with respx.mock() as mock:
        mock.get(OPENROUTER_MODELS_URL).mock(
            return_value=Response(200, json={"data": []})
        )
        result = await mcp_server_module.list_available_models()

    assert result == "Available OpenRouter Models:"


async def test_list_available_models_returns_error_string_on_http_error(mcp_server_module):
    """An HTTP error from the upstream should become an error string."""
    with respx.mock() as mock:
        mock.get(OPENROUTER_MODELS_URL).mock(
            return_value=Response(503, json={"error": "service unavailable"})
        )
        result = await mcp_server_module.list_available_models()

    assert isinstance(result, str)
    assert "Error fetching models" in result


# ---------------------------------------------------------------------------
# mcp_tool decorator
# ---------------------------------------------------------------------------


def test_mcp_tool_decorator_preserves_function_name_call_llm(mcp_server_module):
    """The ``mcp_tool`` decorator must not rename ``call_llm``."""
    assert hasattr(mcp_server_module, "call_llm")
    assert mcp_server_module.call_llm.__name__ == "call_llm", (
        "mcp_tool must preserve the wrapped function's __name__ "
        f"(got {mcp_server_module.call_llm.__name__!r})"
    )


def test_mcp_tool_decorator_preserves_function_name_list_available_models(mcp_server_module):
    """The ``mcp_tool`` decorator must not rename ``list_available_models``."""
    assert hasattr(mcp_server_module, "list_available_models")
    assert mcp_server_module.list_available_models.__name__ == "list_available_models", (
        "mcp_tool must preserve the wrapped function's __name__ "
        f"(got {mcp_server_module.list_available_models.__name__!r})"
    )
