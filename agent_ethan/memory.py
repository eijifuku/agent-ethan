"""LangChain-backed conversation memory adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ChatMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from .schema import MemoryConfig


class MemoryAdapterError(RuntimeError):
    """Raised when the memory adapter cannot initialise."""


@dataclass
class MemorySession:
    """Stateful conversation session that bridges runtime state and history."""

    history: BaseChatMessageHistory
    state_key: str = "messages"
    window_key: str = "messages_window"
    k: Optional[int] = None
    initial_count: int = 0

    def prepare_state(self, state: Dict[str, Any]) -> None:
        """Populate runtime state with messages loaded from history."""

        history_payload = [_message_to_state(entry) for entry in self.history.messages]
        self.initial_count = len(history_payload)

        existing = state.get(self.state_key)
        if existing is None:
            combined: List[Dict[str, Any]] = history_payload
        else:
            if not isinstance(existing, list):
                raise MemoryAdapterError(
                    f"state['{self.state_key}'] must be a list when memory is enabled"
                )
            combined = history_payload + [item for item in existing]

        state[self.state_key] = combined
        if self.k:
            state[self.window_key] = combined[-self.k :]
        else:
            state.pop(self.window_key, None)

    def persist_state(self, state: Dict[str, Any]) -> None:
        """Persist new messages appended to the runtime state back to history."""

        messages = state.get(self.state_key, [])
        if not isinstance(messages, list):
            raise MemoryAdapterError(
                f"state['{self.state_key}'] must be a list when memory is enabled"
            )

        if len(messages) <= self.initial_count:
            return

        new_entries = messages[self.initial_count :]
        new_messages = _state_to_messages(new_entries)
        for message in new_messages:
            self.history.add_message(message)

        if self.k:
            state[self.window_key] = messages[-self.k :]


@dataclass
class ConversationMemory:
    """Factory that materialises LangChain chat histories per runtime run."""

    config: MemoryConfig
    base_path: Path
    state_key: str = "messages"
    window_key: str = "messages_window"
    _sessions: Dict[str, InMemoryChatMessageHistory] = field(default_factory=dict)

    def start_session(self, state: Dict[str, Any], inputs: Dict[str, Any]) -> MemorySession:
        """Prepare a session-specific chat history and prime the runtime state."""

        session_id, storage_id = self._resolve_session_id(state, inputs)
        history = self._resolve_history(storage_id, inputs, state)

        if self.config.session_key not in state:
            state[self.config.session_key] = session_id

        session = MemorySession(history=history, state_key=self.state_key, window_key=self.window_key, k=self.config.k)
        session.prepare_state(state)
        return session

    # ------------------------------------------------------------------
    # History resolution helpers
    # ------------------------------------------------------------------

    def _resolve_session_id(self, state: Dict[str, Any], inputs: Dict[str, Any]) -> Tuple[str, str]:
        key = self.config.session_key
        raw = inputs.get(key, state.get(key, "default"))
        session_id = str(raw)
        if self.config.namespace:
            storage_id = f"{self.config.namespace}:{session_id}"
        else:
            storage_id = session_id
        return session_id, storage_id

    def _resolve_history(
        self,
        storage_id: str,
        inputs: Dict[str, Any],
        state: Dict[str, Any],
    ) -> BaseChatMessageHistory:
        kind = self.config.kind

        if kind == "inmemory":
            return self._sessions.setdefault(storage_id, InMemoryChatMessageHistory())

        if kind == "file":
            path_template = self.config.path
            if not path_template:
                raise MemoryAdapterError("memory.path is required for kind 'file'")
            path = self._format_path(path_template, storage_id, inputs, state)
            path.parent.mkdir(parents=True, exist_ok=True)
            return _import_file_history()(path.as_posix())

        if kind == "redis":
            factory = _import_redis_history()
            url = self.config.dsn
            if not url:
                raise MemoryAdapterError("memory.dsn is required for kind 'redis'")
            return factory(session_id=storage_id, url=url, key_prefix=self.config.namespace or "message_store")

        if kind == "sqlite":
            factory = _import_sql_history()
            dsn = self.config.dsn
            if not dsn:
                raise MemoryAdapterError("memory.dsn is required for kind 'sqlite'")
            table_name = self.config.table or "langchain_chat_history"
            return factory(session_id=storage_id, connection_string=dsn, table_name=table_name)

        if kind == "postgres":
            factory = _import_postgres_history()
            dsn = self.config.dsn
            if not dsn:
                raise MemoryAdapterError("memory.dsn is required for kind 'postgres'")
            table_name = self.config.table or "langchain_pg_chat_history"
            schema = self.config.config.get("schema") if self.config.config else None
            return factory(connection_string=dsn, session_id=storage_id, table_name=table_name, schema=schema)

        if kind == "custom":
            impl_path = self.config.config.get("impl") if self.config.config else None
            if not impl_path:
                raise MemoryAdapterError("memory.config.impl is required for kind 'custom'")
            history_cls = _resolve_custom_history(impl_path, self.base_path)
            return history_cls(config=self.config.config, storage_id=storage_id, inputs=inputs, state=state)

        raise MemoryAdapterError(f"unsupported memory.kind '{kind}'")

    def _format_path(
        self,
        template: str,
        storage_id: str,
        inputs: Dict[str, Any],
        state: Dict[str, Any],
    ) -> Path:
        context: Dict[str, Any] = {
            "session_id": storage_id,
            "namespace": self.config.namespace or "",
        }
        for source in (inputs, state):
            for key, value in source.items():
                if isinstance(value, (str, int, float)):
                    context.setdefault(key, value)
        try:
            formatted = template.format(**context)
        except KeyError as exc:
            raise MemoryAdapterError(f"missing placeholder {exc} in memory.path template '{template}'") from exc
        except Exception as exc:  # pragma: no cover - defensive guard
            raise MemoryAdapterError(f"failed to format memory.path '{template}': {exc}") from exc

        resolved = Path(formatted)
        if not resolved.is_absolute():
            resolved = (self.base_path / resolved).resolve()
        return resolved


# ----------------------------------------------------------------------
# Message conversion helpers
# ----------------------------------------------------------------------

def _message_to_state(message: BaseMessage) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "type": message.type,
        "role": _role_alias(message),
        "content": message.content,
    }
    name = getattr(message, "name", None)
    if name:
        payload["name"] = name
    additional_kwargs = getattr(message, "additional_kwargs", None)
    if additional_kwargs:
        payload["additional_kwargs"] = additional_kwargs
    response_metadata = getattr(message, "response_metadata", None)
    if response_metadata:
        payload["response_metadata"] = response_metadata
    if isinstance(message, ToolMessage):
        payload["tool_call_id"] = message.tool_call_id
    if isinstance(message, AIMessage):
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = tool_calls
    return payload


def _state_to_messages(entries: Iterable[Dict[str, Any]]) -> List[BaseMessage]:
    messages: List[BaseMessage] = []
    for entry in entries:
        message = _entry_to_message(entry)
        if message:
            messages.append(message)
    return messages


def _entry_to_message(entry: Dict[str, Any]) -> Optional[BaseMessage]:
    role = (entry.get("role") or entry.get("type") or "").lower()
    content = entry.get("content")
    additional_kwargs = entry.get("additional_kwargs") or {}
    response_metadata = entry.get("response_metadata") or {}
    name = entry.get("name")

    if role in {"user", "human"}:
        return HumanMessage(content=content, additional_kwargs=additional_kwargs, name=name, response_metadata=response_metadata)
    if role in {"assistant", "ai"}:
        params: Dict[str, Any] = {
            "content": content,
            "additional_kwargs": additional_kwargs,
            "name": name,
        }
        if response_metadata:
            params["response_metadata"] = response_metadata
        tool_calls = entry.get("tool_calls")
        if tool_calls is not None:
            params["tool_calls"] = tool_calls
        return AIMessage(**params)
    if role == "system":
        return SystemMessage(content=content, additional_kwargs=additional_kwargs, name=name, response_metadata=response_metadata)
    if role == "tool":
        tool_call_id = entry.get("tool_call_id") or entry.get("id") or ""
        return ToolMessage(content=content, tool_call_id=tool_call_id, additional_kwargs=additional_kwargs)
    if role == "function":
        return FunctionMessage(content=content, name=name or entry.get("function_name"), additional_kwargs=additional_kwargs)
    if role:
        return ChatMessage(role=role, content=content, additional_kwargs=additional_kwargs)
    return None


def _role_alias(message: BaseMessage) -> str:
    """Map LangChain message type to a conversational role."""

    mapping = {
        "human": "user",
        "ai": "assistant",
        "chat": getattr(message, "role", "assistant"),
        "system": "system",
        "tool": "tool",
        "function": "function",
    }
    return mapping.get(message.type, getattr(message, "role", message.type))


# ----------------------------------------------------------------------
# Optional imports with user-friendly errors
# ----------------------------------------------------------------------

def _import_file_history():
    try:
        from langchain_community.chat_message_histories import FileChatMessageHistory
    except ImportError as exc:  # pragma: no cover - depends on optional dependency
        raise MemoryAdapterError(
            "FileChatMessageHistory requires 'langchain-community' to be installed"
        ) from exc
    return FileChatMessageHistory


def _import_redis_history():
    try:
        from langchain_community.chat_message_histories import RedisChatMessageHistory
    except ImportError as exc:  # pragma: no cover - depends on optional dependency
        raise MemoryAdapterError(
            "RedisChatMessageHistory requires 'langchain-community' to be installed"
        ) from exc
    return RedisChatMessageHistory


def _import_sql_history():
    try:
        from langchain_community.chat_message_histories import SQLChatMessageHistory
    except ImportError as exc:  # pragma: no cover - depends on optional dependency
        raise MemoryAdapterError(
            "SQLChatMessageHistory requires 'langchain-community' to be installed"
        ) from exc
    return SQLChatMessageHistory


def _import_postgres_history():
    try:
        from langchain_community.chat_message_histories import PostgresChatMessageHistory
    except ImportError as exc:  # pragma: no cover - depends on optional dependency
        raise MemoryAdapterError(
            "PostgresChatMessageHistory requires 'langchain-community' to be installed"
        ) from exc
    return PostgresChatMessageHistory


def _resolve_custom_history(impl_path: str, base_path: Path):
    if "#" in impl_path:
        module_path, symbol_name = impl_path.split("#", 1)
    else:
        module_path, symbol_name = impl_path, "create_history"
    if module_path.startswith("."):
        module_path = str((base_path / module_path).resolve())

    module = _import_module_from_path(module_path)
    try:
        symbol = getattr(module, symbol_name)
    except AttributeError as exc:
        raise MemoryAdapterError(f"custom memory implementation '{impl_path}' not found") from exc
    return symbol


def _import_module_from_path(path: str):
    from importlib import import_module
    from importlib.util import module_from_spec, spec_from_file_location

    if path.endswith(".py") or path.endswith(".pyc"):
        spec = spec_from_file_location("custom_memory", path)
        if spec is None or spec.loader is None:
            raise MemoryAdapterError(f"cannot load custom memory module from '{path}'")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return import_module(path)
