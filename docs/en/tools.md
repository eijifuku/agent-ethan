# Tools and Extensions

Tools encapsulate external capabilities (HTTP, MCP, Python functions, LangChain tools, subgraphs) and are declared in the YAML `tools:` section. This page explains how to declare them, call them from graph nodes, and implement custom callables.

## 1. Declaring Tools in YAML

```yaml
tools:
  - id: http_fetch
    kind: http
    impl: "tools/http_call.py#call"
    config:
      method: GET
      timeout: 15

  - id: keyword_fallback
    kind: python
    impl: "../tools/arxiv_keywords.py#fallback_keywords"
    retry:
      max_attempts: 3
      backoff: 2

  - id: github_repo
    kind: mcp
    impl: "mcp://github"
    config:
      repository: "owner/repo"
      token: "{{env.GITHUB_TOKEN}}"

  - id: summarize_subgraph
    kind: subgraph
    impl: "summarize"
```

| Kind | Description |
| ---- | ----------- |
| `http` | Uses the built-in HTTP adapter. `inputs` must contain request fields (method, url, params, headers, etc.). |
| `python` | Imports a Python callable using `<module path>#<function>`. Paths are resolved relative to the YAML file. |
| `mcp` | Connects to a Model Context Protocol endpoint. `impl` is a URI such as `mcp://github`. `config` is sent as MCP parameters. |
| `subgraph` | Exposes a subgraph (declared under `subgraphs:`) as a tool so it can be reused by tool nodes. |
| `langchain` | Instantiates a LangChain `BaseTool` class (`mode: class`) and adapts its output into the runtime schema. |

## 2. Calling a Tool from the Graph

```yaml
- id: repo_issues
  type: tool
  uses: github_repo
  inputs:
    action: "list_issues"
    filters:
      labels: ["bug"]
  map:
    set:
      open_issues: "{{ result.json['items'] }}"
```

- `uses` references the tool ID defined in `tools:`.
- `inputs` is rendered with Jinja before the call.
- `result` is the normalized tool response used by `map` (`status`, `json`, `text`, `items`, `result`, `error`).

## 3. MCP Example: GitHub MCP Server

Assuming you run a GitHub MCP server locally:

```yaml
meta:
  providers: {}

tools:
  - id: github
    kind: mcp
    impl: "mcp://github"
    config:
      repository: "openai/openai-cookbook"
      token: "{{env.GITHUB_TOKEN}}"

  - id: list_prs
    kind: tool
    uses: github
    inputs:
      action: "pulls.list"
      params:
        state: "open"
    map:
      set:
        pull_requests: "{{ result.json['items'] }}"
```

The MCP response must conform to the tool output schema (status/result/error). Most MCP servers already align with this pattern.

## 4. Built-in Python Tools

| Tool | Description |
| ---- | ----------- |
| `tools/local_rag.py#search` | Local corpus search used by the RAG example. |
| `tools/arxiv_local.py#search` | Queries the arXiv Atom API with fallback queries and de-duplicates results. |
| `tools/arxiv_local.py#download` | Downloads PDFs, follows redirects, and enriches entries with metadata. |
| `tools/arxiv_filter.py#parse_selection` | Parses LLM JSON output or falls back to heuristic keyword overlap. |
| `tools/arxiv_keywords.py#fallback_keywords` | Uses LLM output when available, otherwise tokenizes the request. |
| `tools/arxiv_summary.py#fallback_summary` | Builds a factual report listing the downloaded papers. |
| `tools/json_utils.py#parse_object` | Parses a JSON string into a dictionary safely. |
| LangChain adapter (optional) | Bridge to use LangChain's tool ecosystem (install separately). |
| `tools/mock_tools.py` | Test utilities (`echo`, `increment`, `failing`). |

## 5. Writing Custom Python Tools

Create a Python module whose function returns a dictionary with the following keys:

```python
from typing import Any, Dict

ToolOutput = Dict[str, Any]

def my_tool(*, text: str) -> ToolOutput:
    processed = text.upper()
    return {
        "status": 200,
        "json": {"processed": processed},
        "text": processed,
        "items": None,
        "result": {"processed": processed},
        "error": None,
    }
```

- `status`: numeric status code (200 for success).
- `json`: primary payload (any serializable structure).
- `text`: optional string output.
- `items`: optional list output.
- `result`: alias for convenience (often mirrors `json`).
- `error`: `None` on success, or a structured object describing the failure.

Reference the callable:

```yaml
- id: my_tool
  kind: python
  impl: "custom/my_module.py#my_tool"
```

### Signalling Errors

Return an `error` payload to trigger `on_error` handling:

```python
return {
    "status": 500,
    "json": None,
    "text": None,
    "items": None,
    "result": None,
    "error": {"message": "timeout", "type": "upstream_error"},
}
```

### Tool Overrides at Runtime

```python
runtime.run(
    inputs,
    tool_overrides={"github_repo": fake_github},
)
```

Use this for testing or to stub out external services.

## 6. LangChain Class Tools

LangChain tools can be registered by pointing to the class that inherits from `BaseTool` and enabling class mode. Install the optional dependencies that your tool requires. For Retrieval-Augmented Generation with OpenAI embeddings and Chroma, for example:

```
pip install langchain-openai chromadb
```

```yaml
tools:
  - id: serp_search
    kind: langchain
    mode: class
    impl: "my_project.langchain_tools#SerpAPITool"
    config:
      init:
        serpapi_api_key: "{{env.SERPAPI_API_KEY}}"
      input_key: "query"

- id: research
  type: tool
  uses: serp_search
  inputs:
    query: "{{ inputs.topic }}"
  map:
    set:
      search_results: "{{ result['items'] or [] }}"
```

- `config.init` (optional) supplies keyword arguments for the tool constructor.
- `config.input_key` (optional) narrows the rendered payload to a single field when the tool expects a string or a specific argument. Omit it to pass the entire payload dictionary to `BaseTool.invoke`.
- The runtime normalizes the return value into the standard tool response shape (`status`, `json`, `text`, `items`, `result`, `error`).
- See `examples/langchain_list_dir_agent.yaml` for a minimal configuration that lists files using `ListDirectoryTool` with no extra dependencies beyond `langchain-core`/`langchain-community`.
- See `examples/langchain_rag_agent.yaml` for a retrieval workflow that reuses LangChain's Chroma vector store and OpenAI embeddings via `tools/langchain_rag.py#ChromaRetrievalQATool`.

## 7. RAG via LangChain Tools

To build a RAG pipeline without rewriting the runtime, wrap LangChain's vector store utilities in a tool class. The repository ships an example that uses `ChromaRetrievalQATool`, which loads documents from the filesystem, embeds them with OpenAI, builds a Chroma vector store, and answers questions via `RetrievalQA`:

```yaml
tools:
  - id: knowledge_base
    kind: langchain
    mode: class
    impl: "../tools/langchain_rag.py#ChromaRetrievalQATool"
    config:
      init:
        corpus_path: "./examples/corpus"
        glob: "*.md"
        collection_name: "agent-ethan-docs"
        persist_directory: "./examples/chroma_store"
        embedding_model: "text-embedding-3-small"
        llm_model: "gpt-4o-mini"
        top_k: 4

- id: retrieve
  type: tool
  uses: knowledge_base
  inputs:
    query: "{{ query }}"
  map:
    set:
      sources: "{{ result['items'] }}"
      preliminary_answer: "{{ result['json']['answer'] }}"
```

Combine the retrieved context with an LLM node (see `examples/langchain_rag_agent.yaml`) to produce the final answer while still benefiting from the runtime's graph execution, error handling, and state management.

When you already manage LangChain tools in Python, inject them without helper classes by using `tool_overrides`. `examples/langchain_rag_vectorstore_example.py` builds a Chroma store, creates `langchain_community.tools.VectorStoreQATool`, and overrides the `qa_tool` placeholder declared in YAML.

## 8. Common Patterns

- **Decorators** – wrap your tool to standardize logging, metrics, or retries before returning the dict above.
- **Environment Variables** – pass credentials via `config` + `{{env.VAR}}` so you never hardcode secrets.
- **Combination with Subgraphs** – expose subgraphs as tools (`kind: subgraph`) to reuse multi-step flows inside LLM prompts or routers.

With these conventions, any capability—REST APIs, MCP servers, LangChain tools, local Python code—can be wired into the agent graph deterministically.
