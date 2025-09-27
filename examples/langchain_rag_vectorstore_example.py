import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.append(str(Path(__file__).resolve().parents[1]))

from agent_ethan.builder import build_agent_from_path

from langchain_community.tools import VectorStoreQATool
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI, OpenAIEmbeddings


CORPUS_DIR = Path("examples/corpus")


def require_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY before running the LangChain vector store example.")


def load_documents(corpus_dir: Path) -> List[Document]:
    documents: List[Document] = []
    for path in sorted(corpus_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        documents.append(Document(page_content=text, metadata={"source": path.name}))
    if not documents:
        raise SystemExit(f"No documents found in {corpus_dir}")
    return documents


def build_vectorstore(documents: List[Document]) -> Chroma:
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return Chroma.from_documents(documents=documents, embedding=embeddings)


def build_vectorstore_tool(vectorstore: Chroma) -> VectorStoreQATool:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
    return VectorStoreQATool(
        name="agent-ethan-docs",
        description="Answer questions about Agent Ethan documentation.",
        vectorstore=vectorstore,
        llm=llm,
    )


def wrap_tool(tool: VectorStoreQATool, vectorstore: Chroma, top_k: int = 4):
    def _call(query: str, **_: Any) -> Dict[str, Any]:
        answer = tool.run(query)
        docs = vectorstore.similarity_search(query, k=top_k)
        sources = [
            {
                "source": doc.metadata.get("source"),
                "snippet": doc.page_content[:280],
            }
            for doc in docs
        ]
        return {
            "status": 200,
            "json": {"answer": answer, "sources": sources},
            "text": answer,
            "items": sources,
            "error": None,
        }

    return _call


def main() -> None:
    require_api_key()

    documents = load_documents(CORPUS_DIR)
    vectorstore = build_vectorstore(documents)
    qa_tool = build_vectorstore_tool(vectorstore)
    qa_callable = wrap_tool(qa_tool, vectorstore)

    runtime = build_agent_from_path("examples/langchain_rag_vectorstore_agent.yaml")

    question = "How does Agent Ethan integrate with LangChain?"
    state = runtime.run({"query": question}, tool_overrides={"qa_tool": qa_callable})

    print("Question:", question)  # noqa: T201
    print("Answer:\n", state["answer"])  # noqa: T201
    print("Sources:")  # noqa: T201
    for item in state["sources"]:
        print(f"- {item['source']}")  # noqa: T201


if __name__ == "__main__":
    main()
