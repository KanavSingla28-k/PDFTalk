# Services AGENTS.md

Context for the business logic layer (`backend/app/services`).

## Purpose

This directory contains the core business logic of the application. It orchestrates database interactions, calls external APIs, and enforces business rules.

## Core Services

- `document_service.py`: State machine for documents (`PENDING_UPLOAD` → `PENDING` → `PROCESSING` → `READY` | `FAILED`). Handles upload quota checks and ownership verification.
- `extraction.py`: PDF text extraction using PyMuPDF, with a Tesseract OCR fallback for scanned pages.
- `chunking.py`: Text chunking. Configured for 512-token chunks with 64-token overlap, using the `cl100k_base` tokenizer.
- `embedding.py`: Calls OpenAI (`text-embedding-3-small`) to generate L2-normalized vectors.
- `retrieval.py`: Uses pgvector to perform similarity search (`<=>` cosine distance) on chunks, filtered by chat.
- `prompt.py` / `llm.py`: Builds citation-aware prompts and streams responses from `gpt-4o-mini`.
- `user_service.py`: User registration, login, and profile management.
- `email_verification.py` / `password_reset.py`: Uses Resend to send transactional emails.
- `alerting.py`: Processes Alertmanager webhooks.
- `file_validation.py` / `query_validation.py`: Domain-specific validation logic.

## Dependencies

Services depend heavily on the data access layer (`app.models` and `app.db`) and are called by the API routers (`app.routers`) and background workers (`app.workers`).

## Error Handling

Services must raise typed exceptions from `app.exceptions.py` (e.g., `DocumentNotFoundError`, `QuotaExceededError`) rather than FastAPI's `HTTPException`.

## Related Context

- Parent context: `../AGENTS.md`
- API Routers: `../routers/AGENTS.md`
- Background Workers: `../workers/AGENTS.md`
