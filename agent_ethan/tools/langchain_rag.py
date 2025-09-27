"""LangChain-powered RAG tool implementations for Agent Ethan examples.

These helpers intentionally keep LangChain as the only orchestration layer by
wrapping RetrievalQA style chains in a class that inherits from
``langchain_core.tools.BaseTool``. The Agent Ethan runtime can then load them
via ``kind: langchain`` tool declarations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from langchain_core.documents import Document
from langchain_core.tools import BaseTool
from pydantic import PrivateAttr


def _lazy_import_openai_components() -> tuple[Any, Any, Any]:
    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from langchain.chains import RetrievalQA
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise ImportError(
            "Running ChromaRetrievalQATool requires 'langchain-openai' and 'langchain'."
        ) from exc
    return ChatOpenAI, OpenAIEmbeddings, RetrievalQA


def _lazy_import_chroma() -> Any:
    try:
        from langchain_community.vectorstores import Chroma
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise ImportError(
            "Running ChromaRetrievalQATool requires 'chromadb' and 'langchain-community'."
        ) from exc
    return Chroma


def _read_corpus(corpus_path: str | Path, glob: str) -> List[Document]:
    corpus_root = Path(corpus_path).expanduser().resolve()
    if not corpus_root.exists():
        raise FileNotFoundError(f"corpus path '{corpus_root}' does not exist")

    files = sorted(corpus_root.glob(glob))
    if not files:
        raise ValueError(f"corpus path '{corpus_root}' with pattern '{glob}' is empty")

    documents: List[Document] = []
    for file in files:
        text = file.read_text(encoding="utf-8")
        documents.append(Document(page_content=text, metadata={"source": str(file)}))
    return documents


class ChromaRetrievalQATool(BaseTool):
    """Answer questions over a local corpus using Chroma + OpenAI embeddings."""

    name: str = "chroma_retrieval_qa"
    description: str = (
        "Answer questions using a Chroma vector store populated from local files. "
        "Relies on OpenAI embeddings and chat completion models."
    )
    return_direct: bool = False

    corpus_path: str
    glob: str = "*.md"
    collection_name: str = "agent-ethan-rag"
    persist_directory: Optional[str] = None
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"
    top_k: int = 4
    recreate_store: bool = True

    _qa_chain: Any = PrivateAttr(default=None)

    def model_post_init(self, __context: Any) -> None:  # type: ignore[override]
        ChatOpenAI, OpenAIEmbeddings, RetrievalQA = _lazy_import_openai_components()
        Chroma = _lazy_import_chroma()

        documents = _read_corpus(self.corpus_path, self.glob)
        embeddings = OpenAIEmbeddings(model=self.embedding_model)

        persist_dir: Optional[Path] = Path(self.persist_directory).resolve() if self.persist_directory else None

        if persist_dir and self.recreate_store and persist_dir.exists():
            # Recreate the store on every instantiation to keep examples deterministic.
            for child in persist_dir.iterdir():
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    _remove_tree(child)

        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)

        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]
        vectordb = Chroma.from_texts(
            texts=texts,
            metadatas=metadatas,
            embedding=embeddings,
            collection_name=self.collection_name,
            persist_directory=str(persist_dir) if persist_dir else None,
        )
        retriever = vectordb.as_retriever(search_kwargs={"k": self.top_k})

        llm = ChatOpenAI(model=self.llm_model, temperature=0.0)
        self._qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            retriever=retriever,
            return_source_documents=True,
        )

    # ------------------------------------------------------------------
    # BaseTool API
    # ------------------------------------------------------------------

    def _run(self, query: str, **kwargs: Any) -> Dict[str, Any]:  # type: ignore[override]
        response = self._qa_chain({"query": query})
        answer = response.get("result")
        sources = _format_sources(response.get("source_documents"))
        return {
            "text": answer,
            "items": sources,
            "json": {
                "answer": answer,
                "sources": sources,
            },
        }

    async def _arun(self, query: str, **kwargs: Any) -> Dict[str, Any]:  # pragma: no cover - async unsupported
        raise NotImplementedError("ChromaRetrievalQATool does not support async execution")


def _format_sources(source_documents: Optional[Iterable[Document]]) -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    if not source_documents:
        return sources
    for doc in source_documents:
        payload = {
            "source": doc.metadata.get("source"),
        }
        if doc.metadata:
            payload.update({key: value for key, value in doc.metadata.items() if key != "source"})
        payload["snippet"] = doc.page_content[:280]
        sources.append(payload)
    return sources


def _remove_tree(path: Path) -> None:
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()
