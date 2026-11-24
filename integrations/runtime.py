"""Isolate MCP lifetimes so one server cannot cancel the application task."""

import asyncio
import logging
from contextlib import asynccontextmanager

from integrations.errors import error_message
from integrations.filesystem import filesystem_tools
from integrations.tavily import tavily_tools
from integrations.time import time_tools

logger = logging.getLogger(__name__)
STARTUP_TIMEOUT = 65


@asynccontextmanager
async def available_tools(factories=None):
    """Discover working servers; retain each context in its owning task."""
    if factories is None:
        factories = {
            "filesystem": filesystem_tools,
            "tavily": tavily_tools,
            "time": time_tools,
        }
    stop = asyncio.Event()
    tasks = []
    futures = []

    async def own_connection(name, factory, ready):
        try:
            async with factory() as tools:
                ready.set_result(tools)
                await stop.wait()
        except Exception as error:
            logger.warning("MCP server %s: %s", name, error_message(error))
        finally:
            if not ready.done():
                ready.set_result([])

    try:
        for name, factory in factories.items():
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(own_connection(name, factory, ready))
            tasks.append(task)
            futures.append(ready)

        async def discover(task, ready):
            try:
                return await asyncio.wait_for(asyncio.shield(ready), STARTUP_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("MCP discovery timed out")
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return []

        groups = await asyncio.gather(*(discover(t, f) for t, f in zip(tasks, futures)))
        yield [tool for group in groups for tool in group]
    finally:
        stop.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
