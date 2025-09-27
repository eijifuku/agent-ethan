import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_COMPATIBLE_BASE_URL", "http://127.0.0.1:1234/v1")

from agent_ethan.builder import build_agent_from_path


if __name__ == "__main__":
    runtime = build_agent_from_path("examples/memory_agent.yaml")
    session_id = "demo-session"

    data_dir = Path("examples/data")
    data_dir.mkdir(parents=True, exist_ok=True)
    for sid in (session_id, "another-session"):
        history_file = data_dir / f"history-{sid}.jsonl"
        if history_file.exists():
            history_file.unlink()

    print("-- first turn --")
    state = runtime.run({"query": "How are you?", "session_id": session_id})
    print(state["messages"])

    print("-- second turn --")
    state = runtime.run({"query": "Any plans today?", "session_id": session_id})
    print(state["messages"])

    print("-- new session --")
    fresh_state = runtime.run({"query": "Nice to meet you", "session_id": "another-session"})
    print(fresh_state["messages"])
