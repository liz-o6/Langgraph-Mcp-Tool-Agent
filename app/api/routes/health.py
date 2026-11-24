from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Check HTTP liveness only, not graph or MCP readiness."""
    return {"status": "ok"}
