# Troubleshooting

## Missing Environment Variables

```
AgentRuntimeError: environment variable 'OPENAI_API_KEY' is not set
```

Set the variable before running the agent:

```bash
export OPENAI_API_KEY=sk-your-key
```

## Node Fails Without Handler

```
NodeExecutionError: node 'filter' failed without on_error handler: type=llm, prompt=filter_results, exception=...
```

Add an `on_error` block to the node or ensure the upstream service (OpenAI API or compatible backend) is reachable.

## JSON Parsing Errors

If the LLM emits non-JSON text, `tools/arxiv_filter.py#parse_selection` falls back to keyword overlap automatically. You can inspect `state.relevance_raw` to see the raw output.

## Debugging Prompts

Use `AgentRuntime.run(..., max_steps=1)` to stop after the first node and inspect the state. Logging inside custom tools is also helpful:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Common Test Failures

- `FileNotFoundError` for tool modules indicates the YAML path is incorrect relative to the YAML file; use `../agent_ethan/tools/...` when the YAML lives in `examples/`.
- Failing unit tests in CI can often be reproduced locally with `python -m unittest` before pushing.

For more advanced debugging, instrument your tools to return additional metadata under custom keys and inspect them via the runtime state.
