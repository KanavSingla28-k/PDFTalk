# PDFTalk — MVP Task List
## Lightsail · Docker Compose · PostgreSQL + pgvector · Redis · FastAPI · Next.js

> **Stack:** Everything self-hosted on a single AWS Lightsail instance via Docker Compose.
> PostgreSQL (with pgvector), Redis, FastAPI, RQ worker, Nginx — all in containers.
> S3 for document storage. No ECS, no EFS, no ElastiCache, no NAT Gateway.
> **Total tasks:** 63 | **Estimated solo pace:** 3–4 weeks to first real deployment

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
│  └────────────────┬─────────────────────────┘   │
│                   │ internal Docker network      │
│  ┌────────────────┼────────────────────────┐    │
│  │                ▼                        │    │
│  │  api (FastAPI · uvicorn)                │    │
│  │  worker (RQ · ingest queue)             │    │
│  │  postgres (PG 15 + pgvector)            │    │
│  │  redis (Redis 7, AUTH required)         │    │
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
