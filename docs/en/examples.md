# Examples

## RAG Workflow (`examples/rag_agent.yaml`)

This configuration demonstrates a simple retrieval-augmented flow driven by local search.

### Highlights

- Uses `tools/local_rag.py#search` to simulate document retrieval.
- LLM prompt copies the query and retrieved context from state.
- No external dependencies; suitable for smoke tests.

### Execution

```bash
python examples/example.py
```

The script loads the agent, runs it with the default `query`, and prints the final `answer` from state.

## Conversation Memory (`examples/memory_agent.yaml`)

Enables LangChain-backed chat history storage without rewriting the runtime.

### Highlights

- Defines a `memory` block that persists `state.messages` through LangChain's history adapters.
- Uses a lightweight graph: one node appends the user message, another echoes a reply to illustrate assistant turns.
- Out of the box it stores transcripts in `examples/data/history-<session>.jsonl`; swap `kind` to `redis`/`sqlite` for stateful backends.

### Execution

```bash
python examples/memory_example.py
```

The script reuses the same `session_id` twice to show history being reloaded, then starts a fresh session to demonstrate isolation.

## LangChain RAG (`examples/langchain_rag_agent.yaml`)

Combines the runtime graph with LangChain's Chroma vector store and OpenAI embeddings to answer questions over a local corpus.

### Highlights

- `tools/langchain_rag.py#ChromaRetrievalQATool` loads markdown files from `examples/corpus`, embeds them with `OpenAIEmbeddings`, and builds a Chroma store on the fly.
- The tool returns both a draft answer and source snippets; an LLM node recomposes the final response using the retrieved context.
- Set `OPENAI_API_KEY`; `langchain-openai` / `chromadb` are bundled so no extra install is required.

### Execution

```bash
export OPENAI_API_KEY=sk-your-key
python examples/langchain_rag_example.py
```

You should see an answer grounded in the markdown files along with the file paths that supplied supporting context.

## LangChain VectorStore Override (`examples/langchain_rag_vectorstore_agent.yaml`)

Demonstrates how to wire LangChain's built-in `VectorStoreQATool` via `tool_overrides` without relying on the helper class in `tools/langchain_rag.py`.

### Highlights

- YAML declares a placeholder Python tool (`tools/langchain_stub.py#requires_override`) so the runtime builds successfully.
- `examples/langchain_rag_vectorstore_example.py` loads documents, builds a Chroma vector store, instantiates `VectorStoreQATool`, and injects it with `tool_overrides`.
- Use this pattern when you already have bespoke LangChain tooling and only need the runtime for orchestration.

### Execution

```bash
export OPENAI_API_KEY=sk-your-key
python examples/langchain_rag_vectorstore_example.py
```

The script prints the answer returned by `VectorStoreQATool` along with snippets from the most similar documents fetched directly from the vector store.

## arXiv Research Agent (`examples/arxiv_agent.yaml`)

Transforms a natural-language request into a curated list of arXiv papers and downloads the PDFs.

### Graph Stages

1. **Keyword Generation** – LLM attempts to produce keyword phrases. Failures fall back to heuristic keyword extraction.
2. **arXiv Search** – `tools/arxiv_local.py#search` issues multiple query patterns (exact phrase, AND/OR combinations) to gather up to five results across pages.
3. **Filtering** – `filter` node asks the LLM to extract only the entries that are highly relevant to the user's request; `parse_selection` ensures at least a heuristic match even if the LLM response is invalid.
4. **Download** – PDFs are fetched with redirects enabled and enriched with metadata captured from the search stage.
5. **Summary** – Final LLM pass generates a factual report. When unavailable, `summary_fallback` outputs a bullet list of the downloaded papers with local file paths.

### Running the Agent

```bash
export OPENAI_COMPATIBLE_BASE_URL=http://host.docker.internal:1234/v1
python examples/arxiv_example.py "lightgbm feature engineering for time series"
```

Output includes generated keywords, a list of PDFs saved in `downloads/`, and a summary that references actual metadata only.

### Customizing the Workflow

- Adjust `max_pages` / `page_size` in `arxiv_local.py#search` via tool `config` if you need more results.
- Replace `arxiv_download` with your own downloader by adding a new tool entry and updating the graph.
- Use `tool_overrides` inside tests to stub external calls:

```python
runtime.run(
    {"request": request},
    tool_overrides={"arxiv_search": fake_search, "arxiv_download": fake_download},
)
```

## Additional Ideas

- **Multi-turn Agents** – Add router nodes that branch on state to build conversational loops.
- **Subgraph Pipelines** – Encapsulate repeated prompt/response pairs into subgraphs reusable by multiple parent graphs.
- **Hybrid Retrieval** – Combine `http_call` (for external APIs) and `python` tools (for local indexing) to build richer retrieval flows.

Consult `docs/en/configuration.md` for the full YAML reference when extending these examples.
