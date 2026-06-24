# PDFTalk

## Project Overview

PDFTalk is a full-stack Retrieval-Augmented Generation (RAG) application that allows users to upload PDF documents, process them into vectorized embeddings, and interactively chat with their documents. It solves the problem of extracting and querying information from large, unstructured PDF files by providing contextual, AI-generated answers based precisely on the uploaded content.

### High-Level Architecture Summary
PDFTalk consists of a **Next.js frontend** for the user interface, a **FastAPI backend** for API routing and business logic, a **PostgreSQL database with pgvector** for metadata and vector storage, and an **RQ/Redis background worker** system for asynchronous document processing (ingestion, chunking, and embedding). It utilizes **OpenAI** for both generating embeddings and answering queries.

---

## 🚀 Quick Start / How to Use

Experience PDFTalk live right now by visiting:  
**[👉 https://pdftalk.kanavsingla.fyi](https://pdftalk.kanavsingla.fyi)**

### 💡 User Guidelines & Best Practices

To get the most accurate and insightful answers from your documents, please follow these guidelines:
1. **Create an Account**: You must register and verify your email address to start uploading and querying documents.
2. **Upload Text-Based PDFs**: Ensure your PDFs contain selectable, machine-readable text. Purely scanned image PDFs without OCR will yield poor results.
3. **Ask Specific Questions**: The more specific your query, the better the AI can retrieve the exact context from your document and provide an accurate answer.
4. **Wait for Processing**: After uploading, wait until the document status changes to `READY` before querying. The background workers need time to extract text, create chunks, and generate embeddings.
5. **Mind the Limits**: Be aware of your daily token budget, maximum document count, and upload size limits to ensure smooth usage.

---

## Features

- **Document Management**: Securely upload, store, and manage multiple PDF documents.
- **Interactive Chat (RAG)**: Query documents and receive context-aware answers powered by OpenAI.
- **Asynchronous Processing**: Non-blocking document ingestion pipeline using Redis and RQ workers.
- **Vector Search**: Semantic search using PostgreSQL and `pgvector`.
- **Authentication & Security**: Robust JWT-based authentication, password reset flows, email verification, and rate limiting.
- **Cloud Storage**: Seamless integration with AWS S3 for document storage.
- **Containerized Infrastructure**: Fully dockerized setup for local development and production deployments.

---

## Tech Stack

| Category | Technology |
| --- | --- |
| **Frontend Framework** | Next.js 15, React 19 |
| **Styling** | Tailwind CSS v4 |
| **State & Forms** | React Hook Form, Zod |
| **Backend Framework** | FastAPI (Python 3.12) |
| **Backend ORM** | SQLAlchemy, Alembic (Migrations) |
| **Database** | PostgreSQL 15 with pgvector |
| **Caching / Queues** | Redis, RQ (Redis Queue) |
| **AI / LLM** | OpenAI API (Embeddings & Completion) |
| **Storage** | AWS S3 |
| **Containerization** | Docker, Docker Compose, Nginx |
| **CI/CD** | GitHub Actions |
| **Testing** | Pytest (Backend), Jest (Frontend) |

---

## Architecture

### System Overview & Data Flow

1. **Upload Flow**: The user uploads a PDF via the Next.js frontend. The FastAPI backend saves the file to AWS S3, creates a `PENDING` record in PostgreSQL, and enqueues an ingestion job in Redis.
2. **Ingestion Pipeline**: The RQ worker picks up the job, marks it as `PROCESSING`, extracts text from the PDF using PyMuPDF, chunks the text, checks token budgets, generates embeddings via OpenAI, and bulk-inserts the vectors into PostgreSQL using pgvector. The document is then marked `READY`.
3. **Query Flow**: The user submits a question. The backend embeds the query, performs a vector similarity search (cosine similarity) in PostgreSQL to retrieve the top `K` most relevant chunks, and sends the context + query to OpenAI to generate a natural language response.

### Mermaid Architecture Diagram

```mermaid
graph TD
    Client[Next.js Frontend] -->|REST API| API[FastAPI Backend]
    
    API -->|1. Upload PDF| S3[AWS S3]
    API -->|2. Create Record| DB[(PostgreSQL + pgvector)]
    API -->|3. Enqueue Job| Redis[Redis Queue]
    
    Worker[RQ Worker] <-->|Polls| Redis
    Worker -->|4. Download PDF| S3
    Worker -->|5. Extract & Chunk| PyMuPDF[PyMuPDF]
    Worker -->|6. Get Embeddings| OpenAI[OpenAI API]
    Worker -->|7. Store Vectors| DB
    
    API -->|Query Vector Search| DB
    API -->|Generate Answer| OpenAI
```

---

## Repository Structure

```text
PDFTalk/
├── backend/                  # FastAPI backend application
│   ├── alembic/              # Database migration scripts
│   ├── app/
│   │   ├── api/              # API routers and endpoints
│   │   ├── core/             # Configuration and settings
│   │   ├── db/               # Database session and base models
│   │   ├── models/           # SQLAlchemy ORM models (User, Document, Chunk, etc.)
│   │   ├── routers/          # Route handlers (auth, documents, query, health)
│   │   ├── services/         # Business logic (embedding, extraction, user_service)
│   │   └── workers/          # RQ worker entrypoints and ingestion pipeline
│   ├── tests/                # Pytest test suite
│   ├── pyproject.toml        # Python dependencies (managed by uv)
│   └── Dockerfile            # Backend container definition
├── frontend/                 # Next.js frontend application
│   ├── src/
│   │   ├── app/              # Next.js App Router pages
│   │   ├── components/       # Reusable React components
│   │   ├── contexts/         # React Context providers
│   │   ├── hooks/            # Custom React hooks
│   │   └── lib/              # Utility functions and API clients
│   ├── package.json          # Node dependencies
│   └── Dockerfile            # Frontend container definition
├── infra/                    # Infrastructure configs (Nginx)
├── .github/workflows/        # CI/CD pipelines (GitHub Actions)
├── docker-compose.yml        # Production Docker Compose setup
└── docker-compose.dev.yml    # Local development Docker Compose setup
```

---

## Prerequisites

- **Node.js**: >= 20 (for local frontend development)
- **Python**: >= 3.12 (managed via `uv`)
- **Docker & Docker Compose**: Latest versions
- **PostgreSQL**: 15 (with pgvector extension)
- **Redis**: 7+
- **External Accounts**:
  - OpenAI API Key
  - AWS Account (S3 access)
  - Resend API Key (for emails)

---

## Environment Variables

### Backend (`backend/.env.local`)

| Variable | Required | Description | Example |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | Yes | PostgreSQL connection string | `postgresql+asyncpg://postgres:password@localhost:5432/pdftalk` |     # pragma: allowlist secret    
| `REDIS_URL` | Yes | Redis connection string | `redis://localhost:6379/0` |     # pragma: allowlist secret
| `JWT_SECRET_KEY` | Yes | Secret for signing JWTs | `openssl-rand-hex-32` |      # pragma: allowlist secret
| `JWT_ALGORITHM` | No | Algorithm for JWT | `HS256` |    # pragma: allowlist secret
| `RESEND_API_KEY` | No | API key for sending emails | `re_123456789` |     # pragma: allowlist secret
| `FROM_EMAIL` | Yes | Sender email address | `noreply@yourdomain.com` |   # pragma: allowlist secret
| `OPENAI_API_KEY` | Yes | OpenAI API Key for embeddings/LLM | `sk-xxxxxxxx` |  # pragma: allowlist secret
| `AWS_ACCESS_KEY_ID` | Yes | AWS Access Key | `xxxxxxxx` |  # pragma: allowlist secret
| `AWS_SECRET_ACCESS_KEY` | Yes | AWS Secret Key | `xxxxxxxx` |   # pragma: allowlist secret
| `S3_BUCKET_NAME` | Yes | Target S3 bucket for PDFs | `pdftalk-dev` |  # pragma: allowlist secret
| `APP_URL` | Yes | Frontend application URL | `http://localhost:3000` |  # pragma: allowlist secret

### Frontend (`frontend/.env.local`)

| Variable | Required | Description | Example |
| :--- | :--- | :--- | :--- |
| `NEXT_PUBLIC_API_URL` | Yes | Backend API URL | `http://localhost:8000` |     # pragma: allowlist secret
| `NEXT_PUBLIC_APP_NAME` | Yes | Display name of the app | `PDFTalk` |       # pragma: allowlist secret
| `NEXT_PUBLIC_MAX_UPLOAD_MB`| Yes | Max allowed upload size | `50` |      # pragma: allowlist secret

---

## Installation & Local Development

### 1. Clone the Repository

```bash
git clone <repository-url>
cd PDFTalk
```

### 2. Configure Environment Variables

Create `.env.local` files in both the `backend/` and `frontend/` directories based on the provided `.env.example` templates.

### 3. Run via Docker Compose (Recommended)

To start the entire stack (PostgreSQL, Redis, Backend API, RQ Worker, and Frontend) using Docker:

```bash
docker-compose -f docker-compose.dev.yml up --build
```

### 4. Manual Setup (Without Docker)

#### Backend
```bash
cd backend
# Install dependencies using uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r pyproject.toml

# Run database migrations
alembic upgrade head

# Start FastAPI server
fastapi run app/main.py --reload
```

#### Frontend
```bash
cd frontend
# Install dependencies
pnpm install

# Start Next.js development server
pnpm run dev
```

---

## API Documentation

The backend exposes a RESTful API. When running locally, interactive Swagger documentation is available at `http://localhost:8000/docs`.

### Key Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **Auth** | | |
| POST | `/auth/register` | Register a new user |
| POST | `/auth/login` | Authenticate user and return JWT |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/verify-email` | Verify user email address |
| POST | `/auth/password-reset/request`| Request a password reset link |
| POST | `/auth/password-reset/confirm`| Confirm password reset |
| **Documents** | | |
| POST | `/documents/initiate-upload` | Request a presigned S3 URL for direct upload |
| POST | `/documents/confirm-upload` | Confirm S3 upload and enqueue ingestion job |
| GET | `/documents` | List user's documents |
| GET | `/documents/{id}` | Get specific document status |
| DELETE| `/documents/{id}` | Delete a document and its chunks |
| **Query** | | |
| POST | `/query` | Perform a RAG query against a specific document |

---

## Database

**Engine**: PostgreSQL 15 with `pgvector`  
**ORM**: SQLAlchemy (Async)  
**Migrations**: Alembic

### Entity Relationship Model

```mermaid
erDiagram
    USERS ||--o{ DOCUMENTS : owns
    USERS {
        uuid id PK
        text email
        text password_hash
        boolean is_verified
    }
    DOCUMENTS ||--o{ CHUNKS : contains
    DOCUMENTS ||--o{ JOB_LOGS : generates
    DOCUMENTS {
        uuid id PK
        uuid user_id FK
        text filename
        text s3_key
        text status
    }
    CHUNKS {
        uuid id PK
        uuid document_id FK
        text text
        vector embedding
    }
```

---

## Authentication & Security

- **JWT Tokens**: Access tokens (short-lived) and Refresh tokens (long-lived) securely manage sessions.
- **Passwords**: Hashed securely using `bcrypt`.
- **Email Verification**: Required before users can access core features, powered by Resend.
- **CORS & CSP**: Securely configured via FastAPI middleware and Next.js configuration.
- **Rate Limiting**: Monitored and enforced per user (e.g., daily token budgets, daily query limits).
- **Access Control**: Row-level isolation ensures users can only access their own documents and chunks.

---

## Background Processing

PDFTalk uses **RQ (Redis Queue)** for reliable background processing.

- **Ingestion Pipeline (`worker.py` & `ingest.py`)**: 
  - Offloads heavy tasks (PDF text extraction, chunking, OpenAI embeddings generation) from the main API thread.
  - Lifecycle tracking: `PENDING` → `PROCESSING` → `READY` / `FAILED`.
  - Fault tolerance: If a job fails, the error is logged in `job_logs` and the document status reflects the failure. Retries automatically clean up partial state.

---

## Testing

### Backend
Run the backend test suite using Pytest:
```bash
cd backend
pytest
```
*(Note: Integration tests may require local PostgreSQL and Redis instances).*

### Frontend
Run frontend unit tests using Jest:
```bash
cd frontend
pnpm test
```

---

## CI/CD Deployment

The repository includes GitHub Actions workflows:
- **`ci.yml`**: Runs linting (Ruff, ESLint), type checking, and test suites on Pull Requests.
- **`deploy.yml`**: Automates deployment (e.g., to AWS or Lightsail) on merges to the `main` branch.

**Docker Compose (`docker-compose.yml`)** is used for production deployments, spinning up:
- `postgres` (with pgvector)
- `redis`
- `api` (FastAPI)
- `worker` (RQ Ingestion Worker)
- `frontend` (Next.js)
- `nginx` (Reverse Proxy on port 80)

---

## Troubleshooting

- **PDF Stuck in `PROCESSING`**: Check the worker logs (`docker logs pdftalk-worker-prod`). It might be a timeout from the OpenAI API or an extraction failure.
- **Database Connection Errors**: Ensure the `DATABASE_URL` is correctly formatted and the PostgreSQL container is fully healthy.
- **OpenAI Token Limits**: Check the backend logs for `_check_token_budget` failures. Very large PDFs may exceed the configured `MAX_TOKENS_PER_DOCUMENT`.
- **CORS Issues**: Ensure the `APP_URL` in the backend `.env` matches the frontend's origin exactly.

---

## License

This project is licensed under the [MIT License](LICENSE).
