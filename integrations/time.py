"""Connect to the official Time MCP server. No API key required.

Run from hw1: venv/bin/python -m integrations.time
Source: https://github.com/modelcontextprotocol/servers/tree/main/src/time
Time conversion uses today in the source timezone, not an arbitrary date."""

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from importlib.util import find_spec

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_TIMEZONE = "America/Los_Angeles"
TIME_TOOL_NAMES = {"get_current_time", "convert_time"}


def get_server_parameters() -> StdioServerParameters:
    """Prepare server arguments using the current Python environment."""
    if find_spec("mcp_server_time") is None:
        raise RuntimeError(
            "mcp-server-time is not installed. From hw1, run "
            "python -m pip install -r requirements.txt."
        )
    # Use the same default timezone locally and in Cloud Run.
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server_time", "--local-timezone", DEFAULT_TIMEZONE],
    )


@asynccontextmanager
async def time_tools() -> AsyncIterator[list[BaseTool]]:
    """Keep the session open while tools are in use; propagate errors to the caller."""
    async with stdio_client(get_server_parameters()) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=60),
        ) as session:
            await session.initialize()
            tools = await load_mcp_tools(session, handle_tool_errors=False)
            selected = [tool for tool in tools if tool.name in TIME_TOOL_NAMES]
            if len(selected) != 2 or {tool.name for tool in selected} != TIME_TOOL_NAMES:
                raise RuntimeError("Time MCP did not return the two expected time tools.")
            yield selected


async def main() -> None:
    """Check discovery, current time, and optional timezone conversion."""
    parser = argparse.ArgumentParser(description="Query and convert time through Time MCP")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="IANA timezone for queries and source times")
    parser.add_argument("--time", help="Source time to convert, in 24-hour HH:MM format")
    parser.add_argument("--target-timezone", default="Asia/Shanghai", help="Target IANA timezone")
    args = parser.parse_args()

    async with time_tools() as tools:
        print("Loaded tools:", ", ".join(tool.name for tool in tools))
        tools_by_name = {tool.name: tool for tool in tools}
        current = await tools_by_name["get_current_time"].ainvoke(
            {"timezone": args.timezone}
        )
        print("\nCurrent time:", current)
        if args.time is not None:
            converted = await tools_by_name["convert_time"].ainvoke(
                {
                    "source_timezone": args.timezone,
                    "time": args.time,
                    "target_timezone": args.target_timezone,
                }
            )
            print("\nConverted time:", converted)


if __name__ == "__main__":
    asyncio.run(main())
