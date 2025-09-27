import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_COMPATIBLE_BASE_URL", "http://127.0.0.1:1234/v1")

from agent_ethan.builder import NodeExecutionError, build_agent_from_path

if __name__ == "__main__":
    runtime = build_agent_from_path("examples/rag_agent.yaml")
    try:
        state = runtime.run({"query": "RAG とは何ですか"})
    except NodeExecutionError as exc:
        raise SystemExit(
            "LM Studio に接続できませんでした。起動を確認してください。\n"
            f"詳細: {exc}"
        ) from exc
    print(state["answer"])
