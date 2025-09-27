"""Tracing and event logging utilities."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence, TYPE_CHECKING

from .manager import LogManager
from .masking import DEFAULT_DENY_KEYS, DEFAULT_REGEXES, Masker
from .sinks import JsonlSink, LangsmithSink, NullSink, Sink, StdoutSink

if TYPE_CHECKING:  # pragma: no cover
    from agent_ethan.schema import TracingConfig

_LOG_MANAGER: Optional[LogManager] = None


def get_log_manager() -> LogManager:
    """Return the global log manager, creating a disabled instance if needed."""

    global _LOG_MANAGER
    if _LOG_MANAGER is None:
        _LOG_MANAGER = _create_manager(enabled=False)
    return _LOG_MANAGER


def configure_tracing(tracing: Optional["TracingConfig"]) -> LogManager:
    """Configure the global log manager from YAML tracing settings."""

    manager = _create_manager(enabled=False)
    if tracing and tracing.enabled:
        sinks = _build_sinks(tracing)
        deny_keys: Iterable[str] = tracing.deny_keys or list(DEFAULT_DENY_KEYS)
        masker = Masker(deny_keys=deny_keys, max_text=tracing.max_text, regexes=DEFAULT_REGEXES)
        manager = LogManager(
            sinks=sinks,
            sample_rate=tracing.sample,
            masker=masker,
            level=getattr(tracing, "level", "info"),
        )
        manager.enabled = bool(sinks)
    set_log_manager(manager)
    return manager


def set_log_manager(manager: LogManager) -> None:
    """Replace the global log manager instance."""

    global _LOG_MANAGER
    _LOG_MANAGER = manager


def _create_manager(enabled: bool) -> LogManager:
    masker = Masker(deny_keys=DEFAULT_DENY_KEYS, max_text=2048, regexes=DEFAULT_REGEXES)
    manager = LogManager(sinks=[], sample_rate=1.0, masker=masker, level="info")
    manager.enabled = enabled
    return manager


def _build_sinks(tracing: "TracingConfig") -> list[Sink]:
    tokens: Sequence[str] = getattr(tracing, "sinks", []) or []
    if not tokens:
        return [NullSink()]

    sinks: list[Sink] = []
    for token in tokens:
        normalised = token.lower()
        if normalised == "stdout":
            sinks.append(StdoutSink())
        elif normalised == "jsonl":
            sinks.append(JsonlSink(tracing.dir))
        elif normalised == "langsmith":
            sinks.append(LangsmithSink(project=getattr(tracing, "langsmith_project", None)))
        elif normalised == "null":
            return [NullSink()]
    if not sinks:
        sinks.append(NullSink())
    return sinks


__all__ = [
    "configure_tracing",
    "get_log_manager",
    "set_log_manager",
]
