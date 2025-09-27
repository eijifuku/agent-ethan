"""Utilities for building structured logging events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from .masking import Masker

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def utcnow_iso() -> str:
    """Return current UTC time in ISO 8601 format with milliseconds."""

    return datetime.utcnow().strftime(ISO_FORMAT)


def summarize_payload(payload: Any, masker: Masker, preview_chars: int = 256) -> Optional[Dict[str, Any]]:
    """Summarise a payload for logging without dumping full content."""

    if payload is None:
        return None

    masked = masker.redact(payload)
    summary: Dict[str, Any] = {"size": _payload_size(masked)}

    if isinstance(masked, dict):
        summary["keys"] = list(masked.keys())
        summary["preview"] = _render_preview(masked, preview_chars)
        return summary
    if isinstance(masked, (list, tuple)):
        summary["items"] = len(masked)
        summary["preview"] = _render_preview(masked[: preview_chars // 10], preview_chars)
        return summary
    if isinstance(masked, str):
        summary["preview"] = masked[:preview_chars]
        return summary
    summary["preview"] = _render_preview(masked, preview_chars)
    return summary


def _payload_size(payload: Any) -> int:
    try:
        if isinstance(payload, (str, bytes)):
            return len(payload)
        return len(json.dumps(payload, ensure_ascii=False))
    except Exception:
        return 0


def _render_preview(payload: Any, preview_chars: int) -> str:
    try:
        rendered = json.dumps(payload, ensure_ascii=False)
    except Exception:
        rendered = str(payload)
    if len(rendered) <= preview_chars:
        return rendered
    return rendered[:preview_chars] + "…"
