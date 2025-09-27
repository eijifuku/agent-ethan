"""Placeholder utilities for LangChain tool overrides in examples."""

from __future__ import annotations

from typing import Any, Dict


def requires_override(**_: Any) -> Dict[str, Any]:
    """Raise a clear error when a LangChain tool is not provided."""

    raise RuntimeError(
        "Tool 'qa_tool' must be supplied via tool_overrides with a LangChain BaseTool."
    )

