import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_agent_service
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent import AgentService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        502: {"description": "Agent execution failed."},
        503: {"description": "Agent service is not ready."},
    },
)
async def chat(
    request: ChatRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> ChatResponse:
    try:
        return await service.chat(request.query, request.session_id)
    except Exception:
        # Do not expose upstream exception text (which may contain credentials).
        logger.error("Agent execution failed")
        raise HTTPException(status_code=502, detail="Agent execution failed.") from None
