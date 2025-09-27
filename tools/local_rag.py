"""Local search tool for the RAG example."""

from __future__ import annotations

from typing import Any, Dict, List

ToolOutput = Dict[str, Any]

_CORPUS: List[Dict[str, str]] = [
    {
        "title": "LLM Basics",
        "content": "Large language models are trained on vast corpora to generate text.",
    },
    {
        "title": "RAG Pattern",
        "content": "Retrieval-Augmented Generation injects retrieved context into prompts.",
    },
    {
        "title": "LM Studio",
        "content": "LM Studio runs an OpenAI-compatible API locally for experimentation.",
    },
]


def search(*, query: str) -> ToolOutput:
    normalized = query.strip().lower()
    matches = [item for item in _CORPUS if normalized and normalized in item["content"].lower()]
    if not matches:
        matches = _CORPUS[:1]

    payload = {"items": matches}
    summary = "\n".join(entry["content"] for entry in matches)
    return {
        "status": 200,
        "json": payload,
        "text": summary,
        "items": matches,
        "result": payload,
        "error": None,
    }
