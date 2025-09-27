"""MCP tool wrapper that unifies return values into the standard schema."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol


class MCPClient(Protocol):
    """Protocol describing the minimum surface of an MCP client."""

    def invoke(self, resource: str, action: str, payload: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Any:
        ...


ToolOutput = Dict[str, Any]


def invoke(
    *,
    resource: str,
    action: str,
    payload: Optional[Dict[str, Any]] = None,
    client: Optional[MCPClient] = None,
    **kwargs: Any,
) -> ToolOutput:
    """Invoke an MCP resource/action pair using the provided client."""

    if client is None:
        return _error_output("mcp_client_missing", "MCP client instance must be supplied", status=0)

    try:
        result = client.invoke(resource=resource, action=action, payload=payload, **kwargs)
    except Exception as exc:  # pragma: no cover - propagating client errors
        return _error_output(type(exc).__name__, str(exc), status=0)

    json_payload = result if isinstance(result, dict) else None
    text_payload = None
    items_payload = None

    if isinstance(result, str):
        text_payload = result
    elif isinstance(result, list):
        items_payload = result
    elif isinstance(result, dict):
        text_payload = result.get("text")
        candidate_items = result.get("items")
        if isinstance(candidate_items, list):
            items_payload = candidate_items

    return {
        "status": 0,
        "json": json_payload,
        "text": text_payload,
        "items": items_payload,
        "result": result,
        "error": None,
    }


def _error_output(error_type: str, message: str, *, status: int) -> ToolOutput:
    return {
        "status": status,
        "json": None,
        "text": None,
        "items": None,
        "result": None,
        "error": {
            "type": error_type,
            "message": message,
            "status": status,
        },
    }
