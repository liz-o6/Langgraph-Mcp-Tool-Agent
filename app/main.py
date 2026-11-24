"""HTTP entry point: python -m uvicorn app.main:app --reload."""

from fastapi import FastAPI

from app.api.router import api_router
from app.core.lifespan import lifespan


def create_app() -> FastAPI:
    app = FastAPI(
        title="HW1 Agent API",
        version="0.1.0",
        description="LangGraph agent with shared MCP connections and in-memory sessions.",
        lifespan=lifespan,
    )
    app.include_router(api_router)
    return app


app = create_app()
