"""Context variables for tracing identifiers."""

from __future__ import annotations

import contextvars

run_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("run_id", default=None)
span_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("span_id", default=None)
trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)

trace_enabled_var: contextvars.ContextVar[bool] = contextvars.ContextVar("trace_enabled", default=False)
