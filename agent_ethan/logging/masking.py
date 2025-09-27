"""Masking utilities for structured logging."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Pattern


REDACTED = "[REDACTED]"
DEFAULT_DENY_KEYS = {
    "api_key",
    "authorization",
    "password",
    "token",
    "secret",
    "cookie",
    "session",
    "client_secret",
    "private_key",
}
DEFAULT_REGEXES = [
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\.\-_=]+", re.IGNORECASE), r"\1" + REDACTED),
    (re.compile(r"([A-Za-z0-9]{4})[A-Za-z0-9]{8,}([A-Za-z0-9]{4})"), r"\1" + REDACTED + r"\2"),
]


class Masker:
    """Redact sensitive fields and truncate large string payloads."""

    def __init__(
        self,
        deny_keys: Iterable[str] | None = None,
        max_text: int = 2048,
        regexes: Iterable[tuple[Pattern[str], str]] | None = None,
    ) -> None:
        self._deny_keys = {key.lower() for key in (deny_keys or set())}
        self._max_text = max_text if max_text > 0 else 0
        self._regexes = list(regexes or [])

    def redact(self, payload: Any) -> Any:
        return self._redact(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _redact(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return self._redact_mapping(value)
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact(item) for item in value)
        if isinstance(value, set):
            return {self._redact(item) for item in value}
        if isinstance(value, str):
            return self._sanitize_text(value)
        return value

    def _redact_mapping(self, mapping: Mapping[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in mapping.items():
            lowered = key.lower() if isinstance(key, str) else str(key).lower()
            if lowered in self._deny_keys:
                result[key] = REDACTED
                continue
            result[key] = self._redact(value)
        return result

    def _sanitize_text(self, text: str) -> str:
        result = text
        for pattern, replacement in self._regexes:
            result = pattern.sub(replacement, result)
        if self._max_text and len(result) > self._max_text:
            return result[: self._max_text] + "…"
        return result


def default_masker() -> Masker:
    """Factory for default masking configuration."""

    denylist = {
        "api_key",
        "authorization",
        "password",
        "token",
        "secret",
        "cookie",
        "session",
        "client_secret",
        "private_key",
    }
    regexes = [
        (re.compile(r"(Bearer\s+)[A-Za-z0-9\.\-_=]+", re.IGNORECASE), r"\1" + REDACTED),
        (re.compile(r"([A-Za-z0-9]{4})[A-Za-z0-9]{8,}([A-Za-z0-9]{4})"), r"\1" + REDACTED + r"\2"),
    ]
    return Masker(deny_keys=denylist, max_text=2048, regexes=regexes)
