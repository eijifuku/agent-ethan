# Runtime Execution

The `AgentRuntime` orchestrates node execution with deterministic semantics.

## Entry Points

- `build_agent_from_path(path: Union[str, Path])` – load YAML, resolve relative tool modules.
- `build_agent_from_yaml(data: Dict[str, Any], base_path: Path)` – use existing dict (e.g., after preprocessing).
- `AgentRuntime.run(inputs, llm_client=None, llm_callable=None, tool_overrides=None, max_steps=None, max_subgraph_depth=None)` – execute the prepared graph.

Exactly **one** of `llm_client` or `llm_callable` may be provided. If both are omitted, the runtime attempts to instantiate the default provider from `meta.defaults.llm`.

## Node Execution

### Tool Nodes

1. Render inputs with `_render_structure` (Jinja expressions supported).
2. Call the tool callable.
3. If the result lacks `error`, apply `map` directives to update state.
4. Enqueue outgoing edges.

`map` supports:

```yaml
map:
  set:
    output.answer: "{{ result.text }}"
  merge:
  history: { values: "{{ result['items'] }}" }
  delete:
    - temp_field
```

### LLM Nodes

1. Build prompt context from state/inputs.
2. Render the template specified by `prompt` across the roles defined in the template (system, user, assistant, custom messages).
3. Call the resolved `LLMClient`.
4. When `error` is truthy, the node is considered failed. Otherwise `map` applies as with tool nodes.

### Router Nodes

Evaluate `cases` sequentially using JsonLogic expressions; all matching targets are queued. If no case matches and `default` is defined, it is used. Without matches and no default, the router advances along outgoing edges (if any) after evaluation.

### Loop Nodes

Loops run the body node up to `max_iterations`, checking `until` JsonLogic after each iteration. If the body throws an error, the loop fails unless handled by `on_error`.

### Error Handling

- `on_error:
    to: fallback_node` – jump to another node.
- `on_error:
    resume: true` – continue down normal edges.
- Without handlers, `NodeExecutionError` is raised. The runtime includes node id/type, prompt/tool, and the exception message in the error string.

### Timeouts & Retries

Each node/tool can declare `retry` and `timeout`. Missing values fall back to tool-level overrides, then graph defaults, then global defaults. LLM retries use `RetryPolicy(max_attempts, backoff_seconds)`; backoff is a simple sleep.

### Subgraphs

Subgraphs are executed depth-first. A global `max_subgraph_depth` guard prevents infinite recursion. Inputs passed into subgraphs are rendered with the parent context, and results are merged back into the parent state according to `map` rules.
