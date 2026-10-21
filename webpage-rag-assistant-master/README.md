# Webpage RAG Assistant

A Chrome extension that sends the active HTTP(S) tab URL to a local FastAPI
service. The backend scrapes and saves the page, indexes it in a page-specific
ChromaDB collection through LangChain and LangGraph, and answers questions
using retrieved context and Groq.

## Backend setup (Windows, Python 3.14)

From the project root:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set `GROQ_API_KEY` in the existing project-root `.env` or in `backend\.env`.
The backend checks both locations and does not print the key. A non-empty
environment variable takes precedence. If neither file exists, the backend
still starts; question answering reports a configuration error until a key is
set. `.env` files are ignored by Git.

Start the API from the project root (the directory containing `backend\`):

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` to check the API. The first page processed may
take longer while the Hugging Face embedding model is downloaded.

## Chrome extension setup

1. Open `chrome://extensions` and enable **Developer mode**.
2. Select **Load unpacked** and choose the project's `extension` folder.
3. Open an HTTP or HTTPS webpage, open the extension, and select **Process
   Current Page**.
4. After processing succeeds, enter a question and select **Ask**. The extension
   includes the active page URL with both requests, so each question retrieves
   from that page's own collection.

After changing extension files or permissions, click **Reload** on the extension
at `chrome://extensions`. The popup sends API requests through the extension
service worker, which uses the granted backend host permission.

The extension's Options page can change the backend origin. Chrome asks for
permission to contact that origin before saving it.

Browser-internal pages (such as `chrome://settings`) cannot be loaded by the
backend and are rejected by the extension and API's HTTP/HTTPS URL validation.

## API

- `GET /` reports that the backend is running.
- `POST /process-page` accepts `{"url":"https://example.com"}`. The backend
  uses LangChain's `WebBaseLoader`, removes common page boilerplate, saves the
  extracted text and metadata under `backend\documents\`, then splits and
  indexes it using LangGraph, Hugging Face embeddings, and ChromaDB.
- `POST /chat` accepts `{"url":"https://example.com","question":"What is this page about?"}`.
  The URL may be omitted for older clients during the current backend process.

Each URL is assigned a stable document identifier and its own ChromaDB
collection. Existing saved pages are reused on repeat requests; send
`"refresh": true` to `/process-page` to scrape and re-index an updated page.
Refreshing or processing another URL does not delete unrelated documents or
collections.

When processing from Chrome, the extension also supplies rendered page text as
a fallback for pages that cannot be fetched by the backend (for example,
JavaScript-rendered or authenticated pages). Direct API requests can scrape
content available to the backend's HTTP client.
