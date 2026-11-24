from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent import build_graph, create_model
from integrations.filesystem import filesystem_tools
from integrations.tavily import tavily_tools
from integrations.time import time_tools
from integrations.runtime import available_tools
from app.services.agent import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Keep MCP contexts and one graph alive for this worker's lifetime."""
    app.state.agent_service = None
    model = create_model(interactive=False)
    async with available_tools({
        "filesystem": filesystem_tools,
        "tavily": tavily_tools,
        "time": time_tools,
    }) as tools:
        graph = build_graph(model, tools)
        app.state.agent_service = AgentService(graph)
        try:
            yield
        finally:
            app.state.agent_service = None
