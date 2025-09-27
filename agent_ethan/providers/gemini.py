"""Google Gemini provider adapter for Agent Ethan."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..llm import LLMClient
from ..logging.decorators import log_llm


class GeminiProviderUnavailable(RuntimeError):
    """Raised when google-generativeai is missing and no client is supplied."""


def create_gemini_client(
    *,
    model: str,
    api_key: str,
    temperature: float = 0.0,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    client: Any | None = None,
    default_kwargs: Optional[Dict[str, Any]] = None,
) -> LLMClient:
    """Create an `LLMClient` backed by Google Gemini (Generative AI)."""

    default_params = default_kwargs.copy() if default_kwargs else {}

    if client is None:
        try:
            import google.generativeai as genai
        except ImportError as exc:  # pragma: no cover - import guard
            raise GeminiProviderUnavailable(
                "google-generativeai package is required for Gemini provider"
            ) from exc

        genai.configure(api_key=api_key)
        generation_config: Dict[str, Any] = {"temperature": temperature}
        if top_p is not None:
            generation_config["top_p"] = top_p
        if top_k is not None:
            generation_config["top_k"] = top_k
        generation_config.update(default_params)
        client = genai.GenerativeModel(model, generation_config=generation_config)

    def _call(*, node, prompt: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:  # type: ignore[override]
        messages = _prompt_to_parts(prompt)
        response = client.generate_content(messages, request_options={"timeout": timeout})
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

    return LLMClient(call=log_llm("gemini", model)(_call))


def _prompt_to_parts(prompt: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []

    def _push(role: str, content: Optional[str]) -> None:
        if content:
            messages.append({"role": role, "parts": [{"text": str(content)}]})

    _push("system", prompt.get("system"))
    _push("user", prompt.get("user"))
    _push("model", prompt.get("assistant"))

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
            mapped_role = "model" if role == "assistant" else role
            _push(mapped_role, content)

    if not messages:
        _push("user", "")
    return messages


def _extract_text(response: Any) -> Optional[str]:
    if response is None:
        return None
    text = getattr(response, "text", None)
    if text:
        return str(text)
    candidates = getattr(response, "candidates", None)
    if not candidates:
        return None
    first = candidates[0]
    if isinstance(first, dict):
        content = first.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
    else:
        content = getattr(first, "content", None)
        parts = getattr(content, "parts", None)
    if not parts:
        return None
    for part in parts:
        text = part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
        if text:
            return str(text)
    return None


def _to_serializable(response: Any) -> Any:
    if response is None:
        return None
    if hasattr(response, "to_dict"):
        try:
            return response.to_dict()
        except Exception:  # pragma: no cover - fallback for unexpected responses
            pass
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump()
        except Exception:  # pragma: no cover
            pass
    return response

