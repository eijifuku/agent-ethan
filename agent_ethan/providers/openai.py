"""OpenAI provider adapter for Agent Ethan."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..llm import LLMClient
from ..logging.decorators import log_llm


class OpenAIUnavailable(RuntimeError):
    """Raised when the openai package is not available and no client is supplied."""


def create_openai_client(
    *,
    model: str,
    temperature: float = 0.0,
    client: Any | None = None,
    default_kwargs: Optional[Dict[str, Any]] = None,
    client_kwargs: Optional[Dict[str, Any]] = None,
) -> LLMClient:
    """Create an LLMClient backed by OpenAI's chat completions API.

    Parameters
    ----------
    model:
        Target model identifier (e.g., ``gpt-4o-mini``).
    temperature:
        Sampling temperature passed to the API.
    client:
        Optional preconfigured OpenAI client. If omitted, this function attempts to
        instantiate ``openai.OpenAI``.
    default_kwargs:
        Extra keyword arguments forwarded to ``chat.completions.create``.
    """

    openai_client = client or _default_openai_client(client_kwargs)
    kwargs = default_kwargs.copy() if default_kwargs else {}

    def _call(*, node, prompt: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:  # type: ignore[override]
        messages = _prompt_to_messages(prompt)
        request_kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        request_kwargs.update(kwargs)

        response = openai_client.chat.completions.create(**request_kwargs)
        content = _extract_message_content(response)
        return {
            "status": 200,
            "json": _response_to_json(response),
            "text": content,
            "items": None,
            "result": content,
            "error": None,
        }

    return LLMClient(call=log_llm("openai", model)(_call))


def _default_openai_client(client_kwargs: Optional[Dict[str, Any]] = None) -> Any:
    try:
        import openai  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise OpenAIUnavailable(
            "openai package is required to create an OpenAI client or provide a custom client"
        ) from exc
    kwargs = client_kwargs or {}
    return openai.OpenAI(**kwargs)


def _prompt_to_messages(prompt: Dict[str, Any]) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    for role in ("system", "user", "assistant"):
        content = prompt.get(role)
        if content:
            messages.append({"role": role, "content": str(content)})

    indexed: Dict[int, Dict[str, str]] = {}
    for key, value in prompt.items():
        if key.startswith("messages[") and "#" in key:
            index_part, role = key.split("#", 1)
            try:
                index = int(index_part[len("messages[") : -1])
            except ValueError:
                continue
            indexed.setdefault(index, {})[role] = str(value)

    for index in sorted(indexed):
        role_map = indexed[index]
        for role, content in role_map.items():
            messages.append({"role": role, "content": content})

    if not messages:
        messages.append({"role": "user", "content": ""})
    return messages


def _extract_message_content(response: Any) -> Optional[str]:
    choice = None
    if hasattr(response, "choices"):
        choices = getattr(response, "choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
    if choice is None:
        if isinstance(response, dict):
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                choice = choices[0]
    if choice is None:
        return None

    message = None
    if isinstance(choice, dict):
        message = choice.get("message") or {}
    else:
        message = getattr(choice, "message", None) or {}

    if isinstance(message, dict):
        content = message.get("content")
        return str(content) if content is not None else None
    content = getattr(message, "content", None)
    return str(content) if content is not None else None


def _response_to_json(response: Any) -> Any:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()  # type: ignore[attr-defined]
    if hasattr(response, "__dict__"):
        return response.__dict__
    return None
