"""Log manager orchestrating sinks, spans, and masking."""

from __future__ import annotations

import random
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

from .context import run_id_var, span_id_var, trace_id_var, trace_enabled_var
from .events import summarize_payload, utcnow_iso
from .masking import Masker, default_masker
from .sinks import NullSink, Sink

_LEVEL_MAP = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40}


class LogManager:
    """Coordinate event emission across sinks with sampling and masking."""

    def __init__(
        self,
        sinks: Iterable[Sink] | None = None,
        sample_rate: float = 1.0,
        masker: Optional[Masker] = None,
        level: str = "info",
    ) -> None:
        self.sample_rate = max(0.0, min(sample_rate, 1.0))
        self._masker = masker or default_masker()
        self._base_sinks: List[Sink] = list(sinks or [])
        self._span_meta: Dict[str, Dict[str, Any]] = {}
        self._span_tokens: Dict[str, Any] = {}
        self.enabled = bool(self._base_sinks)
        self._level_threshold = _LEVEL_MAP.get(level.lower(), 20)

    # ------------------------------------------------------------------
    # Sampling helpers
    # ------------------------------------------------------------------

    def should_sample(self) -> bool:
        if not self.enabled:
            return False
        if self.sample_rate >= 1.0:
            return True
        return random.random() <= self.sample_rate

    # ------------------------------------------------------------------
    # Span lifecycle
    # ------------------------------------------------------------------

    def start_span(self, kind: str, **meta: Any) -> str:
        if not self.enabled or not trace_enabled_var.get():
            return uuid.uuid4().hex

        span_id = uuid.uuid4().hex
        parent_span = span_id_var.get()
        token = span_id_var.set(span_id)
        self._span_tokens[span_id] = token
        now = time.monotonic()
        self._span_meta[span_id] = {
            "kind": kind,
            "parent": parent_span,
            "start": now,
        }

        event_name = meta.pop("event", f"{kind}_start")
        event = {
            "event": event_name,
            "level": meta.pop("level", "info"),
            "ts": utcnow_iso(),
            "span_id": span_id,
            "parent_span_id": parent_span,
            "kind": kind,
        }
        event.update(self._common_fields())
        event.update(meta)
        self.emit(event)
        return span_id

    def end_span(self, span_id: str, **meta: Any) -> None:
        if not self.enabled or not trace_enabled_var.get():
            return

        token = self._span_tokens.pop(span_id, None)
        if token is not None:
            span_id_var.reset(token)

        info = self._span_meta.pop(span_id, None)
        duration = None
        parent = None
        kind = None
        if info:
            start = info.get("start")
            if isinstance(start, (int, float)):
                duration = (time.monotonic() - start) * 1000
            parent = info.get("parent")
            kind = info.get("kind")

        event_name = meta.pop("event", f"{kind or 'span'}_end")
        event = {
            "event": event_name,
            "level": meta.pop("level", "info"),
            "ts": utcnow_iso(),
            "span_id": span_id,
            "parent_span_id": parent,
            "kind": kind,
        }
        if duration is not None:
            event["duration_ms"] = duration
        event.update(self._common_fields())
        event.update(meta)
        self.emit(event)

    # ------------------------------------------------------------------
    # Emission helpers
    # ------------------------------------------------------------------

    def emit(self, event: Dict[str, Any]) -> None:
        if not self.enabled or not trace_enabled_var.get():
            return
        level_value = _LEVEL_MAP.get(str(event.get("level", "info")).lower(), 20)
        if level_value < self._level_threshold:
            return

        base = {
            "ts": utcnow_iso(),
            "run_id": run_id_var.get(),
            "span_id": event.get("span_id") or span_id_var.get(),
            "trace_id": trace_id_var.get() or run_id_var.get(),
        }
        enriched = {**base, **event}
        masked = self._masker.redact(enriched)
        for sink in self._base_sinks or [NullSink()]:
            sink.emit(masked)

    def summarize(self, payload: Any, preview_chars: int = 256) -> Optional[Dict[str, Any]]:
        return summarize_payload(payload, self._masker, preview_chars)

    def _common_fields(self) -> Dict[str, Any]:
        return {
            "run_id": run_id_var.get(),
            "trace_id": trace_id_var.get() or run_id_var.get(),
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def flush(self) -> None:
        for sink in self._base_sinks:
            sink.flush()

    def close(self) -> None:
        for sink in self._base_sinks:
            try:
                sink.close()
            except Exception:  # pragma: no cover - best effort
                pass
        self._base_sinks.clear()
        self.enabled = False
