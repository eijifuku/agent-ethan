"""Heuristic keyword fallback for arXiv agent."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable

ToolOutput = Dict[str, Any]

_STOPWORDS = {
    "the",
    "and",
    "with",
    "into",
    "using",
    "about",
    "this",
    "that",
    "for",
    "into",
    "from",
    "into",
    "when",
    "where",
    "which",
    "what",
    "about",
    "into",
    "your",
    "their",
    "there",
    "over",
    "under",
    "between",
    "into",
}


def fallback_keywords(*, request: str, llm_keywords: str | None = None, limit: int = 6) -> ToolOutput:
    """Return LLM-provided keywords or generate heuristics from the request."""

    chosen = _sanitize(llm_keywords)
    if not chosen:
        chosen = _heuristic_keywords(request, limit=limit)
    return {
        "status": 200,
        "json": {"keywords": chosen},
        "text": chosen,
        "items": None,
        "result": chosen,
        "error": None,
    }


def _sanitize(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _heuristic_keywords(request: str, *, limit: int) -> str:
    tokens = _tokenize(request)
    filtered = [token for token in tokens if token not in _STOPWORDS]
    unique: list[str] = []
    for token in filtered:
        if token not in unique:
            unique.append(token)
        if len(unique) >= limit:
            break
    return ", ".join(unique) if unique else request.strip()


def _tokenize(text: str) -> Iterable[str]:
    return [token for token in re.split(r"[^a-zA-Z0-9_]+", text.lower()) if token]
