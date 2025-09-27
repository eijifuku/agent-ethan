import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from agent_ethan.builder import build_agent_from_path


def require_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY to use the LangChain RAG example.")


if __name__ == "__main__":
    require_api_key()

    agent_path = Path("examples/langchain_rag_agent.yaml")
    runtime = build_agent_from_path(agent_path)

    question = "How does Agent Ethan integrate with LangChain?"
    state = runtime.run({"query": question})

    print("Question:", question)
    print("Answer:\n", state["answer"])  # noqa: T201
    print("Sources:")  # noqa: T201
    for item in state["sources"]:
        source = item.get("source")
        print(f"- {source}")  # noqa: T201
