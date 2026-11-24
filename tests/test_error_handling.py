"""Fault injection against the real graph and MCP protocol; no paid APIs."""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import agent
from app.services.agent import AgentService
from integrations.runtime import available_tools


class CallingModel:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content=messages[-1].content)
        if messages[-1].content == 'hello':
            return AIMessage(content='hello')
        return AIMessage(content='', tool_calls=[
            {'name': 'probe', 'args': {}, 'id': 'call-1', 'type': 'tool_call'}
        ])


# A subprocess intentionally emits MCP errors, invalid results, or disconnects.
SERVER = '''
import json, sys
mode = sys.argv[1]
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': request['params']['protocolVersion'], 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'fault-test', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'probe', 'description': 'Test tool', 'inputSchema': {'type': 'object', 'properties': {}}}]}
    elif method == 'tools/call':
        if mode == 'disconnect':
            sys.exit(0)
        if mode == 'malformed':
            result = {'content': [{'type': 'text', 'text': {'bad': 'secret-token'}}]}
        elif mode == 'execution':
            result = {'isError': True, 'content': [{'type': 'text', 'text': 'secret-token'}]}
        else:
            result = {'content': [{'type': 'text', 'text': 'success'}]}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['execution', 'malformed', 'disconnect'])
async def test_real_mcp_faults_and_same_session_recovery(tmp_path, mode):
    script = tmp_path / 'server.py'
    script.write_text(SERVER)

    @asynccontextmanager
    async def connection():
        params = StdioServerParameters(command=sys.executable, args=[str(script), mode])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=1)) as session:
                await session.initialize()
                yield await load_mcp_tools(session, handle_tool_errors=False)

    async with available_tools({'fault': connection}) as tools:
        assert len(tools) == 1
        service = AgentService(agent.build_graph(CallingModel(), tools))
        response = await asyncio.wait_for(service.chat('call', 'same'), 5)
        assert 'secret-token' not in response.response
        saved = await service.graph.aget_state(agent.switch_session('same'))
        results = [m for m in saved.values['messages'] if isinstance(m, ToolMessage)]
        assert results[0].status == 'error'
        assert results[0].tool_call_id == 'call-1'
        assert (await service.chat('hello', 'same')).response == 'hello'


@pytest.mark.asyncio
async def test_timeout_and_cancellation(monkeypatch):
    monkeypatch.setattr(agent, 'TOOL_TIMEOUT', 0.02)

    @tool
    async def probe() -> str:
        """Wait to exercise timeouts."""
        await asyncio.sleep(10)
        return 'unexpected'

    service = AgentService(agent.build_graph(CallingModel(), [probe]))
    assert 'timed out' in (await service.chat('call', 'same')).response
    assert (await service.chat('hello', 'same')).response == 'hello'
    task = asyncio.create_task(agent.bounded_tool_call(None, lambda _: asyncio.sleep(10)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_retry_loop_is_bounded_and_next_turn_works():
    calls = []

    @tool
    async def probe() -> str:
        """Record an execution."""
        calls.append(1)
        return 'done'

    class RepeatingModel(CallingModel):
        async def ainvoke(self, messages):
            if messages[-1].content == 'hello':
                return AIMessage(content='hello')
            return AIMessage(content='', tool_calls=[
                {'name': 'probe', 'args': {}, 'id': f'call-{len(messages)}', 'type': 'tool_call'}
            ])

    service = AgentService(agent.build_graph(RepeatingModel(), [probe]))
    assert 'limit' in (await service.chat('call', 'same')).response
    assert len(calls) == agent.MAX_TOOL_ROUNDS
    assert (await service.chat('hello', 'same')).response == 'hello'


@pytest.mark.asyncio
async def test_model_failure_after_tool_result_preserves_valid_history():
    @tool
    async def probe() -> str:
        """Return a value."""
        return 'done'

    class FailingModel(CallingModel):
        async def ainvoke(self, messages):
            if isinstance(messages[-1], ToolMessage):
                raise RuntimeError('secret-token')
            return await super().ainvoke(messages)

    service = AgentService(agent.build_graph(FailingModel(), [probe]))
    assert 'temporarily unavailable' in (await service.chat('call', 'same')).response
    assert (await service.chat('hello', 'same')).response == 'hello'


@pytest.mark.asyncio
async def test_unavailable_startup_and_discovery_timeout(monkeypatch):
    import integrations.runtime as runtime
    monkeypatch.setattr(runtime, 'STARTUP_TIMEOUT', 0.02)

    @asynccontextmanager
    async def unavailable():
        raise ConnectionError('secret-token')
        yield []

    @asynccontextmanager
    async def hanging():
        await asyncio.sleep(10)
        yield []

    async with available_tools({'down': unavailable, 'hang': hanging}) as tools:
        assert tools == []
        service = AgentService(agent.build_graph(CallingModel(), tools))
        assert (await service.chat('hello', 'same')).response == 'hello'


@pytest.mark.asyncio
async def test_parallel_calls_keep_success_and_error_results():
    @tool
    async def good() -> str:
        """Return a successful result."""
        return 'success'

    @tool
    async def bad(count: int) -> str:
        """Require an integer."""
        return str(count)

    class ParallelModel(CallingModel):
        async def ainvoke(self, messages):
            if isinstance(messages[-1], ToolMessage):
                return AIMessage(content='finished')
            return AIMessage(content='', tool_calls=[
                {'name': 'good', 'args': {}, 'id': 'good-1', 'type': 'tool_call'},
                {'name': 'bad', 'args': {'count': 'secret-token'}, 'id': 'bad-1', 'type': 'tool_call'},
                {'name': 'missing', 'args': {}, 'id': 'missing-1', 'type': 'tool_call'},
            ])

    graph = agent.build_graph(ParallelModel(), [good, bad])
    result = await graph.ainvoke({'messages': [HumanMessage(content='call')]}, agent.switch_session('parallel'))
    replies = {m.tool_call_id: m for m in result['messages'] if isinstance(m, ToolMessage)}
    assert set(replies) == {'good-1', 'bad-1', 'missing-1'}
    assert replies['good-1'].status == 'success'
    assert replies['bad-1'].status == replies['missing-1'].status == 'error'
    assert 'secret-token' not in replies['bad-1'].content


@pytest.mark.asyncio
async def test_background_connection_failure_does_not_cancel_other_servers():
    import anyio
    crash = asyncio.Event()
    failed = asyncio.Event()
    closed = asyncio.Event()

    @asynccontextmanager
    async def broken():
        async def fail():
            await crash.wait()
            raise ConnectionError('secret-token')
        try:
            async with anyio.create_task_group() as group:
                group.start_soon(fail)
                yield []
        finally:
            failed.set()

    @tool
    async def probe() -> str:
        """Return data from the healthy server."""
        return 'healthy'

    @asynccontextmanager
    async def healthy():
        try:
            yield [probe]
        finally:
            closed.set()

    async with available_tools({'broken': broken, 'healthy': healthy}) as tools:
        crash.set()
        await asyncio.wait_for(failed.wait(), 1)
        service = AgentService(agent.build_graph(CallingModel(), tools))
        assert (await service.chat('call', 'same')).response == 'healthy'
        assert not closed.is_set()
    assert closed.is_set()
