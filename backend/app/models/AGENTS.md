# Models AGENTS.md

Context for the data models (`backend/app/models`).

## Purpose

Defines the data structures of the application. Both SQLAlchemy ORM models (for database access) and Pydantic schemas (for API validation) are co-located in this directory to maintain high cohesion per domain entity.

## Structure

- `user.py`: `User` model, authentication logic schemas.
- `document.py`: `Document` model, tracking S3 objects and `DocumentStatus` (PENDING, PROCESSING, READY, FAILED).
- `chunk.py`: `Chunk` model, storing document text and `pgvector` embeddings (`VECTOR(1536)`). Uses HNSW index (`idx_chunks_embedding_hnsw`) with `vector_cosine_ops`.
- `chat.py` / `message.py`: Models for chat sessions and conversational turns.
- `auth.py`: Pydantic models for authentication endpoints.
- `query.py`: Pydantic models for the RAG query API.
- `job_log.py`: Logs background task failures.

## Import Order Invariant

The `__init__.py` in this directory controls the import order of ORM models. This is critical because SQLAlchemy relationships require models to be known for forward references. Do not change the import order in `__init__.py` without understanding the relationship dependencies.

## Related Context

- Parent context: `../AGENTS.md`
- Database setup: `../db/session.py`
