"""Utility tools for parsing JSON responses from LLM nodes."""

from __future__ import annotations

import json
from typing import Any, Dict

ToolOutput = Dict[str, Any]


def parse_object(*, text: str) -> ToolOutput:
    """Parse a JSON object encoded as text."""

    data = json.loads(text)
    return {
        "status": 200,
        "json": data,
        "text": text,
        "items": None,
        "result": data,
        "error": None,
    }
