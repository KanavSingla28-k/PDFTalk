# Phase 14 — Architecture Review

This document provides a comprehensive architectural review of the PDFTalk platform, complete with Mermaid diagrams illustrating system components, sequence flows, and lifecycle processes.

## 1. High-Level Architecture Diagram

The system follows a typical modern 3-tier architecture with a Next.js frontend, a FastAPI backend, and a robust data/caching layer.

```mermaid
%%{init: {
  "theme":"dark",
  "flowchart":{"curve":"basis"}
}}%%

flowchart LR

classDef layer fill:#111827,stroke:#60a5fa,color:#fff,stroke-width:2px;

subgraph UL["👤 User Layer"]
    U["User Browser"]
end

subgraph NL["🌐 Network Edge"]
    N["Nginx Reverse Proxy"]
end

subgraph FL["💻 Frontend Tier"]
    FE["Next.js App Router"]
end

subgraph BL["⚙️ Backend Tier"]
    API["FastAPI Server"]
    W["RQ Worker"]
end

subgraph DL["🗄️ Data Tier"]
    DB["PostgreSQL + pgvector"]
    R["Redis Cache & Queue"]
    S3["AWS S3 Storage"]
end

class UL,NL,FL,BL,DL layer;

U --> N
N --> FE
N --> API
FE --> API
API --> DB
API --> R
API --> S3
W --> R
W --> DB
W --> S3
```

## 2. Component Diagram

The Backend component is broken down into Domain-Driven Design (DDD) layers.

```mermaid
classDiagram
    class FastAPI_Router {
        +auth.py
        +documents.py
        +chats.py
        +query.py
    }
    class Auth_Middleware {
        +dependencies.py
        +tokens.py
        +RateLimiter
    }
    class Services {
        +document_service.py
        +chunk_service.py
        +llm.py
        +embedding.py
    }
    class External_Clients {
        +openai_client.py
        +s3_client.py
        +redis_client.py
    }
    class SQLAlchemy_Models {
        +User
        +Document
        +Chunk
        +Chat
        +Message
    }
    class Workers {
        +ingest.py
        +tasks.py
    }

    FastAPI_Router --> Auth_Middleware : validates requests
    FastAPI_Router --> Services : delegates logic
    Services --> External_Clients : calls APIs/Storage
    Services --> SQLAlchemy_Models : mutates state
    Services --> Workers : enqueues jobs
    Workers --> Services : executes long tasks
```

## 3. Data Flow Diagram

```mermaid
flowchart TD
    Client(Client App)
    API(FastAPI)
    DB[(Postgres)]
    Cache[(Redis)]
    LLM(OpenAI API)
    
    Client -- 1. JSON Request --> API
    API -- 2. Check Auth --> Cache
    API -- 3. Query User --> DB
    API -- 4. Fetch History --> DB
    API -- 5. Generate Embedding --> LLM
    API -- 6. Vector Similarity Search --> DB
    API -- 7. Generate Response --> LLM
    API -- 8. Stream Response --> Client
    API -- 9. Async Save Message --> DB
```

## 4. Authentication Lifecycle

PDFTalk uses an OAuth2 Bearer token flow with short-lived JWT access tokens in memory and long-lived Refresh tokens in HTTP-only cookies.

```mermaid
sequenceDiagram
    participant User
    participant NextJS
    participant FastAPI
    participant Postgres
    
    User->>NextJS: Submit email/password
    NextJS->>FastAPI: POST /auth/login
    FastAPI->>Postgres: Verify hash & checks
    FastAPI-->>NextJS: 200 OK + Set-Cookie (Refresh) + JSON(Access Token)
    NextJS->>NextJS: Store Access Token in React Context
    
    rect rgb(240, 248, 255)
        note right of User: API Request Flow
        NextJS->>FastAPI: GET /api/data + Bearer Token
        FastAPI->>FastAPI: Validate JWT Signature & Expiry
        FastAPI-->>NextJS: 200 OK (Data)
    end
    
    rect rgb(255, 240, 245)
        note right of User: Refresh Flow (after 15 min)
        NextJS->>FastAPI: GET /api/data + Bearer Token
        FastAPI-->>NextJS: 401 Unauthorized (Expired)
        NextJS->>FastAPI: POST /auth/refresh + Cookie
        FastAPI->>Postgres: Validate & Delete old refresh token
        FastAPI->>Postgres: Insert new refresh token
        FastAPI-->>NextJS: 200 OK + Set-Cookie (New) + JSON(New Access)
        NextJS->>FastAPI: Retry GET /api/data + New Bearer
        FastAPI-->>NextJS: 200 OK (Data)
    end
```

## 5. Document Upload Lifecycle

PDFTalk uses a Presigned URL architecture to offload massive file uploads directly to AWS S3, sparing the FastAPI server's memory and bandwidth.

```mermaid
sequenceDiagram
    participant Browser
    participant API
    participant S3
    participant Worker
    participant DB
    
    Browser->>API: POST /documents/initiate-upload (metadata)
    API->>DB: Create Document (PENDING_UPLOAD)
    API->>S3: Generate Presigned PUT URL
    API-->>Browser: 201 Created (Upload URL + doc_id)
    
    Browser->>S3: PUT /bucket/key (File Bytes)
    S3-->>Browser: 200 OK
    
    Browser->>API: POST /documents/confirm-upload (doc_id)
    API->>S3: HeadObject (verify exists & size)
    API->>DB: Update Document (PENDING)
    API->>Worker: Enqueue Ingestion Job (RQ)
    API-->>Browser: 202 Accepted
    
    Worker->>Worker: Download, Extract text, Chunk
    Worker->>Worker: Call OpenAI for Embeddings
    Worker->>DB: Insert Chunks + Vectors (pgvector)
    Worker->>DB: Update Document (READY)
```

## 6. Request Lifecycle (RAG / Streaming Chat)

The query endpoint executes a Retrieval-Augmented Generation (RAG) pipeline and streams the output directly to the client via Server-Sent Events (SSE).

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant DB
    participant OpenAI
    
    Client->>API: POST /query (Streaming Request)
    API->>DB: Fetch Chat & Document Context
    API->>OpenAI: Request Embedding for User Query
    OpenAI-->>API: 1536-dim Vector
    API->>DB: pgvector cosine similarity search
    DB-->>API: Top K Chunks
    API->>API: Construct LLM Prompt (History + Context + Query)
    API->>OpenAI: POST /chat/completions (stream=True)
    
    loop Stream Generation
        OpenAI-->>API: Token Chunk
        API-->>Client: SSE Data Event (Yield Chunk)
    end
    
    API->>DB: Save complete Assistant Message asynchronously
```

## 7. Queue Lifecycle

```mermaid
stateDiagram-v2
    [*] --> PENDING_UPLOAD: initiate_upload()
    PENDING_UPLOAD --> PENDING: confirm_upload()
    PENDING_UPLOAD --> FAILED: Abandoned/Timeout
    PENDING --> PROCESSING: Worker takes job
    PROCESSING --> READY: Ingestion success
    PROCESSING --> FAILED: Worker throws exception
    FAILED --> PROCESSING: Manual Retry Request
    READY --> [*]
```
