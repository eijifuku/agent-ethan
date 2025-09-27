"""Mock tools used for unit testing the agent runtime."""

from __future__ import annotations

from typing import Any, Dict

ToolOutput = Dict[str, Any]

def echo(**payload: Any) -> ToolOutput:
    json_payload = payload.get("json", payload)
    items = payload.get("items")
    if items is None and isinstance(json_payload, dict):
        items = json_payload.get("items")
    return {
        "status": payload.get("status", 200),
        "json": json_payload,
        "text": payload.get("text"),
        "items": items,
        "result": json_payload,
        "error": None,
    }

def increment(current: int) -> ToolOutput:
    new_value = current + 1
    json_payload = {"count": new_value}
    return {
        "status": 200,
        "json": json_payload,
        "text": None,
        "items": None,
        "result": json_payload,
        "error": None,
    }

def failing(**payload: Any) -> ToolOutput:
    return {
        "status": payload.get("status", 500),
        "json": None,
        "text": None,
        "items": None,
        "result": None,
        "error": {
            "type": payload.get("error_type", "test_failure"),
            "message": payload.get("message", "intentional failure"),
            "status": payload.get("status", 500),
        },
    }
