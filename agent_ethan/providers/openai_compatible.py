"""OpenAI-compatible provider adapter for Agent Ethan."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..llm import LLMClient
from ..logging.decorators import log_llm


class OpenAICompatibleUnavailable(RuntimeError):
    """Raised when httpx is missing and no client is supplied."""


def create_openai_compatible_client(
    *,
    model: str,
    temperature: float = 0.0,
    base_url: str = "http://127.0.0.1:1234/v1",
    api_key: Optional[str] = None,
    client: Any | None = None,
    default_kwargs: Optional[Dict[str, Any]] = None,
    request_timeout: Optional[float] = None,
    headers: Optional[Dict[str, str]] = None,
) -> LLMClient:
    """Create an LLMClient backed by an OpenAI-compatible chat completions API."""

    http_client = client or _default_httpx_client(base_url=base_url, api_key=api_key, headers=headers)
    kwargs = default_kwargs.copy() if default_kwargs else {}

    def _call(*, node, prompt: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:  # type: ignore[override]
        messages = _prompt_to_messages(prompt)
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        payload.update(kwargs)

        request_kwargs: Dict[str, Any] = {"json": payload}
        effective_timeout = timeout if timeout is not None else request_timeout
        if effective_timeout is not None:
            request_kwargs["timeout"] = effective_timeout

        response = http_client.post("/chat/completions", **request_kwargs)
        response.raise_for_status()
        data = response.json()
        content = _extract_message_content(data)
        return {
            "status": response.status_code,
            "json": data,
            "text": content,
            "items": None,
            "result": content,
            "error": None,
        }

    return LLMClient(call=log_llm("openai_compatible", model)(_call))


def _default_httpx_client(
    *,
    base_url: str,
    api_key: Optional[str],
    headers: Optional[Dict[str, str]],
) -> Any:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - import guard
        raise OpenAICompatibleUnavailable("httpx package is required for OpenAI-compatible providers") from exc

    merged_headers: Dict[str, str] = {}
    if headers:
        merged_headers.update(headers)
    if api_key:
        merged_headers.setdefault("Authorization", f"Bearer {api_key}")

    return httpx.Client(base_url=base_url, headers=merged_headers or None)


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
    choices = None
    if isinstance(response, dict):
        choices = response.get("choices")
    if not choices:
        return None

    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    if not message:
        return None
    content = message.get("content") if isinstance(message, dict) else None
    return str(content) if content is not None else None
