# Architecture

## Page processing graph

`POST /process-page` validates and normalizes the URL, then invokes a LangGraph
workflow:

1. Scrape with LangChain `WebBaseLoader`; use browser-rendered text only when
   server-side scraping fails or returns no readable content.
2. Reuse a saved document unless `refresh` was requested.
3. Save complete extracted text and source/title metadata in
   `backend/documents/`, keyed by a SHA-256 hash of the URL.
4. Load the saved text with LangChain `TextLoader` and split it with
   `RecursiveCharacterTextSplitter`.
5. Generate Hugging Face embeddings and index chunks in the URL's persistent
   ChromaDB collection.

## Question-answer graph

`POST /chat` selects the collection by URL, retrieves relevant chunks using a
LangChain MMR retriever, formats the context with `ChatPromptTemplate`, and
generates a grounded answer using the existing Groq chat model.

## Configuration and persistence

`backend/config.py` checks a non-empty `GROQ_API_KEY` environment variable,
then `backend/.env`, then the project-root `.env`. Missing credentials do not
prevent API startup; chat returns a configuration error when an answer requires
Groq. Keys are not logged or exposed to the extension.

Documents and ChromaDB data persist under `backend/documents/` and
`backend/chroma_db/`. Each page has independent URL-derived storage, and
reprocessing one page does not clear other pages' collections.
