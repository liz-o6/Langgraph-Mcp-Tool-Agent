"""Connect to the official Tavily remote MCP server.

Set TAVILY_API_KEY in the environment or hw1/.env. Run from hw1:
    venv/bin/python -m integrations.tavily "What is Model Context Protocol?"
Source: https://github.com/tavily-ai/tavily-mcp#remote-mcp-server"""

import argparse
import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

HW1_DIR = Path(__file__).resolve().parent.parent
SERVER_URL = "https://mcp.tavily.com/mcp/"
# Accept both server naming conventions.
SEARCH_TOOL_NAMES = {"tavily-search", "tavily_search"}


def get_api_key() -> str:
    """Load the key, preserving existing environment variables."""
    load_dotenv(HW1_DIR / ".env", override=False)
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise ValueError("Set TAVILY_API_KEY in the environment or hw1/.env.")
    return api_key


@asynccontextmanager
async def tavily_tools() -> AsyncIterator[list[BaseTool]]:
    """Keep tools inside this context; close the session and HTTP client on exit."""
    api_key = get_api_key()
    # Keep the key in headers rather than URLs.
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=httpx.Timeout(30, read=60),
    ) as http_client:
        async with streamable_http_client(SERVER_URL, http_client=http_client) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=60),
            ) as session:
                await session.initialize()
                tools = await load_mcp_tools(session, handle_tool_errors=False)
                search_tools = [
                    tool for tool in tools if tool.name in SEARCH_TOOL_NAMES
                ]
                if len(search_tools) != 1:
                    raise RuntimeError("Tavily MCP did not return exactly one search tool.")
                yield search_tools


async def main() -> None:
    """Run one real search without calling a model."""
    parser = argparse.ArgumentParser(description="Search the web through Tavily MCP")
    parser.add_argument("query", nargs="?", default="What is Model Context Protocol?")
    args = parser.parse_args()
    if not args.query.strip():
        parser.error("Search query cannot be empty.")

    async with tavily_tools() as tools:
        search = tools[0]
        print("Loaded tools:", search.name)
        result = await search.ainvoke(
            {"query": args.query, "search_depth": "basic", "max_results": 3}
        )
        print("\nSearch results:", result)


if __name__ == "__main__":
    asyncio.run(main())
