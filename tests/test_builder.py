import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from unittest.mock import patch
from types import ModuleType

try:
    from langchain_core.tools import BaseTool as _LangchainBaseTool
except ImportError:  # pragma: no cover - optional dependency in tests
    _LangchainBaseTool = None


if _LangchainBaseTool is not None:

    class ExampleLangchainTool(_LangchainBaseTool):
        name: str = "example_langchain_tool"
        description: str = "Uppercases input for testing"

        def _run(self, text: str) -> str:
            return text.upper()

        async def _arun(self, *args: Any, **kwargs: Any) -> str:
            raise NotImplementedError

else:  # pragma: no cover - optional dependency in tests
    ExampleLangchainTool = None

os.environ.setdefault("OPENAI_COMPATIBLE_BASE_URL", "http://127.0.0.1:1234/v1")

from agent_ethan.builder import (
    AgentRuntime,
    AgentRuntimeError,
    NodeExecutionError,
    build_agent_from_path,
    build_agent_from_yaml,
)
from agent_ethan.llm import LLMClient
from agent_ethan.providers import create_openai_client, create_openai_compatible_client
from agent_ethan.schema import LLMNode

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = PROJECT_ROOT / "examples"

BASE_CONFIG = {
    "meta": {
        "schema_version": 1,
        "name": "test_agent",
        "defaults": {
            "llm": "openai:gpt-4o-mini",
            "temp": 0.0,
        },
    },
    "state": {
        "shape": {
            "query": "str",
            "route_type": "str | null",
            "context": "list",
            "answer": "str | null",
            "item_type": "str | null",
            "count": "int",
            "history": "dict",
            "final": "str | null",
            "target": "int | null",
            "messages": "list",
            "messages_window": "list",
            "session_id": "str | null",
        },
        "reducer": "deepmerge",
        "init": {
            "context": [],
            "answer": None,
            "item_type": None,
            "count": 0,
            "history": {"values": []},
            "final": None,
            "route_type": None,
            "target": None,
            "messages": [],
            "messages_window": [],
            "session_id": None,
        },
    },
    "prompts": {
        "partials": {
            "sys_base": "ベース",
        },
        "templates": {
            "answer": {
                "system": "{{> sys_base }}",
                "user": "質問: {{ query }}",
            }
        },
    },
    "tools": [
        {"id": "echo", "kind": "python", "impl": "agent_ethan/tools/mock_tools.py#echo"},
        {"id": "increment", "kind": "python", "impl": "agent_ethan/tools/mock_tools.py#increment"},
        {"id": "fail", "kind": "python", "impl": "agent_ethan/tools/mock_tools.py#failing"},
    ],
}


class BuilderTestCase(unittest.TestCase):
    def test_build_agent_from_example(self) -> None:
        runtime = build_agent_from_path(FIXTURES / "rag_agent.yaml")

        self.assertEqual(runtime.definition.config.meta.name, "rag_agent")
        self.assertIn("local_search", runtime.tools)
        self.assertEqual(runtime.graph.nodes["search"].type, "tool")

        rendered = runtime.prompts.render("answer", "system", {"query": "Q", "context": []})
        self.assertIn("アシスタント", rendered)

    def test_build_arxiv_agent(self) -> None:
        runtime = build_agent_from_path(FIXTURES / "arxiv_agent.yaml")

        self.assertIn("arxiv_search", runtime.tools)
        self.assertIn("arxiv_download", runtime.tools)
        self.assertIn("arxiv_select", runtime.tools)
        self.assertIn("keyword_fallback", runtime.tools)
        self.assertIn("summary_fallback", runtime.tools)
        self.assertEqual(runtime.graph.nodes["download"].type, "tool")

    def test_build_agent_from_dict(self) -> None:
        with (FIXTURES / "rag_agent.yaml").open("r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        runtime = build_agent_from_yaml(config, base_path=FIXTURES)
        self.assertEqual(runtime.graph.max_steps, 200)


class RuntimeExecutionTestCase(unittest.TestCase):
    def _runtime(self, graph: dict, *, subgraphs: Optional[dict] = None) -> AgentRuntime:
        config = deepcopy(BASE_CONFIG)
        config["graph"] = graph
        if subgraphs:
            config["subgraphs"] = subgraphs
        return build_agent_from_yaml(config, base_path=PROJECT_ROOT)

    def test_router_executes_branch(self) -> None:
        graph = {
            "inputs": ["query", "route_type"],
            "outputs": ["answer", "context"],
            "nodes": [
                {
                    "id": "fetch",
                    "type": "tool",
                    "uses": "echo",
                    "inputs": {
                        "json": {
                            "type": "{{ inputs.route_type }}",
                            "items": ["doc1"],
                        }
                    },
                    "map": {
                        "set": {
                            "context": "{{ result['items'] }}",
                            "item_type": "{{ result.json.type }}",
                        }
                    },
                },
                {
                    "id": "branch",
                    "type": "router",
                    "cases": [
                        {"when": {"==": [{"var": "state.item_type"}, "A"]}, "to": "handle_a"}
                    ],
                    "default": "handle_other",
                },
                {
                    "id": "handle_a",
                    "type": "noop",
                    "map": {"set": {"answer": "routed_A"}},
                },
                {
                    "id": "handle_other",
                    "type": "noop",
                    "map": {"set": {"answer": "routed_other"}},
                },
            ],
            "edges": [
                {"from": "fetch", "to": "branch"},
            ],
        }

        runtime = self._runtime(graph)
        state = runtime.run({"query": "test", "route_type": "A"})

        self.assertEqual(state["answer"], "routed_A")
        self.assertEqual(state["context"], ["doc1"])

    def test_loop_updates_state_until_condition(self) -> None:
        graph = {
            "inputs": ["target"],
            "outputs": ["count", "history"],
            "nodes": [
                {
                    "id": "increment_loop",
                    "type": "loop",
                    "body": "add_one",
                    "until": {"==": [{"var": "state.count"}, {"var": "inputs.target"}]},
                    "max_iterations": 10,
                },
                {
                    "id": "add_one",
                    "type": "tool",
                    "uses": "increment",
                    "inputs": {"current": "{{ state.count }}"},
                    "map": {
                        "set": {"count": "{{ result.json.count }}"},
                        "merge": {"history": {"values": ["{{ result.json.count }}"]}},
                    },
                },
                {
                    "id": "summarise",
                    "type": "noop",
                    "map": {"set": {"final": "done", "answer": "{{ state.count }}"}},
                },
            ],
            "edges": [
                {"from": "increment_loop", "to": "summarise"},
            ],
        }

        runtime = self._runtime(graph)
        state = runtime.run({"target": 3})

        self.assertEqual(state["count"], 3)
        self.assertEqual(state["answer"], 3)
        self.assertEqual(state["history"]["values"], [1, 2, 3])

    def test_memory_persists_messages_between_runs(self) -> None:
        config = deepcopy(BASE_CONFIG)
        config["memory"] = {
            "enabled": True,
            "type": "langchain_history",
            "kind": "inmemory",
            "k": 2,
        }
        config["graph"] = {
            "inputs": ["query", "session_id"],
            "outputs": ["messages"],
            "nodes": [
                {
                    "id": "record",
                    "type": "noop",
                    "map": {
                        "set": {
                            "messages": "{{ (state.messages or []) + [{'type': 'human', 'role': 'user', 'content': query}] }}",
                            "session_id": "{{ inputs.session_id }}",
                        }
                    },
                }
            ],
            "edges": [],
        }

        runtime = build_agent_from_yaml(config, base_path=PROJECT_ROOT)

        first = runtime.run({"query": "hello", "session_id": "thread-1"})
        self.assertEqual(len(first["messages"]), 1)
        self.assertEqual(first["messages"][0]["content"], "hello")
        self.assertIn("messages_window", first)
        self.assertEqual(len(first["messages_window"]), 1)

        second = runtime.run({"query": "again", "session_id": "thread-1"})
        self.assertEqual(len(second["messages"]), 2)
        self.assertEqual([msg["content"] for msg in second["messages"]], ["hello", "again"])
        self.assertEqual(len(second["messages_window"]), 2)

        third = runtime.run({"query": "fresh", "session_id": "thread-2"})
        self.assertEqual(len(third["messages"]), 1)
        self.assertEqual(third["messages"][0]["content"], "fresh")

    def test_langchain_class_tool_executes(self) -> None:
        module_names = [
            "langchain_core",
            "langchain_core.tools",
            "langchain_core.tools.base",
            "tests.fake_langchain_tool",
        ]
        preserved_modules = {name: sys.modules.get(name) for name in module_names}

        fake_core = ModuleType("langchain_core")
        fake_tools = ModuleType("langchain_core.tools")

        class FakeBaseTool:
            def __init__(self, prefix: str = "") -> None:
                self.prefix = prefix

            def invoke(self, payload: Any) -> Dict[str, Any]:
                value = payload if isinstance(payload, str) else payload.get("text", "")
                text = f"{self.prefix}{value}"
                return {"text": text, "items": [value]}

        fake_tools.BaseTool = FakeBaseTool
        fake_core.tools = fake_tools

        tool_module = ModuleType("tests.fake_langchain_tool")

        class EchoTool(FakeBaseTool):
            pass

        tool_module.EchoTool = EchoTool

        sys.modules.update(
            {
                "langchain_core": fake_core,
                "langchain_core.tools": fake_tools,
                "langchain_core.tools.base": fake_tools,
                "tests.fake_langchain_tool": tool_module,
            }
        )

        try:
            config = deepcopy(BASE_CONFIG)
            config["tools"].append(
                {
                    "id": "langchain_echo",
                    "kind": "langchain",
                    "mode": "class",
                    "impl": "tests.fake_langchain_tool#EchoTool",
                    "config": {
                        "init": {"prefix": "lc:"},
                        "input_key": "text",
                    },
                }
            )
            config["graph"] = {
                "inputs": ["text"],
                "outputs": ["final"],
                "nodes": [
                    {
                        "id": "invoke_langchain",
                        "type": "tool",
                        "uses": "langchain_echo",
                        "inputs": {"text": "{{ inputs.text }}"},
                        "map": {
                            "set": {
                                "final": "{{ result.text }}",
                                "context": "{{ result['items'] }}",
                            }
                        },
                    },
                ],
            }

            runtime = build_agent_from_yaml(config, base_path=PROJECT_ROOT)
            state = runtime.run({"text": "payload"})

            self.assertEqual(state["final"], "lc:payload")
            self.assertEqual(state["context"], ["payload"])
        finally:
            for name, module in preserved_modules.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def test_langchain_tool_with_real_basetool(self) -> None:
        if ExampleLangchainTool is None:
            self.skipTest("langchain_core not installed")

        config = deepcopy(BASE_CONFIG)
        config["tools"].append(
            {
                "id": "langchain_upper",
                "kind": "langchain",
                "mode": "class",
                "impl": "tests.test_builder#ExampleLangchainTool",
            }
        )
        config["graph"] = {
            "inputs": ["text"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "upper",
                    "type": "tool",
                    "uses": "langchain_upper",
                    "inputs": {"text": "{{ inputs.text }}"},
                    "map": {"set": {"answer": "{{ result.text }}"}},
                }
            ],
        }

        runtime = build_agent_from_yaml(config, base_path=PROJECT_ROOT)
        state = runtime.run({"text": "payload"})

        self.assertEqual(state["answer"], "PAYLOAD")
    def test_on_error_redirects_to_fallback(self) -> None:
        graph = {
            "inputs": ["query"],
            "outputs": ["answer", "final"],
            "nodes": [
                {
                    "id": "risky",
                    "type": "tool",
                    "uses": "fail",
                    "on_error": {"to": "recover", "resume": True},
                },
                {
                    "id": "recover",
                    "type": "noop",
                    "map": {"set": {"answer": "fallback"}},
                },
                {
                    "id": "success",
                    "type": "noop",
                    "map": {"set": {"final": "done"}},
                },
            ],
            "edges": [
                {"from": "risky", "to": "success"},
                {"from": "recover", "to": "success"},
            ],
        }

        runtime = self._runtime(graph)
        state = runtime.run({"query": "ignored"})

        self.assertEqual(state["answer"], "fallback")
        self.assertEqual(state["final"], "done")

    def test_missing_input_raises(self) -> None:
        graph = {
            "inputs": ["required"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "starter",
                    "type": "noop",
                    "map": {"set": {"answer": "ok"}},
                }
            ],
            "edges": [],
        }

        runtime = self._runtime(graph)
        with self.assertRaises(AgentRuntimeError):
            runtime.run({})

    def test_node_failure_without_handler_raises(self) -> None:
        graph = {
            "inputs": ["query"],
            "outputs": ["final"],
            "nodes": [
                {
                    "id": "risky",
                    "type": "tool",
                    "uses": "fail",
                }
            ],
            "edges": [],
        }

        runtime = self._runtime(graph)
        with self.assertRaises(NodeExecutionError):
            runtime.run({"query": "ignored"})

    def test_graph_cycle_detection(self) -> None:
        graph = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {"id": "a", "type": "noop"},
                {"id": "b", "type": "noop"},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"},
            ],
        }

        with self.assertRaises(ValueError) as exc:
            self._runtime(graph)
        self.assertIn("cycle", str(exc.exception))

    def test_loop_body_cycle_detection(self) -> None:
        graph = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "loop",
                    "type": "loop",
                    "body": "loop",
                }
            ],
            "edges": [],
        }

        with self.assertRaises(ValueError) as exc:
            self._runtime(graph)
        self.assertIn("cycle", str(exc.exception))

    def test_subgraph_executes_nested_graph(self) -> None:
        main_graph = {
            "inputs": ["query"],
            "outputs": ["final", "history"],
            "nodes": [
                {
                    "id": "prep",
                    "type": "noop",
                    "map": {"set": {"route_type": "{{ inputs.query }}"}},
                },
                {
                    "id": "delegate",
                    "type": "subgraph",
                    "graph": "summary",
                    "inputs": {"route_type": "{{ state.route_type }}"},
                    "map": {"set": {"final": "{{ result.outputs.answer }}"}},
                },
            ],
            "edges": [
                {"from": "prep", "to": "delegate"},
            ],
        }

        subgraphs = {
            "summary": {
                "inputs": ["route_type"],
                "outputs": ["answer", "history"],
                "nodes": [
                    {
                        "id": "respond",
                        "type": "noop",
                        "map": {
                            "set": {"answer": "{{ 'sub-' ~ inputs.route_type }}"},
                            "merge": {"history": {"values": ["{{ inputs.route_type }}"]}},
                        },
                    }
                ],
                "edges": [],
            }
        }

        runtime = self._runtime(main_graph, subgraphs=subgraphs)
        state = runtime.run({"query": "A"})

        self.assertEqual(state["final"], "sub-A")
        self.assertEqual(state["history"]["values"], ["A"])

    def test_subgraph_cycle_detection(self) -> None:
        main_graph = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "delegate",
                    "type": "subgraph",
                    "graph": "loop",
                }
            ],
            "edges": [],
        }

        subgraphs = {
            "loop": {
                "inputs": ["query"],
                "outputs": ["answer"],
                "nodes": [
                    {
                        "id": "inner",
                        "type": "subgraph",
                        "graph": "loop",
                    }
                ],
                "edges": [],
            }
        }

        with self.assertRaises(ValueError) as exc:
            self._runtime(main_graph, subgraphs=subgraphs)
        self.assertIn("subgraph", str(exc.exception))

    @patch("agent_ethan.builder.create_openai_client")
    def test_default_provider_llm_client(self, mock_create) -> None:
        config = deepcopy(BASE_CONFIG)
        config["graph"] = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "prompt": "answer",
                    "map": {"set": {"answer": "{{ result.text }}"}},
                }
            ],
            "edges": [],
        }
        config["meta"]["defaults"]["llm"] = "openai:gpt-mini"
        config["meta"]["providers"] = {
            "openai": {
                "type": "openai",
                "temperature": 0.42,
                "kwargs": {"foo": "{{env.PROVIDER_FOO}}"},
            }
        }

        def _llm_call(*, node, prompt, timeout=None):
            return {"text": "auto", "error": None}

        mock_create.return_value = LLMClient(call=_llm_call)

        with patch.dict(os.environ, {"PROVIDER_FOO": "bar"}):
            runtime = build_agent_from_yaml(config, base_path=PROJECT_ROOT)
            state = runtime.run({"query": "hello"})

        self.assertEqual(state["answer"], "auto")
        self.assertTrue(mock_create.called)
        call_kwargs = mock_create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gpt-mini")
        self.assertEqual(call_kwargs["temperature"], 0.42)
        self.assertEqual(call_kwargs["default_kwargs"], {"foo": "bar"})

    @patch("agent_ethan.builder.create_openai_compatible_client")
    def test_default_provider_openai_compatible_client(self, mock_create) -> None:
        config = deepcopy(BASE_CONFIG)
        config["meta"]["defaults"]["llm"] = "local:lmstudio-model"
        config["meta"]["providers"] = {
            "local": {
                "type": "lmstudio",
                "temperature": 0.12,
                "base_url": "http://localhost:4455/v1",
                "api_key": "{{env.LM_API_KEY}}",
                "request_timeout": 30.0,
                "headers": {"X-Test": "1"},
                "kwargs": {"max_tokens": 256},
            }
        }
        config["graph"] = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "prompt": "answer",
                    "map": {"set": {"answer": "{{ result.text }}"}},
                }
            ],
            "edges": [],
        }

        def _llm_call(*, node, prompt, timeout=None):
            return {"text": "local", "error": None}

        mock_create.return_value = LLMClient(call=_llm_call)

        with patch.dict(os.environ, {"LM_API_KEY": "secret"}):
            runtime = build_agent_from_yaml(config, base_path=PROJECT_ROOT)
            state = runtime.run({"query": "hello"})

        self.assertEqual(state["answer"], "local")
        self.assertTrue(mock_create.called)
        call_kwargs = mock_create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "lmstudio-model")
        self.assertEqual(call_kwargs["temperature"], 0.12)
        self.assertEqual(call_kwargs["base_url"], "http://localhost:4455/v1")
        self.assertEqual(call_kwargs["api_key"], "secret")
        self.assertEqual(call_kwargs["default_kwargs"], {"max_tokens": 256})
        self.assertEqual(call_kwargs["request_timeout"], 30.0)
        self.assertEqual(call_kwargs["headers"], {"X-Test": "1"})

    @patch("agent_ethan.builder.create_gemini_client")
    def test_default_provider_gemini_client(self, mock_create) -> None:
        config = deepcopy(BASE_CONFIG)
        config["meta"]["defaults"]["llm"] = "gemini:gemini-1.5-flash"
        config["meta"]["providers"] = {
            "gemini": {
                "type": "gemini",
                "model": "gemini-1.5-flash",
                "api_key": "{{env.GEMINI_API_KEY}}",
                "temperature": 0.25,
                "top_p": 0.8,
                "top_k": 32,
                "kwargs": {"safety_settings": "strict"},
            }
        }
        config["graph"] = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "prompt": "answer",
                    "map": {"set": {"answer": "{{ result.text }}"}},
                }
            ],
            "edges": [],
        }

        mock_create.return_value = LLMClient(call=lambda **_: {"text": "gemini", "error": None})

        with patch.dict(os.environ, {"GEMINI_API_KEY": "g-key"}):
            runtime = build_agent_from_yaml(config, base_path=PROJECT_ROOT)
            state = runtime.run({"query": "hello"})

        self.assertEqual(state["answer"], "gemini")
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gemini-1.5-flash")
        self.assertEqual(call_kwargs["api_key"], "g-key")
        self.assertEqual(call_kwargs["temperature"], 0.25)
        self.assertEqual(call_kwargs["top_p"], 0.8)
        self.assertEqual(call_kwargs["top_k"], 32)
        self.assertEqual(call_kwargs["default_kwargs"], {"safety_settings": "strict"})

    @patch("agent_ethan.builder.create_claude_client")
    def test_default_provider_claude_client(self, mock_create) -> None:
        config = deepcopy(BASE_CONFIG)
        config["meta"]["defaults"]["llm"] = "claude:claude-3-sonnet"
        config["meta"]["providers"] = {
            "claude": {
                "type": "claude",
                "model": "claude-3-sonnet-20240229",
                "api_key": "{{env.ANTHROPIC_API_KEY}}",
                "temperature": 0.1,
                "max_tokens": 900,
                "kwargs": {"extra_headers": {"anthropic-beta": "prompt-caching"}},
            }
        }
        config["graph"] = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "prompt": "answer",
                    "map": {"set": {"answer": "{{ result.text }}"}},
                }
            ],
            "edges": [],
        }

        mock_create.return_value = LLMClient(call=lambda **_: {"text": "claude", "error": None})

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "a-key"}):
            runtime = build_agent_from_yaml(config, base_path=PROJECT_ROOT)
            state = runtime.run({"query": "hello"})

        self.assertEqual(state["answer"], "claude")
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "claude-3-sonnet-20240229")
        self.assertEqual(call_kwargs["api_key"], "a-key")
        self.assertEqual(call_kwargs["temperature"], 0.1)
        self.assertEqual(call_kwargs["max_tokens"], 900)
        self.assertEqual(call_kwargs["default_kwargs"], {"extra_headers": {"anthropic-beta": "prompt-caching"}})

    def test_subgraph_depth_limit(self) -> None:
        main_graph = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {"id": "start", "type": "subgraph", "graph": "sg1"}
            ],
            "edges": [],
        }

        subgraphs = {
            "sg1": {
                "inputs": ["query"],
                "outputs": ["answer"],
                "nodes": [
                    {"id": "next", "type": "subgraph", "graph": "sg2"}
                ],
                "edges": [],
            },
            "sg2": {
                "inputs": ["query"],
                "outputs": ["answer"],
                "nodes": [
                    {"id": "noop", "type": "noop"}
                ],
                "edges": [],
            },
        }

        runtime = self._runtime(main_graph, subgraphs=subgraphs)
        stub_llm = LLMClient(call=lambda *, node, prompt, timeout=None: {"text": "", "error": None})

        with self.assertRaises(AgentRuntimeError):
            runtime.run({"query": "q"}, llm_client=stub_llm, max_subgraph_depth=1)

    def test_llm_client_retry(self) -> None:
        graph = {
            "inputs": ["query"],
            "outputs": ["answer"],
            "nodes": [
                {
                    "id": "ask",
                    "type": "llm",
                    "prompt": "answer",
                    "retry": {"max_attempts": 2, "backoff": 0},
                    "map": {"set": {"answer": "{{ result.text }}"}},
                }
            ],
            "edges": [],
        }

        runtime = self._runtime(graph)
        attempts = {"count": 0}

        def fake_llm(*, node, prompt, timeout=None):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return {"error": {"message": "retry"}, "text": None}
            return {"status": 200, "text": "ok", "error": None}

        client = LLMClient(call=fake_llm)
        state = runtime.run({"query": "ignored"}, llm_client=client)

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(state["answer"], "ok")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class ProviderAdapterTestCase(unittest.TestCase):
    def test_openai_client_formats_messages(self) -> None:
        class DummyChoice:
            def __init__(self, content: str) -> None:
                self.message = {"content": content}

        class DummyResponse:
            def __init__(self, content: str) -> None:
                self.choices = [DummyChoice(content)]

        class DummyCompletions:
            def __init__(self, parent: "DummyChat") -> None:
                self.parent = parent

            def create(self, **kwargs: Any) -> DummyResponse:
                self.parent.calls.append(kwargs)
                return DummyResponse("OK")

        class DummyChat:
            def __init__(self, outer: "DummyClient") -> None:
                self.outer = outer
                self.calls: List[Dict[str, Any]] = []
                self.completions = DummyCompletions(self)

        class DummyClient:
            def __init__(self) -> None:
                self.chat = DummyChat(self)

        dummy = DummyClient()
        client = create_openai_client(model="gpt-test", client=dummy)
        node = LLMNode(id="ask", prompt="answer")
        prompt = {"system": "sys", "user": "hi", "messages[0]#assistant": "prev"}

        result = client.generate(node=node, prompt=prompt, retry=None, timeout=1.0)

        self.assertEqual(result["text"], "OK")
        self.assertEqual(len(dummy.chat.calls), 1)
        call = dummy.chat.calls[0]
        self.assertEqual(call["model"], "gpt-test")
        self.assertEqual(call["temperature"], 0.0)
        roles = [msg["role"] for msg in call["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant"])

    def test_openai_compatible_client_formats_messages(self) -> None:
        class DummyResponse:
            def __init__(self, payload: Dict[str, Any]) -> None:
                self.payload = payload
                self.status_code = 200

            def json(self) -> Dict[str, Any]:
                return self.payload

            def raise_for_status(self) -> None:
                return None

        class DummyClient:
            def __init__(self) -> None:
                self.calls: List[Any] = []

            def post(self, path: str, **kwargs: Any) -> DummyResponse:
                self.calls.append((path, kwargs))
                return DummyResponse({"choices": [{"message": {"content": "OK"}}]})

        dummy = DummyClient()
        client = create_openai_compatible_client(
            model="local-model",
            client=dummy,
            default_kwargs={"top_p": 0.9},
            request_timeout=5.0,
        )
        node = LLMNode(id="ask", prompt="answer")
        prompt = {"system": "sys", "user": "hi", "messages[0]#assistant": "prev"}

        result = client.generate(node=node, prompt=prompt, retry=None, timeout=1.2)

        self.assertEqual(result["text"], "OK")
        self.assertEqual(len(dummy.calls), 1)
        path, kwargs = dummy.calls[0]
        self.assertEqual(path, "/chat/completions")
        payload = kwargs["json"]
        self.assertEqual(payload["model"], "local-model")
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["top_p"], 0.9)
        roles = [msg["role"] for msg in payload["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant"])
        self.assertEqual(kwargs["timeout"], 1.2)
