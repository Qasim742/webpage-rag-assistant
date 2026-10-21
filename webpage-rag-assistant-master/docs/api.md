# API

The backend defaults to `http://127.0.0.1:8000`.

## `GET /`

Returns a message confirming that the backend is running.

## `POST /process-page`

Request:

```json
{
  "url": "https://example.com",
  "title": "Optional browser title",
  "content": "Optional rendered browser text used if server scraping fails or returns no readable text",
  "refresh": false
}
```

`url` must be an HTTP or HTTPS URL. `content` is optional and capped at
500,000 characters. By default, a saved document is reused instead of
re-scraping the URL. Set `refresh` to `true` to scrape and index the latest
content.

The backend extracts readable page text with LangChain's `WebBaseLoader`, saves
it under `backend/documents/` using a stable URL-derived filename, then splits,
embeds, and stores it in that URL's ChromaDB collection.

## `POST /chat`

Request:

```json
{
  "url": "https://example.com",
  "question": "What is this page about?"
}
```

The `url` selects the page-specific ChromaDB collection. It is optional for
older clients while the backend process is running and defaults to the most
recently processed URL. Answers use retrieved webpage context only.

## Errors

The API returns a clear error for unsupported URLs, empty pages, scraping
failures, document/indexing failures, missing Groq configuration, and failed
answer generation. The API key is never returned in responses or logs.
