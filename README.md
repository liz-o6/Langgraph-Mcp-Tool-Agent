# LangGraph MCP Tool Agent

A CSCI 599 course project: a LangGraph assistant that uses three MCP servers for filesystem operations, Tavily web search, and time. FastAPI exposes a session-based chat API; the app can be containerized and deployed to Google Cloud Run.

## Highlights

- Discovers MCP tools through `tools/list` and invokes them through `tools/call`.
- Routes between direct answers and tool calls; `InMemorySaver` keeps separate session histories while the process runs.
- Returns bounded tool errors to the model and provides a six-round limit on tool use.
- Includes automated tests for sessions, API validation, file access, and tool failures.

## Run locally

Use Python 3.10 or newer and Node.js for the filesystem MCP server.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in OPENAI_API_KEY and TAVILY_API_KEY in .env.
mkdir -p workspace/files/inputs workspace/files/outputs
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` and call `POST /chat`. Run offline tests with `python -m pytest -q`. The original course run passed 22 local tests; that result is a historical snapshot, not a claim about your environment.

`deploy.sh` supports Cloud Run deployment and requires your own GCP project and API credentials. The public repository contains only blank variable names in `.env.example`; never commit a populated `.env`.

The filesystem tool is confined to `workspace/files`. A public deployment exposes files created there, so do not store private data in the service.

## Attribution

The project integrates existing [Filesystem MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem), [Tavily MCP](https://github.com/tavily-ai/tavily-mcp), and [Time MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/time) servers. The agent, API integration, deployment, and tests are the course project work.
