"""Connect to the official Filesystem MCP server. Requires Node.js/npm.

Run from hw1: venv/bin/python -m integrations.filesystem
The first run may download the server through npx. No model API key is needed."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from shutil import which

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HW1_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = HW1_DIR / "workspace" / "files"
SERVER_PACKAGE = "@modelcontextprotocol/server-filesystem"


def get_server_parameters() -> StdioServerParameters:
    """Validate the environment and prepare server arguments."""
    if not FILES_DIR.is_dir():
        raise FileNotFoundError(f"MCP workspace directory does not exist: {FILES_DIR}")
    # Containers preinstall the server at build time; no runtime npm download.
    server_path = which("mcp-server-filesystem")
    if server_path is not None:
        return StdioServerParameters(command=server_path, args=[str(FILES_DIR)])
    npx_path = which("npx")
    if npx_path is None or which("node") is None:
        raise RuntimeError("node/npx not found. Install Node.js/npm and add them to PATH.")

    # npx -y @modelcontextprotocol/server-filesystem <directory>
    return StdioServerParameters(
        command=npx_path,
        args=["-y", SERVER_PACKAGE, str(FILES_DIR)],
    )


@asynccontextmanager
async def filesystem_tools() -> AsyncIterator[list[BaseTool]]:
    """Keep tools inside this context; close the session and subprocess on exit."""
    parameters = get_server_parameters()

    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=60),
        ) as session:
            await session.initialize()

            tools = await load_mcp_tools(session, handle_tool_errors=False)
            yield tools


async def main() -> None:
    """List tools, allowed directories, and input files without modifying them."""
    async with filesystem_tools() as tools:
        print("Loaded tools:", ", ".join(tool.name for tool in tools))
        tools_by_name = {tool.name: tool for tool in tools}

        allowed = await tools_by_name["list_allowed_directories"].ainvoke({})
        print("\nAllowed directories:", allowed)

        listing = await tools_by_name["list_directory"].ainvoke(
            {"path": str(FILES_DIR / "inputs")}
        )
        print("\nInput files:", listing)


if __name__ == "__main__":
    asyncio.run(main())
