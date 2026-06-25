# PDFTalk (v2.0)
<p align="center"> A production-grade SaaS for intelligent document interaction. Upload, chat, and extract insights from your PDFs using RAG and advanced OCR. </p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white">
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-15-black?logo=next.js&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.111+-009688?logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-15-336791?logo=postgresql&logoColor=white">
  <img alt="Redis" src="https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white">
</p>

---

## 🚀 Experience PDFTalk Live
Experience PDFTalk live right now by visiting:  
**[👉 https://pdftalk.kanavsingla.fyi](https://pdftalk.kanavsingla.fyi)**

---

## 🌟 The Vision
We live in an era of information overload. Countless hours are spent reading through lengthy, complex, or scanned documents to find a single piece of critical information. 

**PDFTalk** was built to change that. It transforms static PDFs into interactive, conversational partners. By leveraging Retrieval-Augmented Generation (RAG) and optical character recognition (OCR), PDFTalk understands your documents—whether they are pristine digital text or scanned image pages—and provides precise, context-aware answers to your questions.

## 🗺️ The Journey of a Document
PDFTalk isn't just an API; it's a seamless pipeline designed for scale and accuracy. Here is the journey your document takes from upload to insight:

### 1. The Arrival (Upload & Validation)
When a user uploads a document, the FastAPI backend instantly intercepts it. The file undergoes strict validation (magic bytes checking, size limits) before being securely vaulted into an **AWS S3** bucket. 

### 2. The Awakening (Extraction & OCR)
The heavy lifting begins. To keep the API lightning-fast, an asynchronous **RQ (Redis Queue) Worker** picks up the document. 
- **PyMuPDF** attempts to extract native digital text.
- If it encounters scanned pages or embedded images, **PyTesseract (OCR)** automatically steps in, ensuring no data is left behind.

### 3. The Mapping (Chunking & Embedding)
Large documents can't fit into an LLM's context window. The worker intelligently splits the text into semantic chunks. These chunks are sent to **OpenAI**, which returns high-dimensional vector embeddings. These embeddings are mapped and stored in a **PostgreSQL** database powered by `pgvector` for hyper-fast similarity searches.

### 4. The Conversation (Retrieval & Insight)
When the user asks a question, the system vectorizes the query and performs a lightning-fast nearest-neighbor search (`pgvector` HNSW/IVFFlat indexes) across the document's chunks. The most relevant context is retrieved and fed back to the LLM, which synthesizes a precise, conversational answer.

---

## ✨ Features That Power the Journey
- **Robust Security:** JWT-based access with refresh tokens, bcrypt password hashing, CORS, and HTTP security headers.
- **Resilient Background Processing:** Decoupled architecture using Redis and RQ ensures that massive OCR tasks never block the main web server.
- **Rate Limiting & Quotas:** Strict enforcement of daily tokens, document counts, and query limits to prevent abuse and manage costs.
- **Enterprise-Grade Observability:** Built-in Prometheus metrics, Grafana dashboards, Alertmanager, and structured JSON logging (Structlog) for real-time system health monitoring.
- **Transactional Integrity:** Row-Level Security logic applied via SQLAlchemy prevents unauthorized access across tenant boundaries.

## 🏗️ High Level Architecture Diagram

```mermaid
graph TD
    Client[Client Browser] --> Nginx[Nginx Reverse Proxy]
    Nginx --> Frontend[Next.js Frontend]
    Nginx --> API[FastAPI Backend]
    
    API --> DB[(PostgreSQL + pgvector)]
    API --> Redis[(Redis)]
    API --> S3[(AWS S3)]
    API --> LLM[OpenAI API]
    
    subgraph Background Processing
    Redis --> Worker[RQ Background Worker]
    Worker --> DB
    Worker --> S3
    Worker --> Tesseract[PyTesseract OCR]
    Worker --> PyMuPDF[PyMuPDF Extractor]
    Worker --> LLM
    end
    
    subgraph Observability
    Prometheus[Prometheus] -.Scrapes.-> API
    Prometheus -.Scrapes.-> Worker
    Grafana[Grafana] -.Reads.-> Prometheus
    Alertmanager[Alertmanager] -.Alerts.-> Prometheus
    end
```

## 🗄️ Database Schema Connection

```mermaid
erDiagram
    User ||--o{ Document : "owns"
    User ||--o{ Chat : "starts"
    User ||--o{ RefreshToken : "has"
    User ||--o{ EmailVerification : "receives"
    
    Document ||--o{ Chunk : "split into"
    Document ||--o{ JobLog : "generates"
    
    Chat ||--o{ Message : "contains"
    
    User {
        uuid id PK
        string email
        string full_name
        boolean is_active
    }
    
    Document {
        string id PK
        uuid user_id FK
        string title
        string s3_key
        string status
    }
    
    Chunk {
        uuid id PK
        string document_id FK
        text text_content
        vector embedding
        int page_number
    }
    
    Chat {
        uuid id PK
        uuid user_id FK
        string title
        jsonb document_ids
    }
    
    Message {
        uuid id PK
        uuid chat_id FK
        string role
        text content
    }
```

## 💻 Technology Stack

| Layer | Technologies |
|-------|--------------|
| **Frontend** | Next.js 15, React 19, TypeScript, TailwindCSS 4, React Hook Form, Zod |
| **Backend** | Python 3.12, FastAPI, SQLAlchemy (Async), Alembic, Pydantic |
| **Database** | PostgreSQL 15 (pgvector for embeddings), Redis 7 |
| **AI / NLP** | OpenAI API (LLM & Embeddings), PyMuPDF, PyTesseract |
| **Storage** | AWS S3 |
| **Job Queue**| RQ (Redis Queue) |
| **DevOps** | Docker, Docker Compose, Nginx, GitHub Actions (CI/CD) |
| **Observability**| Prometheus, Grafana, Alertmanager, Structlog |
| **Testing** | Pytest, Jest, React Testing Library |

## 📁 Repository Structure

```text
pdftalk/
├── backend/
│   ├── alembic/             # Database migration scripts
│   ├── app/
│   │   ├── auth/            # Authentication logic & password hashing
│   │   ├── core/            # App configuration & settings
│   │   ├── db/              # SQLAlchemy models & sessions
│   │   ├── middleware/      # Security, CORS, and logging middleware
│   │   ├── routers/         # API endpoint definitions
│   │   ├── services/        # Business logic (LLM, RAG, File handling)
│   │   └── workers/         # RQ background job definitions
│   ├── scripts/             # Utility scripts (e.g., S3 orphan cleanup)
│   ├── tests/               # Pytest integration and unit tests
│   ├── Dockerfile           # Backend API container image
│   └── Dockerfile.worker    # Background worker container image
├── frontend/
│   ├── src/                 # Next.js app router, components, hooks, and contexts
│   ├── public/              # Static assets
│   └── Dockerfile           # Frontend container image
├── infra/                   # Nginx reverse proxy & SSL configurations
├── monitoring/              # Prometheus, Grafana, and Alertmanager configs
├── .github/workflows/       # CI/CD pipelines (ci.yml, deploy.yml)
├── docker-compose.yml       # Production Docker deployment
└── docker-compose.dev.yml   # Local development Docker setup
```

## 🚦 Getting Started

### Prerequisites
- Node.js (v20+) & pnpm
- Python 3.12+ (or `uv` package manager)
- Docker & Docker Compose
- PostgreSQL 15+ (with `pgvector` extension if running locally without Docker)
- Redis 7+

### 1. Docker Setup (Recommended for Dev)

To spin up the entire stack including databases locally:
```bash
docker compose -f docker-compose.dev.yml up -d --build
```
The application will be available at `http://localhost:3000` and the API at `http://localhost:8000`.

### 2. Local Setup (Manual)

**Backend:**
```bash
cd backend
# Using uv (recommended) or pip
uv sync 
# Run database migrations
alembic upgrade head
# Start the FastAPI server
uvicorn app.main:app --reload --port 8000
```

**Background Worker:**
```bash
cd backend
# Start the RQ worker
python -m app.workers.worker
```

**Frontend:**
```bash
cd frontend
pnpm install
pnpm run dev
```

## ⚙️ Environment Variables

Create `.env.local` files in both frontend and backend directories based on the provided `.env.example` templates.

**Backend (`backend/.env`):**
```env
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/pdftalk
REDIS_URL=redis://localhost:6379/0
JWT_SECRET_KEY=your_secure_random_string
OPENAI_API_KEY=sk-...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=ap-south-1
S3_BUCKET_NAME=pdftalk-dev
RESEND_API_KEY=re_...
MAX_DOCS_PER_USER=20
```

**Frontend (`frontend/.env.local`):**
```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_APP_NAME=PDFTalk
NEXT_PUBLIC_MAX_UPLOAD_MB=50
```

## 📡 API Overview

The backend exposes a highly structured RESTful API. Below are the core endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/register` | Register a new user |
| `POST` | `/auth/login` | Authenticate and retrieve JWT |
| `POST` | `/auth/verify` | Verify user email address |
| `POST` | `/documents/` | Upload and ingest a new PDF |
| `GET`  | `/documents/` | Retrieve a list of user documents |
| `DELETE`| `/documents/{id}` | Permanently delete a document & embeddings |
| `POST` | `/query/` | Ask a question against a specific document |
| `GET`  | `/chats/` | Retrieve chat history |
| `GET`  | `/health/` | Service healthiness and readiness checks |

## 🧪 Testing
The repository features comprehensive test coverage.
- **Backend:** Uses `pytest` with `pytest-asyncio`. Run tests using `pytest tests/`. Integration tests are marked and require PostgreSQL/OpenAI connectivity.
- **Frontend:** Uses `Jest` and React Testing Library. Run via `pnpm test`.

## 🚢 Deployment
PDFTalk is fully containerized and intended for deployment on a Linux host using Docker Compose. Images are automatically built and published to GitHub Container Registry (GHCR) via the `deploy.yml` pipeline upon pushing to the `main` branch. 

```bash
# Deploy core services
docker compose up -d --build

# Bring up observability stack on demand
docker compose --profile observability up -d
```

## 🤝 Contributing
1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Ensure backend code passes `ruff` and `mypy` checks.
4. Ensure frontend code passes `eslint` and `tsc` checks.
5. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
6. Push to the branch (`git push origin feature/AmazingFeature`)
7. Open a Pull Request

## 🔮 Future Enhancements
- Multi-provider AI support (Anthropic Claude, Google Gemini).
- Multi-document conversational querying.
- Advanced Hybrid Search (BM25 + Dense Vectors).
- Single Sign-On (OAuth / Google / GitHub).

## 📄 License
Distributed under the MIT License. See `LICENSE` for more information.
