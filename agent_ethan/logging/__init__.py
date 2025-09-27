"""Tracing and event logging utilities."""

from __future__ import annotations

import os
from typing import Iterable, Optional

from .context import trace_enabled_var
from .manager import LogManager
from .masking import DEFAULT_DENY_KEYS, DEFAULT_REGEXES, Masker, default_masker
from .sinks import JsonlSink, LangsmithSink, NullSink, Sink, StdoutSink

_LOG_MANAGER: Optional[LogManager] = None


def get_log_manager() -> LogManager:
    global _LOG_MANAGER
    if _LOG_MANAGER is None:
        _LOG_MANAGER = configure_from_env()
    return _LOG_MANAGER


def configure_from_env() -> LogManager:
    enabled = _env_flag("AE_TRACE_ENABLED", default=False)
    sinks = _build_sinks(os.getenv("AE_TRACE_SINKS", "")) if enabled else []
    sample = float(os.getenv("AE_TRACE_SAMPLE", "1.0"))
    deny_keys_env = set(_parse_csv(os.getenv("AE_TRACE_DENY_KEYS", "")))
    max_text = int(os.getenv("AE_TRACE_MAX_TEXT", "2048"))
    deny_keys = deny_keys_env or DEFAULT_DENY_KEYS
    masker = Masker(deny_keys=deny_keys, max_text=max_text, regexes=DEFAULT_REGEXES)
    level = os.getenv("AE_TRACE_LEVEL", "info")

    manager = LogManager(sinks=sinks, sample_rate=sample, masker=masker, level=level)
    manager.enabled = enabled and bool(sinks)
    return manager


def set_log_manager(manager: LogManager) -> None:
    global _LOG_MANAGER
    _LOG_MANAGER = manager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _parse_csv(value: str) -> Iterable[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _build_sinks(config: str) -> list[Sink]:
    if not config.strip():
        return [NullSink()]

    sinks: list[Sink] = []
    tokens = [token.strip().lower() for token in config.split(",") if token.strip()]
    if not tokens:
        return [NullSink()]

    for token in tokens:
        if token == "stdout":
            sinks.append(StdoutSink())
        elif token == "jsonl":
            root = os.getenv("AE_TRACE_DIR", "./logs")
            sinks.append(JsonlSink(root))
        elif token == "langsmith":
            project = os.getenv("AE_TRACE_LANGSMITH_PROJECT")
            sinks.append(LangsmithSink(project=project))
        elif token == "null":
            return [NullSink()]
    if not sinks:
        sinks.append(NullSink())
    return sinks
