"""HTTP tool that produces normalized output compatible with the agent runtime."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

import httpx


ToolOutput = Dict[str, Any]


def call(
    *,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    json: Any = None,
    data: Any = None,
    timeout: Optional[float] = None,
    auth: Optional[Tuple[str, str]] = None,
    allow_redirects: bool = True,
) -> ToolOutput:
    """Perform an HTTP request with httpx and normalize the response payload."""

    request_args = {
        "method": method.upper(),
        "url": url,
        "params": params,
        "headers": headers,
        "json": json,
        "data": data,
        "timeout": timeout,
        "auth": auth,
        "follow_redirects": allow_redirects,
    }

    try:
        with httpx.Client() as client:
            response = client.request(**request_args)
    except httpx.HTTPError as exc:  # pragma: no cover - network failures are environment specific
        return _error_output(message=str(exc), status=getattr(exc.response, "status_code", 0))

    parsed_json = _safe_json(response)
    parsed_items = _extract_items(parsed_json)

    return {
        "status": response.status_code,
        "json": parsed_json,
        "text": response.text,
        "items": parsed_items,
        "result": parsed_json or response.text,
        "error": None,
    }


def _safe_json(response: httpx.Response) -> Optional[Any]:
    try:
        return response.json()
    except ValueError:
        return None


def _extract_items(payload: Any) -> Optional[Iterable[Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def _error_output(*, message: str, status: int) -> ToolOutput:
    return {
        "status": status,
        "json": None,
        "text": None,
        "items": None,
        "result": None,
        "error": {
            "type": "http_error",
            "message": message,
            "status": status,
        },
    }
