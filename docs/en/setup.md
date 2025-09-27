# Setup Guide

## Requirements

- Python 3.10 or newer
- LLM API access (OpenAI / Gemini / Claude / OpenAI‑compatible API)
- LangChain support is bundled (`langchain-core`, `langchain-community`, `langchain-openai`) so the built-in adapters and examples run without extra installs
- Additionally, some tools may require extra libraries depending on what you use

## Environment Variables

| Variable | Purpose |
| -------- | ------- |
| `OPENAI_COMPATIBLE_BASE_URL` | Base URL for an OpenAI-compatible local API (LM Studio, vLLM, etc.). |
| `OPENAI_API_KEY` | When using OpenAI or compatible providers that require a key. |
| `GEMINI_API_KEY` | API key for Google Gemini. |
| `ANTHROPIC_API_KEY` | API key for Anthropic Claude. |

Note: Set only the keys for the providers you actually use.

Use `.env` files with `python-dotenv` if you prefer not to export variables manually.

```bash
cat <<'ENV' > .env
OPENAI_COMPATIBLE_BASE_URL=http://127.0.0.1:1234/v1
OPENAI_API_KEY=your-openai-api-key
GEMINI_API_KEY=your-gemini-key
ANTHROPIC_API_KEY=your-claude-key\
ENV
```

## Running Examples

1. **RAG Workflow**
   ```bash
   python examples/example.py
   ```
   Downloads the YAML, runs the local search tool, and prints the answer.

2. **arXiv Workflow**
   ```bash
   export OPENAI_COMPATIBLE_BASE_URL=http://host.docker.internal:1234/v1
   python examples/arxiv_example.py "lightgbm 時系列 特徴量"
   ```
   Fetches papers from arXiv, filters them, downloads PDFs, and generates a factual report.

## Docker

The repository provides `Dockerfile` and `docker-compose.yml` for reproducible environments.

```bash
docker compose run --rm agent
```

This builds the image, mounts the repository into `/workspace`, installs the package, and runs the unit tests. Override `OPENAI_COMPATIBLE_BASE_URL` in the compose file or via `docker compose run -e` to target your OpenAI-compatible endpoint (e.g. LM Studio).

## Testing

```bash
python -m unittest
```

All CI-critical tests reside under `tests/`. See `tests/test_arxiv_tools.py` for fallbacks, and `tests/test_builder.py` for runtime scenarios.
