"""Utility helpers for interpreting LLM relevance output for arXiv results."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Sequence

ToolOutput = Dict[str, Any]


def parse_selection(
    *,
    raw_text: str,
    search_results: Sequence[Dict[str, Any]],
    keywords: str | None = None,
    max_results: int = 3,
) -> ToolOutput:
    """Parse LLM output into a relevance decision with heuristic fallback."""

    selection = _extract_json(raw_text)
    available_ids = {item.get("id") for item in search_results if isinstance(item, dict)}
    relevant_ids: List[str] = []
    reason = ""

    if selection and isinstance(selection, dict):
        ids = selection.get("relevant_ids")
        if isinstance(ids, list):
            relevant_ids = [str(paper_id) for paper_id in ids if str(paper_id) in available_ids]
        reason = str(
            selection.get("reason")
            or selection.get("rationale")
            or selection.get("explanation")
            or ""
        )

    if not relevant_ids:
        relevant_ids = _heuristic_select(search_results, keywords or "", max_results=max_results)
        if not reason:
            reason = "Selected via heuristic keyword overlap."

    payload = {"relevant_ids": relevant_ids, "reason": reason}
    return {
        "status": 200,
        "json": payload,
        "text": json.dumps(payload, ensure_ascii=False),
        "items": payload["relevant_ids"],
        "result": payload,
        "error": None,
    }


def _extract_json(raw_text: str) -> Dict[str, Any] | None:
    text = raw_text.strip()
    if not text:
        return None

    try:
        candidate = json.loads(text)
        if isinstance(candidate, dict):
            return candidate
    except json.JSONDecodeError:
        pass

    brace_match = _extract_braced_json(text)
    if brace_match:
        try:
            candidate = json.loads(brace_match)
            if isinstance(candidate, dict):
                return candidate
        except json.JSONDecodeError:
            return None
    return None


def _extract_braced_json(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _heuristic_select(
    search_results: Sequence[Dict[str, Any]],
    keywords: str,
    *,
    max_results: int,
) -> List[str]:
    tokens = _tokenize(keywords)
    scored: List[tuple[int, str]] = []
    for item in search_results:
        if not isinstance(item, dict):
            continue
        paper_id = item.get("id")
        if not paper_id:
            continue
        haystack_parts = [str(item.get(key, "")) for key in ("title", "summary", "keywords")]
        categories = item.get("categories")
        if isinstance(categories, list):
            haystack_parts.append(" ".join(str(cat) for cat in categories))
        haystack = " ".join(haystack_parts).lower()
        score = sum(1 for token in tokens if token and token in haystack)
        scored.append((score, str(paper_id)))

    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    filtered = [paper_id for score, paper_id in scored if score > 0]
    if not filtered:
        filtered = [paper_id for _, paper_id in scored]
    return filtered[:max_results]


def _tokenize(text: str) -> List[str]:
    return [token for token in re.split(r"\W+", text.lower()) if token]
