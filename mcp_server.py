import os
import httpx
# from fastmcp import FastMCP
from mcp.server.fastmcp import FastMCP

from dotenv import load_dotenv

load_dotenv()

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Create a custom decorator that wraps @server.tool with structured_output=False
from typing import Callable, TypeVar, Awaitable

# Type variables for the decorator
F = TypeVar('F', bound=Callable[..., Awaitable[str]])

server = FastMCP("llm_through_mcp")


def mcp_tool(func: F) -> F:
    """Custom decorator for MCP tools that automatically sets structured_output=False"""
    return server.tool(structured_output=False)(func)  # type: ignore


@mcp_tool
async def call_llm(persona: str, query: str, model: str = "google/gemini-2.0-flash-001", temperature: float = 0.7) -> str:
    """
    Delegates a task to a specialized LLM persona via OpenRouter.
    Args:
        query: The user's query or task description.
        temperature: The temperature setting for the LLM.
        model: OpenRouter ID (e.g., 'anthropic/claude-3.5-sonnet', 'meta-llama/llama-3.1-70b-instruct')
        persona: The system prompt defining the agent's expertise.
    """
    if not OPENROUTER_KEY:
        return "Error: OPENROUTER_API_KEY not found in environment."

    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "HTTP-Referer": "http://localhost:3000", # Required by OpenRouter
        "X-Title": "MCP Multi-Agent Hub",
        "Content-Type": "application/json"
    }

    # Type annotation for the payload to help the type checker
    payload: dict[str, str | list[dict[str, str]] | float] = {
        "model": model,
        "messages": [
            {"role": "system", "content": persona},
            {"role": "user", "content": query}
        ],
        "temperature": temperature
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Agent Error: {str(e)}"

@mcp_tool
async def list_available_models() -> str:
    """
    Fetches the current list of all models available on OpenRouter.
    Use this to find model IDs, pricing, and context limits.
    """
    url = "https://openrouter.ai/api/v1/models"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            
            # Format the output to be token-efficient for the LLM
            models = data.get("data", [])
            summary = ["Available OpenRouter Models:"]
            for m in models[:50]: # Limit to top 50 to save context space
                summary.append(f"- ID: {m['id']} | Name: {m['name']} | Context: {m['context_length']}")
            
            return "\n".join(summary)
        except Exception as e:
            return f"Error fetching models: {str(e)}"

if __name__ == "__main__":
    server.run()