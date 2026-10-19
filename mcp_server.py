"""MCP server that proxies LLM requests to OpenRouter.

This file intentionally mirrors the structure of ``base.py`` (decorator +
tool + transport) but for a fixed upstream (OpenRouter) so ``base_url`` is
never caller-controlled and SSRF is not a concern here.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Awaitable, Callable, TypeVar

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Create a custom decorator that wraps @server.tool with structured_output=False
F = TypeVar("F", bound=Callable[..., Awaitable[str]])

server = FastMCP("llm_through_mcp")


def mcp_tool(func: F) -> F:
    """Custom decorator for MCP tools that automatically sets structured_output=False."""
    return server.tool(structured_output=False)(func)  # type: ignore


@mcp_tool
async def call_llm(
    persona: str,
    query: str,
    model: str = "google/gemini-2.0-flash-001",
    temperature: float = 0.7,
) -> str:
    """Delegate a task to a specialized LLM persona via OpenRouter.

    Args:
        persona: The system prompt defining the agent's expertise.
        query: The user's query or task description.
        model: OpenRouter model ID (e.g. ``anthropic/claude-3.5-sonnet``).
        temperature: Sampling temperature for the LLM.

    Returns:
        The assistant message content, or a friendly error string.
    """
    if not OPENROUTER_KEY:
        return "Error: OPENROUTER_API_KEY not found in environment."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "http://localhost:3000",  # OpenRouter attribution
        "X-Title": "MCP Multi-Agent Hub",
        "Content-Type": "application/json",
    }

    # Type annotation for the payload to help the type checker
    payload: dict[str, str | list[dict[str, str]] | float] = {
        "model": model,
        "messages": [
            {"role": "system", "content": persona},
            {"role": "user", "content": query},
        ],
        "temperature": temperature,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                OPENROUTER_URL, json=payload, headers=headers, timeout=60.0
            )
            response.raise_for_status()
        except httpx.HTTPError as http_err:
            # Transport-level failure (connection refused, timeout, 4xx/5xx, ...).
            logger.exception("OpenRouter HTTP error in call_llm")
            return f"Agent Error: {http_err}"

        try:
            data = response.json()
        except json.JSONDecodeError as json_err:
            # Upstream returned a non-JSON body (or an HTML error page).
            logger.exception("OpenRouter returned non-JSON body in call_llm")
            return f"Agent Error: invalid JSON response ({json_err})"

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as shape_err:
            # Upstream returned JSON that doesn't match the OpenAI schema.
            logger.exception(
                "OpenRouter returned unexpected response shape in call_llm: %r",
                data,
            )
            return f"Agent Error: unexpected response shape ({shape_err})"


@mcp_tool
async def list_available_models() -> str:
    """Fetch the current list of all models available on OpenRouter.

    Use this to find model IDs, pricing, and context limits.
    """
    url = "https://openrouter.ai/api/v1/models"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as http_err:
            logger.exception("OpenRouter HTTP error in list_available_models")
            return f"Error fetching models: {http_err}"

        try:
            data = response.json()
        except json.JSONDecodeError as json_err:
            logger.exception(
                "OpenRouter returned non-JSON body in list_available_models"
            )
            return f"Error fetching models: invalid JSON response ({json_err})"

        try:
            # Format the output to be token-efficient for the LLM
            models = data.get("data", [])
            summary = ["Available OpenRouter Models:"]
            for m in models[:50]:  # Limit to top 50 to save context space
                summary.append(
                    f"- ID: {m['id']} | Name: {m['name']} | "
                    f"Context: {m['context_length']}"
                )
            return "\n".join(summary)
        except (KeyError, TypeError) as shape_err:
            logger.exception(
                "OpenRouter returned unexpected response shape in "
                "list_available_models: %r",
                data,
            )
            return f"Error fetching models: unexpected response shape ({shape_err})"


if __name__ == "__main__":
    server.run()