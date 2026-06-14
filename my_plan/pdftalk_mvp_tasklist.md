# PDFTalk — MVP Task List
## Lightsail · Docker Compose · PostgreSQL + pgvector · Redis · FastAPI · Next.js

> **Stack:** Everything self-hosted on a single AWS Lightsail instance via Docker Compose.
> PostgreSQL (with pgvector), Redis, FastAPI, RQ worker, Nginx, Prometheus, Grafana — all in containers.
> S3 for document storage. No ECS, no EFS, no ElastiCache, no NAT Gateway.
> **Total tasks:** 71 | **Estimated solo pace:** 3–4 weeks to first real deployment

---

## Architecture Overview

```
INTERNET
   │ HTTPS (443) / HTTP (80 → redirect)
   ▼
┌─────────────────────────────────────────────────┐
│  LIGHTSAIL INSTANCE ($20/month)                  │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │  nginx (public network)                  │   │
│  │  - SSL termination (Let's Encrypt)       │   │
│  │  - Security headers                      │   │
│  │  - Rate limiting (nginx limit_req)       │   │
│  │  - Static frontend (Next.js out/)        │   │
│  │  - Reverse proxy → api:8000              │   │
│  │  - Proxy /grafana/ → grafana:3000        │   │
│  └────────────────┬─────────────────────────┘   │
│                   │ internal Docker network      │
│  ┌────────────────┼────────────────────────┐    │
│  │                ▼                        │    │
│  │  api (FastAPI · uvicorn)                │    │
│  │    └── /metrics (Prometheus scrape)     │    │
│  │  worker (RQ · ingest queue)             │    │
│  │    └── prometheus_multiproc_dir         │    │
│  │  postgres (PG 15 + pgvector)            │    │
│  │  redis (Redis 7, AUTH required)         │    │
│  │  prometheus (scrapes api:8000/metrics)  │    │
│  │  grafana (reads from prometheus)        │    │
│  │                                         │    │
│  │  All on isolated internal network       │    │
│  │  Zero ports exposed to host             │    │
│  └─────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
         │ S3 API (HTTPS, IAM user)
         ▼
┌─────────────────┐
│  AWS S3 Bucket  │  Document storage
│  (private)      │  Block all public access
└─────────────────┘
         │ HTTPS API
         ▼
┌─────────────────┐
│  OpenAI API     │  Embeddings + GPT-4o-mini
└─────────────────┘
```

---

## Architectural Decisions (Read First)

> **ADR-001: PostgreSQL + pgvector instead of FAISS + EFS**
> pgvector runs inside your existing Postgres container. Zero additional services. Zero file locking. Zero index corruption risk. The query is 5 lines of SQL. Performance is indistinguishable from FAISS at MVP scale (<100K chunks per user). Migration path to Pinecone when needed is a single module swap.

> **ADR-002: Everything in Docker Compose on Lightsail**
> No ECS, no Fargate, no ALB. One instance, one compose file, one place to look when something breaks. The operational surface area is radically smaller. A solo developer should be shipping features, not debugging ECS service discovery.

> **ADR-003: Postgres and Redis in Docker, not managed services**
> For MVP this is correct. You save $30/month on ElastiCache and $13/month on RDS. The trade-off is that backup automation (pg_dump cron) is your responsibility — covered in T-62. Add managed RDS when you have paying users and a clear uptime SLA requirement.

> **ADR-004: S3 for document storage, not Lightsail disk**
> Lightsail SSD should not hold user-uploaded documents. Disk fills up silently. If the instance is recreated, files are gone. S3 provides durable, cheap, scalable object storage for ~$0.023/GB. This is not negotiable.

---

# Phase 1 — Project Foundation

---

### T-01 · Monorepo scaffold

**What to build:** Initialise the repo. Create `backend/` (FastAPI) and `frontend/` (Next.js) workspaces. Add root `Makefile` with `make dev`, `make test`, `make deploy` shortcuts. Create `README.md` and `LICENSE`.

**Tech:** Git, Python `uv` (or pip), Node.js, pnpm, Makefile

**Depends on:** —

> 🔒 **Security — Do this before your first commit:**
> Create `.gitignore` that covers ALL of the following. A credential leaked to a public repo is a permanent breach — git history cannot be fully purged from GitHub's caches.
> ```
> # Secrets — NEVER commit these
> .env
> .env.*
> !.env.example
> backend/.env
> frontend/.env.local
>
> # Python
> __pycache__/
> *.pyc
> .venv/
> .pytest_cache/
> htmlcov/
> .mypy_cache/
>
> # Node
> node_modules/
> .next/
> out/
>
> # Docker
> *.tar.gz
>
> # OS
> .DS_Store
> ```

> 🎓 **Senior Insight:** Install a pre-commit hook right now to prevent accidental secret commits. `pip install detect-secrets && detect-secrets scan > .secrets.baseline` then add to `.pre-commit-config.yaml`. This catches API keys, passwords, and tokens before they ever reach the remote. One leaked OpenAI key will cost you hundreds of dollars before you notice.

---

### T-02 · Environment variable strategy

**What to build:** Create `.env.example` files for both `backend/` and `frontend/`. Document every variable: name, purpose, required/optional, example value. Set up `python-dotenv` in FastAPI. Set up zod env validation in Next.js.

**Tech:** `python-dotenv`, `zod`

**Depends on:** T-01

> 🔒 **Security:** The `.env.example` is committed to git. The `.env` file is NEVER committed. Treat `.env` like a password — it contains all credentials for every service.

> 🎓 **Senior Insight:** Validate env vars at app startup, not at first use. If `OPENAI_API_KEY` is missing, fail loudly on boot, not when the first user uploads a document 3 hours after deployment. In FastAPI, use a Pydantic `Settings` class with `BaseSettings` from `pydantic-settings` — it reads `.env` automatically and raises a clear error on missing required fields.
> ```python
> from pydantic_settings import BaseSettings
>
> class Settings(BaseSettings):
>     DATABASE_URL: str
>     REDIS_URL: str
>     JWT_SECRET: str          # min 32 chars, generated with: openssl rand -hex 32
>     OPENAI_API_KEY: str
>     AWS_ACCESS_KEY_ID: str
>     AWS_SECRET_ACCESS_KEY: str
>     S3_BUCKET_NAME: str
>     SMTP_HOST: str
>     SMTP_PORT: int = 587
>     SMTP_USER: str
>     SMTP_PASSWORD: str
>     APP_URL: str             # e.g. https://pdftalk.com
>     MAX_DOCS_PER_USER: int = 20
>     MAX_DAILY_TOKENS_PER_USER: int = 100000
>
>     class Config:
>         env_file = ".env"
>
> settings = Settings()  # Raises immediately if any required field is missing
> ```

---

### T-03 · Local Docker Compose (full dev environment)

**What to build:** A `docker-compose.dev.yml` that spins up the complete local stack: `postgres` (with pgvector), `redis`, `api` (hot-reload), `worker`, and `nginx`. The `api` service should mount `./backend:/app` for live code reloading.

**Tech:** Docker Compose, `pgvector/pgvector:pg15` image

**Depends on:** T-01, T-02

> 🎓 **Senior Insight:** Your local environment must mirror production. The moment they diverge, you get "works on my machine" bugs that waste hours. Use the same Postgres version, same Redis version, same Nginx config. The only difference is hot-reload mounts and `--reload` flag on uvicorn.

> 🔒 **Security — Docker network isolation:**
> ```yaml
> networks:
>   internal:    # postgres, redis, api, worker — never exposed
>     driver: bridge
>   external:    # nginx only — has ports 80/443 on host
>     driver: bridge
>
> services:
>   postgres:
>     networks: [internal]    # NO external network
>     # Port 5432 NOT exposed to host in production
>
>   redis:
>     networks: [internal]    # NO external network
>     # Port 6379 NOT exposed to host in production
>
>   api:
>     networks: [internal]    # Nginx proxies to it
>
>   nginx:
>     networks: [internal, external]  # Bridge between internet and internal
>     ports: ["80:80", "443:443"]
> ```
> In local dev only, you may expose `5432` and `6379` to host for direct inspection. Remove these from the production compose file.

---

# Phase 2 — Database

---

### T-04 · Database schema + pgvector + Alembic

**What to build:** Configure Alembic. Write migrations for all 6 tables: `users`, `documents`, `chunks` (with `embedding vector(1536)` column), `refresh_tokens`, `email_verifications`, `job_logs`. Enable the `pgvector` extension in the first migration. Add all indexes.

**Tech:** SQLAlchemy, Alembic, PostgreSQL 15, pgvector

**Depends on:** T-03

```sql
-- Migration 001: enable pgvector + create schema
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    email_lower TEXT NOT NULL UNIQUE,  -- lowercase normalized to prevent dupe accounts
    password_hash TEXT NOT NULL,
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    mime_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING|PROCESSING|READY|FAILED
    error_message TEXT,
    chunk_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_documents_user_id ON documents(user_id);
CREATE INDEX idx_documents_status ON documents(status);

CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    embedding vector(1536)
);
CREATE INDEX idx_chunks_document_id ON chunks(document_id);
CREATE INDEX idx_chunks_user_id ON chunks(user_id);
-- NOTE: IVFFlat index added in migration 002 after first data load (needs ~100 rows min)

CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,  -- SHA-256 hash, never store raw token
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);

CREATE TABLE email_verifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE job_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    traceback TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

> 🎓 **Senior Insight — pgvector image:**
> Use `pgvector/pgvector:pg15` as your Postgres Docker image — it has pgvector pre-installed. The standard `postgres:15` image does not. Your `alembic env.py` should call `CREATE EXTENSION IF NOT EXISTS vector` in the first migration, not manually. Any schema state not in a migration is state that can't be reproduced.

> 🔒 **Security:** Store `email_lower = email.lower()` and query by `email_lower` to prevent duplicate accounts via `User@example.com` vs `user@example.com`. Store token hashes (SHA-256), never raw tokens, in the DB. If the tokens table is compromised, attackers get hashes, not usable tokens.

> 🎓 **Senior Insight — IVFFlat index timing:**
> Do NOT create the IVFFlat index in migration 001. IVFFlat requires data to build its clusters. Create it in migration 002 after you've ingested your first real documents, or conditionally only if the table has >1000 rows. For MVP with <100K chunks, a full table scan (no index) takes <50ms. Add the index when it gets slow, not before.

---

### T-05 · Database client (async + connection pooling)

**What to build:** Configure `SQLAlchemy` async engine with `asyncpg`. Create `db/session.py` with `get_db()` dependency. Tune `pool_size` and `max_overflow`. Add a startup check that confirms DB connectivity.

**Tech:** SQLAlchemy (async), asyncpg, FastAPI `Depends`

**Depends on:** T-04

> 🎓 **Senior Insight — connection math:**
> Postgres running in Docker on a 4GB Lightsail instance defaults to `max_connections = 100`. Your stack has: 1 API process (pool_size=10) + 1 worker process (pool_size=5) = 15 active connections max. You have headroom for multiple workers. **Never set pool_size > 20 per process on this instance.** When you scale to multiple workers, add PgBouncer in front of Postgres.
> ```python
> engine = create_async_engine(
>     settings.DATABASE_URL,
>     pool_size=10,
>     max_overflow=5,
>     pool_pre_ping=True,   # Reconnect on stale connections after Docker restart
>     pool_recycle=3600,    # Recycle connections hourly
> )
> ```

---

# Phase 3 — Lightsail Infrastructure

---

### T-06 · S3 bucket + IAM user

**What to build:** Create S3 bucket `pdftalk-documents` in `ap-south-1`. Enable versioning, SSE-S3 encryption, block all public access. Create a dedicated IAM user `pdftalk-app` with a minimal custom policy: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:HeadObject` on `arn:aws:s3:::pdftalk-documents/*` only. Generate access keys, store in `.env`.

**Tech:** AWS S3, AWS IAM

**Depends on:** —

> 🔒 **Security — IAM policy (minimal):**
> ```json
> {
>   "Version": "2012-10-17",
>   "Statement": [{
>     "Effect": "Allow",
>     "Action": ["s3:PutObject","s3:GetObject","s3:DeleteObject","s3:HeadObject"],
>     "Resource": "arn:aws:s3:::pdftalk-documents/*"
>   }, {
>     "Effect": "Allow",
>     "Action": ["s3:ListBucket"],
>     "Resource": "arn:aws:s3:::pdftalk-documents",
>     "Condition": {"StringLike": {"s3:prefix": ["*"]}}
>   }]
> }
> ```
> This user cannot: create buckets, delete buckets, list all buckets, change bucket policy, access any other bucket. Principle of least privilege.

> 🎓 **Senior Insight:** Store files as `{user_id}/{document_id}/{original_filename}` — never flat. This gives you: user data isolation, predictable delete patterns, and no filename collision. A user named `../../../etc/passwd` uploading a file is defeated by this structure (S3 keys are not filesystem paths, but the pattern is still correct).

---

### T-07 · Lightsail instance + SSH hardening + firewall

**What to build:** Provision a `$20/month` Lightsail instance (2 vCPU, 4GB RAM, Ubuntu 22.04 LTS, `ap-south-1`). Assign a static IP. Harden SSH. Configure UFW. Install fail2ban.

**Tech:** AWS Lightsail, Ubuntu 22.04, UFW, fail2ban, SSH

**Depends on:** —

> 🔒 **Security — SSH hardening (run immediately after first login):**
> ```bash
> # 1. Add your SSH public key to authorized_keys FIRST
> # Then edit /etc/ssh/sshd_config:
>
> PermitRootLogin no
> PasswordAuthentication no
> PubkeyAuthentication yes
> AuthorizedKeysFile .ssh/authorized_keys
> MaxAuthTries 3
> ClientAliveInterval 300
> ClientAliveCountMax 2
>
> sudo systemctl restart sshd
>
> # 2. UFW firewall - ONLY 22, 80, 443
> sudo ufw default deny incoming
> sudo ufw default allow outgoing
> sudo ufw allow 22/tcp comment 'SSH'
> sudo ufw allow 80/tcp comment 'HTTP'
> sudo ufw allow 443/tcp comment 'HTTPS'
> sudo ufw enable
> sudo ufw status verbose  # verify
>
> # 3. fail2ban - blocks SSH brute force
> sudo apt install fail2ban -y
> sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
> # Edit jail.local: bantime = 3600, maxretry = 5, findtime = 600
> sudo systemctl enable fail2ban && sudo systemctl start fail2ban
>
> # 4. Automatic security updates
> sudo apt install unattended-upgrades -y
> sudo dpkg-reconfigure -plow unattended-upgrades  # Enable
> ```

> 🎓 **Senior Insight:** Do NOT use Lightsail's "networking" tab to open ports. Use UFW directly on the instance — it also applies to traffic originating from within the VPC. Lightsail's networking is an additional layer, not a replacement. Set both to be consistent.

---

### T-08 · Docker + Docker Compose on Lightsail

**What to build:** Install Docker Engine and Docker Compose v2 on the Lightsail instance. Create `/opt/pdftalk/` as the application directory. Set correct ownership. Add `ubuntu` user to the `docker` group.

**Tech:** Docker Engine, Docker Compose v2

**Depends on:** T-07

```bash
# Install Docker Engine (official script — don't use apt's outdated version)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker  # apply group without re-login

# Verify
docker --version
docker compose version

# Create app directory
sudo mkdir -p /opt/pdftalk /opt/backups
sudo chown ubuntu:ubuntu /opt/pdftalk /opt/backups
```

> 🎓 **Senior Insight:** Use the official Docker install script, not `apt install docker.io`. The Ubuntu package manager ships a version that's often 2+ major versions behind. Docker Compose v2 (`docker compose`) is a CLI plugin — it's what's installed by the official script. The legacy `docker-compose` (v1) is deprecated.

---

### T-09 · Route 53 DNS + Lightsail static IP

**What to build:** In Route 53, create a hosted zone for your domain. Add an A record pointing `pdftalk.com` (and `www.pdftalk.com`) to the Lightsail static IP. If using an existing registrar, update name servers to Route 53's. Verify DNS propagation.

**Tech:** AWS Route 53

**Depends on:** T-07

> 🎓 **Senior Insight:** DNS propagation takes up to 48 hours but is usually <1 hour for Route 53. Run `dig +short yourdomain.com` to check. You need DNS pointing at your server BEFORE you can get a Let's Encrypt certificate — certbot validates domain ownership via HTTP challenge.

---

### T-10 · Nginx + Let's Encrypt SSL

**What to build:** Install Nginx on Lightsail host (NOT in Docker yet — this is for certbot). Get Let's Encrypt certificates via certbot. Then move to the Docker Nginx setup. Configure auto-renewal cron.

**Tech:** Nginx, certbot, Let's Encrypt

**Depends on:** T-09

> 🎓 **Senior Insight — certbot for Docker Nginx:**
> The cleanest approach is to get certs via certbot on the host (using the standalone or webroot method) and then mount them into the Nginx container. Alternatively, use the `certbot/certbot` Docker image with shared volumes. Either way, set up a cron job to renew:
> ```bash
> # /etc/cron.d/certbot-renew
> 0 0,12 * * * root certbot renew --quiet --deploy-hook "docker compose -f /opt/pdftalk/docker-compose.yml exec -T nginx nginx -s reload"
> ```
> Let's Encrypt certs expire every 90 days. Certbot renews when <30 days remain. The deploy hook reloads Nginx after renewal without downtime.

> 🔒 **Security — Nginx SSL config (production-grade TLS):**
> ```nginx
> ssl_protocols TLSv1.2 TLSv1.3;
> ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
> ssl_prefer_server_ciphers off;
> ssl_session_cache shared:SSL:10m;
> ssl_session_timeout 10m;
> ssl_stapling on;
> ssl_stapling_verify on;
> ```
> This enforces TLS 1.2+ only (TLS 1.0 and 1.1 are deprecated) and uses only strong cipher suites. Test with `ssllabs.com/ssltest` after deployment.

---

### T-11 · Production secrets on Lightsail

**What to build:** Create `/opt/pdftalk/.env` on the Lightsail instance with all production credentials. Set file permissions to `600` (owner read/write only). Add this path to the production Docker Compose `env_file` directive. Never commit this file.

**Tech:** Linux file permissions, Docker Compose env_file

**Depends on:** T-08

```bash
# On Lightsail instance:
nano /opt/pdftalk/.env  # Add all production credentials
chmod 600 /opt/pdftalk/.env
chown ubuntu:ubuntu /opt/pdftalk/.env

# Verify only owner can read
ls -la /opt/pdftalk/.env
# Output: -rw------- 1 ubuntu ubuntu ... .env
```

> 🔒 **Security:** Generate strong, unique values for each secret:
> ```bash
> # JWT secret (32+ bytes):
> openssl rand -hex 32
>
> # Postgres password (strong):
> openssl rand -base64 24
>
> # Redis password:
> openssl rand -base64 24
>
> # Each should be unique — never reuse passwords across services
> ```

---

# Phase 4 — FastAPI Backend Scaffold

---

### T-12 · FastAPI project scaffold

**What to build:** Create `backend/` with: `main.py`, `pyproject.toml`, folder structure (`routers/`, `services/`, `models/`, `db/`, `workers/`, `utils/`, `middleware/`). Install all dependencies. Configure uvicorn. Add a `/health` placeholder.

**Tech:** FastAPI, Python 3.12, uvicorn, pyproject.toml

**Depends on:** T-02

```toml
# pyproject.toml dependencies
[project.dependencies]
fastapi = ">=0.111"
uvicorn = {extras = ["standard"]}
sqlalchemy = {extras = ["asyncio"]}
asyncpg = "*"
alembic = "*"
pydantic-settings = "*"
passlib = {extras = ["bcrypt"]}
python-jose = {extras = ["cryptography"]}
redis = "*"
rq = "*"
boto3 = "*"
openai = "*"
pymupdf = "*"
tiktoken = "*"
structlog = "*"
python-multipart = "*"    # For file uploads
python-magic = "*"        # For MIME type validation
httpx = "*"               # For tests
email-validator = "*"     # For Pydantic email validation

[project.optional-dependencies]
test = ["pytest", "pytest-asyncio", "pytest-cov", "fakeredis", "moto[s3]"]
```

> 🎓 **Senior Insight:** Structure your FastAPI app with a single `app/` package and register routers explicitly. Avoid putting business logic in route handlers — route handlers should only do: validate input, call a service function, return the response. All logic lives in `services/`. This makes testing trivial and the codebase navigable.

---

### T-13 · Redis client

**What to build:** Create `utils/redis_client.py`. Configure `redis.asyncio` connection pool with AUTH, TLS (optional for local). Expose typed helper functions: `set_with_ttl()`, `get()`, `delete()`, `increment_counter()`.

**Tech:** `redis-py` (async)

**Depends on:** T-03, T-12

> 🔒 **Security:** Use key namespacing to prevent collisions between different data types:
> ```python
> # Token keys:   "token:refresh:{sha256_hash}"
> # Rate limit:   "ratelimit:login:{ip_address}"
> # Lockout:      "lockout:{user_id}"
> # Quota:        "quota:tokens:{user_id}:{date_YYYYMMDD}"
> # Email verify: "emailverify:{token_hash}"
> ```
> Never store raw tokens in Redis. Always hash first (SHA-256).

---

### T-14 · S3 client

**What to build:** Create `utils/s3_client.py`. Wrap `boto3` with helper functions: `upload_file()`, `download_file()`, `delete_object()`, `generate_presigned_download_url()`. Configure with IAM credentials from `settings`. Add unit tests with `moto[s3]` mock.

**Tech:** boto3, moto (for tests)

**Depends on:** T-06, T-12

> 🎓 **Senior Insight:** Abstract S3 behind a clean interface from day one. If you ever need to move to Cloudflare R2 or a self-hosted MinIO, you change one file. More importantly, a clean `S3Client` class makes testing trivially easy — mock one object, not scattered `boto3` calls throughout the codebase.

---

# Phase 5 — Authentication System

---

### T-15 · User model + password hashing

**What to build:** Implement the `User` SQLAlchemy model. Create `auth/password.py` with `hash_password()` and `verify_password()` using `passlib[bcrypt]` at 12 rounds. Unit test both functions.

**Tech:** SQLAlchemy, `passlib[bcrypt]`

**Depends on:** T-05

> 🔒 **Security — bcrypt details:**
> - 12 rounds is correct. 10 is the minimum acceptable; 12 is the current safe default.
> - bcrypt is intentionally slow (~250ms at 12 rounds). This is a feature, not a bug. It makes brute-force infeasible.
> - Never use bcrypt for anything other than passwords. For tokens and other data, use `secrets.compare_digest()` for constant-time comparison.
> - The `passlib` library handles salt generation automatically. Never generate your own salt.

---

### T-16 · JWT token service + refresh token storage

**What to build:** Implement `auth/tokens.py`. Generate access tokens (15-min expiry, HS256). Generate opaque refresh tokens (stored in DB as SHA-256 hash, raw token returned to client only once). Implement `decode_access_token()` with typed exceptions. Implement `store_refresh_token()` and `validate_and_rotate_refresh_token()`.

**Tech:** `python-jose`, SHA-256 (stdlib `hashlib`)

**Depends on:** T-05, T-13, T-15

> 🔒 **Security — refresh token design:**
> Refresh tokens are stored as `SHA-256(raw_token)` in the database. The raw token (a `secrets.token_urlsafe(32)`) is sent to the client once in an httpOnly cookie and never stored anywhere server-side. This means even if your database is breached, the attacker gets only hashes — they cannot derive valid tokens from them.
>
> **Rotation on every use:** When a refresh token is used, it is immediately deleted and a new one is issued. If an attacker steals a refresh token and uses it, the legitimate user's next refresh attempt will fail (token already used/deleted), alerting them of a possible session theft.

> 🔒 **JWT access token claims:**
> ```python
> payload = {
>     "sub": str(user_id),     # subject
>     "iat": now,              # issued at
>     "exp": now + timedelta(minutes=15),  # expiry — short
>     "jti": str(uuid4()),     # JWT ID for revocation if needed
>     "type": "access"         # prevent refresh tokens being used as access tokens
> }
> ```
> Always check the `type` claim on decode. A malicious actor who somehow obtains a refresh token should not be able to use it as an access token.

---

### T-17 · Email verification service

**What to build:** Create `services/email_verification.py`. Generate a secure verification token (`secrets.token_urlsafe(32)`), store its hash in `email_verifications` table with a 24-hour expiry, and send an email with the verification link. Create `utils/email.py` to send HTML email via SMTP (or Resend API).

**Tech:** Python `smtplib`, or `resend` SDK, `secrets`

**Depends on:** T-05, T-13

> 🎓 **Senior Insight — email provider choice:**
> For MVP, use [Resend](https://resend.com) ($0/month for first 3,000 emails). It's a modern transactional email API with a clean Python SDK (`pip install resend`). Avoid setting up raw SMTP with Gmail — Gmail blocks programmatic logins by default and has low send limits. AWS SES requires domain verification and is overkill at this stage.

> 🔒 **Security:** Email verification is non-negotiable before allowing API access. Without it: bots register with fake emails, your IP gets flagged for spam, and attackers abuse your OpenAI quota with throwaway accounts. `POST /auth/register` issues a verification email and returns `202 Accepted`. Tokens are NOT issued until the email is verified.

---

### T-18 · Registration endpoint

**What to build:** `POST /auth/register` — validate email uniqueness (by `email_lower`), validate password strength (min 8 chars, at least 1 uppercase, 1 number), hash password, insert user row with `is_verified=False`, generate email verification token, send verification email. Return `202 { message: "Verification email sent" }`. Do NOT issue tokens yet.

**Tech:** FastAPI, Pydantic, SQLAlchemy

**Depends on:** T-15, T-16, T-17

> 🔒 **Security:**
> - Return the same generic response whether the email is new or already registered. Never reveal "that email is already taken" — it leaks which emails are in your database (user enumeration attack).
> - Validate password strength server-side even if the frontend also validates. Never trust client-side validation alone.
> - Apply a rate limit of 5 registrations per IP per hour. Spam registrations are common.

---

### T-19 · Email verification endpoint

**What to build:** `GET /auth/verify-email?token={raw_token}` — hash the incoming token, look up in `email_verifications`, validate expiry, mark `users.is_verified = True`, delete the verification row. Redirect to frontend `/login?verified=true`.

**Tech:** FastAPI, SQLAlchemy

**Depends on:** T-17, T-18

> 🔒 **Security:** Delete the verification token immediately after successful use. One-time-use tokens must be one-time-use. Also delete expired tokens periodically (daily cron or on-use cleanup).

---

### T-20 · Login endpoint

**What to build:** `POST /auth/login` — look up user by `email_lower`, check `is_verified`, check `is_active`, check `locked_until` (account lockout), verify password (passlib), increment `failed_login_attempts` on failure. On success: reset `failed_login_attempts`, issue access token (JSON body) + refresh token (httpOnly cookie). Rate-limit to 10 requests/min per IP.

**Tech:** FastAPI, Redis (rate limiting + lockout), passlib

**Depends on:** T-15, T-16, T-18

> 🔒 **Security — account lockout:**
> After 10 consecutive failed login attempts, set `locked_until = NOW() + INTERVAL '15 minutes'`. Return a generic `401 Invalid credentials` — never `401 Account locked` (reveals the account exists).
>
> **Cookie settings (non-negotiable):**
> ```python
> response.set_cookie(
>     key="refresh_token",
>     value=raw_refresh_token,
>     httponly=True,      # Cannot be read by JavaScript
>     secure=True,        # Only sent over HTTPS
>     samesite="strict",  # Not sent on cross-site requests (CSRF protection)
>     max_age=60 * 60 * 24 * 7,  # 7 days
>     path="/auth/refresh",       # Cookie only sent to this path, not every request
> )
> ```
> Setting `path="/auth/refresh"` is often overlooked. It means the refresh token cookie is only sent when the browser hits `/auth/refresh`, not on every API request. This reduces the attack surface significantly.

---

### T-21 · Token refresh + logout endpoints

**What to build:** `POST /auth/refresh` — read refresh token from httpOnly cookie, hash it, validate against DB (check user binding + expiry), immediately delete old token, issue new access token + new refresh token (rotation). `POST /auth/logout` — hash and delete refresh token from DB, clear cookie. Return `204`.

**Tech:** FastAPI, SQLAlchemy, Redis

**Depends on:** T-16, T-20

> 🎓 **Senior Insight:** The logout endpoint MUST delete the refresh token from the database. Simply clearing the cookie is not enough — an attacker who has already copied the cookie value could still use it. The server-side deletion is what actually invalidates the session.

---

### T-22 · JWT auth middleware (dependency)

**What to build:** Create `auth/dependencies.py` with `get_current_user()` FastAPI dependency. Extracts Bearer token from `Authorization` header, decodes it, validates `type == "access"`, returns the `user_id`. Also create `get_verified_user()` that additionally checks `is_verified=True` and `is_active=True`. Apply `get_verified_user` to all data endpoints.

**Tech:** FastAPI `Depends`, python-jose

**Depends on:** T-16, T-20

> 🔒 **Security:** Always check `is_active` and `is_verified` on every protected request, not just at login. If you deactivate a user's account, their existing JWT should stop working at next DB check — but since JWTs are stateless, a 15-min window exists before the token expires naturally. For immediate revocation, store a `revoked_jtis` set in Redis (overkill for MVP, but note it exists).

---

### T-23 · Auth integration tests

**What to build:** Pytest integration tests covering the full auth lifecycle: register → receives 202 → verify email → login → get access token → access protected route → refresh → logout → verify token revoked. Test failure paths: wrong password, locked account, expired token, unverified email.

**Tech:** pytest, httpx (AsyncClient), fakeredis

**Depends on:** T-20, T-21, T-22

---

# Phase 6 — File Ingestion Pipeline

---

### T-24 · Document model + state machine

**What to build:** Implement the `Document` SQLAlchemy model with status transitions: `PENDING → PROCESSING → READY | FAILED`. Create typed status enum. Write Alembic migration.

**Tech:** SQLAlchemy, PostgreSQL enum, Alembic

**Depends on:** T-05

> 🎓 **Senior Insight:** Treat document status as a state machine with enforced transitions. A document should never go from `READY` back to `PENDING` without going through `PROCESSING` first. Enforce this in the service layer, not the DB (application-level state machine). It prevents a class of concurrency bugs where two workers process the same document.

---

### T-25 · File validation service

**What to build:** `services/file_validation.py` — validate: allowed MIME types (`application/pdf`, `text/plain`, `text/markdown`), file size ≤ 50MB, magic byte validation (first 4 bytes for PDF: `%PDF`). Raise typed `FileValidationError` with specific reason.

**Tech:** `python-magic`, Python stdlib

**Depends on:** T-12

> 🔒 **Security:** Never trust the `Content-Type` header from the browser. Always validate magic bytes server-side. A malicious user can send a PHP script with `Content-Type: application/pdf`. The magic byte check (`%PDF` for PDFs) is a second layer that actually inspects file content.
>
> Validate file size BEFORE reading the full file into memory. Use `UploadFile.size` if available, or stream-read with a byte counter to enforce the limit without loading a 50MB file into RAM.

---

### T-26 · Document upload endpoint

**What to build:** `POST /documents/upload` — authenticate user, check per-user document quota (`MAX_DOCS_PER_USER`), run file validation, generate UUID `document_id`, upload to S3 at `{user_id}/{document_id}/{filename}`, insert `Document` row (status=PENDING), enqueue RQ job. Return `202 { document_id, status }`.

**Tech:** FastAPI, boto3, SQLAlchemy, RQ

**Depends on:** T-14, T-22, T-24, T-25

> 🔒 **Security:** Enforce per-user document quota BEFORE accepting the file upload. If the user has reached 20 documents, return `429` immediately — don't accept the upload, run validation, upload to S3, and THEN reject. Fail fast.
>
> Generate the S3 key from a UUID, not from the original filename. Store the original filename in the database only. Never use user-supplied filenames as file paths anywhere.

---

### T-27 · Document status / list / delete endpoints

**What to build:**
- `GET /documents/{document_id}/status` — ownership check, return status + metadata
- `GET /documents` — paginated list for the authenticated user (`?status=READY&limit=20&offset=0`)
- `DELETE /documents/{document_id}` — verify ownership, delete from S3, delete DB rows (cascade deletes chunks), return `204`

**Tech:** FastAPI, SQLAlchemy, boto3

**Depends on:** T-22, T-24, T-26

> 🔒 **Security:** Always verify document ownership on every single endpoint — check `document.user_id == current_user.id`. Never assume ownership from the URL alone. A user who guesses another user's `document_id` UUID should get `404` (not `403` — a 404 doesn't reveal the resource exists).

---

### T-28 · RQ worker setup

**What to build:** Create `workers/worker.py` as the RQ worker entrypoint. Configure `failed` queue (dead-letter), `max_retries = 3`, exponential backoff (`30s → 120s → 480s`). On final failure: update document status to `FAILED`, write to `job_logs`.

**Tech:** RQ, Redis

**Depends on:** T-13, T-24

> 🎓 **Senior Insight:** RQ jobs are executed in a separate process from the API. This means your worker has its own DB connection pool and its own Redis connection. Configure both independently. The worker's pool_size can be smaller (5 connections) since it processes one document at a time.

---

### T-29 · Text extraction service

**What to build:** `services/extraction.py` — download raw file from S3, dispatch to correct extractor: PyMuPDF for PDFs (page-by-page text), `open()` for TXT/MD. Return single cleaned text string. Handle encrypted/corrupt PDFs with a typed `ExtractionError`.

**Tech:** PyMuPDF (`fitz`), boto3

**Depends on:** T-14, T-28

---

### T-30 · Chunking service

**What to build:** `services/chunking.py` — split extracted text into 512-token chunks with 64-token overlap using `tiktoken` (`cl100k_base`). Before accepting the job, calculate the estimated embedding cost (total tokens × price) and reject if it exceeds the per-user daily quota. Return `List[{ chunk_index, text, token_count }]`.

**Tech:** tiktoken

**Depends on:** T-29

> 🔒 **Security — OpenAI cost protection:**
> ```python
> MAX_TOKENS_PER_DOCUMENT = 500_000  # ~$0.01 at current pricing
> estimated_tokens = sum(c.token_count for c in chunks)
> if estimated_tokens > MAX_TOKENS_PER_DOCUMENT:
>     raise DocumentTooLargeError(f"Document has {estimated_tokens} tokens, limit is {MAX_TOKENS_PER_DOCUMENT}")
> ```
> Also check the user's rolling daily token usage from Redis before embedding. A user on a free tier grinding through your OpenAI budget is a business risk, not just a technical one.

---

### T-31 · Ingestion worker orchestrator

**What to build:** `workers/ingest.py` — full RQ job: `status=PROCESSING` → extract → chunk → cost check → embed (batched) → store chunks + vectors in Postgres → `status=READY`. Wrapped in try/except that sets `status=FAILED` and writes to `job_logs` on any error.

**Tech:** RQ, PyMuPDF, tiktoken, OpenAI, SQLAlchemy, boto3

**Depends on:** T-28, T-29, T-30, T-35 (run after pgvector setup)

---

# Phase 7 — Embeddings + pgvector

---

### T-32 · OpenAI client (with circuit breaker + cost guard)

**What to build:** `utils/openai_client.py` — wrap the OpenAI SDK. Configure API key from settings. Add a retry wrapper for `RateLimitError` (3 attempts, exponential backoff). Add a per-user daily token counter in Redis. Add a circuit breaker pattern: if OpenAI returns 5xx 3 times in a row, stop sending requests for 60 seconds.

**Tech:** `openai` SDK, Redis (token counter)

**Depends on:** T-13, T-12

> 🔒 **Security — daily token quota (Redis counter):**
> ```python
> async def check_and_increment_token_usage(user_id: str, tokens: int) -> None:
>     today = datetime.utcnow().strftime("%Y%m%d")
>     key = f"quota:tokens:{user_id}:{today}"
>     current = await redis.incr(key, tokens)
>     if current == tokens:  # First write today — set expiry
>         await redis.expire(key, 86400 + 3600)  # 25h to account for timezone edges
>     if current > settings.MAX_DAILY_TOKENS_PER_USER:
>         raise DailyQuotaExceededError()
> ```

---

### T-33 · Embedding service

**What to build:** `services/embedding.py` — accept list of text strings, batch into groups of 100, call `text-embedding-3-small`, L2-normalize each vector. Return `List[List[float]]` of shape `(n, 1536)`.

**Tech:** openai SDK, numpy

**Depends on:** T-32

---

### T-34 · pgvector retrieval service

**What to build:** `services/retrieval.py` — embed the query string, run a pgvector cosine similarity search filtered by `user_id` and `document_ids`, return top-K results. Pure SQL — no external services, no file I/O, no memory-mapped indexes.

**Tech:** asyncpg, pgvector

**Depends on:** T-04, T-33

```python
async def retrieve_similar_chunks(
    user_id: str,
    document_ids: List[str],
    query_embedding: List[float],
    k: int = 5,
    db: AsyncSession = None,
) -> List[Chunk]:
    # This is the entire vector search. No FAISS. No EFS. No file locking.
    result = await db.execute(
        text("""
            SELECT id, text, document_id, chunk_index
            FROM chunks
            WHERE user_id = :user_id
              AND document_id = ANY(:doc_ids)
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :query_vec
            LIMIT :k
        """),
        {
            "user_id": user_id,
            "doc_ids": document_ids,
            "query_vec": str(query_embedding),
            "k": k,
        }
    )
    return result.fetchall()
```

> 🎓 **Senior Insight — pgvector operator choice:**
> Use `<=>` (cosine distance) for text embeddings. It measures the angle between vectors, not their magnitude, which makes it appropriate for semantic similarity where you've L2-normalized your vectors. `<->` (Euclidean distance) and `<#>` (inner product) are the other options. For OpenAI embeddings that have been L2-normalized, all three give the same ranking — but `<=>` is semantically clearest.

---

### T-35 · Chunk model + pgvector persistence

**What to build:** Implement the `Chunk` SQLAlchemy model including the `embedding` column (using pgvector's `Vector` type). After embedding generation, bulk-insert all chunks + their embeddings in a single transaction. Verify row counts match.

**Tech:** SQLAlchemy, pgvector SQLAlchemy integration (`sqlalchemy-pgvector`)

**Depends on:** T-04, T-33

> 🎓 **Senior Insight — bulk insert performance:**
> Use `session.add_all(chunk_objects)` + single `session.commit()` rather than inserting one row at a time. For a 200-chunk document, a bulk insert takes ~50ms. Row-by-row takes ~2 seconds. The difference compounds at scale.

---

### T-36 · End-to-end ingestion integration test

**What to build:** Integration test: upload a real small PDF → trigger worker synchronously → assert `status=READY`, chunk rows exist in DB with non-null embeddings, pgvector similarity search returns results.

**Tech:** pytest, httpx, test PostgreSQL

**Depends on:** T-31, T-34, T-35

---

# Phase 8 — LLM Integration + Streaming

---

### T-37 · Prompt builder + query validation

**What to build:** `services/prompt.py` — build the grounded RAG prompt: system instruction (answer only from context, cite sources by filename, say "I don't know" if unsure), context block (chunks with source labels), user question. Cap context at 3,000 tokens using tiktoken. `services/query_validation.py` — validate request schema: `document_ids` (non-empty, max 10, all READY, all owned by user), `question` (non-empty, max 1,000 chars).

**Tech:** tiktoken, FastAPI, Pydantic

**Depends on:** T-22, T-27, T-34

---

### T-38 · Streaming LLM service

**What to build:** `services/llm.py` — call `gpt-4o-mini` with `stream=True`. Return an async generator yielding token strings. Wrap in retry logic for `RateLimitError` (3 attempts, 5s backoff). Count output tokens for quota tracking.

**Tech:** openai SDK (async), Python async generators

**Depends on:** T-32, T-37

---

### T-39 · SSE streaming endpoint

**What to build:** `POST /query/ask` — validate request, run ownership + readiness guard, embed query, retrieve top-K chunks, hydrate text, build prompt, stream GPT-4o-mini response. Use FastAPI `StreamingResponse` with `Content-Type: text/event-stream`. Format: `data: {token}\n\n`. Final event: `data: [DONE]\n\n`. Error event: `data: {"error": "..."}\n\n`.

**Tech:** FastAPI `StreamingResponse`, SSE, OpenAI async streaming

**Depends on:** T-34, T-37, T-38

> 🎓 **Senior Insight — SSE via POST in the browser:**
> `EventSource` in browsers only supports GET requests. For a POST-based SSE endpoint, use the `fetch` API with `ReadableStream` on the frontend:
> ```typescript
> const response = await fetch('/api/query/ask', {
>   method: 'POST',
>   headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
>   body: JSON.stringify({ document_ids, question }),
> });
> const reader = response.body!.getReader();
> const decoder = new TextDecoder();
> while (true) {
>   const { done, value } = await reader.read();
>   if (done) break;
>   const text = decoder.decode(value);
>   // Parse SSE format: "data: {token}\n\n"
>   for (const line of text.split('\n')) {
>     if (line.startsWith('data: ')) {
>       const data = line.slice(6);
>       if (data === '[DONE]') return;
>       onToken(data);
>     }
>   }
> }
> ```

> 🔒 **Security — SSE response headers:**
> ```python
> return StreamingResponse(
>     stream_generator(),
>     media_type="text/event-stream",
>     headers={
>         "Cache-Control": "no-cache, no-store",
>         "X-Accel-Buffering": "no",   # Disables Nginx buffering for SSE
>         "Connection": "keep-alive",
>     }
> )
> ```

---

### T-40 · Query error handling

**What to build:** Handle all error cases in the query path: `503` if OpenAI unreachable after retries, `504` on timeout, `403` if document not owned by user, `409` if document not READY. Surface errors as SSE events so the frontend can display them inline without breaking the stream.

**Tech:** FastAPI, Python exception hierarchy

**Depends on:** T-39

---

# Phase 9 — Security Hardening

---

### T-41 · Security headers middleware + CORS

**What to build:** Add a FastAPI middleware that injects security headers on every response. Configure CORS to whitelist only the production frontend domain.

**Tech:** FastAPI middleware, Starlette CORS

**Depends on:** T-12

```python
# middleware/security.py
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Do NOT add HSTS here — Nginx handles it for the full domain
    return response

# CORS config (main.py)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.APP_URL],   # e.g. "https://pdftalk.com"
    allow_credentials=True,             # Required for cookies
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
```

> 🔒 **Security — never use `allow_origins=["*"]` with `allow_credentials=True`.**
> Browsers will reject this combination. And even without credentials, `*` allows any domain to make requests to your API. Explicitly whitelist your frontend domain.

---

### T-42 · Rate limiting (Redis sliding window)

**What to build:** Implement a Redis sliding window rate limiter as a FastAPI dependency. Apply different limits per endpoint: `/auth/register` (5/hr/IP), `/auth/login` (10/min/IP), `/documents/upload` (5/min/user), `/query/ask` (20/min/user). Return `429 Too Many Requests` with `Retry-After` header.

**Tech:** Redis, FastAPI `Depends`

**Depends on:** T-13, T-41

> 🎓 **Senior Insight:** Also apply rate limiting at the Nginx level (before requests hit Python) for basic DDoS protection. Nginx rate limiting is orders of magnitude cheaper computationally than Redis:
> ```nginx
> # In nginx.conf
> limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
> limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;
>
> location /api/ {
>     limit_req zone=api burst=50 nodelay;
>     proxy_pass http://api:8000;
> }
>
> location /api/auth/ {
>     limit_req zone=auth burst=3;
>     proxy_pass http://api:8000;
> }
> ```
> Two layers: Nginx drops volumetric attacks, Redis enforces per-user business logic limits.

---

### T-43 · Structured logging (no PII)

**What to build:** Configure `structlog` to emit JSON logs. Inject `request_id` (UUID) per request via middleware. Log: `request_id`, `user_id` (if authenticated), `endpoint`, `method`, `status_code`, `duration_ms`, `error` (on exceptions). Explicitly exclude: passwords, tokens, email addresses, document content.

**Tech:** structlog, FastAPI middleware

**Depends on:** T-12

> 🔒 **Security:** Log enough to debug production incidents, but never log PII or credentials. A log line containing a user's email or token is a PII breach waiting to happen when those logs are forwarded to a third-party logging service. Define a log schema and stick to it.

---

### T-44 · Per-user quotas + OpenAI spend alarm

**What to build:** Enforce: `MAX_DOCS_PER_USER` (checked on upload), `MAX_DAILY_TOKENS_PER_USER` (checked before embedding), `MAX_DAILY_QUERIES_PER_USER` (checked on `/query/ask`). Log daily token usage per user. Set up a simple daily cron that alerts (email/Slack webhook) if any user's token usage exceeds a threshold.

**Tech:** Redis (counters), Python cron (APScheduler or simple shell cron)

**Depends on:** T-32, T-43

---

### T-45 · Health check endpoint

**What to build:** `GET /health` — returns `200 { status, db, redis, s3, timestamp }`. Checks: PostgreSQL via `SELECT 1`, Redis via `PING`, S3 via `HeadBucket`. Each check has a 500ms timeout. Returns `503` if any dependency is unhealthy. Used by Nginx, monitoring, and deployment scripts.

**Tech:** FastAPI, asyncpg, redis-py, boto3

**Depends on:** T-05, T-13, T-14

---

# Phase 10 — Frontend

---

### T-46 · Next.js scaffold

**What to build:** Initialise Next.js 14 (App Router) in `frontend/`. Configure TypeScript, ESLint, Prettier, TailwindCSS. Install: `react-hook-form`, `zod`, `@hookform/resolvers`. Configure `next.config.js` with `NEXT_PUBLIC_API_URL`. Set up `middleware.ts` for protected route redirects.

**Tech:** Next.js 14, TypeScript, TailwindCSS

**Depends on:** T-01

> 🎓 **Senior Insight:** Use the App Router (not Pages Router). Use Server Components by default for pages that don't need interactivity. Mark components as `"use client"` only when they need state, effects, or event handlers. This reduces the JS bundle size and makes the app faster on initial load.

---

### T-47 · API client layer

**What to build:** `lib/api.ts` — typed fetch wrapper. Attaches `Authorization: Bearer {token}` from in-memory state. On `401`, calls `/auth/refresh` and retries once. Throws typed `ApiError` on non-2xx. Separate modules: `auth.api.ts`, `documents.api.ts`, `query.api.ts`.

**Tech:** TypeScript, fetch

**Depends on:** T-39, T-40, T-46

> 🔒 **Security:** Store the access token in memory (React state or Context), never in `localStorage`. `localStorage` is accessible to JavaScript, making it vulnerable to XSS. The refresh token lives in an httpOnly cookie (unreachable by JS). On page refresh, the app calls `GET /auth/me` with the cookie to silently get a new access token — this is the correct "silent refresh" pattern.

---

### T-48 · Auth pages + email verification UI

**What to build:** `/register` and `/login` pages with Zod-validated forms. On register: show "Check your email" confirmation. On login: handle unverified email (show "resend verification" link). Email verification landing page at `/verify-email?token=...`.

**Tech:** Next.js App Router, react-hook-form, zod

**Depends on:** T-18, T-20, T-22, T-46, T-47

---

### T-49 · Auth context + protected routes

**What to build:** `AuthContext` holding `{ user, accessToken, isLoading }`. `useAuth()` hook. Next.js `middleware.ts` redirecting unauthenticated requests to `/login`. Auto-refresh access token on expiry using the refresh endpoint.

**Tech:** React Context, Next.js Middleware

**Depends on:** T-21, T-47, T-48

---

### T-50 · Document upload UI

**What to build:** `/dashboard/upload` — drag-and-drop picker (PDF/TXT/MD, max 50MB), client-side validation, progress indicator, quota warning if near limit. On success: redirect to document list and begin status polling.

**Tech:** Next.js, react-dropzone

**Depends on:** T-26, T-47, T-49

---

### T-51 · Document list + status UI

**What to build:** `/dashboard/documents` — list all user documents with status badges (PENDING / PROCESSING / READY / FAILED). Poll `GET /documents/{id}/status` every 3s for non-terminal documents. Show error message for FAILED. Link READY documents to the chat page.

**Tech:** Next.js, React, setInterval polling

**Depends on:** T-27, T-47, T-49

---

### T-52 · Chat / Q&A UI (SSE streaming)

**What to build:** `/dashboard/chat` — multi-select document picker (READY documents only), question input, streaming response using `fetch` + `ReadableStream`. Progressively render tokens into a chat bubble. Display source citations at the end. Handle `[DONE]` and error events.

**Tech:** Next.js, React, `ReadableStream`, TypeScript

**Depends on:** T-39, T-47, T-49, T-51

---

### T-53 · Error boundaries + toast notifications + responsive design

**What to build:** Global React error boundary. Toast system (`react-hot-toast`) mapping `ApiError` codes to user-friendly messages. Ensure all pages are responsive (mobile, tablet, desktop). Semantic HTML5, ARIA labels, keyboard navigation, colour contrast ≥ 4.5:1.

**Tech:** React Error Boundaries, react-hot-toast, CSS

**Depends on:** T-47, T-50, T-51, T-52

---

# Phase 11 — Docker + Production

---

### T-54 · Dockerize FastAPI (multi-stage, non-root)

**What to build:** Multi-stage `Dockerfile` for `backend/`: builder stage installs deps → production stage copies only necessary files. Run as non-root user (`uid=1000`). Expose port 8000. Add `.dockerignore`. Verify image size.

**Tech:** Docker, Python 3.12-slim

**Depends on:** T-23, T-36

```dockerfile
# Multi-stage — builder installs dependencies
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Production image — small and secure
FROM python:3.12-slim AS production
RUN groupadd -r appuser && useradd -r -g appuser appuser
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .
RUN chown -R appuser:appuser /app
USER appuser          # NEVER run as root in production
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

> 🔒 **Security:** Running as non-root (`USER appuser`) means that if a remote code execution vulnerability is exploited, the attacker gets a low-privilege process, not root. Combined with Docker's namespace isolation, this significantly limits blast radius.

---

### T-55 · Dockerize RQ worker

**What to build:** `Dockerfile.worker` — same base as API but with entrypoint `rq worker ingest --with-scheduler`. Same non-root user. No exposed ports.

**Depends on:** T-31, T-54

---

### T-56 · Production Docker Compose

**What to build:** `docker-compose.yml` (production) with: all services, named volumes, resource limits, restart policies, health checks, internal network isolation, env_file pointing to `.env`.

**Tech:** Docker Compose v2

**Depends on:** T-54, T-55

```yaml
version: "3.9"

networks:
  internal:
    driver: bridge
  external:
    driver: bridge

volumes:
  postgres_data:
  redis_data:
  nginx_certs:
  app_logs:

services:
  postgres:
    image: pgvector/pgvector:pg15
    environment:
      POSTGRES_DB: pdftalk
      POSTGRES_USER: pdftalk
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks: [internal]
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1G      # Prevents OOM cascade killing all containers
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pdftalk"]
      interval: 10s
      retries: 5

  redis:
    image: redis:7-alpine
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --appendonly yes
      --maxmemory 256mb
      --maxmemory-policy noeviction
    volumes:
      - redis_data:/data
    networks: [internal]
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 384M
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s

  api:
    image: pdftalk-api:${GIT_SHA:-latest}
    env_file: .env
    networks: [internal]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 768M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      retries: 3

  worker:
    image: pdftalk-worker:${GIT_SHA:-latest}
    env_file: .env
    networks: [internal]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 1.5G    # Larger — PyMuPDF + NumPy + OpenAI SDK in memory

  nginx:
    image: nginx:1.25-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - ./frontend/out:/usr/share/nginx/html:ro
      - app_logs:/var/log/nginx
    networks: [internal, external]
    depends_on: [api]
    restart: unless-stopped
```

> 🎓 **Senior Insight — memory limits:**
> Set `memory` limits on every container. Without them, a single misbehaving container (e.g., the worker loading a large PyMuPDF document) can consume all 4GB of RAM, causing the OS to OOM-kill other containers, including Postgres. Memory limits turn a "everything down" incident into an "only the worker is slow" incident.

---

### T-57 · Production Nginx config

**What to build:** Complete `nginx/nginx.conf` with: HTTP→HTTPS redirect, SSL configuration (TLS 1.2/1.3 only), security headers (HSTS, X-Frame-Options, CSP, etc.), rate limiting zones, reverse proxy to `api:8000`, static frontend serving, SSE-specific config for `/api/query/ask`.

**Tech:** Nginx

**Depends on:** T-10, T-56

```nginx
# nginx.conf (key sections)

# Rate limiting zones (defined in http block)
limit_req_zone $binary_remote_addr zone=api_global:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=auth_endpoints:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=upload_endpoint:10m rate=5r/m;

server {
    listen 443 ssl http2;
    server_name pdftalk.com;

    # SSL
    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

    # Frontend static files
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri.html /index.html;
    }

    # API — standard endpoints
    location /api/ {
        limit_req zone=api_global burst=50 nodelay;
        proxy_pass http://api:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    # Auth endpoints — stricter rate limit
    location ~ ^/api/(auth/login|auth/register) {
        limit_req zone=auth_endpoints burst=3 nodelay;
        proxy_pass http://api:8000;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # SSE streaming — special config (NO buffering)
    location /api/query/ask {
        proxy_pass http://api:8000/query/ask;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;   # 5 min — longer than any LLM response
        proxy_send_timeout 300s;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding on;
        add_header Cache-Control "no-cache, no-store" always;
        add_header X-Accel-Buffering "no" always;
    }
}

# HTTP redirect
server {
    listen 80;
    server_name pdftalk.com www.pdftalk.com;
    return 301 https://pdftalk.com$request_uri;
}
```

> 🎓 **Senior Insight:** The SSE location block MUST have `proxy_buffering off`. Without this, Nginx buffers the entire response before forwarding it to the client, which means the user sees nothing until the LLM finishes generating — defeating the entire purpose of streaming. This is a common production gotcha.

---

### T-58 · GitHub Actions CI pipeline

**What to build:** `.github/workflows/ci.yml` — triggered on every PR. Jobs: backend tests (pytest with test Postgres + Redis services), frontend tests (Jest + TSC), linting (ruff, mypy, eslint). Cache pip and pnpm dependencies.

**Tech:** GitHub Actions, pytest, jest, ruff, mypy

**Depends on:** T-59, T-60

```yaml
# .github/workflows/ci.yml
on:
  pull_request:
    branches: [main]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg15
        env:
          POSTGRES_DB: pdftalk_test
          POSTGRES_PASSWORD: test
          POSTGRES_USER: pdftalk
        options: --health-cmd pg_isready --health-interval 10s --health-retries 5
      redis:
        image: redis:7-alpine
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: pip-${{ hashFiles('backend/pyproject.toml') }}
      - run: pip install -e ".[test]"
        working-directory: backend
      - run: ruff check .
        working-directory: backend
      - run: mypy app/
        working-directory: backend
      - run: pytest --cov=app --cov-report=xml -x
        working-directory: backend
        env:
          DATABASE_URL: postgresql+asyncpg://pdftalk:test@localhost/pdftalk_test
          REDIS_URL: redis://localhost:6379

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: pnpm install --frozen-lockfile
        working-directory: frontend
      - run: pnpm type-check && pnpm lint && pnpm test
        working-directory: frontend
```

---

### T-59 · GitHub Actions CD pipeline (SSH deploy to Lightsail)

**What to build:** `.github/workflows/deploy.yml` — triggered on push to `main` after CI passes. Build Docker images tagged with git SHA, save as tar.gz, scp to Lightsail, load + deploy. Run `alembic upgrade head` before restarting API. Run smoke test after deploy. Manual approval gate for production pushes.

**Tech:** GitHub Actions, SSH, Docker

**Depends on:** T-57, T-58

```yaml
# .github/workflows/deploy.yml
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production  # Requires manual approval in GitHub UI
    steps:
      - uses: actions/checkout@v4

      - name: Build images
        run: |
          docker build -t pdftalk-api:${{ github.sha }} ./backend
          docker build -t pdftalk-worker:${{ github.sha }} -f ./backend/Dockerfile.worker ./backend
          docker save pdftalk-api:${{ github.sha }} pdftalk-worker:${{ github.sha }} | gzip > images.tar.gz

      - name: Transfer images to Lightsail
        run: |
          echo "${{ secrets.LIGHTSAIL_KEY }}" > /tmp/key && chmod 600 /tmp/key
          scp -i /tmp/key -o StrictHostKeyChecking=no images.tar.gz \
            ubuntu@${{ secrets.LIGHTSAIL_IP }}:/tmp/

      - name: Deploy
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.LIGHTSAIL_IP }}
          username: ubuntu
          key: ${{ secrets.LIGHTSAIL_KEY }}
          script: |
            set -e
            cd /opt/pdftalk

            # Load new images
            docker load < /tmp/images.tar.gz
            export GIT_SHA=${{ github.sha }}

            # Run DB migrations BEFORE restarting API
            docker compose run --rm api alembic upgrade head

            # Rolling restart (zero-ish downtime)
            docker compose up -d --no-deps api worker
            docker compose up -d nginx  # nginx doesn't need restart usually

            # Clean up old images (keep last 3)
            docker image prune -f --filter "until=72h"
            rm /tmp/images.tar.gz

      - name: Smoke test
        run: |
          sleep 10  # Wait for containers to be healthy
          curl -f https://${{ secrets.APP_DOMAIN }}/health || exit 1
```

> 🎓 **Senior Insight:** Tag images with the git SHA, not `:latest`. `:latest` is a lie — it doesn't tell you what's running or how to roll back. With SHA tags, your rollback is: find the previous deploy's SHA, export that image from Docker (or rebuild), and re-deploy. Your deployment history is your audit trail.

---

# Phase 12 — Testing & Launch

---

### T-60 · Backend unit tests

**What to build:** pytest unit tests for all service modules: `file_validation`, `chunking` (known inputs → expected chunk counts), `embedding` (mocked OpenAI), `retrieval` (mocked DB), `prompt` (token count stays within budget), `password` hashing. Target: ≥80% coverage on the service layer.

**Tech:** pytest, unittest.mock, pytest-asyncio

**Depends on:** T-25, T-30, T-33, T-34, T-37

---

### T-61 · Backend integration tests

**What to build:** Full auth lifecycle test (register → verify email → login → refresh → logout). Full ingestion test (upload → process → READY status). Full query test (embed → retrieve → stream). Test failure paths: wrong credentials, unverified email, document not found, quota exceeded.

**Tech:** pytest, httpx (AsyncClient), fakeredis, moto[s3]

**Depends on:** T-23, T-36, T-40

---

### T-62 · Backup automation

**What to build:** Automated daily PostgreSQL backup via `pg_dump`, compressed and uploaded to S3. Lightsail weekly snapshots enabled. Backup verification script (attempt a restore to a temp container). Document the restore procedure.

**Tech:** Docker, pg_dump, boto3, cron

**Depends on:** T-06, T-56

```bash
#!/bin/bash
# /opt/pdftalk/scripts/backup.sh
set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="/opt/backups/pdftalk_${TIMESTAMP}.sql.gz"

# Dump and compress
docker compose -f /opt/pdftalk/docker-compose.yml exec -T postgres \
  pg_dump -U pdftalk pdftalk | gzip > "$BACKUP_FILE"

# Upload to S3
aws s3 cp "$BACKUP_FILE" "s3://pdftalk-backups/${TIMESTAMP}.sql.gz" \
  --sse AES256

# Keep last 7 local backups
find /opt/backups -name "pdftalk_*.sql.gz" -mtime +7 -delete

echo "Backup completed: $BACKUP_FILE"
```

```bash
# Add to cron: /etc/cron.d/pdftalk-backup
0 2 * * * ubuntu /opt/pdftalk/scripts/backup.sh >> /var/log/pdftalk-backup.log 2>&1
```

> 🎓 **Senior Insight:** A backup you've never restored is not a backup — it's a hypothesis. Schedule a monthly restore test: spin up a temp Postgres container, restore from backup, run `SELECT COUNT(*) FROM users`, confirm the number matches production. Document the restore procedure in your README so that when you need it at 2am, you're not figuring it out under pressure.

---

### T-63 · Production smoke test + launch checklist

**What to build:** A scripted end-to-end smoke test: register → verify email → login → upload a known small PDF → wait for READY (poll with timeout) → query a known question → assert answer is non-empty → logout. Run automatically as the final CD step.

**Tech:** pytest / bash, httpx, production endpoints

**Depends on:** T-59, T-61

> 🔒 **Final Security Checklist — verify before launch:**
>
> **Server hardening:**
> - [ ] SSH: `PasswordAuthentication no`, `PermitRootLogin no`
> - [ ] UFW: Only ports 22, 80, 443 open
> - [ ] fail2ban running and protecting SSH
> - [ ] Unattended security upgrades enabled
>
> **HTTPS/TLS:**
> - [ ] All HTTP redirected to HTTPS (301)
> - [ ] TLS 1.2+ only (no 1.0 or 1.1)
> - [ ] HSTS header present with long max-age
> - [ ] SSL Labs test: A or A+ rating
>
> **Application:**
> - [ ] CORS: Only your frontend domain whitelisted
> - [ ] All security headers present (X-Frame-Options, CSP, etc.)
> - [ ] Rate limiting active on auth + upload + query endpoints
> - [ ] Email verification working (test with a real email)
> - [ ] Account lockout after failed logins (test manually)
> - [ ] httpOnly + Secure + SameSite cookies (inspect in browser DevTools)
> - [ ] No sensitive data in API responses (no password_hash, no tokens)
> - [ ] No secrets in git history (`git log --all -- .env` should be empty)
>
> **Infrastructure:**
> - [ ] Postgres: not exposed to host (`docker ps` shows no 5432 port binding)
> - [ ] Redis: not exposed to host, requires AUTH
> - [ ] S3: Block all public access enabled, versioning on
> - [ ] IAM user: only S3 permissions, no console access
> - [ ] `.env` file: `chmod 600`, `ls -la` confirms `-rw-------`
>
> **Backup:**
> - [ ] Daily pg_dump cron running (`crontab -l` to verify)
> - [ ] Lightsail weekly snapshots enabled
> - [ ] Restore procedure tested and documented

---

## Task Dependency Summary

| Phase | Tasks | Blocks Until Complete |
|---|---|---|
| 1 — Foundation | T-01 → T-03 | Everything |
| 2 — Database | T-04 → T-05 | Auth, ingestion, embeddings |
| 3 — Infrastructure | T-06 → T-11 | Deployment, CI/CD |
| 4 — Backend Scaffold | T-12 → T-14 | All application code |
| 5 — Authentication | T-15 → T-23 | Upload, query, frontend auth |
| 6 — Ingestion | T-24 → T-31 | Embeddings, query |
| 7 — Embeddings + pgvector | T-32 → T-36 | Query, streaming |
| 8 — LLM + Streaming | T-37 → T-40 | Frontend chat UI |
| 9 — Security Hardening | T-41 → T-45 | Production deployment |
| 10 — Frontend | T-46 → T-53 | CI/CD, launch |
| 11 — Docker + CI/CD | T-54 → T-59 | Launch |
| 12 — Testing + Launch | T-60 → T-63 | Ship |
| 13 — Observability + Admin | T-69 → T-71 | Production visibility |

---

## Monthly Cost Estimate

| Service | Configuration | Cost |
|---|---|---|
| Lightsail instance | $20/month plan (2 vCPU, 4GB, 80GB, 4TB transfer) | $20 |
| Lightsail static IP | Attached (free while attached) | $0 |
| Lightsail snapshots | Weekly, ~30GB | ~$1.50 |
| S3 (documents) | 20GB + requests | ~$0.50 |
| S3 (backups) | 7 daily backups, ~1GB compressed | ~$0.02 |
| Route 53 | 1 hosted zone + records | $0.50 |
| OpenAI | Usage-based (scales with users) | Variable |
| Email (Resend) | Up to 3,000 emails/month | $0 |
| **Total fixed** | | **~$22.50/month** |

This is approximately **10× cheaper** than the original ECS+Fargate+ALB+ElastiCache+RDS stack (~$266–330/month).

---

## When to Migrate Away from This Stack

Migrate to managed services when you hit these specific triggers — not before:

| Trigger | Migration |
|---|---|
| Lightsail CPU consistently > 70% under normal load | Upgrade Lightsail plan ($40/month = 4 vCPU, 8GB) |
| > 100 paying users with defined uptime SLA | Add RDS (remove Postgres Docker) + ElastiCache (remove Redis Docker) |
| > 1,000 documents/day processed | Add second Lightsail worker instance |
| pgvector query P95 > 200ms under real load | Migrate to Pinecone (swap retrieval module only) |
| Lightsail instance throughput ceiling hit | Migrate to ECS + Fargate (use this architecture as the target) |

---

> **Review cadence:** Before each phase begins
> **Next review trigger:** Before Phase 11 (Docker + CI/CD)

---

# Phase 13 — Observability, Alerting & Admin Dashboard

> **Why this phase exists:** Without observability you discover problems from users. With observability you discover them before users do. This phase adds three things: (1) a Prometheus metrics endpoint on the API + worker that records every meaningful event as it happens, (2) Grafana dashboards that visualise those metrics so degradation is visible before it becomes an outage, and (3) a secured admin API + frontend dashboard for business metrics (sign-ups, email volume, token spend by user) with Resend + Slack alerts for threshold breaches.

> **ADR-005: Prometheus + Grafana in Docker, not a managed service**
> Grafana Cloud is free up to 10k series, but adds an external dependency and ships your internal metrics off-box. At MVP scale (one instance, one operator), running both in the same Docker Compose file is correct. Total memory overhead: ~150MB. When you exceed the Lightsail instance limits, moving Grafana to a managed service is a two-line config change.

> **ADR-006: prometheus-fastapi-instrumentator for automatic HTTP metrics**
> Writing `Counter`, `Histogram`, and `Gauge` calls by hand for every endpoint is tedious and error-prone. `prometheus-fastapi-instrumentator` auto-instruments every route for latency, request count, and status code distribution in five lines of code. Custom business metrics (queue depth, OpenAI errors, document states) are added on top with explicit `Counter`/`Gauge` objects registered in a single `utils/metrics.py` module.

> **ADR-007: Multiprocess mode for worker metrics**
> Prometheus's default `CollectorRegistry` is per-process. The worker is a separate process from the API. To expose worker metrics through the same `/metrics` endpoint, use `prometheus_client`'s multiprocess mode: set `PROMETHEUS_MULTIPROC_DIR` to a shared `tmpfs` volume. Both the API process and the worker process write `.db` files to that directory; the API's `/metrics` handler aggregates and exposes them all. Zero extra ports, zero extra scrape targets.

---

### T-69 · Prometheus metrics instrumentation

**What to build:** Add `prometheus_client` and `prometheus-fastapi-instrumentator` to `pyproject.toml`. Create `app/utils/metrics.py` defining all custom metrics as module-level singletons. Instrument the FastAPI app and the RQ worker. Expose `/metrics` on the API. Wire multiprocess mode so worker metrics flow through the same endpoint.

**Tech:** `prometheus-fastapi-instrumentator`, `prometheus_client`, Docker `tmpfs` volume

**Depends on:** T-12, T-28, T-31, T-32, T-56

**New env vars:**
```
PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus_multiproc   # shared tmpfs in Docker
```

**`app/utils/metrics.py` — define all metrics here and nowhere else:**
```python
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry
from prometheus_client import multiprocess

# ── Ingestion pipeline ──────────────────────────────────────────────────────
documents_processed_total = Counter(
    "pdftalk_documents_processed_total",
    "Documents that completed ingestion successfully",
    ["user_id"],          # label: per-user breakdowns in Grafana
)
documents_failed_total = Counter(
    "pdftalk_documents_failed_total",
    "Documents that exhausted all retries and entered FAILED state",
    ["reason"],           # label: "extraction_error" | "embedding_error" | "quota_exceeded" | "unknown"
)
processing_duration_seconds = Histogram(
    "pdftalk_processing_duration_seconds",
    "Wall-clock time for the full ingest pipeline (extract→chunk→embed→store)",
    buckets=[5, 10, 30, 60, 120, 300, 600],
)
queue_length = Gauge(
    "pdftalk_queue_length",
    "Current number of jobs waiting in the RQ ingest queue",
    # Updated by a background thread in the worker every 15s
)
dead_letter_queue_length = Gauge(
    "pdftalk_dead_letter_queue_length",
    "Jobs in the RQ FailedJobRegistry (exhausted all retries)",
)

# ── External service errors ─────────────────────────────────────────────────
openai_errors_total = Counter(
    "pdftalk_openai_errors_total",
    "Errors returned by the OpenAI API",
    ["error_type"],       # "rate_limit" | "timeout" | "server_error" | "quota_exceeded"
)
s3_errors_total = Counter(
    "pdftalk_s3_errors_total",
    "Errors returned by AWS S3",
    ["operation"],        # "upload" | "download" | "delete"
)

# ── Auth & user activity ────────────────────────────────────────────────────
user_registrations_total = Counter(
    "pdftalk_user_registrations_total",
    "Total user registrations (includes unverified)",
)
user_logins_total = Counter(
    "pdftalk_user_logins_total",
    "Successful logins",
)
login_failures_total = Counter(
    "pdftalk_login_failures_total",
    "Failed login attempts (wrong password, locked, unverified)",
    ["reason"],           # "wrong_password" | "locked" | "unverified" | "not_found"
)
emails_sent_total = Counter(
    "pdftalk_emails_sent_total",
    "Emails dispatched via Resend",
    ["type"],             # "verification" | "password_reset"
)

# ── Token quota ─────────────────────────────────────────────────────────────
openai_tokens_used_total = Counter(
    "pdftalk_openai_tokens_used_total",
    "Cumulative OpenAI tokens consumed (embedding + completion)",
    ["kind"],             # "embedding" | "completion"
)
daily_quota_breaches_total = Counter(
    "pdftalk_daily_quota_breaches_total",
    "Times a user hit their daily token quota ceiling",
)

# ── Query / streaming ───────────────────────────────────────────────────────
queries_total = Counter(
    "pdftalk_queries_total",
    "Total RAG queries submitted",
)
stream_errors_total = Counter(
    "pdftalk_stream_errors_total",
    "SSE stream errors (timeout, OpenAI error mid-stream, etc.)",
    ["error_code"],
)
```

**Instrument FastAPI in `main.py`:**
```python
from prometheus_fastapi_instrumentator import Instrumentator

# After app creation, before router registration:
Instrumentator(
    should_group_status_codes=True,      # 2xx, 4xx, 5xx — not 201/204/422 separately
    should_ignore_untemplated=True,      # drop /metrics itself, health spam, etc.
    excluded_handlers=["/health", "/metrics"],
).instrument(app).expose(app, endpoint="/metrics")
```

**Worker — queue depth poller (run in a daemon thread inside `workers/worker.py`):**
```python
import threading
import time
from rq import Queue
from rq.registry import FailedJobRegistry
from app.utils.metrics import queue_length, dead_letter_queue_length

def _poll_queue_metrics(redis_conn, interval: int = 15) -> None:
    """Background daemon thread — updates queue depth Gauges every `interval` seconds."""
    ingest_q = Queue("ingest", connection=redis_conn)
    failed_registry = FailedJobRegistry("ingest", connection=redis_conn)
    while True:
        try:
            queue_length.set(ingest_q.count)
            # FailedJobRegistry.count is the RQ aggregated count across all
            # jobs in the dead-letter registry — no manual iteration needed.
            dead_letter_queue_length.set(failed_registry.count)
        except Exception:
            pass   # Never crash the worker over a metrics update
        time.sleep(interval)

# In worker entrypoint, before rq.Worker(...).work():
t = threading.Thread(target=_poll_queue_metrics, args=(redis_conn,), daemon=True)
t.start()
```

**Multiprocess mode — `docker-compose.yml` additions:**
```yaml
services:
  api:
    environment:
      PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus_multiproc
    volumes:
      - prometheus_multiproc:/tmp/prometheus_multiproc   # tmpfs shared with worker

  worker:
    environment:
      PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus_multiproc
    volumes:
      - prometheus_multiproc:/tmp/prometheus_multiproc

volumes:
  prometheus_multiproc:
    driver_opts:
      type: tmpfs
      device: tmpfs     # lives in RAM, auto-wiped on restart — correct for ephemeral counters
```

> 🎓 **Senior Insight — label cardinality:** Never use `user_id` as a label on high-frequency metrics like `queries_total` or `stream_errors_total`. Prometheus stores one time series per unique label combination; 10,000 users × one metric = 10,000 series, which will OOM a small Prometheus instance. Use `user_id` only on low-frequency metrics like `documents_processed_total` where the per-user breakdown is operationally important. For aggregate token spend, use the existing Redis counters and expose them as a Gauge scraped periodically.

> 🎓 **Senior Insight — `FailedJobRegistry.count` vs manual scan:** RQ's `FailedJobRegistry` maintains a sorted set in Redis keyed by job ID and score = enqueue timestamp. `registry.count` is a single `ZCARD` call — O(1), safe to call on every poll cycle. Never iterate `get_job_ids()` on the dead-letter queue in a hot path; at scale it returns thousands of IDs and serialises all of them.

---

### T-70 · Prometheus + Grafana containers + dashboards

**What to build:** Add `prometheus` and `grafana` services to `docker-compose.yml`. Write `monitoring/prometheus.yml` scrape config targeting `api:8000/metrics`. Write a provisioned Grafana datasource config and three pre-built dashboard JSON files (ingestion pipeline, auth/users, system health) so dashboards exist on first boot — no manual clicking in the UI. Proxy Grafana through Nginx at `/grafana/` so it is accessible over HTTPS without exposing a new port.

**Tech:** `prom/prometheus:v2.51`, `grafana/grafana:10.4-alpine`, Nginx sub-path proxy

**Depends on:** T-57, T-69

**New env vars:**
```
GF_SECURITY_ADMIN_PASSWORD=<strong-random>   # Grafana admin password
GF_SERVER_ROOT_URL=https://pdftalk.com/grafana
GF_SERVER_SERVE_FROM_SUB_PATH=true
```

**`monitoring/prometheus.yml`:**
```yaml
global:
  scrape_interval: 15s      # How often to collect metrics
  evaluation_interval: 15s  # How often to evaluate alert rules

scrape_configs:
  - job_name: pdftalk_api
    static_configs:
      - targets: ["api:8000"]    # Internal Docker hostname — no auth needed on /metrics
    metrics_path: /metrics

  # Optional: scrape Prometheus's own health metrics
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]
```

**`monitoring/grafana/provisioning/datasources/prometheus.yml`:**
```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

**`monitoring/grafana/provisioning/dashboards/dashboards.yml`:**
```yaml
apiVersion: 1
providers:
  - name: PDFTalk
    folder: PDFTalk
    type: file
    options:
      path: /var/lib/grafana/dashboards
```

**Three dashboard JSON files to provision** (place in `monitoring/grafana/dashboards/`):

*Dashboard 1 — `ingestion_pipeline.json`:* Panels:
- Documents processed/min (rate of `pdftalk_documents_processed_total`)
- Documents failed/min (rate of `pdftalk_documents_failed_total` by `reason` label)
- Failure rate % (`failed / (failed + processed)` — alert when >10%)
- Processing duration P50/P95/P99 (histogram quantiles of `pdftalk_processing_duration_seconds`)
- Queue depth over time (`pdftalk_queue_length` — alert when >50)
- Dead-letter queue depth (`pdftalk_dead_letter_queue_length` — alert when >0)
- OpenAI error rate by type (`pdftalk_openai_errors_total` by `error_type`)
- S3 error rate by operation (`pdftalk_s3_errors_total` by `operation`)

*Dashboard 2 — `auth_users.json`:* Panels:
- New registrations/hour (rate of `pdftalk_user_registrations_total`)
- Successful logins/min (rate of `pdftalk_user_logins_total`)
- Login failure rate by reason (rate of `pdftalk_login_failures_total` by `reason`)
- Emails sent by type (rate of `pdftalk_emails_sent_total` by `type`)
- Token consumption rate — embedding vs completion (rate of `pdftalk_openai_tokens_used_total` by `kind`)
- Daily quota breach count (rate of `pdftalk_daily_quota_breaches_total`)
- Total queries/min (rate of `pdftalk_queries_total`)
- Stream errors by code (rate of `pdftalk_stream_errors_total` by `error_code`)

*Dashboard 3 — `system_health.json`:* Panels:
- HTTP request rate by endpoint (from `http_requests_total` auto-instrumented by `prometheus-fastapi-instrumentator`)
- HTTP error rate (5xx/total)
- HTTP latency P95 by route
- Prometheus scrape health (is the target up?)

**`docker-compose.yml` — add monitoring services:**
```yaml
  prometheus:
    image: prom/prometheus:v2.51.0
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=30d"   # Keep 30 days of metrics locally
      - "--web.enable-lifecycle"               # Allows POST /-/reload to hot-reload config
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    networks: [internal]
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M

  grafana:
    image: grafana/grafana:10.4-alpine
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GF_SECURITY_ADMIN_PASSWORD}
      GF_SERVER_ROOT_URL: ${GF_SERVER_ROOT_URL}
      GF_SERVER_SERVE_FROM_SUB_PATH: "true"
      GF_AUTH_ANONYMOUS_ENABLED: "false"     # Never allow anonymous access
      GF_USERS_ALLOW_SIGN_UP: "false"        # Only the admin account exists
      GF_SECURITY_DISABLE_GRAVATAR: "true"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards:ro
    networks: [internal]
    depends_on: [prometheus]
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 256M

volumes:
  prometheus_data:    # Persists metric history across restarts
  grafana_data:       # Persists Grafana users, custom dashboards, annotations
```

**Nginx — add Grafana proxy block** (add before the `/api/` block in `nginx.conf`):
```nginx
# Grafana — accessible at https://pdftalk.com/grafana/
# Protected by Grafana's own login — do NOT add public access
location /grafana/ {
    proxy_pass http://grafana:3000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Rewrite sub-path headers so Grafana knows it's behind a prefix
    proxy_set_header X-Forwarded-Prefix /grafana;

    # WebSocket support — Grafana uses WS for live dashboard updates
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

# Block direct access to Prometheus — internal only, never expose to internet
# (prometheus has no auth — protect it via network isolation only)
location /prometheus/ {
    deny all;
    return 404;
}
```

> 🔒 **Security:** Prometheus has no built-in authentication. It is on the `internal` Docker network only and must never be reachable from outside the instance. Grafana is exposed through Nginx but requires a login. Set a strong `GF_SECURITY_ADMIN_PASSWORD` (use `openssl rand -base64 24`). The admin credentials go in `.env` — never committed.

> 🎓 **Senior Insight — dashboard-as-code:** Provisioned dashboards (JSON files in the repo) are the correct approach for a solo-operated service. If you build dashboards by clicking in the Grafana UI and the `grafana_data` volume is lost, those dashboards are gone forever. With provisioned dashboards, a `docker compose up` restores everything. The trade-off: you can't save edits from the UI back to JSON automatically — use Grafana's "Export → Save to file" when you iterate on a dashboard, and commit the updated JSON.

---

### T-71 · Alerting service (Prometheus rules + Resend email + Slack webhook)

**What to build:** Write Prometheus alerting rules that fire on the conditions below. Create `app/services/alerting.py` — a thin service that receives fired alerts via a Prometheus Alertmanager webhook and dispatches notifications to both Resend (email) and Slack (webhook). Add `alertmanager` to Docker Compose. Protect the admin dashboard API endpoints with `ADMIN_TOKEN`. Build the `/admin/*` API routes and the Next.js `/admin` page.

**Tech:** Prometheus Alertmanager, `prom/alertmanager:v0.27`, Resend SDK, Slack Incoming Webhooks, FastAPI, Next.js

**Depends on:** T-17, T-56, T-70

**New env vars:**
```
ADMIN_TOKEN=<openssl rand -hex 32>      # Bearer token for /admin/* API routes
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
ALERT_EMAIL_TO=you@yourdomain.com       # Where alert emails go
```

---

#### Part A — Prometheus alert rules

**`monitoring/prometheus_rules.yml`:**
```yaml
groups:
  - name: pdftalk_ingestion
    rules:
      - alert: HighIngestionFailureRate
        expr: |
          rate(pdftalk_documents_failed_total[5m])
          /
          (rate(pdftalk_documents_processed_total[5m]) + rate(pdftalk_documents_failed_total[5m]) + 0.001)
          > 0.10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Ingestion failure rate above 10%"
          description: "{{ $value | humanizePercentage }} of documents are failing in the last 5 minutes."

      - alert: DeadLetterQueueGrowing
        expr: pdftalk_dead_letter_queue_length > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Failed jobs accumulating in dead-letter queue"
          description: "{{ $value }} jobs have exhausted all retries. Check job_logs table."

      - alert: IngestQueueBacklog
        expr: pdftalk_queue_length > 50
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Ingest queue backlog: {{ $value }} jobs waiting"
          description: "Queue has been above 50 jobs for 10+ minutes. Worker may be down or overwhelmed."

      - alert: WorkerAppearsDead
        expr: pdftalk_queue_length > 10 and rate(pdftalk_documents_processed_total[10m]) == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Worker is not processing jobs"
          description: "Queue is growing but no documents completed in the last 10 minutes."

      - alert: SlowIngestion
        expr: histogram_quantile(0.95, rate(pdftalk_processing_duration_seconds_bucket[10m])) > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "P95 ingestion latency above 5 minutes"
          description: "95th percentile processing time: {{ $value | humanizeDuration }}."

  - name: pdftalk_external_services
    rules:
      - alert: OpenAIErrorSpike
        expr: rate(pdftalk_openai_errors_total[5m]) > 0.5
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "OpenAI API errors: {{ $value | humanize }} errors/sec"
          description: "Error type breakdown available in Grafana ingestion dashboard."

      - alert: S3ErrorSpike
        expr: rate(pdftalk_s3_errors_total[5m]) > 0.2
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "S3 errors: {{ $value | humanize }} errors/sec on {{ $labels.operation }}"

  - name: pdftalk_quota
    rules:
      - alert: HighDailyQuotaBreaches
        expr: increase(pdftalk_daily_quota_breaches_total[1h]) > 5
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "5+ users hit daily token quota in the last hour"
          description: "Consider raising MAX_DAILY_TOKENS_PER_USER or adding a paid tier."

  - name: pdftalk_api
    rules:
      - alert: High5xxRate
        expr: |
          rate(http_requests_total{status=~"5.."}[5m])
          /
          rate(http_requests_total[5m])
          > 0.05
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "API 5xx rate above 5%"
          description: "{{ $value | humanizePercentage }} of requests returning 5xx."

      - alert: APIDown
        expr: up{job="pdftalk_api"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "API container is not reachable by Prometheus"
```

Add to `prometheus.yml`:
```yaml
rule_files:
  - /etc/prometheus/rules.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

---

#### Part B — Alertmanager + webhook receiver

**`monitoring/alertmanager.yml`:**
```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ["alertname", "severity"]
  group_wait: 30s          # Wait 30s to batch alerts that fire together
  group_interval: 5m       # Re-notify every 5m while alert is active
  repeat_interval: 4h      # Don't spam — re-notify max every 4h for the same alert
  receiver: pdftalk_alerts

  routes:
    - match:
        severity: critical
      receiver: pdftalk_alerts
      repeat_interval: 1h  # Critical alerts re-notify every hour until resolved

receivers:
  - name: pdftalk_alerts
    webhook_configs:
      - url: http://api:8000/internal/alerts/webhook
        send_resolved: true   # Also notify when the alert clears
        http_config:
          bearer_token: ${ADMIN_TOKEN}   # Alertmanager calls our API with admin token
```

**`docker-compose.yml` — add alertmanager:**
```yaml
  alertmanager:
    image: prom/alertmanager:v0.27.0
    command:
      - "--config.file=/etc/alertmanager/alertmanager.yml"
      - "--storage.path=/alertmanager"
    volumes:
      - ./monitoring/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
      - alertmanager_data:/alertmanager
    environment:
      ADMIN_TOKEN: ${ADMIN_TOKEN}   # Injected into alertmanager.yml via env substitution
    networks: [internal]
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 64M

volumes:
  alertmanager_data:
```

---

#### Part C — Alert dispatch service + webhook receiver

**`app/services/alerting.py`:**
```python
"""
Receives fired Prometheus alerts from Alertmanager and dispatches
notifications to Resend (email) and Slack.
"""
import logging
from typing import Any
import httpx
import resend
from app.core.config import settings

log = logging.getLogger(__name__)


async def dispatch_alert(payload: dict[str, Any]) -> None:
    """Called from the /internal/alerts/webhook endpoint for each Alertmanager POST."""
    alerts = payload.get("alerts", [])
    if not alerts:
        return

    for alert in alerts:
        name        = alert["labels"].get("alertname", "UnknownAlert")
        severity    = alert["labels"].get("severity", "unknown")
        summary     = alert["annotations"].get("summary", name)
        description = alert["annotations"].get("description", "")
        status      = alert["status"]           # "firing" | "resolved"
        emoji       = "🔴" if status == "firing" else "✅"

        subject = f"{emoji} [{severity.upper()}] {summary}"
        body    = f"{description}\n\nStatus: {status}\nAlert: {name}"

        # ── Resend (email) ────────────────────────────────────────────────
        if settings.ALERT_EMAIL_TO and settings.RESEND_API_KEY:
            try:
                resend.api_key = settings.RESEND_API_KEY
                resend.Emails.send({
                    "from":    f"PDFTalk Alerts <alerts@{settings.EMAIL_FROM_DOMAIN}>",
                    "to":      [settings.ALERT_EMAIL_TO],
                    "subject": subject,
                    "text":    body,
                })
            except Exception as e:
                log.warning("alert_email_failed", error=str(e), alert=name)

        # ── Slack (webhook) ───────────────────────────────────────────────
        if settings.SLACK_WEBHOOK_URL:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        settings.SLACK_WEBHOOK_URL,
                        json={
                            "text": f"{emoji} *{subject}*\n{description}",
                            "username": "PDFTalk Monitor",
                            "icon_emoji": ":bell:",
                        },
                    )
            except Exception as e:
                log.warning("alert_slack_failed", error=str(e), alert=name)
```

**`app/routers/internal.py` — webhook receiver + admin API routes:**
```python
"""
Internal-only routes:
  POST /internal/alerts/webhook  — Alertmanager fires here
  GET  /admin/stats              — Executive dashboard data
All protected by ADMIN_TOKEN bearer auth.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.core.config import settings
from app.db.session import get_db
from app.models.auth import User, EmailVerification
from app.models.documents import Document
from app.models.job_logs import JobLog
from app.services.alerting import dispatch_alert
from app.utils.redis_client import get_redis

router = APIRouter(prefix="/internal", tags=["internal"])
bearer = HTTPBearer()


def _require_admin(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> None:
    if creds.credentials != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.post("/alerts/webhook", dependencies=[Depends(_require_admin)], status_code=204)
async def alertmanager_webhook(payload: dict) -> None:
    """Alertmanager calls this. Fire and forget — don't block on dispatch."""
    import asyncio
    asyncio.create_task(dispatch_alert(payload))


@router.get("/admin/stats", dependencies=[Depends(_require_admin)])
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> dict:
    """
    Aggregated business metrics for the executive dashboard.
    All queries are read-only and use indexed columns — safe to call on production DB.
    """
    from datetime import date, timedelta
    today = date.today()

    # ── User signups (last 30 days, daily buckets) ────────────────────────
    signups_row = await db.execute(
        text("""
            SELECT DATE(created_at) AS day, COUNT(*) AS count
            FROM users
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY day
            ORDER BY day
        """)
    )
    signups_by_day = [{"day": str(r.day), "count": r.count} for r in signups_row]

    # ── Aggregate counts ──────────────────────────────────────────────────
    total_users        = (await db.execute(select(func.count()).select_from(User))).scalar()
    verified_users     = (await db.execute(
        select(func.count()).select_from(User).where(User.is_verified)
    )).scalar()
    total_documents    = (await db.execute(select(func.count()).select_from(Document))).scalar()
    documents_by_status = (await db.execute(
        select(Document.status, func.count()).group_by(Document.status)
    )).all()
    failed_jobs_7d     = (await db.execute(
        text("SELECT COUNT(*) FROM job_logs WHERE created_at >= NOW() - INTERVAL '7 days'")
    )).scalar()

    # ── Emails sent (count rows in email_verifications created, all time) ─
    # email_verifications rows are deleted on use, so count job_logs proxy or
    # use the Prometheus counter. Here we count from the Prometheus TSDB via
    # a separate scrape — but for the DB-only path, we track a simple counter
    # table. For MVP, return the total from the emails_sent_total Prometheus
    # metric via the admin API; the frontend fetches Grafana for graphs.
    emails_verification = (await db.execute(
        text("SELECT COUNT(*) FROM email_verifications")
    )).scalar()

    # ── Token utilization (today, from Redis) ─────────────────────────────
    # Scan all quota keys for today. Acceptable at MVP user counts (<1000).
    today_str = today.strftime("%Y%m%d")
    token_data: list[dict] = []
    async for key in redis.scan_iter(f"quota:tokens:*:{today_str}"):
        val = await redis.get(key)
        if val:
            user_id = key.decode().split(":")[2]
            token_data.append({"user_id": user_id, "tokens_today": int(val)})
    token_data.sort(key=lambda x: x["tokens_today"], reverse=True)

    # ── Dead-letter queue count (RQ FailedJobRegistry) ───────────────────
    from rq import Queue
    from rq.registry import FailedJobRegistry
    from app.utils.redis_client import get_sync_redis   # sync client for RQ
    sync_redis = get_sync_redis()
    failed_registry = FailedJobRegistry("ingest", connection=sync_redis)
    dead_letter_count = failed_registry.count   # O(1) ZCARD — safe

    return {
        "users": {
            "total": total_users,
            "verified": verified_users,
            "unverified": total_users - verified_users,
            "signups_by_day": signups_by_day,
        },
        "documents": {
            "total": total_documents,
            "by_status": {row[0]: row[1] for row in documents_by_status},
        },
        "emails": {
            "verification_tokens_active": emails_verification,
            # Resend/Prometheus totals available via Grafana dashboard
        },
        "tokens": {
            "top_users_today": token_data[:20],    # Top 20 consumers today
        },
        "queue": {
            "dead_letter_count": dead_letter_count,
            "failed_jobs_7d": failed_jobs_7d,
        },
    }
```

Register the router in `main.py`:
```python
from app.routers.internal import router as internal_router
app.include_router(internal_router)
```

---

#### Part D — Next.js admin dashboard page

**`frontend/app/admin/page.tsx`** — a `"use client"` page protected by checking `ADMIN_TOKEN` in a cookie (set manually by the operator, never by the app — operator pastes it into browser storage once):

```typescript
// app/admin/page.tsx
"use client";
import { useEffect, useState } from "react";

// The operator sets this token in the browser manually:
// localStorage.setItem("admin_token", "<ADMIN_TOKEN value>")
// This is intentional — the admin page is for the operator only,
// not for regular users, so a full auth flow is unnecessary.
function getAdminToken(): string {
  return typeof window !== "undefined"
    ? localStorage.getItem("admin_token") ?? ""
    : "";
}

type Stats = {
  users: {
    total: number;
    verified: number;
    unverified: number;
    signups_by_day: { day: string; count: number }[];
  };
  documents: { total: number; by_status: Record<string, number> };
  emails: { verification_tokens_active: number };
  tokens: { top_users_today: { user_id: string; tokens_today: number }[] };
  queue: { dead_letter_count: number; failed_jobs_7d: number };
};

export default function AdminDashboard() {
  const [stats, setStats]     = useState<Stats | null>(null);
  const [error, setError]     = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL}/internal/admin/stats`, {
      headers: { Authorization: `Bearer ${getAdminToken()}` },
    })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} — check ADMIN_TOKEN in localStorage`);
        return r.json();
      })
      .then(setStats)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="p-8 text-gray-500">Loading…</p>;
  if (error)   return <p className="p-8 text-red-600 font-mono">{error}</p>;
  if (!stats)  return null;

  const { users, documents, tokens, queue } = stats;
  const maxQuota = Number(process.env.NEXT_PUBLIC_MAX_DAILY_TOKENS ?? 100000);

  return (
    <main className="p-8 max-w-5xl mx-auto space-y-8">
      <h1 className="text-2xl font-bold">PDFTalk Admin</h1>

      {/* ── Users ───────────────────────────────────────────────────── */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Users</h2>
        <div className="grid grid-cols-3 gap-4">
          <Stat label="Total"      value={users.total} />
          <Stat label="Verified"   value={users.verified} />
          <Stat label="Unverified" value={users.unverified} />
        </div>
        <p className="mt-4 text-sm text-gray-500">
          Sign-ups last 30 days:{" "}
          {users.signups_by_day.map((d) => `${d.day}: ${d.count}`).join(" · ")}
        </p>
      </section>

      {/* ── Documents ───────────────────────────────────────────────── */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Documents</h2>
        <div className="grid grid-cols-4 gap-4">
          {Object.entries(documents.by_status).map(([status, count]) => (
            <Stat key={status} label={status} value={count as number} />
          ))}
        </div>
      </section>

      {/* ── Queue health ────────────────────────────────────────────── */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Queue Health</h2>
        <div className="grid grid-cols-2 gap-4">
          <Stat
            label="Dead-letter jobs"
            value={queue.dead_letter_count}
            alert={queue.dead_letter_count > 0}
          />
          <Stat
            label="Failed jobs (7d)"
            value={queue.failed_jobs_7d}
            alert={queue.failed_jobs_7d > 10}
          />
        </div>
      </section>

      {/* ── Token utilization ───────────────────────────────────────── */}
      <section>
        <h2 className="text-lg font-semibold mb-3">
          Token Utilization Today (Top 20 Users)
        </h2>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2 pr-4">User ID</th>
              <th className="py-2 pr-4">Tokens Used</th>
              <th className="py-2">% of Daily Quota</th>
            </tr>
          </thead>
          <tbody>
            {tokens.top_users_today.map((u) => {
              const pct = ((u.tokens_today / maxQuota) * 100).toFixed(1);
              return (
                <tr key={u.user_id} className="border-b hover:bg-gray-50">
                  <td className="py-1 pr-4 font-mono text-xs">{u.user_id}</td>
                  <td className="py-1 pr-4">{u.tokens_today.toLocaleString()}</td>
                  <td className="py-1">
                    <div className="flex items-center gap-2">
                      <div className="w-32 bg-gray-200 rounded-full h-1.5">
                        <div
                          className={`h-1.5 rounded-full ${
                            Number(pct) > 80 ? "bg-red-500" : "bg-blue-500"
                          }`}
                          style={{ width: `${Math.min(Number(pct), 100)}%` }}
                        />
                      </div>
                      <span className={Number(pct) > 80 ? "text-red-600 font-medium" : ""}>
                        {pct}%
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {/* ── Grafana link ────────────────────────────────────────────── */}
      <section className="border-t pt-4">
        <a
          href="/grafana"
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 underline text-sm"
        >
          → Open Grafana dashboards (ingestion pipeline, system health)
        </a>
      </section>
    </main>
  );
}

function Stat({
  label,
  value,
  alert = false,
}: {
  label: string;
  value: number;
  alert?: boolean;
}) {
  return (
    <div className={`rounded-lg border p-4 ${alert ? "border-red-400 bg-red-50" : "bg-white"}`}>
      <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
      <p className={`text-2xl font-bold mt-1 ${alert ? "text-red-600" : ""}`}>
        {value.toLocaleString()}
      </p>
    </div>
  );
}
```

> 🎓 **Senior Insight — admin token in localStorage:** Using `localStorage` for the admin token is intentional and appropriate here. This page is only for you (the operator), not end users. There is no signup flow, no session management, no cookie. You paste the token once into the browser console: `localStorage.setItem("admin_token", "...")`. If your laptop is compromised, an attacker with access to your browser already has everything — the token is not the meaningful risk surface. This is operationally equivalent to storing a kubeconfig or AWS credentials file locally.

> 🎓 **Senior Insight — why not APScheduler for alert polling:** The T-44 stub mentioned a cron-based approach. This phase replaces it with the correct architecture: metrics are emitted by the application as events happen (pull model via Prometheus), not polled by a scheduler (push model). This means you get sub-minute alert latency instead of hourly batch checks, and you don't need a separate scheduler process or cron job. The only scheduled check that remains is the Redis quota scan in `GET /admin/stats`, which runs on-demand when you open the dashboard.

> 🔒 **Security:** The `/internal/alerts/webhook` endpoint is called by Alertmanager (internal Docker network only) using the `ADMIN_TOKEN` as a Bearer token. It is also reachable at the Nginx level because `/internal/` is under `/api/`. Add an Nginx deny rule to block external access:
> ```nginx
> location /api/internal/ {
>     allow 172.0.0.0/8;   # Docker internal networks
>     deny all;
>     proxy_pass http://api:8000/internal/;
> }
> ```
> This means even if someone knows the URL and the token, they cannot reach the endpoint from outside the instance. Defence in depth.

---

#### Instrumentation call sites — where to add metric increments

After T-69 defines the metric objects, add `.inc()` / `.observe()` calls in the service layer. Key locations:

| File | Where | Call |
|---|---|---|
| `workers/ingest.py` | On successful completion | `documents_processed_total.labels(user_id=user_id).inc()` |
| `workers/ingest.py` | In the `except` block before `status=FAILED` | `documents_failed_total.labels(reason=classify_error(e)).inc()` |
| `workers/ingest.py` | Around the full pipeline | `with processing_duration_seconds.time():` |
| `services/embedding.py` | After each OpenAI call | `openai_tokens_used_total.labels(kind="embedding").inc(token_count)` |
| `services/llm.py` | After stream completes | `openai_tokens_used_total.labels(kind="completion").inc(token_count)` |
| `utils/openai_client.py` | In each except branch | `openai_errors_total.labels(error_type="rate_limit").inc()` |
| `utils/s3_client.py` | In each except branch | `s3_errors_total.labels(operation="upload").inc()` |
| `services/auth.py` (register) | After user insert | `user_registrations_total.inc()` |
| `services/auth.py` (login) | On success | `user_logins_total.inc()` |
| `services/auth.py` (login) | On each failure path | `login_failures_total.labels(reason=...).inc()` |
| `services/email_verification.py` | After `resend.Emails.send()` | `emails_sent_total.labels(type="verification").inc()` |
| `services/password_reset.py` | After `resend.Emails.send()` | `emails_sent_total.labels(type="password_reset").inc()` |
| `utils/openai_client.py` | In `check_and_increment_token_usage` | `daily_quota_breaches_total.inc()` on quota exceeded |
| `routers/query.py` | Before stream begins | `queries_total.inc()` |
| `routers/query.py` | In SSE error paths | `stream_errors_total.labels(error_code=...).inc()` |

> 🎓 **Senior Insight:** Import the metric objects from `app.utils.metrics` at the top of each file. Never instantiate `Counter(...)` or `Gauge(...)` inside a function — Prometheus raises a `ValueError` if you register the same metric name twice, which happens the moment the module is imported more than once. Module-level singletons in `utils/metrics.py` prevent this entirely.
