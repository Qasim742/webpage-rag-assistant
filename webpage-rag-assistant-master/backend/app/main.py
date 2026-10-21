import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.rag import (
    DocumentStorageError,
    EmptyPageError,
    IndexingError,
    MissingGroqApiKeyError,
    WebpageFetchError,
    _safe_url_for_log,
    canonicalize_url,
    page_processing_graph,
    question_answer_graph,
)
from backend.schemas import (
    ChatRequest,
    ChatResponse,
    HomeResponse,
    ProcessPageRequest,
    ProcessPageResponse,
)


logger = logging.getLogger(__name__)

app = FastAPI(title="Webpage RAG Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

last_processed_url: str | None = None


@app.get("/", response_model=HomeResponse)
def home() -> HomeResponse:
    return HomeResponse(message="Webpage RAG Assistant backend is running!")


@app.post("/process-page", response_model=ProcessPageResponse)
def process_page(request: ProcessPageRequest) -> ProcessPageResponse:
    global last_processed_url

    try:
        url = canonicalize_url(str(request.url))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    safe_url = _safe_url_for_log(url)
    logger.info("Received page-processing request for %s", safe_url)

    try:
        result = page_processing_graph.invoke(
            {
                "url": url,
                "title": request.title,
                "browser_content": request.content,
                "refresh": request.refresh,
            }
        )
    except WebpageFetchError as exc:
        logger.error("Webpage scraping failed for %s (%s)", safe_url, str(exc))
        raise HTTPException(
            status_code=502,
            detail=(
                "The backend could not scrape this webpage. Verify it is publicly "
                "reachable or retry from the open browser tab."
            ),
        ) from exc
    except EmptyPageError as exc:
        logger.warning("No readable webpage content found for %s", safe_url)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DocumentStorageError as exc:
        logger.error("Document processing failed for %s (%s)", safe_url, str(exc))
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc
    except IndexingError as exc:
        logger.error("Webpage indexing failed for %s (%s)", safe_url, str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Unexpected page-processing failure for %s (%s)",
            safe_url,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="The webpage could not be processed. Check the backend logs.",
        ) from exc

    last_processed_url = url
    logger.info("Stored %d vectors for %s", result["vectors"], safe_url)
    return ProcessPageResponse(
        message="Page processed successfully",
        url=request.url,
        documents=1,
        chunks=len(result["chunks"]),
        vectors=result["vectors"],
    )


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    url = str(request.url) if request.url else last_processed_url
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Please process a webpage before asking a question.",
        )
    if not request.question.strip():
        raise HTTPException(
            status_code=422,
            detail="The question must not be empty.",
        )

    try:
        result = question_answer_graph.invoke(
            {
                "url": canonicalize_url(url),
                "question": request.question.strip(),
            }
        )
    except MissingGroqApiKeyError as exc:
        logger.error("Chat request cannot run because the Groq API key is missing.")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Chat request failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="Answer generation failed. Check the backend logs and try again.",
        ) from exc

    return ChatResponse(answer=result["answer"])
