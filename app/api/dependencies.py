from fastapi import HTTPException, Request

from app.services.agent import AgentService


def get_agent_service(request: Request) -> AgentService:
    service = getattr(request.app.state, "agent_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent service is not ready.")
    return service
