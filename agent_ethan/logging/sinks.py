"""Logging sinks for tracing events."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, IO, Optional


LOGGER = logging.getLogger(__name__)


class Sink:
    """Interface for log sinks."""

    def emit(self, event: Dict[str, Any]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def flush(self) -> None:  # pragma: no cover - optional override
        pass

    def close(self) -> None:  # pragma: no cover - optional override
        pass


class StdoutSink(Sink):
    """Write events to stdout as JSON Lines."""

    def __init__(self) -> None:
        self._encoder = json.JSONEncoder(ensure_ascii=False)

    def emit(self, event: Dict[str, Any]) -> None:
        print(self._encoder.encode(event))


class JsonlSink(Sink):
    """Persist events to disk under a run-specific JSONL file."""

    def __init__(self, root_dir: str) -> None:
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        self._files: Dict[str, IO[str]] = {}

    def emit(self, event: Dict[str, Any]) -> None:
        run_id = event.get("run_id") or "unknown"
        handle = self._ensure_file(run_id)
        json.dump(event, handle, ensure_ascii=False)
        handle.write("\n")
        handle.flush()

    def _ensure_file(self, run_id: str) -> IO[str]:
        if run_id in self._files:
            return self._files[run_id]
        today = datetime.utcnow().strftime("%Y-%m-%d")
        target_dir = self._root / today
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{run_id}.jsonl"
        handle = path.open("a", encoding="utf-8")
        self._files[run_id] = handle
        return handle

    def close(self) -> None:
        for handle in self._files.values():
            handle.flush()
            handle.close()
        self._files.clear()


class LangsmithSink(Sink):
    """Send events to LangSmith if the SDK is available."""

    def __init__(self, project: Optional[str] = None) -> None:
        self._enabled = False
        self._client = None
        try:  # pragma: no cover - optional dependency
            from langsmith import Client  # type: ignore
        except Exception:  # noqa: BLE001
            LOGGER.warning("LangSmith sink not available; install 'langsmith' to enable it")
            return
        try:
            self._client = Client(project=project)
            self._enabled = True
        except Exception as exc:  # pragma: no cover - safety guard
            LOGGER.warning("Failed to initialise LangSmith client: %s", exc)

    def emit(self, event: Dict[str, Any]) -> None:
        if not self._enabled or self._client is None:
            return
        try:
            log_event = getattr(self._client, "log_event", None)
            if callable(log_event):
                log_event(event)
                return
            log_json = getattr(self._client, "log_json", None)
            if callable(log_json):  # pragma: no cover - depends on SDK version
                log_json(event)
                return
            LOGGER.debug("LangSmith client lacks log_event/log_json; dropping event")
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.warning("LangSmith sink failed to emit event: %s", exc)


class NullSink(Sink):
    """Sink that discards all events (Null Object pattern)."""

    def emit(self, event: Dict[str, Any]) -> None:  # noqa: D401
        return
