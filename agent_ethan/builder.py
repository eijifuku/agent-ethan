"""Build and execute an agent runtime from a validated YAML configuration."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import re
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Deque, Dict, List, Match, Optional, Tuple

import yaml
from jinja2 import Environment, StrictUndefined

from .llm import LLMClient, RetryPolicy
from .memory import ConversationMemory, MemoryAdapterError, MemorySession
from .providers import (
    create_claude_client,
    create_gemini_client,
    create_openai_client,
    create_openai_compatible_client,
)
from .schema import (
    AgentConfig,
    GraphConfig,
    GraphEdge,
    GraphNode,
    LLMNode,
    LoopNode,
    MapOperation,
    NoopNode,
    RetryConfig,
    RouterNode,
    SubgraphNode,
    TimeoutConfig,
    ToolConfig,
    ToolNode,
    load_config,
)


DEFAULT_MAX_SUBGRAPH_DEPTH = 8
ENV_PATTERN = re.compile(r"^{{\s*env\.([A-Z0-9_]+)\s*}}$")


class AgentRuntimeError(RuntimeError):
    """Raised when the runtime encounters an unrecoverable condition."""


class NodeExecutionError(RuntimeError):
    """Raised when a node fails and no on_error strategy applies."""


@dataclass
class ToolHandle:
    """Resolved tool callable paired with its configuration."""

    id: str
    kind: str
    callable: Callable[..., Any]
    config: Dict[str, Any]
    retry: Optional[RetryConfig] = None
    timeout: Optional[TimeoutConfig] = None


@dataclass
class GraphDefinition:
    """Container for nodes and edges ready for execution."""

    name: str
    nodes: Dict[str, GraphNode]
    edges: List[GraphEdge]
    inputs: List[str]
    outputs: List[str]
    max_steps: int
    timeout_seconds: Optional[float]
    edges_by_source: Dict[str, List[GraphEdge]]
    entry_nodes: List[str]


@dataclass
class AgentDefinition:
    """Combined configuration and derived artifacts."""

    config: AgentConfig
    base_path: Path


@dataclass
class PromptRenderer:
    """Jinja-backed renderer with partial support and expression helpers."""

    env: Environment
    templates: Dict[str, Dict[str, str]]
    partials: Dict[str, str]

    def render(self, name: str, role: str, context: Dict[str, Any]) -> str:
        try:
            template_payload = self.templates[name]
        except KeyError as exc:
            raise KeyError(f"prompt template '{name}' is not defined") from exc
        try:
            source = template_payload[role]
        except KeyError as exc:
            raise KeyError(f"prompt template '{name}' does not define role '{role}'") from exc
        return self.render_string(source, context)

    def render_string(self, source: str, context: Dict[str, Any]) -> str:
        return self._render_source(source, context)

    def evaluate(self, expression: str, context: Dict[str, Any]) -> Any:
        compiled = self.env.compile_expression(expression)
        return compiled(**context, partial=self._partial_factory(context))

    def _render_source(self, source: str, context: Dict[str, Any]) -> str:
        template = self.env.from_string(_inject_partials(source))
        return template.render(**context, partial=self._partial_factory(context))

    def _partial_factory(self, ctx: Dict[str, Any]) -> Callable[[str, Optional[Dict[str, Any]]], str]:
        def _render_partial(name: str, override: Optional[Dict[str, Any]] = None) -> str:
            try:
                source = self.partials[name]
            except KeyError as exc:
                raise KeyError(f"prompt partial '{name}' is not defined") from exc
            merged_context = {**ctx, **(override or {})}
            return self._render_source(source, merged_context)

        return _render_partial


@dataclass
class AgentRuntime:
    """Executable agent artifacts with a run method."""

    definition: AgentDefinition
    prompts: PromptRenderer
    tools: Dict[str, ToolHandle]
    graph: GraphDefinition
    subgraphs: Dict[str, GraphDefinition]
    memory: Optional[ConversationMemory] = None
    _active_step_count: int = field(init=False, default=0)
    _active_max_steps: int = field(init=False, default=0)
    _max_subgraph_depth: int = field(init=False, default=DEFAULT_MAX_SUBGRAPH_DEPTH)

    _EXPRESSION_PATTERN: re.Pattern[str] = re.compile(r"^\s*{{\s*(.+?)\s*}}\s*$")

    def run(
        self,
        inputs: Dict[str, Any],
        *,
        llm_client: Optional[LLMClient] = None,
        llm_callable: Optional[Callable[[LLMNode, Dict[str, Any]], Dict[str, Any]]] = None,
        tool_overrides: Optional[Dict[str, Callable[..., Any]]] = None,
        max_steps: Optional[int] = None,
        max_subgraph_depth: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute the graph from its entry nodes with the provided input state."""

        resolved_llm_client = self._resolve_llm_client(llm_client, llm_callable)
        state = self._initial_state(self.graph, inputs)
        self._active_step_count = 0
        self._active_max_steps = max_steps or self.graph.max_steps
        overrides = tool_overrides or {}
        self._max_subgraph_depth = (
            max_subgraph_depth if max_subgraph_depth is not None else DEFAULT_MAX_SUBGRAPH_DEPTH
        )

        memory_session: Optional[MemorySession] = None
        if self.memory and self.memory.config.enabled:
            memory_session = self.memory.start_session(state, inputs)

        self._run_graph(
            graph=self.graph,
            state=state,
            inputs=dict(inputs),
            llm_client=resolved_llm_client,
            tool_overrides=overrides,
            graph_name=self.graph.name,
            depth=0,
        )

        if memory_session:
            memory_session.persist_state(state)
        return state

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def _run_graph(
        self,
        graph: GraphDefinition,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        llm_client: Optional[LLMClient],
        tool_overrides: Dict[str, Callable[..., Any]],
        graph_name: str,
        depth: int,
    ) -> None:
        if depth > self._max_subgraph_depth:
            raise AgentRuntimeError(
                f"max subgraph depth {self._max_subgraph_depth} exceeded while entering graph '{graph_name}'"
            )
        queue: Deque[str] = deque(graph.entry_nodes)
        if not queue:
            raise AgentRuntimeError(f"graph '{graph_name}' has no entry nodes to execute")

        while queue:
            node_id = queue.popleft()
            node = graph.nodes[node_id]

            self._active_step_count += 1
            if self._active_step_count > self._active_max_steps:
                raise AgentRuntimeError(f"max_steps exceeded ({self._active_max_steps})")

            try:
                success, output, next_nodes = self._execute_node(
                    graph=graph,
                    node=node,
                    state=state,
                    inputs=inputs,
                    llm_client=llm_client,
                    tool_overrides=tool_overrides,
                    depth=depth,
                )
            except (AgentRuntimeError, NodeExecutionError):
                raise
            except Exception as exc:  # pragma: no cover - safety net
                success = False
                output = {"exception": exc}
                next_nodes = []

            if success:
                queue.extend(next_nodes)
                continue

            next_from_error = self._handle_error(graph, node, state, inputs, output)
            queue.extendleft(reversed(next_from_error))

    # ------------------------------------------------------------------
    # Node execution helpers
    # ------------------------------------------------------------------

    def _execute_node(
        self,
        graph: GraphDefinition,
        node: GraphNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        llm_client: Optional[LLMClient],
        tool_overrides: Dict[str, Callable[..., Any]],
        depth: int,
        traverse_edges: bool = True,
    ) -> tuple[bool, Optional[Dict[str, Any]], List[str]]:
        if isinstance(node, ToolNode):
            return self._execute_tool_node(graph, node, state, inputs, tool_overrides, traverse_edges)
        if isinstance(node, LLMNode):
            return self._execute_llm_node(graph, node, state, inputs, llm_client, traverse_edges)
        if isinstance(node, RouterNode):
            return self._execute_router_node(graph, node, state, inputs, traverse_edges)
        if isinstance(node, LoopNode):
            return self._execute_loop_node(
                graph,
                node,
                state,
                inputs,
                llm_client,
                tool_overrides,
                depth,
                traverse_edges,
            )
        if isinstance(node, SubgraphNode):
            return self._execute_subgraph_node(
                graph,
                node,
                state,
                inputs,
                llm_client,
                tool_overrides,
                depth,
                traverse_edges,
            )
        if isinstance(node, NoopNode):
            return self._execute_noop_node(graph, node, state, inputs, traverse_edges)
        raise AgentRuntimeError(f"unsupported node type '{node.type}'")

    def _execute_tool_node(
        self,
        graph: GraphDefinition,
        node: ToolNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        tool_overrides: Dict[str, Callable[..., Any]],
        traverse_edges: bool,
    ) -> tuple[bool, Dict[str, Any], List[str]]:
        try:
            handle = self.tools[node.uses]
        except KeyError as exc:
            raise AgentRuntimeError(f"tool '{node.uses}' not registered") from exc

        tool_callable = tool_overrides.get(handle.id, handle.callable)
        rendered_inputs = self._render_structure(node.inputs, state, inputs, result=None)
        payload = {**handle.config, **rendered_inputs}

        timeout_seconds = self._resolve_timeout(node.timeout, handle.timeout)
        if timeout_seconds is not None and "timeout" not in payload:
            payload["timeout"] = timeout_seconds

        retry_config = self._select_retry(node.retry, handle.retry)
        retry_policy = self._to_retry_policy(retry_config)

        attempts = retry_policy.max_attempts if retry_policy else 1
        backoff = retry_policy.backoff if retry_policy else 0.0
        last_result: Optional[Dict[str, Any]] = None
        last_exception: Optional[BaseException] = None

        for attempt in range(1, attempts + 1):
            try:
                result = tool_callable(**payload)
            except Exception as exc:  # pragma: no cover - delegated to on_error
                last_exception = exc
                if attempt == attempts:
                    return False, {"exception": exc}, []
            else:
                last_result = result
                if not result.get("error"):
                    self._apply_map(node.map, state, inputs, result)
                    next_nodes = self._edge_targets(graph, node, state, inputs, result) if traverse_edges else []
                    return True, result, next_nodes
                if attempt == attempts:
                    return False, result, []
            if backoff:
                time.sleep(backoff)

        if last_exception is not None:
            return False, {"exception": last_exception}, []
        return False, last_result or {}, []

    def _execute_llm_node(
        self,
        graph: GraphDefinition,
        node: LLMNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        llm_client: Optional[LLMClient],
        traverse_edges: bool,
    ) -> tuple[bool, Dict[str, Any], List[str]]:
        if llm_client is None:
            raise AgentRuntimeError(f"llm node '{node.id}' requires llm_client or llm_callable")

        template_payload = self.prompts.templates[node.prompt]
        prompt_context = self._render_context(state, inputs, result=None)
        rendered_prompt = {
            role: self.prompts.render(node.prompt, role, prompt_context)
            for role in template_payload
        }

        retry_policy = self._to_retry_policy(self._select_retry(node.retry, None))
        timeout_seconds = self._resolve_timeout(node.timeout, None)

        try:
            result = llm_client.generate(
                node,
                rendered_prompt,
                retry=retry_policy,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pragma: no cover - delegated to on_error
            return False, {"exception": exc}, []

        success = not result.get("error")
        if success:
            self._apply_map(node.map, state, inputs, result)
        next_nodes = self._edge_targets(graph, node, state, inputs, result) if traverse_edges else []
        return success, result, next_nodes

    def _execute_router_node(
        self,
        graph: GraphDefinition,
        node: RouterNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        traverse_edges: bool,
    ) -> tuple[bool, Dict[str, Any], List[str]]:
        context = self._condition_context(state, inputs, None, node)
        targets: List[str] = []
        for case in node.cases:
            if self._evaluate_condition(case.when, context):
                targets.append(case.to)
        if not targets and node.default:
            targets.append(node.default)
        if not targets and traverse_edges:
            targets.extend(self._edge_targets(graph, node, state, inputs, None))
        return True, {"targets": targets}, targets

    def _execute_loop_node(
        self,
        graph: GraphDefinition,
        node: LoopNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        llm_client: Optional[LLMClient],
        tool_overrides: Dict[str, Callable[..., Any]],
        depth: int,
        traverse_edges: bool,
    ) -> tuple[bool, Optional[Dict[str, Any]], List[str]]:
        last_output: Optional[Dict[str, Any]] = None
        for _ in range(node.max_iterations):
            body_node = graph.nodes.get(node.body)
            if body_node is None:
                raise AgentRuntimeError(f"loop node '{node.id}' references unknown body '{node.body}'")
            success, output, _ = self._execute_node(
                graph=graph,
                node=body_node,
                state=state,
                inputs=inputs,
                llm_client=llm_client,
                tool_overrides=tool_overrides,
                depth=depth,
                traverse_edges=False,
            )
            if not success:
                return False, output, []
            last_output = output
            if node.until:
                context = self._condition_context(state, inputs, output, node)
                if self._evaluate_condition(node.until, context):
                    break
        else:
            raise AgentRuntimeError(f"loop node '{node.id}' exceeded max_iterations")

        next_nodes = self._edge_targets(graph, node, state, inputs, last_output) if traverse_edges else []
        return True, last_output, next_nodes

    def _execute_subgraph_node(
        self,
        graph: GraphDefinition,
        node: SubgraphNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        llm_client: Optional[LLMClient],
        tool_overrides: Dict[str, Callable[..., Any]],
        depth: int,
        traverse_edges: bool,
    ) -> tuple[bool, Optional[Dict[str, Any]], List[str]]:
        try:
            subgraph = self.subgraphs[node.graph]
        except KeyError as exc:
            raise AgentRuntimeError(f"subgraph '{node.graph}' not registered") from exc

        rendered_inputs = self._render_structure(node.inputs, state, inputs, result=None)
        sub_inputs_context = {**inputs, **rendered_inputs}
        sub_state = deepcopy(state)
        for key, value in rendered_inputs.items():
            sub_state[key] = value

        try:
            self._run_graph(
                graph=subgraph,
                state=sub_state,
                inputs=sub_inputs_context,
                llm_client=llm_client,
                tool_overrides=tool_overrides,
                graph_name=subgraph.name,
                depth=depth + 1,
            )
        except NodeExecutionError as exc:  # propagate to parent handlers
            return False, {"exception": exc}, []

        merged_state = _deep_merge(state, sub_state)
        state.clear()
        state.update(merged_state)

        result_payload: Dict[str, Any] = {
            "state": sub_state,
            "outputs": {name: sub_state.get(name) for name in subgraph.outputs},
        }

        self._apply_map(node.map, state, sub_inputs_context, result_payload)
        next_nodes = (
            self._edge_targets(graph, node, state, sub_inputs_context, result_payload)
            if traverse_edges
            else []
        )
        return True, result_payload, next_nodes

    def _execute_noop_node(
        self,
        graph: GraphDefinition,
        node: NoopNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        traverse_edges: bool,
    ) -> tuple[bool, Dict[str, Any], List[str]]:
        payload: Dict[str, Any] = {}
        self._apply_map(node.map, state, inputs, payload)
        next_nodes = self._edge_targets(graph, node, state, inputs, payload) if traverse_edges else []
        return True, payload, next_nodes

    # ------------------------------------------------------------------
    # Support utilities
    # ------------------------------------------------------------------

    def _resolve_llm_client(
        self,
        provided: Optional[LLMClient],
        llm_callable: Optional[Callable[[LLMNode, Dict[str, Any]], Dict[str, Any]]],
    ) -> Optional[LLMClient]:
        if provided and llm_callable:
            raise ValueError("Specify either llm_client or llm_callable, not both")
        if provided:
            return provided
        if llm_callable is None:
            default_llm = self.definition.config.meta.defaults.llm
            if not default_llm:
                return None
            provider_id, _, model_hint = default_llm.partition(":")
            provider_id = provider_id or "openai"
            provider_settings = self.definition.config.meta.providers.get(provider_id)
            if provider_settings is None:
                return None
            return self._instantiate_llm_provider(provider_id, model_hint or None, provider_settings)

        def _adapter(*, node: LLMNode, prompt: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
            del timeout
            return llm_callable(node, prompt)

        return LLMClient(call=_adapter)

    def _instantiate_llm_provider(
        self,
        provider_id: str,
        model_hint: Optional[str],
        settings: Dict[str, Any],
    ) -> LLMClient:
        provider_type = settings.get("type", provider_id)
        resolved_settings = _resolve_env_placeholders(settings)
        defaults = self.definition.config.meta.defaults

        if provider_type == "openai":
            model = resolved_settings.get("model") or model_hint
            if not model:
                raise AgentRuntimeError(
                    f"provider '{provider_id}' requires a model hint via defaults.llm or providers.{provider_id}.model"
                )
            temperature = resolved_settings.get("temperature", defaults.temp)
            default_kwargs = resolved_settings.get("kwargs")
            client_kwargs = resolved_settings.get("client_kwargs")
            return create_openai_client(
                model=model,
                temperature=temperature,
                default_kwargs=default_kwargs,
                client_kwargs=client_kwargs,
            )

        if provider_type in {"lmstudio", "openai_compatible"}:
            model = resolved_settings.get("model") or model_hint
            if not model:
                raise AgentRuntimeError(
                    f"provider '{provider_id}' requires a model hint via defaults.llm or providers.{provider_id}.model"
                )
            temperature = resolved_settings.get("temperature", defaults.temp)
            default_kwargs = resolved_settings.get("kwargs")
            base_url = resolved_settings.get("base_url", "http://127.0.0.1:1234/v1")
            api_key = resolved_settings.get("api_key")
            request_timeout = resolved_settings.get("request_timeout")
            headers = resolved_settings.get("headers")
            return create_openai_compatible_client(
                model=model,
                temperature=temperature,
                base_url=base_url,
                api_key=api_key,
                default_kwargs=default_kwargs,
                request_timeout=request_timeout,
                headers=headers,
            )

        if provider_type == "gemini":
            model = resolved_settings.get("model") or model_hint
            if not model:
                raise AgentRuntimeError(
                    f"provider '{provider_id}' requires a model hint via defaults.llm or providers.{provider_id}.model"
                )
            api_key = resolved_settings.get("api_key")
            if not api_key:
                raise AgentRuntimeError(f"provider '{provider_id}' requires api_key")
            temperature = resolved_settings.get("temperature", defaults.temp)
            top_p = resolved_settings.get("top_p")
            top_k = resolved_settings.get("top_k")
            kwargs = resolved_settings.get("kwargs")
            return create_gemini_client(
                model=model,
                api_key=api_key,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                default_kwargs=kwargs,
            )

        if provider_type == "claude":
            model = resolved_settings.get("model") or model_hint
            if not model:
                raise AgentRuntimeError(
                    f"provider '{provider_id}' requires a model hint via defaults.llm or providers.{provider_id}.model"
                )
            api_key = resolved_settings.get("api_key")
            if not api_key:
                raise AgentRuntimeError(f"provider '{provider_id}' requires api_key")
            temperature = resolved_settings.get("temperature", defaults.temp)
            max_tokens = resolved_settings.get("max_tokens", 1024)
            kwargs = resolved_settings.get("kwargs")
            return create_claude_client(
                model=model,
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                default_kwargs=kwargs,
            )

        raise AgentRuntimeError(f"unsupported provider type '{provider_type}' for provider '{provider_id}'")

    def _initial_state(self, graph: GraphDefinition, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config_state = self.definition.config.state
        initial = deepcopy(config_state.init)
        for key in config_state.shape:
            initial.setdefault(key, None)

        provided: Dict[str, Any] = {}
        missing: List[str] = []
        for name in graph.inputs:
            if name not in inputs:
                missing.append(name)
            else:
                provided[name] = inputs[name]
        if missing:
            raise AgentRuntimeError(f"missing required inputs: {missing}")

        if config_state.reducer == "deepmerge":
            merged = _deep_merge(initial, provided)
        else:
            merged = {**initial, **provided}
        return merged

    def _render_structure(
        self,
        payload: Any,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> Any:
        if isinstance(payload, dict):
            return {
                key: self._render_structure(value, state, inputs, result)
                for key, value in payload.items()
            }
        if isinstance(payload, list):
            return [self._render_structure(item, state, inputs, result) for item in payload]
        if isinstance(payload, str):
            match = self._EXPRESSION_PATTERN.match(payload)
            context = self._render_context(state, inputs, result)
            if match:
                expression = match.group(1)
                return self.prompts.evaluate(expression, context)
            return self.prompts.render_string(payload, context)
        return payload

    def _render_context(
        self,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            **state,
            "state": state,
            "inputs": inputs,
            "output": result,
            "result": result,
        }

    def _apply_map(
        self,
        map_op: Optional[MapOperation],
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if map_op is None:
            return
        context = self._render_context(state, inputs, result)
        rendered_set = self._render_structure(map_op.set, state, inputs, result) if map_op.set else {}
        rendered_merge = self._render_structure(map_op.merge, state, inputs, result) if map_op.merge else {}
        rendered_delete = (
            [
                self.prompts.render_string(target, context) if isinstance(target, str) else target
                for target in map_op.delete
            ]
            if map_op.delete
            else []
        )

        for key, value in rendered_set.items():
            state[key] = value

        for key, fragment in rendered_merge.items():
            state[key] = _deep_merge(state.get(key), fragment)

        for key in rendered_delete:
            state.pop(key, None)

    def _edge_targets(
        self,
        graph: GraphDefinition,
        node: GraphNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        result: Optional[Dict[str, Any]],
    ) -> List[str]:
        targets: List[str] = []
        for edge in graph.edges_by_source.get(node.id, []):
            if edge.when:
                context = self._condition_context(state, inputs, result, node)
                if not self._evaluate_condition(edge.when, context):
                    continue
            targets.append(edge.to)
        return targets

    def _condition_context(
        self,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        result: Optional[Dict[str, Any]],
        node: GraphNode,
    ) -> Dict[str, Any]:
        return {
            "state": state,
            "inputs": inputs,
            "result": result,
            "output": result,
            "node": {"id": node.id, "type": node.type},
        }

    def _evaluate_condition(self, expression: Dict[str, Any], context: Dict[str, Any]) -> bool:
        try:
            outcome = _evaluate_json_logic(expression, context)
        except Exception as exc:  # pragma: no cover - invalid condition expression
            raise AgentRuntimeError(f"failed to evaluate condition {expression}: {exc}") from exc
        return bool(outcome)

    def _handle_error(
        self,
        graph: GraphDefinition,
        node: GraphNode,
        state: Dict[str, Any],
        inputs: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> List[str]:
        strategy = getattr(node, "on_error", None)
        if not strategy:
            details = self._format_failure_details(node, payload)
            message = f"node '{node.id}' failed without on_error handler"
            if details:
                message = f"{message}: {details}"
            raise NodeExecutionError(message)

        targets: List[str] = []
        if strategy.to:
            targets.append(strategy.to)
        if strategy.resume:
            targets.extend(self._edge_targets(graph, node, state, inputs, payload))
        return targets

    def _select_retry(
        self,
        node_retry: Optional[RetryConfig],
        fallback_retry: Optional[RetryConfig],
    ) -> Optional[RetryConfig]:
        if node_retry:
            return node_retry
        if fallback_retry:
            return fallback_retry
        return self.definition.config.meta.defaults.retry

    def _resolve_timeout(
        self,
        node_timeout: Optional[TimeoutConfig],
        fallback_timeout: Optional[TimeoutConfig],
    ) -> Optional[float]:
        timeout = node_timeout or fallback_timeout or self.definition.config.meta.defaults.timeout
        return timeout.seconds if timeout else None

    @staticmethod
    def _to_retry_policy(retry: Optional[RetryConfig]) -> Optional[RetryPolicy]:
        if retry is None:
            return None
        return RetryPolicy(max_attempts=retry.max_attempts, backoff=retry.backoff)

    @staticmethod
    def _format_failure_details(node: GraphNode, payload: Dict[str, Any]) -> str:
        details: List[str] = []
        details.append(f"type={node.type}")
        if hasattr(node, "prompt") and getattr(node, "prompt"):
            details.append(f"prompt={getattr(node, 'prompt')}")
        if hasattr(node, "uses") and getattr(node, "uses"):
            details.append(f"tool={getattr(node, 'uses')}")

        error_payload = payload.get("error") if isinstance(payload, dict) else None
        if error_payload:
            details.append(f"error={error_payload}")
        exception_payload = payload.get("exception") if isinstance(payload, dict) else None
        if exception_payload:
            details.append(f"exception={exception_payload}")

        return ", ".join(details)


_PARTIAL_PATTERN = re.compile(r"{{>\s*([a-zA-Z0-9_]+)\s*}}")


def build_agent_from_path(path: str | Path) -> AgentRuntime:
    """Load YAML configuration from a file path and compile it into a runtime."""

    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return build_agent_from_yaml(data, base_path=path.parent)


def build_agent_from_yaml(data: Dict[str, Any], base_path: str | Path | None = None) -> AgentRuntime:
    """Compile a Python dictionary (typically from YAML) into runtime artifacts."""

    base = Path(base_path or ".").resolve()
    config = load_config(data)
    definition = AgentDefinition(config=config, base_path=base)
    prompts = _build_prompt_renderer(config)
    tools = _build_tool_handles(config, base)
    memory = _build_memory_adapter(config, base)
    main_graph, subgraphs = _build_graphs(config)
    return AgentRuntime(
        definition=definition,
        prompts=prompts,
        tools=tools,
        graph=main_graph,
        subgraphs=subgraphs,
        memory=memory,
    )


def _build_prompt_renderer(config: AgentConfig) -> PromptRenderer:
    env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)
    templates: Dict[str, Dict[str, str]] = {}

    for name, template in config.prompts.templates.items():
        payload: Dict[str, str] = {}
        if template.system:
            payload["system"] = template.system
        if template.user:
            payload["user"] = template.user
        if template.assistant:
            payload["assistant"] = template.assistant
        if template.messages:
            for index, message in enumerate(template.messages):
                role = message.get("role")
                content = message.get("content")
                if not role or content is None:
                    raise ValueError(f"prompt template '{name}' messages[{index}] missing role/content")
                payload[f"messages[{index}]#{role}"] = content
        templates[name] = payload

    return PromptRenderer(env=env, templates=templates, partials=config.prompts.partials)


def _build_memory_adapter(config: AgentConfig, base_path: Path) -> Optional[ConversationMemory]:
    memory_config = config.memory
    if not memory_config or not memory_config.enabled:
        return None
    try:
        return ConversationMemory(config=memory_config, base_path=base_path)
    except MemoryAdapterError as exc:  # pragma: no cover - configuration error envelope
        raise AgentRuntimeError(str(exc)) from exc


def _inject_partials(source: str) -> str:
    """Replace custom partial syntax with a helper call."""

    def _replacement(match: Match[str]) -> str:
        name = match.group(1)
        return "{{ partial('" + name + "') }}"

    return _PARTIAL_PATTERN.sub(_replacement, source)


def _build_tool_handles(config: AgentConfig, base_path: Path) -> Dict[str, ToolHandle]:
    handles: Dict[str, ToolHandle] = {}
    for tool in config.tools:
        callable_obj, tool_defaults = _resolve_tool_callable(tool, base_path)
        handles[tool.id] = ToolHandle(
            id=tool.id,
            kind=tool.kind,
            callable=callable_obj,
            config=tool_defaults,
            retry=tool.retry,
            timeout=tool.timeout,
        )
    return handles


def _resolve_tool_callable(tool: ToolConfig, base_path: Path) -> Tuple[Callable[..., Any], Dict[str, Any]]:
    config_defaults = deepcopy(tool.config)

    if tool.mode == "class":
        if tool.kind == "langchain":
            return _resolve_langchain_tool(tool, base_path, config_defaults)
        return _resolve_python_class_tool(tool, base_path, config_defaults)

    callable_obj = _resolve_callable(tool.impl, base_path)
    return callable_obj, config_defaults


def _resolve_python_class_tool(
    tool: ToolConfig,
    base_path: Path,
    config_defaults: Dict[str, Any],
) -> Tuple[Callable[..., Any], Dict[str, Any]]:
    attr = _resolve_callable(tool.impl, base_path)
    if not inspect.isclass(attr):
        raise TypeError(f"tool '{tool.id}' mode 'class' requires a class reference")

    init_payload = config_defaults.pop("init", {})
    if not isinstance(init_payload, dict):
        raise TypeError(f"tool '{tool.id}' config.init must be a mapping when mode is 'class'")

    instance = attr(**init_payload)
    if not callable(instance):
        raise TypeError(f"tool '{tool.id}' instantiated object is not callable")

    return instance, config_defaults


def _resolve_langchain_tool(
    tool: ToolConfig,
    base_path: Path,
    config_defaults: Dict[str, Any],
) -> Tuple[Callable[..., Any], Dict[str, Any]]:
    langchain_base = _import_langchain_base_tool()
    attr = _resolve_callable(tool.impl, base_path)

    if not inspect.isclass(attr):
        raise TypeError(f"langchain tool '{tool.id}' must reference a class")
    if not issubclass(attr, langchain_base):
        raise TypeError(f"langchain tool '{tool.id}' must inherit from LangChain BaseTool")

    init_payload = config_defaults.pop("init", {})
    if not isinstance(init_payload, dict):
        raise TypeError(f"langchain tool '{tool.id}' config.init must be a mapping")

    input_key = config_defaults.pop("input_key", None)
    if input_key is not None and not isinstance(input_key, str):
        raise TypeError(f"langchain tool '{tool.id}' config.input_key must be a string when provided")

    instance = attr(**init_payload)

    def _call_langchain_tool(**payload: Any) -> Dict[str, Any]:
        call_payload = dict(payload)
        call_payload.pop("timeout", None)

        tool_input = _prepare_langchain_input(call_payload, input_key)
        result = _invoke_langchain_tool(instance, tool_input)
        return _normalize_tool_output(result)

    return _call_langchain_tool, config_defaults


def _prepare_langchain_input(payload: Dict[str, Any], input_key: Optional[str]) -> Any:
    if input_key:
        if input_key not in payload:
            raise KeyError(f"expected langchain tool input key '{input_key}' in payload")
        return payload[input_key]
    return payload


def _invoke_langchain_tool(tool_instance: Any, tool_input: Any) -> Any:
    if hasattr(tool_instance, "invoke"):
        return tool_instance.invoke(tool_input)
    if hasattr(tool_instance, "run"):
        return tool_instance.run(tool_input)
    return tool_instance(tool_input)


def _normalize_tool_output(result: Any) -> Dict[str, Any]:
    json_payload: Optional[Any]
    text_payload: Optional[str]
    items_payload: Optional[List[Any]]

    if isinstance(result, dict):
        json_payload = result
        text_candidate = result.get("text") or result.get("output")
        text_payload = text_candidate if isinstance(text_candidate, str) else None
        items_candidate = result.get("items")
        items_payload = items_candidate if isinstance(items_candidate, list) else None
    elif isinstance(result, list):
        json_payload = None
        text_payload = None
        items_payload = result
    elif isinstance(result, str):
        json_payload = None
        text_payload = result
        items_payload = None
    else:
        json_payload = None
        text_payload = str(result) if result is not None else None
        items_payload = None

    return {
        "status": 200,
        "json": json_payload,
        "text": text_payload,
        "items": items_payload,
        "result": result,
        "error": None,
    }


def _import_langchain_base_tool() -> type:
    try:
        from langchain_core.tools import BaseTool  # type: ignore
    except ImportError:
        try:
            from langchain_core.tools.base import BaseTool  # type: ignore
        except ImportError:
            try:
                from langchain.tools.base import BaseTool  # type: ignore
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise ImportError(
                    "langchain is required for tools with kind 'langchain' and mode 'class'"
                ) from exc
    return BaseTool


def _resolve_callable(impl: str, base_path: Path) -> Callable[..., Any]:
    module_path, separator, attr = impl.partition("#")
    if not separator:
        raise ValueError(f"tool impl '{impl}' must contain '#' separating callable name")

    if module_path.endswith(".py"):
        candidate_path = (base_path / module_path).resolve()
        if not candidate_path.exists():
            fallback = _maybe_resolve_tool_path(module_path)
            if fallback is not None:
                candidate_path = fallback
        module = _load_module_from_file(candidate_path)
    else:
        dotted = module_path.replace("/", ".")
        module = importlib.import_module(dotted)

    try:
        callable_obj = getattr(module, attr)
    except AttributeError as exc:
        raise AttributeError(f"callable '{attr}' not found in module '{module.__name__}'") from exc

    if not callable(callable_obj):
        raise TypeError(f"resolved object '{impl}' is not callable")
    return callable_obj


def _load_module_from_file(path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(f"tool implementation file '{path}' does not exist")
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load module from '{path}'")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[call-arg]
    return module


def _maybe_resolve_tool_path(module_path: str) -> Optional[Path]:
    module_path_obj = Path(module_path)
    try:
        index = module_path_obj.parts.index("tools")
    except ValueError:
        return None

    relative_after_tools = Path(*module_path_obj.parts[index + 1 :])
    candidate = Path(__file__).resolve().parent / "tools" / relative_after_tools
    return candidate if candidate.exists() else None


def _build_graphs(config: AgentConfig) -> tuple[GraphDefinition, Dict[str, GraphDefinition]]:
    compiled_subgraphs = {
        name: _compile_graph(name, subgraph)
        for name, subgraph in config.subgraphs.items()
    }
    dependencies: Dict[str, List[str]] = {"__root__": _collect_subgraph_references(config.graph)}
    for name, subgraph in config.subgraphs.items():
        dependencies[name] = _collect_subgraph_references(subgraph)
    _ensure_subgraph_cycles(dependencies)
    main_graph = _compile_graph("__root__", config.graph)
    return main_graph, compiled_subgraphs


def _compile_graph(name: str, graph_config: GraphConfig) -> GraphDefinition:
    node_index = {node.id: node for node in graph_config.nodes}
    edges = list(graph_config.edges)
    edges_by_source: Dict[str, List[GraphEdge]] = {}
    incoming_counts: Dict[str, int] = {node_id: 0 for node_id in node_index}

    for edge in edges:
        edges_by_source.setdefault(edge.from_, []).append(edge)
        incoming_counts[edge.to] = incoming_counts.get(edge.to, 0) + 1

    for node in node_index.values():
        if isinstance(node, RouterNode):
            for case in node.cases:
                if case.to in incoming_counts:
                    incoming_counts[case.to] += 1
            if node.default and node.default in incoming_counts:
                incoming_counts[node.default] += 1
        if isinstance(node, LoopNode) and node.body in incoming_counts:
            incoming_counts[node.body] += 1

    entry_nodes = [node_id for node_id, count in incoming_counts.items() if count == 0]

    adjacency: Dict[str, List[str]] = {node_id: [] for node_id in node_index}
    for source, edges_for_source in edges_by_source.items():
        adjacency[source].extend(edge.to for edge in edges_for_source)

    for node in node_index.values():
        if isinstance(node, LoopNode):
            adjacency.setdefault(node.id, []).append(node.body)

    _ensure_acyclic_graph(name, adjacency)

    return GraphDefinition(
        name=name,
        nodes=node_index,
        edges=edges,
        inputs=list(graph_config.inputs),
        outputs=list(graph_config.outputs),
        max_steps=graph_config.max_steps,
        timeout_seconds=graph_config.timeout.seconds if graph_config.timeout else None,
        edges_by_source=edges_by_source,
        entry_nodes=entry_nodes,
    )


def _deep_merge(base: Any, incoming: Any) -> Any:
    if base is None:
        return deepcopy(incoming)
    if incoming is None:
        return deepcopy(base)
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = {key: deepcopy(value) for key, value in base.items()}
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    if isinstance(base, list) and isinstance(incoming, list):
        return [*base, *incoming]
    return deepcopy(incoming)


def _evaluate_json_logic(expression: Any, context: Dict[str, Any]) -> Any:
    if not isinstance(expression, dict):
        if isinstance(expression, list):
            return [_evaluate_json_logic(item, context) for item in expression]
        return expression

    if len(expression) != 1:
        raise ValueError(f"invalid JsonLogic expression: {expression}")

    operator, value = next(iter(expression.items()))

    if operator == "var":
        if isinstance(value, list):
            path = value[0]
            default = value[1] if len(value) > 1 else None
        else:
            path = value
            default = None
        return _resolve_context_path(context, path, default)

    values = value if isinstance(value, list) else [value]
    evaluated = [_evaluate_json_logic(item, context) for item in values]

    if operator == "==":
        return evaluated[0] == evaluated[1]
    if operator == "!=":
        return evaluated[0] != evaluated[1]
    if operator in {"<", "<=", ">", ">="}:
        left, right = evaluated[0], evaluated[1]
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        return left >= right
    if operator == "+":
        return sum(evaluated)
    if operator == "-":
        return evaluated[0] - evaluated[1]
    if operator == "*":
        result = 1
        for item in evaluated:
            result *= item
        return result
    if operator == "/":
        left, right = evaluated[0], evaluated[1]
        return left / right
    if operator == "!":
        return not evaluated[0]
    if operator == "and":
        return all(evaluated)
    if operator == "or":
        return any(evaluated)
    if operator == "in":
        return evaluated[0] in evaluated[1]
    if operator == "max":
        return max(evaluated)
    if operator == "min":
        return min(evaluated)

    raise ValueError(f"unsupported JsonLogic operator '{operator}'")


def _resolve_context_path(context: Dict[str, Any], path: Any, default: Any = None) -> Any:
    if not isinstance(path, str):
        return path
    if path == "" or path == "var":
        return context

    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def _resolve_env_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_env_placeholders(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_resolve_env_placeholders(item) for item in value]
    if isinstance(value, str):
        match = ENV_PATTERN.match(value)
        if match:
            env_name = match.group(1)
            try:
                return os.environ[env_name]
            except KeyError as exc:
                raise AgentRuntimeError(f"environment variable '{env_name}' is not set") from exc
        return value
    return value


def _ensure_acyclic_graph(name: str, adjacency: Dict[str, List[str]]) -> None:
    visited: set[str] = set()
    path: List[str] = []

    def _dfs(node_id: str) -> None:
        if node_id in path:
            cycle_start = path.index(node_id)
            cycle_path = " -> ".join(path[cycle_start:] + [node_id])
            raise ValueError(f"graph '{name}' contains a cycle: {cycle_path}")
        if node_id in visited:
            return
        path.append(node_id)
        for neighbor in adjacency.get(node_id, []):
            _dfs(neighbor)
        path.pop()
        visited.add(node_id)

    for node in adjacency:
        if node not in visited:
            _dfs(node)


def _collect_subgraph_references(graph_config: GraphConfig) -> List[str]:
    return [node.graph for node in graph_config.nodes if isinstance(node, SubgraphNode)]


def _ensure_subgraph_cycles(dependencies: Dict[str, List[str]]) -> None:
    visited: set[str] = set()
    stack: List[str] = []

    def _dfs(name: str) -> None:
        if name in stack:
            cycle = " -> ".join(stack + [name])
            raise ValueError(f"subgraph dependency cycle detected: {cycle}")
        if name in visited:
            return
        stack.append(name)
        for dep in dependencies.get(name, []):
            _dfs(dep)
        stack.pop()
        visited.add(name)

    for graph_name in dependencies:
        if graph_name not in visited:
            _dfs(graph_name)


# Note: .env auto-loading is intentionally not performed in the library runtime.


# removed custom parser; rely on python-dotenv for parsing and exporting
