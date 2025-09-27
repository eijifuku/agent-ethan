# Tracing & Logging

Agent Ethan includes an optional structured tracing facility that records high-level run, node, tool, and LLM events. Tracing is configured in YAML under `meta.defaults.tracing`; when it is omitted or disabled the runtime behaves exactly as before.

## Quick Start

Add a tracing block to your agent configuration:

```yaml
meta:
  defaults:
    tracing:
      enabled: true
      sinks: ["stdout", "jsonl"]
```

Run the agent and you will see JSON events similar to:

```json
{"ts":"2025-09-27T13:35:20.481Z","event":"run_start","run_id":"f6a0...","graph":"support_flow","level":"info"}
```

The example configuration `examples/arxiv_agent.yaml` already enables `sinks: ["stdout"]`, so running `examples/arxiv_example.py` will stream trace events to the console out of the box.

## Configuration Reference

All properties live under `meta.defaults.tracing`.

- `enabled` (`bool`, default `false`) – master switch.
- `sinks` (`list[str]`) – any combination of `stdout`, `jsonl`, `langsmith`, or `null`.
- `sample` (`float`, default `1.0`) – sampling rate between `0.0` and `1.0`.
- `level` (`str`, default `info`) – minimum event level (`debug` | `info` | `warn` | `error`).
- `dir` (`str`, default `./logs`) – root directory for JSONL files.
- `langsmith_project` (`str | null`) – optional LangSmith project name.
- `max_text` (`int`, default `2048`) – truncate long strings after N characters.
- `deny_keys` (`list[str]`) – additional keys to redact; defaults include `api_key`, `authorization`, `password`, `token`, `secret`, `cookie`, `session`, `client_secret`, `private_key`.

If `sinks` is empty or contains `null`, the logger installs a `NullSink` that drops all events (useful for “sampled out” runs).

### Sinks

- **Stdout** – prints one JSON object per line to standard output.
- **Jsonl** – writes per-run JSONL files under `dir/<date>/<run_id>.jsonl`.
- **LangSmith** – forwards events to LangSmith. Install `langsmith` and supply `langsmith_project` (and the usual LangSmith environment variables).
- **Null** – discards everything.

You can combine multiple sinks, e.g. `sinks: ["stdout", "langsmith"]`.

### Sampling & Levels

At run start the logger draws a random number and compares it with `sample`. If the run is not selected the decorators fall back to a `NullSink`, so the overhead stays negligible. Level filtering is applied per-event after masking; set `level: debug` to capture router decisions and loop summaries.

### Masking & Payload Summaries

The logger redacts values whose keys match the deny list (`deny_keys`) and applies regex-based replacements (for example, `Bearer …`). Long strings are truncated to `max_text` characters, and summaries record the key set and a short preview rather than the full payload.

### Event Types

Instrumentation touches the main runtime layers:

- **Runs** – `run_start`, `run_end`, and `run_exception` with input/output summaries.
- **Nodes** – `node_start`, `node_end`, and `node_exception` include node id/type, graph name, and state diff keys.
- **Tools** – `tool_start`, `tool_end`, and `tool_exception` carry tool id/kind plus payload summaries.
- **LLMs** – `llm_start`, `llm_end`, and `llm_exception` include provider/model metadata and prompt/output summaries.
- **Routers & Loops** – additional `router_decision` and `loop_complete` events capture branch selection and iteration counts.

Each event carries `ts`, `run_id`, `span_id`, and `trace_id` so you can reconstruct the execution flow.

## Custom Setups

The module `agent_ethan.logging` exposes helpers in case you want to install bespoke sinks programmatically:

```python
from agent_ethan.logging import LogManager, set_log_manager
from agent_ethan.logging.sinks import Sink

class ListSink(Sink):
    def __init__(self):
        self.events = []
    def emit(self, event):
        self.events.append(event)

manager = LogManager(sinks=[ListSink()], sample_rate=1.0)
set_log_manager(manager)
```

Keep the built-in decorators (`@log_run`, `@log_node`, `@log_tool`, `@log_llm`) in place; they automatically reference the current `LogManager` instance.

## Troubleshooting

- **No output when enabled** – ensure `sinks` is not empty and that the process can write to `dir` when using `jsonl`.
- **Missing LangSmith events** – install `langsmith` and populate the required credentials (`LANGSMITH_API_KEY`, etc.).
- **Sensitive data still present** – add custom keys to `deny_keys` or redact data before returning it from your tools/LLM wrappers.

Tracing remains optional—remove the `tracing` block or set `enabled: false` to turn it off.
