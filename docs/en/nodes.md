# Node Catalogue

This guide describes every node type in the Agent Ethan graph model. Each section explains required fields, optional fields, execution semantics, mapping behavior, and typical use cases. Copy the snippets to bootstrap your own configuration.

## Tool Node

### When to Use
- Call Python helpers, HTTP endpoints, MCP tools, or subgraphs.
- Transform structured data (API responses, arithmetic results) before updating state.

### Required Fields
| Field | Description |
| ----- | ----------- |
| `id` | Unique node identifier. |
| `type` | Must be `tool`. |
| `uses` | ID of a tool declared in `tools:`. |

### Optional Fields
| Field | Description |
| `name`, `description` | Human-readable metadata. |
| `retry`, `timeout` | Node-level overrides. |
| `on_error` | Fallback behavior (see below). |
| `inputs` | Jinja-rendered structure passed to the tool callable. |
| `map` | Post-processing directives (`set`, `merge`, `delete`). |

### Example: HTTP Search
```yaml
- id: search
  type: tool
  uses: http_fetch
  inputs:
    method: GET
    url: "https://api.example.com/search"
    params:
      q: "{{ state.keywords }}"
  map:
    set:
      search_results: "{{ result['items'] or [] }}"
    merge:
      history:
        queries: ["{{ state.keywords }}"]
```

### Notes
- `result` in mapping expressions references the normalized tool response (`status`, `json`, `text`, `items`, `result`, `error`).
- Tools should return `error` when something goes wrong; the runtime then respects `on_error` or raises.

---

## LLM Node

### When to Use
- Invoke an LLM provider with prompts rendered from state/inputs.
- Post-process the result via `map` directives.

### Required Fields
| Field | Description |
| ----- | ----------- |
| `id` | Node identifier. |
| `type` | `llm`. |
| `prompt` | Name of a prompt template declared under `prompts.templates`. |

### Optional Fields
| Field | Description |
| `retry`, `timeout` | Override global/default policies. |
| `on_error` | Redirect or resume when the provider fails. |
| `map` | Mutate state using the LLM response. |

### Example: Generate Draft
```yaml
- id: draft
  type: llm
  prompt: respond
  retry:
    max_attempts: 3
    backoff: 1
  timeout:
    seconds: 45
  map:
    set:
      draft_text: "{{ result.text }}"
      prompt_tokens: "{{ result.json['usage']['prompt_tokens'] }}"
```

### Notes
- The prompt template receives `state`, `inputs`, and `result` contexts. Expressions such as `{{ state.request }}` are valid inside templates.
- When the provider returns an error, `result.error` should be non-null; the runtime treats that as failure.

---

## Router Node

### When to Use
- Branch execution based on JsonLogic expressions.
- Route to multiple targets (all matching cases fire) or a default.

### Fields
| Field | Required | Description |
| `cases` | ✓ | List of `{when: <JsonLogic>, to: <node_id>}` pairs. |
| `default` | ✗ | Node to enqueue when no case matches. |

### Example
```yaml
- id: branch
  type: router
  cases:
    - when:
        ">": ["{{ state.score }}", 0.8]
      to: approve
    - when:
        "<": ["{{ state.score }}", 0.5]
      to: reject
  default: refine
```

### Notes
- JsonLogic context includes `state`, `inputs`, `result`, `node`.
- Multiple cases may enqueue multiple targets (fan-out behavior).

---

## Loop Node

### When to Use
- Repeat a node until a condition is satisfied or a max iteration count is hit.

### Fields
| Field | Required | Description |
| `body` | ✓ | Node ID executed each iteration. |
| `max_iterations` | ✗ | Defaults to 10. Hard stop to avoid infinite loops. |
| `until` | ✗ | JsonLogic expression evaluated after each iteration. |
| `on_error` | ✗ | handle failures inside the loop. |

### Example
```yaml
- id: refine_loop
  type: loop
  body: draft
  until:
    ">": ["{{ state.score }}", 0.75]
  max_iterations: 4
```

### Notes
- The loop shares the parent state; any mutations persist across iterations.
- Failure inside `body` propagates unless `on_error` is defined on the loop node or the body node.

---

## Subgraph Node

### When to Use
- Reuse a sequence of nodes as a callable unit.

### Fields
| Field | Required | Description |
| `graph` | ✓ | Name of the subgraph defined under top-level `subgraphs`. |
| `inputs` | ✓ | Mapping from parent context to subgraph inputs. |
| `map` | ✗ | Merge subgraph outputs back into parent state. |

### Example
```yaml
subgraphs:
  summarize:
    inputs: [text]
    outputs: [summary]
    nodes:
      - id: llm
        type: llm
        prompt: summarize
        map:
          set:
            summary: "{{ result.text }}"
    edges: []

- id: summary_step
  type: subgraph
  graph: summarize
  inputs:
    text: "{{ state.answer }}"
  map:
    set:
      final_summary: "{{ output.summary }}"
```

### Notes
- Subgraphs obey the same semantics as top-level graphs (inputs, outputs, nodes, edges).
- `runtime.run(max_subgraph_depth=...)` prevents infinite recursion.

---

## Noop Node

### When to Use
- Mutate state without calling tools or LLMs.
- Clean up temporary fields.

### Example
```yaml
- id: cleanup
  type: noop
  map:
    delete:
      - draft_text
    merge:
      audit:
        actions: ["cleanup"]
```

---

## Error Handling (`on_error`)

Each node type supports an optional `on_error` block with two strategies:

```yaml
on_error:
  to: fallback_node
```
- Enqueues `fallback_node` and skips normal edges.

```yaml
on_error:
  resume: true
```
- Continues along the original edges despite the failure.

You can chain both behaviors:

```yaml
on_error:
  to: fallback_node
  resume: false  # implicit
```

When a node fails without `on_error`, the runtime raises `NodeExecutionError` containing detailed diagnostics (`node id`, `type`, `prompt` or `tool`, and the underlying exception/error payload).

---

## Mapping Cheat Sheet

| Directive | Description | Example |
| --------- | ----------- | ------- |
| `set` | Assign values (overwrites existing keys). | `set: {answer: "{{ result.text }}"}` |
| `merge` | Deep merge dictionaries/lists. | `merge: {history: {entries: ["{{ result.text }}"]}}` |
| `delete` | Remove keys from state. | `delete: [temporary_token]` |

Expressions inside mapping directives can reference:
- `state`: current state dictionary
- `inputs`: original inputs passed to `run`
- `result`: tool/LLM response
- `output`: alias for `result`

---

## Practical Tips

- Start simple: create a graph with one tool node + one LLM node, then layer routers/loops.
- Use `noop` nodes to restructure state between steps without external calls.
- Always provide meaningful `on_error` handling for external integrations (LLM, HTTP).
- When debugging, log `state` inside custom tools or add `debug` fields via `map.set`.
- Validate YAML early by running `python -m unittest` – builder tests load sample configurations and catch missing files.

Use this catalogue alongside the [Configuration Reference](configuration.md) to design agents confidently.
