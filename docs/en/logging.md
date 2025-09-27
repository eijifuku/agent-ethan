# Tracing & Logging

Agent Ethan includes an optional structured tracing facility that records high-level run, node, tool, and LLM events. Tracing is off by default; enable it with environment variables so runtime behaviour remains unchanged unless you opt in.

## Quick Start

```bash
export AE_TRACE_ENABLED=true
export AE_TRACE_SINKS=stdout,jsonl
python -m agent_ethan.examples.simple_agent
```

With tracing enabled the runtime automatically emits JSON events, for example:

```json
{"ts":"2025-09-27T13:35:20.481Z","event":"run_start","run_id":"f6a0...","graph":"support_flow","level":"info"}
```

## Configuration Reference

- `AE_TRACE_ENABLED` – master on/off switch (`false` by default).
- `AE_TRACE_SINKS` – comma-separated sinks: `stdout`, `jsonl`, `langsmith`, or `null`.
- `AE_TRACE_SAMPLE` – sampling rate between `0.0` and `1.0` (default `1.0`).
- `AE_TRACE_LEVEL` – minimum level to record (`debug`, `info`, `warn`, `error`; default `info`).
- `AE_TRACE_DIR` – root directory for JSONL files (default `./logs`).
- `AE_TRACE_LANGSMITH_PROJECT` – optional LangSmith project name.
- `AE_TRACE_MAX_TEXT` – truncate long strings after N characters (default `2048`).
- `AE_TRACE_DENY_KEYS` – comma-separated list of additional keys to redact.

If `AE_TRACE_SINKS` is empty or resolves to `null`, the logger installs a `NullSink` that drops all events even when tracing is enabled. This is useful in sampling scenarios where non-sampled runs should avoid any logging overhead.

### Sinks

- **Stdout** – prints one JSON object per line to standard output.
- **Jsonl** – writes per-run JSONL files under `AE_TRACE_DIR/<date>/<run_id>.jsonl`.
- **LangSmith** – forwards events to LangSmith. The optional dependency `langsmith` must be installed; otherwise the sink is silently disabled with a warning.
- **Null** – discards everything (useful when you only want to flip sampling on/off).

You can combine multiple sinks, e.g. `AE_TRACE_SINKS=stdout,langsmith`.

### Sampling & Levels

When a run starts, the logger draws a random number and compares it to `AE_TRACE_SAMPLE`. If the run is not sampled, instrumentation switches to a `NullSink` so decorators return immediately. Level filtering is applied per-event after masking; set `AE_TRACE_LEVEL=debug` to capture router decisions and loop summaries.

### Masking & Payload Summaries

The logger guards against leaking secrets by redacting values whose keys match a deny list (`api_key`, `token`, `password`, etc.) and by applying regex-based replacements (e.g. `Bearer ...`). You can extend the deny list via `AE_TRACE_DENY_KEYS=client_secret,my_secret`. Long strings are truncated to `AE_TRACE_MAX_TEXT` characters; summaries store the original key set and a preview rather than full payloads.

### Event Types

Instrumentation touches the main runtime layers:

- **Runs** – `run_start`, `run_end`, and `run_exception` with input/output summaries.
- **Nodes** – `node_start`, `node_end`, and `node_exception` include node id/type, graph name, and state diff keys.
- **Tools** – `tool_start`, `tool_end`, and `tool_exception` carry tool id/kind plus payload summaries.
- **LLMs** – `llm_start`, `llm_end`, and `llm_exception` include provider/model metadata and prompt/output summaries.
- **Routers & Loops** – additional `router_decision` and `loop_complete` events capture branch selection and iteration counts.

Every event shares `ts`, `run_id`, `span_id`, and `trace_id` fields to help visualise execution flow. Spans nest based on node/tool/LLM relationships.

## Custom Setups

The module `agent_ethan.logging` exposes `configure_from_env()` and `set_log_manager()` if you need programmatic control. For instance, tests can install an in-memory sink:

```python
from agent_ethan.logging import LogManager, set_log_manager
from agent_ethan.logging.sinks import Sink

class ListSink(Sink):
    def __init__(self):
        self.events = []
    def emit(self, event):
        self.events.append(event)

sink = ListSink()
set_log_manager(LogManager(sinks=[sink], sample_rate=1.0))
```

Keep the existing decorators in place; they automatically pick up the active `LogManager` instance. When tracing is disabled the overhead is negligible because the decorators exit early.

## Troubleshooting

- **No output when enabled** – ensure `AE_TRACE_SINKS` is set and not `null`; check the process has write access to `AE_TRACE_DIR`.
- **Missing LangSmith events** – confirm `pip install langsmith` and the required environment variables (`LANGSMITH_API_KEY`, etc.) are present.
- **Sensitive data still present** – add custom keys via `AE_TRACE_DENY_KEYS` or wrap tools/LLMs to pre-redact data before returning it.

Tracing is still optional; if you do not define `AE_TRACE_ENABLED` the runtime behaves exactly as before.
