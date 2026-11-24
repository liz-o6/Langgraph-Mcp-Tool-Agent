from typing import Annotated

from pydantic import BaseModel, StringConstraints

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChatRequest(BaseModel):
    query: NonEmptyString
    session_id: NonEmptyString | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
