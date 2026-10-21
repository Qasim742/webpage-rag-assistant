import hashlib
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlsplit, urlunsplit

os.environ.setdefault("USER_AGENT", "WebpageRAGAssistant/1.0")

from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader, WebBaseLoader
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph

from backend.config import GROQ_API_KEY


logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parent
DOCUMENTS_DIR = BACKEND_DIR / "documents"
CHROMA_DIR = str(BACKEND_DIR / "chroma_db")


class WebpageFetchError(Exception):
    pass


class EmptyPageError(Exception):
    pass


class DocumentStorageError(Exception):
    pass


class IndexingError(Exception):
    pass


class MissingGroqApiKeyError(Exception):
    pass


class PageProcessingState(TypedDict, total=False):
    url: str
    title: str
    browser_content: str | None
    refresh: bool
    content: str
    content_hash: str
    chunks: list[Document]
    cached: bool
    vectors: int


class QuestionAnswerState(TypedDict, total=False):
    url: str
    question: str
    documents: list[Document]
    answer: str


RAG_PROMPT = ChatPromptTemplate.from_template(
    """You are a helpful AI assistant.

Answer the user's question using ONLY the provided webpage context.
If the answer cannot be found in the context, say:
"I couldn't find the answer in this webpage."
Do not make up information.

Webpage Context:
{context}

Question:
{question}

Answer:"""
)


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Only valid HTTP and HTTPS webpage URLs are supported.")
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, "")
    )


def _safe_url_for_log(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _document_paths(url: str) -> tuple[Path, Path]:
    identifier = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return (
        DOCUMENTS_DIR / f"{identifier}.txt",
        DOCUMENTS_DIR / f"{identifier}.metadata.json",
    )


def _extract_readable_text(soup: Any) -> str:
    for element in soup(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "header",
            "nav",
            "footer",
            "aside",
            "form",
            "button",
        ]
    ):
        element.decompose()

    for element in soup.select(
        '[aria-hidden="true"], [role="navigation"], [role="banner"], '
        '[role="contentinfo"], [role="complementary"]'
    ):
        element.decompose()

    boilerplate = re.compile(
        r"cookie|consent|advert|breadcrumb|sidebar|social|share|"
        r"site[-_ ]?menu|primary[-_ ]?nav",
        re.IGNORECASE,
    )
    for element in soup.find_all(True):
        identifiers = " ".join(
            [str(element.get("id", "")), *(str(value) for value in element.get("class", []))]
        )
        if boilerplate.search(identifiers):
            element.decompose()

    primary_content = (
        soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("article")
        or soup.body
        or soup
    )
    text = primary_content.get_text(separator="\n", strip=True)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def load_webpage(url: str) -> list[Document]:
    logger.info("Scraping webpage %s", _safe_url_for_log(url))
    loader = WebBaseLoader(
        url,
        header_template={"User-Agent": "WebpageRAGAssistant/1.0"},
        requests_kwargs={"timeout": 20},
        raise_for_status=True,
    )

    try:
        soup = loader.scrape()
        content = _extract_readable_text(soup)
    except Exception as exc:
        raise WebpageFetchError(type(exc).__name__) from exc

    if not content:
        return []

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description = soup.find("meta", attrs={"name": "description"})
    metadata = {
        "source": url,
        "title": title,
    }
    if description and description.get("content"):
        metadata["description"] = description["content"].strip()
    return [Document(page_content=content, metadata=metadata)]


def split_documents(documents: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )
    return splitter.split_documents(documents)


@lru_cache(maxsize=1)
def get_embedding_model() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")


def _get_vector_store(url: str) -> Chroma:
    return Chroma(
        collection_name=_collection_name_for_url(url),
        embedding_function=get_embedding_model(),
        persist_directory=CHROMA_DIR,
    )


def _collection_name_for_url(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"page-{digest[:32]}"


def create_vector_store(
    chunks: list[Document],
    url: str,
    reuse_existing: bool,
) -> tuple[Chroma, int]:
    vector_store = _get_vector_store(url)
    existing_ids = vector_store.get()["ids"]
    if reuse_existing and existing_ids:
        return vector_store, len(existing_ids)

    if existing_ids:
        vector_store.delete(ids=existing_ids)

    vector_ids = vector_store.add_documents(chunks)
    logger.info(
        "Indexed %d vectors in ChromaDB collection %s",
        len(vector_ids),
        _collection_name_for_url(url),
    )
    return vector_store, len(vector_ids)


def create_retriever(vector_store: Chroma):
    return vector_store.as_retriever(
        search_type="mmr",
        search_kwargs={"k": 4, "fetch_k": 20},
    )


def _scrape_page_node(state: PageProcessingState) -> dict[str, Any]:
    url = state["url"]
    document_path, metadata_path = _document_paths(url)

    if not state.get("refresh") and document_path.is_file():
        try:
            document = TextLoader(str(document_path), encoding="utf-8").load()[0]
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(metadata, dict):
                raise TypeError("Saved webpage metadata must be an object.")
            return {
                "content": document.page_content,
                "title": str(metadata.get("title", "")),
                "content_hash": str(metadata.get("content_hash", "")),
                "cached": True,
            }
        except (OSError, IndexError, json.JSONDecodeError, TypeError) as exc:
            raise DocumentStorageError(
                f"Could not read the saved webpage document ({type(exc).__name__})."
            ) from exc

    try:
        documents = load_webpage(url)
    except WebpageFetchError:
        browser_content = (state.get("browser_content") or "").strip()
        if not browser_content:
            raise
        logger.info(
            "Using rendered browser text after server-side scraping failed for %s",
            _safe_url_for_log(url),
        )
        documents = [
            Document(
                page_content=browser_content,
                metadata={"source": url, "title": state.get("title", "")},
            )
        ]

    if not documents or not documents[0].page_content.strip():
        browser_content = (state.get("browser_content") or "").strip()
        if browser_content:
            documents = [
                Document(
                    page_content=browser_content,
                    metadata={"source": url, "title": state.get("title", "")},
                )
            ]
        else:
            raise EmptyPageError("No readable text was found on this webpage.")

    document = documents[0]
    title = str(document.metadata.get("title") or state.get("title", ""))
    content_hash = hashlib.sha256(document.page_content.encode("utf-8")).hexdigest()
    try:
        existing_metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.is_file()
            else {}
        )
        if not isinstance(existing_metadata, dict):
            raise TypeError("Saved webpage metadata must be an object.")
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise DocumentStorageError(
            f"Could not check saved webpage metadata ({type(exc).__name__})."
        ) from exc
    return {
        "content": document.page_content,
        "title": title,
        "content_hash": content_hash,
        "cached": existing_metadata.get("content_hash") == content_hash,
    }


def _save_document_node(state: PageProcessingState) -> dict[str, Any]:
    url = state["url"]
    document_path, metadata_path = _document_paths(url)
    content = state["content"]
    content_hash = state["content_hash"]

    try:
        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        previous_metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            previous_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(previous_metadata, dict):
                raise TypeError("Saved webpage metadata must be an object.")

        if previous_metadata.get("content_hash") != content_hash:
            document_path.write_text(content, encoding="utf-8")

        metadata = {
            "source": url,
            "title": state.get("title", ""),
            "content_hash": content_hash,
        }
        if metadata != previous_metadata:
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise DocumentStorageError(
            f"Could not save the webpage document ({type(exc).__name__})."
        ) from exc

    return {}


def _split_saved_document_node(state: PageProcessingState) -> dict[str, Any]:
    document_path, _ = _document_paths(state["url"])
    try:
        documents = TextLoader(str(document_path), encoding="utf-8").load()
        if not documents or not documents[0].page_content.strip():
            raise EmptyPageError("No readable text was found on this webpage.")
        documents[0].metadata.update(
            {"source": state["url"], "title": state.get("title", "")}
        )
        chunks = split_documents(documents)
    except EmptyPageError:
        raise
    except Exception as exc:
        raise DocumentStorageError(
            f"Could not load or split the saved webpage document ({type(exc).__name__})."
        ) from exc

    if not chunks:
        raise EmptyPageError("No text chunks could be created from this webpage.")
    return {"chunks": chunks}


def _index_page_node(state: PageProcessingState) -> dict[str, Any]:
    try:
        vector_store, vector_count = create_vector_store(
            state["chunks"],
            state["url"],
            reuse_existing=state.get("cached", False),
        )
        del vector_store
    except Exception as exc:
        raise IndexingError(
            f"Could not create webpage embeddings or store them in ChromaDB "
            f"({type(exc).__name__})."
        ) from exc
    return {"vectors": vector_count}


def _retrieve_context_node(state: QuestionAnswerState) -> dict[str, Any]:
    vector_store = _get_vector_store(state["url"])
    if not vector_store.get()["ids"]:
        return {"documents": []}
    documents = create_retriever(vector_store).invoke(state["question"])
    logger.info("Retrieved %d chunks for %s", len(documents), _safe_url_for_log(state["url"]))
    return {"documents": documents}


def _generate_answer_node(state: QuestionAnswerState) -> dict[str, str]:
    documents = state.get("documents", [])
    context = "\n\n".join(document.page_content for document in documents)
    if not context.strip():
        return {"answer": "I couldn't find the answer in this webpage."}
    if not GROQ_API_KEY:
        raise MissingGroqApiKeyError(
            "GROQ_API_KEY is not configured. Set it in backend/.env or the project-root .env."
        )

    llm = ChatGroq(
        api_key=GROQ_API_KEY,
        model="openai/gpt-oss-20b",
        temperature=0,
    )
    prompt = RAG_PROMPT.invoke(
        {"context": context, "question": state["question"]}
    )
    response = llm.invoke(prompt)
    answer = response.content
    if not isinstance(answer, str):
        answer = "\n".join(str(part) for part in answer)
    return {"answer": answer}


def _build_page_processing_graph():
    graph = StateGraph(PageProcessingState)
    graph.add_node("scrape_webpage", _scrape_page_node)
    graph.add_node("save_document", _save_document_node)
    graph.add_node("split_document", _split_saved_document_node)
    graph.add_node("embed_and_store", _index_page_node)
    graph.add_edge(START, "scrape_webpage")
    graph.add_edge("scrape_webpage", "save_document")
    graph.add_edge("save_document", "split_document")
    graph.add_edge("split_document", "embed_and_store")
    graph.add_edge("embed_and_store", END)
    return graph.compile()


def _build_question_answer_graph():
    graph = StateGraph(QuestionAnswerState)
    graph.add_node("retrieve_context", _retrieve_context_node)
    graph.add_node("generate_answer", _generate_answer_node)
    graph.add_edge(START, "retrieve_context")
    graph.add_edge("retrieve_context", "generate_answer")
    graph.add_edge("generate_answer", END)
    return graph.compile()


page_processing_graph = _build_page_processing_graph()
question_answer_graph = _build_question_answer_graph()
