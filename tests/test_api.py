import asyncio
from contextlib import asynccontextmanager
from importlib import import_module

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from agent import build_graph, create_model
from app.main import create_app
from app.services.agent import AgentService

lifecycle = import_module('app.core.lifespan')


class MemoryModel:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        await asyncio.sleep(0)
        return AIMessage(content='|'.join(m.content for m in messages if isinstance(m, HumanMessage)))


@pytest.fixture
def runtime(monkeypatch):
    events = []
    graphs = []

    def connection(name):
        @asynccontextmanager
        async def context():
            events.append('open:' + name)
            try:
                yield []
            finally:
                events.append('close:' + name)
        return context

    monkeypatch.setattr(lifecycle, 'create_model', lambda **kw: MemoryModel())
    for name in ('filesystem', 'tavily', 'time'):
        monkeypatch.setattr(lifecycle, name + '_tools', connection(name))

    def build(model, tools):
        graph = build_graph(model, tools)
        graphs.append(graph)
        return graph

    monkeypatch.setattr(lifecycle, 'build_graph', build)
    return events, graphs


def test_chat_sessions_and_resource_reuse(runtime):
    events, graphs = runtime
    app = create_app()
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        assert client.get('/docs').status_code == 200
        first = client.post('/chat', json={'query': 'alpha'}).json()
        session = first['session_id']
        assert first['response'] == 'alpha'
        second = client.post('/chat', json={'query': 'beta', 'session_id': session})
        assert second.json() == {'response': 'alpha|beta', 'session_id': session}
        other = client.post('/chat', json={'query': 'gamma'}).json()
        assert other['response'] == 'gamma' and other['session_id'] != session
        assert len(graphs) == 1
        assert events == ['open:filesystem', 'open:tavily', 'open:time']
    assert set(events[-3:]) == {'close:time', 'close:tavily', 'close:filesystem'}
    assert app.state.agent_service is None


@pytest.mark.parametrize('body', [{}, {'query': '  '}, {'query': 'x', 'session_id': ''}])
def test_validation(runtime, body):
    with TestClient(create_app()) as client:
        assert client.post('/chat', json=body).status_code == 422


def test_failure_is_sanitized_and_service_recovers(runtime, monkeypatch):
    app = create_app()
    with TestClient(app) as client:
        graph = app.state.agent_service.graph
        original = graph.ainvoke

        async def fail(*args, **kwargs):
            raise RuntimeError('private-token')

        monkeypatch.setattr(graph, 'ainvoke', fail)
        response = client.post('/chat', json={'query': 'x', 'session_id': 'same'})
        assert response.status_code == 502
        assert 'private-token' not in response.text
        monkeypatch.setattr(graph, 'ainvoke', original)
        assert client.post('/chat', json={'query': 'ok', 'session_id': 'same'}).status_code == 200


def test_partial_startup_cleanup(runtime, monkeypatch):
    events, graphs = runtime

    @asynccontextmanager
    async def fail():
        raise RuntimeError('connection failed')
        yield

    monkeypatch.setattr(lifecycle, 'time_tools', fail)
    with TestClient(create_app()) as client:
        assert client.post('/chat', json={'query': 'still working'}).status_code == 200
    assert set(events) == {'open:filesystem', 'open:tavily', 'close:tavily', 'close:filesystem'}
    assert len(graphs) == 1


def test_missing_key_does_not_prompt(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr('agent.getpass', lambda *a: pytest.fail('Must not prompt'))
    with pytest.raises(ValueError, match='OPENAI_API_KEY'):
        create_model(interactive=False)


@pytest.mark.asyncio
async def test_concurrent_same_session_keeps_history():
    service = AgentService(build_graph(MemoryModel(), []))
    results = await asyncio.gather(*(service.chat(str(i), 'same') for i in range(5)))
    assert results[-1].response == '0|1|2|3|4'
    assert len(service._locks) == 0


@pytest.mark.asyncio
async def test_different_sessions_can_run_concurrently():
    both_entered = asyncio.Event()
    active = 0

    class Graph:
        async def ainvoke(self, state, config):
            nonlocal active
            active += 1
            if active == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=2)
            return {'messages': [AIMessage(content='ok')]}

    service = AgentService(Graph())
    await asyncio.gather(service.chat('x', 'a'), service.chat('y', 'b'))


def test_uninitialized_service_returns_503():
    client = TestClient(create_app())
    assert client.post('/chat', json={'query': 'hello'}).status_code == 503


def test_graph_build_failure_closes_all_connections(runtime, monkeypatch):
    events, _ = runtime

    def fail(*args):
        raise ValueError('build failed')

    monkeypatch.setattr(lifecycle, 'build_graph', fail)
    with pytest.raises(ValueError, match='build failed'):
        with TestClient(create_app()):
            pass
    assert set(events[-3:]) == {'close:time', 'close:tavily', 'close:filesystem'}


@pytest.mark.asyncio
async def test_graph_executes_tool_and_returns_final_answer():
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import tool

    calls = []

    @tool
    async def get_demo_time() -> str:
        """Return a deterministic time for testing."""
        calls.append('time')
        return '12:34'

    class ToolModel(MemoryModel):
        async def ainvoke(self, messages):
            if isinstance(messages[-1], ToolMessage):
                return AIMessage(content='Time: ' + messages[-1].content)
            return AIMessage(content='', tool_calls=[
                {'name': 'get_demo_time', 'args': {}, 'id': 'call-1', 'type': 'tool_call'}
            ])

    service = AgentService(build_graph(ToolModel(), [get_demo_time]))
    result = await service.chat('time?', 'tool-session')
    assert result.response == 'Time: 12:34'
    assert calls == ['time']
