"""Shared graph invocation and per-session serialization."""

import asyncio
from weakref import WeakValueDictionary

from langchain_core.messages import HumanMessage

from agent import switch_session
from app.schemas.chat import ChatResponse


class AgentService:
    def __init__(self, graph):
        self.graph = graph
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def chat(self, query: str, session_id: str | None) -> ChatResponse:
        config = switch_session(session_id)
        thread_id = config["configurable"]["thread_id"]
        # No await between lookup and insertion; waiting callers keep locks alive.
        lock = self._locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[thread_id] = lock
        async with lock:
            result = await self.graph.ainvoke(
                {"messages": [HumanMessage(content=query)]},
                config={**config, "recursion_limit": 30},
            )
        return ChatResponse(response=result["messages"][-1].text, session_id=thread_id)
