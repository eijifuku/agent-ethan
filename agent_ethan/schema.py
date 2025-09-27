"""Pydantic models that validate the YAML agent configuration."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, PositiveInt, ValidationError, field_validator, model_validator


class RetryConfig(BaseModel):
    """Retry policy for nodes, tools, or defaults."""

    max_attempts: PositiveInt = Field(default=1, alias="max_attempts")
    backoff: float = Field(default=1.0, ge=0.0)


class TimeoutConfig(BaseModel):
    """Timeout expressed in seconds."""

    seconds: float = Field(..., gt=0.0)


class DefaultsConfig(BaseModel):
    """Defaults applied across nodes unless overridden."""

    llm: Optional[str] = None
    temp: float = Field(default=0.3, ge=0.0)
    retry: Optional[RetryConfig] = None
    timeout: Optional[TimeoutConfig] = None


class MemoryConfig(BaseModel):
    """Conversation memory configuration."""

    enabled: bool = False
    type: Literal["langchain_history"] = "langchain_history"
    kind: Literal["inmemory", "redis", "sqlite", "postgres", "file", "custom"] = "inmemory"
    dsn: Optional[str] = None
    table: Optional[str] = None
    path: Optional[str] = None
    namespace: Optional[str] = None
    k: Optional[PositiveInt] = None
    session_key: str = Field(default="session_id")
    config: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_backend(self) -> "MemoryConfig":
        if not self.enabled:
            return self

        if self.kind == "file" and not self.path:
            raise ValueError("memory.kind 'file' requires 'path'")
        if self.kind in {"redis", "sqlite", "postgres"} and not self.dsn:
            raise ValueError(f"memory.kind '{self.kind}' requires 'dsn'")
        if self.kind == "custom" and not self.config:
            raise ValueError("memory.kind 'custom' requires 'config' with implementation details")
        return self


class MetaConfig(BaseModel):
    """Top-level metadata for the agent."""

    schema_version: PositiveInt = Field(default=1, alias="schema_version")
    name: str
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    providers: Dict[str, Any] = Field(default_factory=dict)


class StateConfig(BaseModel):
    """State schema and merge strategy."""

    shape: Dict[str, Any]
    reducer: Literal["deepmerge", "replace"] = "deepmerge"
    init: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("shape")
    @classmethod
    def ensure_shape_keys(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if not value:
            raise ValueError("state.shape must define at least one field")
        return value

    @model_validator(mode="after")
    def validate_init_subset(self) -> "StateConfig":
        undefined = set(self.init) - set(self.shape)
        if undefined:
            raise ValueError(f"state.init keys {sorted(undefined)} are not present in state.shape")
        return self


class PromptTemplate(BaseModel):
    """A prompt template referencing named partials."""

    system: Optional[str] = None
    user: Optional[str] = None
    assistant: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None

    @model_validator(mode="after")
    def ensure_content(self) -> "PromptTemplate":
        if not any([self.system, self.user, self.assistant, self.messages]):
            raise ValueError("prompt template must define at least one message field")
        return self


class PromptsConfig(BaseModel):
    """Prompt partials and templates."""

    partials: Dict[str, str] = Field(default_factory=dict)
    templates: Dict[str, PromptTemplate]

    @field_validator("templates")
    @classmethod
    def ensure_templates(cls, value: Dict[str, PromptTemplate]) -> Dict[str, PromptTemplate]:
        if not value:
            raise ValueError("prompts.templates must define at least one template")
        return value


class ToolConfig(BaseModel):
    """Tool declaration referencing an implementation callable or class."""

    id: str
    kind: Literal["mcp", "http", "python", "subgraph", "langchain"]
    impl: str
    mode: Literal["callable", "class"] = "callable"
    config: Dict[str, Any] = Field(default_factory=dict)
    retry: Optional[RetryConfig] = None
    timeout: Optional[TimeoutConfig] = None

    @model_validator(mode="after")
    def validate_mode(self) -> "ToolConfig":
        if self.kind == "langchain" and self.mode != "class":
            raise ValueError("langchain tools must set mode to 'class'")
        if self.mode == "class" and self.kind not in {"python", "langchain"}:
            raise ValueError("mode 'class' is supported only for python or langchain tools")
        return self


class MapOperation(BaseModel):
    """State mutation expressed as set/merge/delete directives."""

    set: Dict[str, Any] = Field(default_factory=dict)
    merge: Dict[str, Any] = Field(default_factory=dict)
    delete: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_payload(self) -> "MapOperation":
        if not any([self.set, self.merge, self.delete]):
            raise ValueError("map operation must define at least one of set/merge/delete")
        return self


class OnErrorTransition(BaseModel):
    """Fallback node or termination directive when an error occurs."""

    to: Optional[str] = None
    resume: bool = False

    @model_validator(mode="after")
    def validate_choice(self) -> "OnErrorTransition":
        if not self.to and not self.resume:
            raise ValueError("on_error must set 'to' or 'resume'")
        return self


class BaseNode(BaseModel):
    """Common fields shared by all graph nodes."""

    id: str
    type: Literal["tool", "llm", "router", "loop", "subgraph", "noop"]
    name: Optional[str] = None
    description: Optional[str] = None
    retry: Optional[RetryConfig] = None
    timeout: Optional[TimeoutConfig] = None
    on_error: Optional[OnErrorTransition] = None


class ToolNode(BaseNode):
    type: Literal["tool"] = "tool"
    uses: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    map: Optional[MapOperation] = None


class LLMNode(BaseNode):
    type: Literal["llm"] = "llm"
    prompt: str
    map: Optional[MapOperation] = None


class RouterCase(BaseModel):
    """Single routing path described via JsonLogic expression."""

    when: Dict[str, Any]
    to: str


class RouterNode(BaseNode):
    type: Literal["router"] = "router"
    cases: List[RouterCase]
    default: Optional[str] = None

    @field_validator("cases")
    @classmethod
    def ensure_cases(cls, value: List[RouterCase]) -> List[RouterCase]:
        if not value:
            raise ValueError("router node requires at least one case")
        return value


class LoopNode(BaseNode):
    type: Literal["loop"] = "loop"
    body: str
    until: Optional[Dict[str, Any]] = None
    max_iterations: PositiveInt = Field(default=10)


class SubgraphNode(BaseNode):
    type: Literal["subgraph"] = "subgraph"
    graph: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    map: Optional[MapOperation] = None


class NoopNode(BaseNode):
    type: Literal["noop"] = "noop"
    map: Optional[MapOperation] = None


GraphNode = ToolNode | LLMNode | RouterNode | LoopNode | SubgraphNode | NoopNode


class GraphEdge(BaseModel):
    """Edge connecting nodes, optionally guarded by JsonLogic condition."""

    from_: str = Field(alias="from")
    to: str
    when: Optional[Dict[str, Any]] = None


class GraphConfig(BaseModel):
    """Graph inputs/outputs and node connectivity."""

    inputs: List[str]
    outputs: List[str]
    nodes: List[GraphNode]
    edges: List[GraphEdge] = Field(default_factory=list)
    max_steps: PositiveInt = Field(default=200)
    timeout: Optional[TimeoutConfig] = None

    @field_validator("inputs", "outputs")
    @classmethod
    def ensure_non_empty(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("graph inputs/outputs must not be empty")
        return value

    @model_validator(mode="after")
    def validate_graph(self) -> "GraphConfig":
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("graph node ids must be unique")
        for edge in self.edges:
            if edge.from_ not in node_ids:
                raise ValueError(f"edge.from references unknown node '{edge.from_}'")
            if edge.to not in node_ids:
                raise ValueError(f"edge.to references unknown node '{edge.to}'")
        return self


class AgentConfig(BaseModel):
    """Root configuration object."""

    meta: MetaConfig
    state: StateConfig
    prompts: PromptsConfig
    memory: Optional[MemoryConfig] = None
    tools: List[ToolConfig] = Field(default_factory=list)
    graph: GraphConfig
    subgraphs: Dict[str, GraphConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ensure_tool_references(self) -> "AgentConfig":
        tool_ids = {tool.id for tool in self.tools}
        graphs = {"__root__": self.graph, **self.subgraphs}

        for name, graph in graphs.items():
            for node in graph.nodes:
                if isinstance(node, ToolNode) and node.uses not in tool_ids:
                    raise ValueError(
                        f"tool node '{node.id}' in graph '{name}' references unknown tool '{node.uses}'"
                    )
                if isinstance(node, SubgraphNode) and node.graph not in self.subgraphs:
                    raise ValueError(
                        f"subgraph node '{node.id}' references undefined graph '{node.graph}'"
                    )
        return self


def load_config(data: Dict[str, Any]) -> AgentConfig:
    """Parse a raw dict (typically loaded from YAML) into an AgentConfig."""

    try:
        return AgentConfig.model_validate(data)
    except ValidationError as exc:  # pragma: no cover - sanity envelope
        raise ValueError(str(exc)) from exc
