"""Fallback summary generator for downloaded arXiv papers."""

from __future__ import annotations

from typing import Any, Dict, Sequence

ToolOutput = Dict[str, Any]


def fallback_summary(
    *,
    downloads: Sequence[Dict[str, Any]] | None,
    llm_summary: str | None = None,
) -> ToolOutput:
    summary = (llm_summary or "").strip()
    if not summary:
        summary = _build_fallback(downloads)
    return {
        "status": 200,
        "json": {"summary": summary},
        "text": summary,
        "items": None,
        "result": summary,
        "error": None,
    }


def _build_fallback(downloads: Sequence[Dict[str, Any]] | None) -> str:
    if not downloads:
        return ""  # nothing to report
    lines = ["選定した論文一覧:"]
    for item in downloads:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id") or item.get("identifier") or ""
        title = item.get("title") or "タイトル不明"
        path = item.get("path") or item.get("url") or ""
        lines.append(f"- {identifier}: {title} ({path})")
    return "\n".join(lines)
