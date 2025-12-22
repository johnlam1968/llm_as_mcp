# from fastmcp import FastMCP
from mcp.server.fastmcp import FastMCP
import httpx
import sys
import os
import json
from typing import Dict

secret_dict_env = os.environ.get("LLM_API_KEY_DICT")
secret_dict: Dict[str, str] | None = json.loads(secret_dict_env) if secret_dict_env else None
if not secret_dict:
    print("⚠️  secret_dict not set. Please set it in your .env file.")
    sys.exit(1)

server=FastMCP("name of server")

# Create a custom decorator that wraps @server.tool with structured_output=False
from typing import Callable, TypeVar, Awaitable

# Type variables for the decorator
F = TypeVar('F', bound=Callable[..., Awaitable[str]])

server = FastMCP("llm_through_mcp")


def mcp_tool(func: F) -> F:
    """Custom decorator for MCP tools that automatically sets structured_output=False"""
    return server.tool(structured_output=False)(func)  # type: ignore

@mcp_tool
async def call_another_llm(persona: str, query: str, model: str, temperature: float, base_url: str) -> str:
    """
    Call this tool to query another LLM.
    Args:
        persona (str): The persona or role the LLM should assume.
        query (str): The user's query or prompt.
        model (str): The model name to use for the LLM.
        temperature (float): The temperature setting for the LLM.
        base_url (str): The base URL of the LLM API endpoint.
    Returns:
        str: The response from the LLM.
    """
    if not secret_dict:
        raise ValueError("secret_dict is not set.")
    
    api_key = secret_dict.get(model)
    if not api_key:
        raise ValueError(f"API key for model {model} not found in secret_dict.")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            base_url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": persona},
                    {"role": "user", "content": query}
                ]
            },
            headers={"Authorization": "Bearer " + api_key}
        )
    data = response.json()
    return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    server.run()