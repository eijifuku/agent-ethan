"""Run the LangChain list-directory agent example."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


try:
    import langchain_core.tools  # noqa: F401
except ImportError as exc:  # pragma: no cover - runtime guard
    raise SystemExit(
        "langchain-core (and langchain-community) must be installed to run this example."
    ) from exc

from agent_ethan.builder import build_agent_from_path


def main() -> None:
    example_path = Path(__file__).with_name("langchain_list_dir_agent.yaml")
    runtime = build_agent_from_path(example_path)

    result = runtime.run({"directory": "examples"})
    entries = result.get("entries", "<no output>")
    print("Directory listing for 'examples':")
    print(entries)


if __name__ == "__main__":
    main()
