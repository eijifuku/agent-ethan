"""Simple LLM client wrapper with retry handling."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .schema import LLMNode


class LLMCallable(Protocol):
    """Protocol describing a callable that produces LLM responses."""

    def __call__(
        self,
        *,
        node: "LLMNode",
        prompt: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        ...


@dataclass
class RetryPolicy:
    """Retry parameters applied to LLM invocations."""

    max_attempts: int = 1
    backoff: float = 0.0


class LLMClient:
    """Retry-aware wrapper around a low-level LLM callable."""

    def __init__(self, *, call: LLMCallable) -> None:
        self._call = call

    def generate(
        self,
        node: "LLMNode",
        prompt: Dict[str, Any],
        *,
        retry: Optional[RetryPolicy] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        attempts = retry.max_attempts if retry else 1
        backoff = retry.backoff if retry else 0.0
        last_exception: Optional[BaseException] = None
        last_response: Optional[Dict[str, Any]] = None

        for attempt in range(1, attempts + 1):
            try:
                response = self._call(node=node, prompt=prompt, timeout=timeout)
            except Exception as exc:  # pragma: no cover - surface to caller on final attempt
                last_exception = exc
                if attempt == attempts:
                    raise
            else:
                last_response = response
                if not response.get("error") or attempt == attempts:
                    return response
            if backoff:
                time.sleep(backoff)

        if last_exception is not None:  # pragma: no cover - defensive guard
            raise last_exception
        return last_response or {}
