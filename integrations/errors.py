"""Safe error messages for tool results and logs."""

import asyncio
import json

import anyio
import httpx
from langchain_core.tools import ToolException
from pydantic import ValidationError


def error_message(error: Exception) -> str:
    nested = getattr(error, "exceptions", ())
    if nested:
        return error_message(nested[0])
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "Tool request timed out. Do not repeat the same request this turn."
    if isinstance(error, (ConnectionError, OSError, anyio.EndOfStream,
                          anyio.BrokenResourceError, anyio.ClosedResourceError,
                          httpx.TransportError)):
        return "Tool server is unavailable or disconnected. Use another tool or report the failure."
    if isinstance(error, (ValidationError, json.JSONDecodeError)):
        return "Invalid tool arguments or malformed server response. Report the failure; do not invent a result."
    if isinstance(error, ToolException):
        return "Tool execution failed. Check the request or report that it could not be completed."
    # Upstream text can contain credentials, URLs, or private file content.
    return "Tool request failed. No successful result is available."
