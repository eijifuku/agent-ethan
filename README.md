# Agent Ethan

[日本語版 README](README.ja.md)

Agent Ethan is an LLM‑centric agent runtime: it orchestrates prompts, tools, routing, loops, and subgraphs from declarative YAML. From prompt rendering to tool execution and state updates, flows are executed end‑to‑end.It delivers an almost no-code experience: instead of hand-writing orchestration code, you describe flows declaratively and let the runtime wire LLMs and tools together. It bundles schema validation, graph execution with JsonLogic conditions, built-in tool adapters, and provider helpers for OpenAI-compatible backends such as LM Studio.

> ⚠️ Important Notice (No Support / No PR / No Issues)
>
> This repository is primarily for personal use. You may use it freely under the license, but the author provides:
> - No warranty, no liability
> - No support or Q&A
> - No pull requests or issues will be accepted
>
> Use at your own risk.

## Features

- Build agents almost no‑code with declarative YAML
- State management with merge strategies (deepmerge / replace)
- Conversation memory (LangChain adapters available)
- Use the LangChain tool ecosystem (optional) and create custom tools
- Graph‑based workflows (LLM / tool / router / loop / subgraph)
- RAG via LangChain RetrievalQA (optional adapter)
- Robust execution with retries, timeouts, and on_error
- Provider‑agnostic: OpenAI‑compatible endpoints, LM Studio, etc.
- Tool kinds (Python / HTTP / MCP) and reusable subgraphs
- Testability via tool_overrides and deterministic mapping
- Logging outputs: stdout, JSONL, and LangSmith

Agent Ethan compiles declarative YAML into an executable workflow. Each configuration defines:

1. **Metadata** – schema version, agent name, default LLM provider/model, retry/timeout defaults, provider-specific settings
2. **State** – typed fields managed across the graph, with initialization and merge strategy (`deepmerge` or `replace`)
3. **Prompts** – partials and templates rendered (via Jinja) for LLM nodes
4. **Tools** – declarative handles mapping to Python callables, HTTP or MCP adapters. Tools included in LangChain are also available (install separately).RAG available via LangChain's RetrievalQA tools through the adapter (optional dependency)
5. **Graph** – nodes (LLM, tool, router, loop, subgraph, noop) and edges describing execution and routing
6. **Subgraphs** – optional reusable graphs

The YAML is validated by Pydantic models in `agent_ethan.schema`, and `agent_ethan.builder` resolves tools/providers and produces an `AgentRuntime` that executes nodes while honoring retries, timeouts, and `on_error`.

See [docs/en/nodes.md](docs/en/nodes.md) for node fields and behavior, and [docs/en/configuration.md](docs/en/configuration.md) for a full YAML reference and samples.

## Installation

```bash
# Install from GitHub (recommended)
pip install git+https://github.com/eijifuku/agent-ethan.git

# Or install locally in editable mode
git clone https://github.com/eijifuku/agent-ethan.git
cd agent-ethan
pip install -e .
```

## Quick Start

```python
from agent_ethan.builder import build_agent_from_path

runtime = build_agent_from_path("examples/rag_agent.yaml")
state = runtime.run({"query": "Hello"})
print(state["answer"])
```

For a slightly more involved, end-to-end sample, see [docs/en/examples.md](docs/en/examples.md).

Minimal YAML example (what the code above runs):

```yaml
meta:
  schema_version: 1
  name: demo
  defaults:
    llm: openai:gpt-4o-mini
  providers:
    openai:
      type: openai
      client_kwargs:
        api_key: "{{env.OPENAI_API_KEY}}"

state:
  shape:
    query: str
    context: list[dict]
    answer: str | null
  reducer: deepmerge
  init:
    context: []

prompts:
  partials:
    sys: |
      You are a helpful assistant. Answer concisely.
  templates:
    answer:
      system: "{{> sys }}"
      user: |
        Question: {{ query }}
        Context: {{ context }}

tools:
  - id: local_search
    kind: python
    impl: "tools/local_rag.py#search"

graph:
  inputs: [query]
  outputs: [answer]
  nodes:
    - id: search
      type: tool
      uses: local_search
      inputs:
        query: "{{ query }}"
      map:
        set:
          context: "{{ result['items'] }}"

    - id: generate
      type: llm
      prompt: answer
      map:
        set:
          answer: "{{ output.text }}"

  edges:
    - from: search
      to: generate
```

- **Conversation memory** – enable LangChain-backed history without rewiring the runtime:

```yaml
memory:
  enabled: true
  type: langchain_history
  kind: file
  path: "./data/history-{session_id}.jsonl"
  session_key: session_id
  k: 20

state:
  shape:
    messages: list[dict]
    session_id: str | null
  init:
    messages: []
    session_id: null
```

See `examples/memory_agent.yaml` and `docs/en/configuration.md` for more combinations (Redis, SQLite, custom adapters, etc.).

- Set `OPENAI_API_KEY` before running examples.
- `python examples/arxiv_example.py "lightgbm time series feature engineering"` downloads matching papers and saves a factual report.
- To target OpenAI directly, export `OPENAI_API_KEY` and set `meta.defaults.llm: openai:gpt-4o-mini` with a corresponding `providers.openai` block (see `docs/en/providers.md`).
- `python examples/langchain_rag_example.py` demonstrates a LangChain-powered RAG workflow backed by Chroma and OpenAI embeddings (requires `pip install langchain-openai chromadb` and `OPENAI_API_KEY`).
- `python examples/langchain_rag_vectorstore_example.py` shows how to inject LangChain's `VectorStoreQATool` via `tool_overrides` when you already manage the vector store in Python.

## Tests

```bash
python -m unittest
```

## Documentation

Comprehensive guides are available under [docs/en/index.md](docs/en/index.md) (English) and [docs/ja/index.md](docs/ja/index.md) (Japanese).

## License

See [LICENSE](LICENSE) for details.
