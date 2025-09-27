"""Decorators that instrument runtime execution for structured logging."""

from __future__ import annotations

import functools
import inspect
import uuid
from typing import Any, Awaitable, Callable, Dict, Tuple

from . import get_log_manager
from .context import run_id_var, trace_enabled_var, trace_id_var


def log_run(fn: Callable[..., Any]) -> Callable[..., Any]:
    manager = get_log_manager()

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not manager.enabled:
                return await fn(*args, **kwargs)

            sampled = manager.should_sample()
            trace_token = trace_enabled_var.set(sampled)
            if not sampled:
                try:
                    return await fn(*args, **kwargs)
                finally:
                    trace_enabled_var.reset(trace_token)

            run_id = uuid.uuid4().hex
            run_token = run_id_var.set(run_id)
            trace_token2 = trace_id_var.set(run_id)

            span_id = manager.start_span(
                "run",
                event="run_start",
                run_id=run_id,
                level="info",
                input_summary=manager.summarize(_extract_argument(fn, args, kwargs, "inputs")),
            )
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                manager.emit(
                    {
                        "event": "run_exception",
                        "level": "error",
                        "run_id": run_id,
                        "error": repr(exc),
                    }
                )
                manager.end_span(span_id, event="run_end", level="error", status="error")
                raise
            else:
                manager.end_span(
                    span_id,
                    event="run_end",
                    status="ok",
                    output_summary=manager.summarize(result),
                )
                return result
            finally:
                trace_id_var.reset(trace_token2)
                run_id_var.reset(run_token)
                trace_enabled_var.reset(trace_token)

        return async_wrapper

    @functools.wraps(fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        if not manager.enabled:
            return fn(*args, **kwargs)

        sampled = manager.should_sample()
        trace_token = trace_enabled_var.set(sampled)
        if not sampled:
            try:
                return fn(*args, **kwargs)
            finally:
                trace_enabled_var.reset(trace_token)

        run_id = uuid.uuid4().hex
        run_token = run_id_var.set(run_id)
        trace_token2 = trace_id_var.set(run_id)

        span_id = manager.start_span(
            "run",
            event="run_start",
            run_id=run_id,
            level="info",
            input_summary=manager.summarize(_extract_argument(fn, args, kwargs, "inputs")),
        )
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            manager.emit(
                {
                    "event": "run_exception",
                    "level": "error",
                    "run_id": run_id,
                    "error": repr(exc),
                }
            )
            manager.end_span(span_id, event="run_end", level="error", status="error")
            raise
        else:
            manager.end_span(
                span_id,
                event="run_end",
                status="ok",
                output_summary=manager.summarize(result),
            )
            return result
        finally:
            trace_id_var.reset(trace_token2)
            run_id_var.reset(run_token)
            trace_enabled_var.reset(trace_token)

    return sync_wrapper


def log_node(fn: Callable[..., Any]) -> Callable[..., Any]:
    manager = get_log_manager()

    def before(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        if not manager.enabled:
            return {}
        bound = _bind_arguments(fn, args, kwargs)
        node = bound.arguments.get("node")
        graph = bound.arguments.get("graph")
        graph_name = getattr(graph, "name", None)
        node_id = getattr(node, "id", None)
        node_type = getattr(node, "type", None)
        state = bound.arguments.get("state")
        ctx = {
            "span_id": manager.start_span(
                "node",
                event="node_start",
                level="info",
                graph=graph_name,
                node_id=node_id,
                node_type=node_type,
                input_summary=manager.summarize(bound.arguments.get("inputs")),
            ),
            "state_keys": set(state.keys()) if isinstance(state, dict) else set(),
            "graph": graph_name,
            "node_id": node_id,
            "node_type": node_type,
        }
        return ctx

    def after(result: Any, ctx: Dict[str, Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
        if not ctx:
            return
        success, output, next_nodes = (result if isinstance(result, tuple) else (True, result, None))
        bound = _bind_arguments(fn, args, kwargs)
        state = bound.arguments.get("state")
        state_keys_after = set(state.keys()) if isinstance(state, dict) else set()
        diff = _diff_keys(ctx.get("state_keys", set()), state_keys_after)
        manager.end_span(
            ctx["span_id"],
            event="node_end",
            status="ok" if success else "error",
            graph=ctx.get("graph"),
            node_id=ctx.get("node_id"),
            node_type=ctx.get("node_type"),
            output_summary=manager.summarize(output),
            state_diff_keys=diff,
        )

    def on_error(exc: Exception, ctx: Dict[str, Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
        if not ctx:
            return
        manager.emit(
            {
                "event": "node_exception",
                "level": "error",
                "graph": ctx.get("graph"),
                "node_id": ctx.get("node_id"),
                "node_type": ctx.get("node_type"),
                "error": repr(exc),
            }
        )
        manager.end_span(
            ctx["span_id"],
            event="node_end",
            level="error",
            status="error",
        )

    return _wrap_callable(fn, before, after, on_error)


def log_tool(tool_id: str, tool_kind: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    manager = get_log_manager()

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def before(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Dict[str, Any]:
            if not manager.enabled:
                return {}
            return {
                "span_id": manager.start_span(
                    "tool",
                    event="tool_start",
                    level="info",
                    tool_id=tool_id,
                    tool_kind=tool_kind,
                    input_summary=manager.summarize(kwargs or args),
                )
            }

        def after(result: Any, ctx: Dict[str, Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
            if not ctx:
                return
            manager.end_span(
                ctx["span_id"],
                event="tool_end",
                status="ok",
                tool_id=tool_id,
                tool_kind=tool_kind,
                output_summary=manager.summarize(result),
            )

        def on_error(exc: Exception, ctx: Dict[str, Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
            if not ctx:
                return
            manager.emit(
                {
                    "event": "tool_exception",
                    "level": "error",
                    "tool_id": tool_id,
                    "tool_kind": tool_kind,
                    "error": repr(exc),
                }
            )
            manager.end_span(
                ctx["span_id"],
                event="tool_end",
                level="error",
                status="error",
            )

        return _wrap_callable(fn, before, after, on_error)

    return decorator


def log_llm(provider: str | None, model: str | None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    manager = get_log_manager()

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        def before(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Dict[str, Any]:
            if not manager.enabled:
                return {}
            bound = _bind_arguments(fn, args, kwargs)
            node = bound.arguments.get("node")
            prompt = bound.arguments.get("prompt")
            span_id = manager.start_span(
                "llm",
                event="llm_start",
                level="info",
                node_id=getattr(node, "id", None),
                provider=provider,
                model=model,
                input_summary=manager.summarize(prompt),
            )
            return {"span_id": span_id, "node_id": getattr(node, "id", None)}

        def after(result: Any, ctx: Dict[str, Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
            if not ctx:
                return
            meta = {
                "event": "llm_end",
                "status": "ok",
                "provider": provider,
                "model": model,
                "node_id": ctx.get("node_id"),
                "output_summary": manager.summarize(result),
            }
            manager.end_span(ctx["span_id"], **meta)

        def on_error(exc: Exception, ctx: Dict[str, Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> None:
            if not ctx:
                return
            manager.emit(
                {
                    "event": "llm_exception",
                    "level": "error",
                    "provider": provider,
                    "model": model,
                    "error": repr(exc),
                }
            )
            manager.end_span(ctx["span_id"], event="llm_end", level="error", status="error")

        return _wrap_callable(fn, before, after, on_error)

    return decorator


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _wrap_callable(
    fn: Callable[..., Any],
    before: Callable[[Tuple[Any, ...], Dict[str, Any]], Dict[str, Any]],
    after: Callable[[Any, Dict[str, Any], Tuple[Any, ...], Dict[str, Any]], None],
    on_error: Callable[[Exception, Dict[str, Any], Tuple[Any, ...], Dict[str, Any]], None],
) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            ctx = before(args, kwargs)
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                on_error(exc, ctx, args, kwargs)
                raise
            after(result, ctx, args, kwargs)
            return result

        return async_wrapper

    @functools.wraps(fn)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx = before(args, kwargs)
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            on_error(exc, ctx, args, kwargs)
            raise
        after(result, ctx, args, kwargs)
        return result

    return sync_wrapper


def _bind_arguments(fn: Callable[..., Any], args: Tuple[Any, ...], kwargs: Dict[str, Any]):
    signature = inspect.signature(fn)
    bound = signature.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    return bound


def _diff_keys(before: set[str], after: set[str]) -> Dict[str, list[str]]:
    added = sorted(after - before)
    removed = sorted(before - after)
    diff: Dict[str, list[str]] = {}
    if added:
        diff["added"] = added
    if removed:
        diff["removed"] = removed
    return diff


def _extract_argument(fn: Callable[..., Any], args: Tuple[Any, ...], kwargs: Dict[str, Any], name: str) -> Any:
    try:
        bound = _bind_arguments(fn, args, kwargs)
        return bound.arguments.get(name)
    except Exception:
        return None
