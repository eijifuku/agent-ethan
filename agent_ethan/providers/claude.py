"""Anthropic Claude provider adapter for Agent Ethan."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..llm import LLMClient
from ..logging.decorators import log_llm


class ClaudeProviderUnavailable(RuntimeError):
    """Raised when the anthropic package is unavailable."""


def create_claude_client(
    *,
    model: str,
    api_key: str,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    client: Any | None = None,
    default_kwargs: Optional[Dict[str, Any]] = None,
) -> LLMClient:
    """Create an `LLMClient` backed by Anthropic Claude messages API."""

    extra = default_kwargs.copy() if default_kwargs else {}

    if client is None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - import guard
            raise ClaudeProviderUnavailable("anthropic package is required for Claude provider") from exc

        client = anthropic.Anthropic(api_key=api_key)

    def _call(*, node, prompt: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:  # type: ignore[override]
        messages = _prompt_to_messages(prompt)
        request_kwargs: Dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        request_kwargs.update(extra)
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        response = client.messages.create(**request_kwargs)
        text = _extract_text(response)
        payload = _to_serializable(response)
        return {
            "status": 200,
            "json": payload,
            "text": text,
            "items": None,
            "result": text,
            "error": None,
        }

    return LLMClient(call=log_llm("claude", model)(_call))


def _prompt_to_messages(prompt: Dict[str, Any]) -> list[Dict[str, Any]]:
    messages: list[Dict[str, Any]] = []

    def _append(role: str, content: Optional[str]) -> None:
        if content:
            messages.append({"role": role, "content": content})

    _append("user", prompt.get("user"))
    _append("assistant", prompt.get("assistant"))
    _append("system", prompt.get("system"))

    indexed: Dict[int, Dict[str, str]] = {}
    for key, value in prompt.items():
        if key.startswith("messages[") and "#" in key:
            index_part, role = key.split("#", 1)
            try:
                idx = int(index_part[len("messages[") : -1])
            except ValueError:
                continue
            indexed.setdefault(idx, {})[role] = str(value)

    for idx in sorted(indexed):
        role_map = indexed[idx]
        for role, content in role_map.items():
            mapped_role = "assistant" if role == "assistant" else "user" if role == "user" else role
            _append(mapped_role, content)

    if not messages:
        _append("user", "")
    return messages


def _extract_text(response: Any) -> Optional[str]:
    content = getattr(response, "content", None)
    if not content:
        return None
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text" and block.get("text"):
                return str(block["text"])
        else:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text = getattr(block, "text", None)
                if text:
                    return str(text)
    return None


def _to_serializable(response: Any) -> Any:
    if response is None:
        return None
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump()
        except Exception:  # pragma: no cover - fallback
            pass
    if hasattr(response, "to_dict"):
        try:
            return response.to_dict()
        except Exception:  # pragma: no cover
            pass
    return response

