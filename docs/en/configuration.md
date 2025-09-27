# Configuration Reference

Agent Ethan YAML has a consistent structure. This guide explains every section and supplies copy‑ready samples for each node type so you can assemble complex agents without guesswork.

```
meta:
  schema_version: 1
  name: research_agent
  defaults:
    llm: local:google/gemma-3-12b
    temp: 0.2
    retry:
      max_attempts: 2
      backoff: 1.0
  providers:
    local:
      type: openai_compatible
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b

state:
  shape:
    request: str
    answer: str | null
    history: list[str]
  reducer: deepmerge
  init:
    history: []

prompts:
  partials:
    system/base: |
      You are a concise assistant.
  templates:
    respond:
      system: "{{> system/base }}"
      user: |
        {{ request }}

tools:
  - id: http_fetch
    kind: http
    impl: "tools/http_call.py#call"

  - id: summarizer
    kind: python
    impl: "tools/arxiv_summary.py#fallback_summary"

graph:
  inputs: [request]
  outputs: [answer]
  nodes:
    - id: keyword
      type: tool
      uses: http_fetch
      inputs:
        url: "https://example.com/search"
        params:
          q: "{{ inputs.request }}"
      map:
        set:
          history: "{{ result['items'] }}"

    - id: answer
      type: llm
      prompt: respond
      map:
        set:
          answer: "{{ result.text }}"

  edges:
    - from: keyword
      to: answer
```

The subsections below unpack each component with deeper samples.

---

## 1. `meta`

| Field | Purpose | Example |
| ----- | ------- | ------- |
| `schema_version` | Configuration format version. Currently `1`. | `schema_version: 1` |
| `name` | Human-friendly agent identifier. | `name: support_agent` |
| `defaults.llm` | Provider hint in the form `<provider_id>:<model>`. Used when `run()` receives no client. | `defaults.llm: openai:gpt-4o-mini` |
| `defaults.temp` | Default temperature for LLM nodes. | `temp: 0.2` |
| `defaults.retry` | Global retry policy (attempts + backoff seconds). | `retry:
  max_attempts: 3
  backoff: 1.5` |
| `defaults.timeout` | Default timeout in seconds (optional). | `timeout:
  seconds: 60` |
| `providers` | Provider-specific settings keyed by id. | see below |

### Provider Examples

**OpenAI**

```yaml
meta:
  defaults:
    llm: openai:gpt-4o-mini
  providers:
    openai:
      type: openai
      temperature: 0.3
      client_kwargs:
        api_key: "{{env.OPENAI_API_KEY}}"
      kwargs:
        max_tokens: 512
```

**OpenAI-compatible (e.g. LM Studio)**

```yaml
meta:
  defaults:
    llm: local:google/gemma-3-12b
  providers:
    local:
      type: openai_compatible
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b
      request_timeout: 120
      kwargs:
        max_tokens: 1024
```

> **Environment placeholders** – values wrapped in `{{env.VAR}}` are resolved at runtime. Missing variables raise `AgentRuntimeError` to prevent silent misconfiguration.

---

## 2. `state`

```yaml
state:
  shape:
    request: str
    context: list[str]
    answer: str | null
    attempts: int
  reducer: deepmerge
  init:
    context: []
    attempts: 0
```

- `shape` documents allowed keys and their broad types (for validation only).
- `reducer` controls how incoming inputs merge with existing state:
  - `deepmerge` (default) merges nested dictionaries/lists.
  - `replace` overwrites existing values entirely.
- `init` seeds default values before incoming inputs merge. Keys must exist in `shape` or validation fails.

---

## 3. `memory`

```yaml
memory:
  enabled: true
  type: langchain_history
  kind: redis
  session_key: session_id
  namespace: agent-ethan
  dsn: "redis://localhost:6379/0"
  k: 20
```

- `enabled` – toggles conversation tracking. When `false` the runtime ignores the section entirely.
- `type` – for now only `langchain_history` is supported. It uses LangChain's `BaseChatMessageHistory` implementations under the hood.
- `kind` – storage backend. Supported options: `inmemory`, `file`, `redis`, `sqlite`, `postgres`, `custom`.
- `session_key` – key that identifies the conversation. The runtime reads it from inputs first, then from state. Defaults to `session_id`.
- `namespace` – optional prefix for storage keys (useful when sharing Redis/Postgres between agents).
- `dsn` – connection string for `redis`, `sqlite`, or `postgres` backends.
- `path` – required for `file`, relative paths are resolved from the YAML file location.
- `table` – optional table name for SQL-based stores.
- `k` – optional window size; the runtime also exposes the last `k` messages in `state.messages_window`.
- `config` – free-form dictionary for backend-specific settings. `kind: custom` must provide `config.impl` pointing to a callable that returns a `BaseChatMessageHistory`.

> **State requirements** – include `messages` (list) in `state.shape` / `state.init` when enabling memory. The runtime populates it with the entire history before graph execution and flushes newly appended entries after the run.

## 4. `prompts`

```yaml
prompts:
  partials:
    system/base: |
      You are a helpful assistant.
    user/header: |
      Provide clear, concise answers.
  templates:
    qa:
      system: "{{> system/base }}"
      user: |
        {{> user/header }}
        Question: {{ request }}
        Context:
        {%- for item in context %}
        - {{ item }}
        {%- endfor %}
    qa_with_assistant:
      system: "{{> system/base }}"
      assistant: "Previously you answered: {{ last_answer }}"
      user: |
        Follow-up question: {{ request }}
```

- Use partials for reusable blocks (`{{> name }}` syntax).
- Templates may define `system`, `user`, `assistant`, and/or a `messages` list.
- Any `{{ expression }}` is evaluated with a context containing `state`, `inputs`, `result`, `output`, and helper functions.

---

## 5. `tools`

```yaml
tools:
  - id: http_fetch
    kind: http
    impl: "tools/http_call.py#call"
    config:
      timeout: 30

  - id: keyword_local
    kind: python
    impl: "../tools/arxiv_keywords.py#fallback_keywords"
    retry:
      max_attempts: 3
      backoff: 2

  - id: keyword_remote
    kind: mcp
    impl: "mcp://keyword-service"
```

| Field | Description |
| ----- | ----------- |
| `id` | Identifier referenced by nodes (`uses`). |
| `kind` | `python`, `http`, `mcp`, `subgraph`, or `langchain`. |
| `mode` | Optional. Set to `class` to instantiate a Python/LangChain class instead of calling a function. |
| `impl` | Module path + attribute (`path/to/module.py#function_or_class`). For MCP, supply a URI. |
| `config` | Arbitrary options supplied to the tool at call time. |
| `retry` / `timeout` | Optional overrides that mirror `meta.defaults`. |

> **Relative paths** – When your YAML lives in `examples/`, reference sibling tools with `../tools/...`.

> **LangChain RAG** – Point `kind: langchain` tools to `tools/langchain_rag.py#ChromaRetrievalQATool` (see `examples/langchain_rag_agent.yaml`) to reuse LangChain's Chroma vector store with OpenAI embeddings.

When `mode: class` is supplied, the runtime imports the class specified by `impl`, instantiates it with `config.init` (if provided), and then calls the resulting object. LangChain tools (`kind: langchain`) also accept `config.input_key` to map a single field from the rendered inputs to the tool's `invoke` method; omit `input_key` to pass the entire payload dictionary.

---

## 6. `graph`

### 6.1 Inputs & Outputs

```yaml
graph:
  inputs: [request]
  outputs: [answer, downloads]
  max_steps: 400
  timeout:
    seconds: 180
```

- `inputs` must be present when calling `runtime.run`.
- `outputs` must exist in the final state or the runtime raises an error.
- `max_steps` caps the total number of node executions (default 200). Use this to prevent runaway graphs.
- `timeout` enforces a wall-clock limit for the entire graph. It accepts the same layout as other timeout settings (`seconds: <float>`).

### 6.2 Node Types

#### Tool Node

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
        results: "{{ result['items'] or [] }}"
```

`map` can combine `set`, `merge`, and `delete`:

```yaml
map:
  set:
    answer.text: "{{ result.text }}"
    answer.tokens: "{{ result.json.usage.total_tokens }}"
  merge:
    history:
      entries: ["{{ result.text }}"]
  delete:
    - draft_answer
```

#### LLM Node

```yaml
- id: draft
  type: llm
  prompt: qa
  retry:
    max_attempts: 3
    backoff: 1
  timeout:
    seconds: 45
  map:
    set:
      draft_answer: "{{ result.text }}"
```

#### Router Node

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

JsonLogic expressions receive a context that includes `state`, `inputs`, `result`, and `node` metadata.

#### Loop Node

```yaml
- id: retry_loop
  type: loop
  body: draft
  until:
    ">": ["{{ state.score }}", 0.7]
  max_iterations: 3
```

The loop executes the `body` node repeatedly until the condition succeeds or the iteration cap is reached. Errors bubble unless handled by `on_error`.

#### Subgraph Node

```yaml
- id: summarize
  type: subgraph
  graph: summarize_subgraph
  inputs:
    text: "{{ state.draft_answer }}"
```

Subgraphs are defined under a top-level `subgraphs:` section (same shape as `graph`). `runtime.run(max_subgraph_depth=...)` guards against infinite recursion.

#### Noop Node

```yaml
- id: stash
  type: noop
  map:
    set:
      history: "{{ history + [state.answer] }}"
```

### 6.3 Edges

```yaml
edges:
  - from: keyword
    to: filter
    when:
      "!!": "{{ state.search_results }}"  # JsonLogic double negation
  - from: filter
    to: fallback
    when:
      "==": ["{{ state.relevant_ids | length }}", 0]
```

Edges are evaluated after the source node succeeds (or `on_error.resume` fires). Conditions use JsonLogic.

### 6.4 Error Handling (`on_error`)

```yaml
- id: filter
  type: llm
  prompt: filter_results
  on_error:
    to: heuristic_filter

- id: summary
  type: llm
  prompt: summarize
  on_error:
    resume: true
```

- `to` redirects execution to another node.
- `resume: true` continues down the normal edges even after failure.

---

## 7. Subgraphs

Declare additional graphs under `subgraphs:` for reuse and modularity.

```yaml
subgraphs:
  summarize:
    inputs: [text]
    outputs: [summary]
    nodes:
      - id: respond
        type: llm
        prompt: respond
        map:
          set:
            summary: "{{ result.text }}"
    edges: []
```

Invoke them via subgraph nodes as shown earlier.

---

## 8. Advanced Patterns & Tips

- **Environment-aware prompts** – Example: `"{{env.TITLE_PREFIX}} {{ request }}"` enables localization.
- **State versioning** – Introduce `state.version` and update it via `map` to coordinate downstream tools.
- **Debug payloads** – Capture raw tool responses by stashing `result.json` under a debug key.
- **Tool overrides in tests** – Use `runtime.run(..., tool_overrides={"arxiv_search": fake_search})` to isolate external calls.
- **Graceful fallbacks** – Chain tool-based fallbacks after LLM nodes using `on_error: resume` followed by a deterministic tool node (see `examples/arxiv_agent.yaml`).

---

## 9. Complete Sample: Research Agent

The configuration below mirrors the arXiv workflow with full fallbacks.

```yaml
meta:
  schema_version: 1
  name: lightgbm_researcher
  defaults:
    llm: local:google/gemma-3-12b
    retry:
      max_attempts: 2
      backoff: 1
  providers:
    local:
      type: openai_compatible
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b

state:
  shape:
    request: str
    keywords: str | null
    keywords_llm: str | null
    search_results: list[dict]
    relevance_raw: str | null
    relevant_ids: list[str]
    downloads: list[dict]
    summary: str | null
  reducer: deepmerge
  init:
    relevant_ids: []
    downloads: []
    keywords: ""
    keywords_llm: ""
    relevance_raw: ""

prompts:
  partials:
    sys/filter: |
      Return valid JSON with keys "relevant_ids" and "reason".
  templates:
    keyword:
      system: "Generate concise keywords for arXiv search."
      user: "{{ request }}"
    filter:
      system: "{{> sys/filter }}"
      user: |
        Request: {{ request }}
        Candidates:
        {%- for item in search_results %}
        - id: {{ item.id }} | title: {{ item.title }}
        {%- endfor %}
    summary:
      system: "Provide a factual report of downloaded papers."
      user: |
        Papers:
        {%- for paper in downloads %}
        - {{ paper.id }}: {{ paper.title }} ({{ paper.path }})
        {%- endfor %}

subgraphs: {}

tools:
  - id: keyword_fallback
    kind: python
    impl: "../tools/arxiv_keywords.py#fallback_keywords"
  - id: arxiv_search
    kind: python
    impl: "../tools/arxiv_local.py#search"
  - id: arxiv_select
    kind: python
    impl: "../tools/arxiv_filter.py#parse_selection"
  - id: arxiv_download
    kind: python
    impl: "../tools/arxiv_local.py#download"
  - id: summary_fallback
    kind: python
    impl: "../tools/arxiv_summary.py#fallback_summary"

graph:
  inputs: [request]
  outputs: [keywords, downloads, summary]
  nodes:
    - id: keyword_llm
      type: llm
      prompt: keyword
      on_error:
        resume: true
      map:
        set:
          keywords_llm: "{{ result.text.strip() }}"

    - id: keyword_ensure
      type: tool
      uses: keyword_fallback
      inputs:
        request: "{{ state.request }}"
        llm_keywords: "{{ state.keywords_llm }}"
      map:
        set:
          keywords: "{{ result.json['keywords'] }}"

    - id: search
      type: tool
      uses: arxiv_search
      inputs:
        query: "{{ state.keywords }}"
      map:
        set:
          search_results: "{{ result.json['items'] }}"

    - id: filter
      type: llm
      prompt: filter
      on_error:
        resume: true
      map:
        set:
          relevance_raw: "{{ result.text }}"

    - id: parse
      type: tool
      uses: arxiv_select
      inputs:
        raw_text: "{{ state.relevance_raw | default('') }}"
        search_results: "{{ state.search_results }}"
        keywords: "{{ state.keywords }}"
        max_results: 5
      map:
        set:
          relevant_ids: "{{ result.json['relevant_ids'] }}"
          rationale: "{{ result.json['reason'] }}"

    - id: download
      type: tool
      uses: arxiv_download
      inputs:
        paper_ids: "{{ state.relevant_ids }}"
        search_results: "{{ state.search_results }}"
      map:
        set:
          downloads: "{{ result.json['downloads'] }}"

    - id: summary_llm
      type: llm
      prompt: summary
      on_error:
        resume: true
      map:
        set:
          summary: "{{ result.text.strip() }}"

    - id: summary_ensure
      type: tool
      uses: summary_fallback
      inputs:
        downloads: "{{ state.downloads }}"
        llm_summary: "{{ state.summary }}"
      map:
        set:
          summary: "{{ result.json['summary'] }}"

  edges:
    - from: keyword_llm
      to: keyword_ensure
    - from: keyword_ensure
      to: search
    - from: search
      to: filter
    - from: filter
      to: parse
    - from: parse
      to: download
    - from: download
      to: summary_llm
    - from: summary_llm
      to: summary_ensure
```

Use this as a reference when constructing research agents or workflows that must survive flaky LLM responses. The same patterns (LLM + tool fallbacks, metadata enrichment, structured prompts) carry over to other domains.
