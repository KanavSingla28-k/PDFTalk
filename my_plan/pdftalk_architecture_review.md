# PDFTalk — Principal Engineer Architecture Review

> **Document Type:** Technical Architecture Review + Implementation Roadmap
> **Reviewer Role:** Principal Software Engineer / Cloud Architect / Staff DevOps / Startup CTO
> **Project:** PDFTalk — Production-Grade RAG SaaS
> **Status:** Pre-MVP | Infrastructure partially provisioned
> **Date reviewed:** Based on `build_plan.md` v1 + `system_design.md` v2

---

## Navigation

1. [Executive Summary](#part-1--executive-summary)
2. [Brutal Architecture Review](#part-2--brutal-architecture-review)
3. [Lightsail Dev & Testing Strategy](#part-3--lightsail-development--testing-strategy)
4. [Production AWS Architecture](#part-4--production-aws-architecture)
5. [Cost Analysis](#part-5--cost-analysis)
6. [Technical Debt & Risk Register](#part-6--technical-debt--risk-register)
7. [Recommended Architecture Stacks](#part-7--recommended-architecture-stacks)
8. [Action Plan](#part-8--action-plan)

---

# PART 1 — Executive Summary

## Scorecard

| Dimension | Score | Verdict |
|---|---|---|
| **Overall Architecture Quality** | 7 / 10 | Fundamentally sound, technically literate, wrong phase |
| **MVP Suitability** | 3 / 10 | Critically overengineered for zero users |
| **Production Readiness** | 7 / 10 | Right components, misconfigured, sequencing inverted |
| **Operational Complexity** | 9 / 10 (bad) | Full-time SRE territory for a solo dev |
| **Learning Value** | 10 / 10 | Exceptional — this covers the entire production engineering curriculum |

---

## CTO Verdict

> ⚠️ **You have provisioned a production-grade multi-service AWS architecture before writing a single line of application code. Three tasks are already marked COMPLETE (IAM, VPC, RDS) — meaning you are already paying ~$50–80/month in infrastructure costs for an application that does not yet exist. This is the canonical mistake of overengineering at the wrong moment.**

This is not a bad architecture. In fact, for a production system serving real users, most of the choices here are defensible. The problem is **timing and sequence**. You are solving Year-2 infrastructure problems in Week 0.

---

## Is This Realistic for a Solo Developer?

**No — not on the original sequence.** The build plan as written has 79 tasks and deploys directly to ECS/Fargate on day one. At a realistic solo-developer pace of 1–2 tasks/day (accounting for debugging, learning AWS quirks, and context switching), that is **6–10 weeks before first deployment**. This is the fastest path to abandonment.

A solo developer needs feedback loops. You should be deploying something real within **2 weeks** — even if that something runs on a single Lightsail instance with Docker Compose.

---

## Is This Architecture Overengineered?

**Yes, for MVP. Appropriately scoped for production.** Specifically:

- **ECS + Fargate + ALB + VPC + NAT Gateway** for zero users is the SaaS equivalent of buying a semi-truck to deliver groceries. You need a bicycle right now.
- **EFS + FAISS file locking** is the most complex part of the stack and the part most likely to produce hard-to-debug production incidents.
- **Multi-service orchestration** (API + Worker + Redis + RDS + S3 + EFS) from day one means your local development story is Docker Compose with 6 services, and your "quick test" becomes a 5-minute startup sequence.
- **79 tasks** before ship is 6–10 weeks of work. Your competitor ships in 2 weeks.

---

## What Is Excellent

- **Tech stack selection is correct.** FastAPI, Next.js, PostgreSQL, Redis, S3, CloudFront — these are all right choices with strong ecosystem support.
- **Security posture is strong.** IAM task roles (no API keys in containers), httpOnly cookies, bcrypt at 12 rounds, JWT with rotation, Secrets Manager — this is better security hygiene than most funded startups.
- **The data flow diagrams are clear and complete.** The 24-step ingestion and 14-step query flows are well-specified and would survive an engineering interview.
- **S3 over R2 is correct.** The VPC Gateway Endpoint decision is smart — zero egress costs and native IAM integration.
- **The future migration paths are well-planned.** FAISS → Pinecone, password login → Google OAuth, presigned uploads — these are the right escape hatches.
- **Alembic + structured migrations.** Many solo projects skip this and pay dearly later.
- **Structured logging with structlog.** This is rare for a first project and will save you hours.

---

## What Is Risky

- **FAISS on EFS is the single largest technical risk in the system.** EFS is a network filesystem with ~5–15ms latency per operation. FAISS index files for power users can reach 500MB–2GB. File locking across 10 concurrent Fargate tasks is brittle and creates serialization bottlenecks. This design will work in development and fail silently in production under load. **Replace with pgvector immediately.**
- **Redis is a single point of failure for both session storage AND the job queue.** An ElastiCache outage kills both active user sessions AND document processing simultaneously. Two distinct failure modes collapsed into one.
- **NAT Gateway is running right now, costing ~$32/month, for nothing.** Three tasks are "COMPLETE" and your NAT Gateway is billing $0.045/hour while you have no application traffic.
- **ALB idle timeout is not configured.** Your SSE streaming endpoint will silently terminate connections after 60 seconds for long LLM responses. This is not mentioned anywhere in the 79 tasks.
- **No OpenAI cost controls.** A single user uploading a 50MB PDF with dense text could generate 200,000 tokens of embedding calls. At $0.02/1M tokens for text-embedding-3-small, a single document costs ~$0.004. At 1,000 documents per user, that's $4. At 10,000 users, that's $40,000. The plan has no per-user quotas, no spend alerts, no circuit breakers on the OpenAI client.
- **No email verification.** T-17 registers a user and immediately issues tokens. Without email verification, your system is trivially exploitable for API abuse.

---

## What Is Missing

- **pgvector** — the correct MVP vector store is already in your RDS instance; FAISS+EFS is unnecessary complexity
- **Email verification** — T-17 through T-22 never verify the email address
- **User quotas** — no document count limit, no monthly query limit, no storage limit per user
- **PgBouncer** — ECS tasks scaling 1→10 will create 10+ direct database connections; you need a connection pooler
- **ALB timeout configuration** — must be set to ≥120s for SSE to work reliably
- **OpenAI spend alerts** — CloudWatch alarm on daily embedding cost
- **Presigned upload URLs** — planned for Phase 2 but should be architected from day one; the current API-proxied upload limits you to files fitting in ECS task memory
- **The entire Lightsail phase** — your stated plan included Lightsail; your build plan skips it entirely

---

## What Would You Change Immediately

1. **Stop the NAT Gateway bleed.** Delete it or replace with a VPC Interface Endpoint if you need SSM access. Save $32/month.
2. **Replace FAISS + EFS with pgvector.** Delete T-08, simplify T-34, and eliminate the most complex failure mode in the system.
3. **Add a Lightsail phase.** Ship a working app on a $10/month Lightsail instance in 2 weeks before touching ECS.
4. **Compress 79 tasks to 40.** Many tasks (T-63 load testing, T-68 autoscaling, T-75–T-76 dashboards) are post-launch concerns.
5. **Configure ALB idle timeout to 300s** before any SSE endpoint touches production.

---

# PART 2 — Brutal Architecture Review

## Component Decision Table

| Component | Purpose in PDFTalk | MVP Phase | Staging | Production | Keep / Delay / Remove |
|---|---|---|---|---|---|
| **FastAPI** | API + streaming endpoint | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — correct choice |
| **Next.js** | Frontend SPA + streaming UI | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — SSE support is a genuine requirement |
| **PostgreSQL (RDS)** | Users, docs, chunks, state machine | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — already deployed |
| **Redis (ElastiCache)** | Job queue + refresh tokens | ⚠️ Simplify | ✅ Keep | ✅ Keep | **DELAY** — use Upstash free tier or local Redis in MVP |
| **RQ** | Background job processing | ✅ Keep | ✅ Keep | ⚠️ Reconsider | **KEEP for now** — fine at MVP scale; consider SQS before 1K users |
| **S3** | Raw file storage | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — already deployed, correct decision |
| **OpenAI** | Embeddings + LLM | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — correct choice |
| **FAISS** | Vector similarity search | ❌ Remove | ❌ Remove | ⚠️ Optional | **REMOVE MVP** — replace with pgvector |
| **ECS + Fargate** | API + worker containers | ❌ Delay | ✅ Use | ✅ Keep | **DELAY** — Lightsail first |
| **EFS** | FAISS index persistence | ❌ Remove | ❌ Remove | ❌ Remove | **REMOVE** — eliminated by pgvector |
| **ALB** | Load balancing + SSL termination | ❌ Delay | ✅ Use | ✅ Keep | **DELAY** — Lightsail Nginx handles this |
| **CloudFront** | CDN for frontend + latency | ❌ Delay | ✅ Use | ✅ Keep | **DELAY** — unnecessary at 0 users |
| **VPC** | Network isolation | ⚠️ Simplify | ✅ Keep | ✅ Keep | **KEEP** — already deployed; delete NAT GW |
| **NAT Gateway** | Private subnet internet egress | ❌ Delete | ⚠️ Optional | ✅ If private subnets | **DELETE NOW** — $32/month with no users |
| **Secrets Manager** | Credentials management | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — right choice, already used |
| **CloudWatch** | Metrics + logs + alarms | ❌ Delay | ✅ Basic | ✅ Full | **DELAY** — add after first deployment |
| **GitHub Actions** | CI/CD pipeline | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — essential from day one |
| **SSE Streaming** | Token-by-token LLM output | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — core UX requirement |
| **Docker** | Container runtime | ✅ Keep | ✅ Keep | ✅ Keep | **KEEP** — essential |
| **Docker Compose** | Local orchestration | ✅ Keep | ✅ Keep | ❌ Not in prod | **KEEP for dev** — primary dev tool |
| **ECR** | Container registry | ❌ Delay | ✅ Use | ✅ Keep | **DELAY** — use GitHub Registry or Docker Hub for MVP |

---

## Component Deep-Dive

### FastAPI

**Why it exists:** Python-native async API framework with first-class streaming support — essential for the SSE endpoint.

**Assessment:** Correct choice. The Python ecosystem co-location with PyMuPDF, NumPy, and faiss-cpu is a genuine advantage. `StreamingResponse` with `text/event-stream` works well. The Pydantic validation layer eliminates a class of input bugs.

**Risk:** The plan uses `asyncpg` with SQLAlchemy async throughout. This is correct but requires care — any blocking I/O in an async handler (including synchronous FAISS operations) will block the event loop. The `faiss_manager.py` file locking (`fcntl`) is synchronous and will block the async API worker during retrieval.

**Action:** Run all FAISS operations in a thread pool executor (`asyncio.get_event_loop().run_in_executor()`). This is not mentioned anywhere in the build plan.

---

### FAISS + EFS (The Critical Problem)

**Why it exists:** Per-user vector similarity search across embedded document chunks.

**The real problem this creates:**

The design stores per-user FAISS `IndexFlatIP` binary files on EFS, shared across all ECS worker tasks. This creates cascading failure modes:

1. **EFS latency at FAISS scale:** Loading a 200MB FAISS index from EFS takes 500ms–2s over NFS. For the query endpoint, every single request loads the index from EFS into memory. 100 concurrent users = 100 parallel 200MB file reads from EFS. EFS has a credit burst system; sustained throughput is throttled.

2. **File locking serialization:** With 10 workers processing documents for the same user simultaneously, `filelock` serializes all 10 into a queue. Worker throughput degrades linearly with user popularity. The 10th worker waits for 9 others to finish sequentially.

3. **Index corruption risk:** The `save(user_id)` operation writes a new binary file to EFS. If a Fargate task is SIGTERM'd mid-write (during a deployment or scale-in), the index file is corrupted. There is no write-ahead log, no atomic rename pattern, no checksum validation.

4. **Memory pressure:** The API task definition specifies 2GB RAM. A user with 500 documents × 200 chunks × 1536 dimensions × 4 bytes = **614MB FAISS index**. The query task holds this index in memory for the duration of the request, plus the rest of the Python process. Two concurrent queries from the same user = two simultaneous 614MB allocations in 2GB RAM.

**The fix is trivial:** PostgreSQL `pgvector` is available as an extension on your existing RDS instance. The equivalent query is:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE chunks ADD COLUMN embedding vector(1536);
SELECT id, text, document_id FROM chunks 
  WHERE user_id = $1 AND document_id = ANY($2)
  ORDER BY embedding <=> $3 
  LIMIT 5;
```

This eliminates: EFS, file locking, the `faiss_manager.py` module, the `filelock` dependency, T-08, T-34's complexity, and the memory pressure risk. Performance at MVP scale (<100K chunks per user) is indistinguishable from FAISS.

> 💡 **Decision Record:** Replace FAISS + EFS with pgvector on existing RDS. This removes 1 AWS service, 1 dependency module, and 1 complex failure mode. Migrate to Pinecone when pgvector query time exceeds 200ms under load — the interface is nearly identical.

---

### Redis / ElastiCache + RQ

**Why it exists:** (1) Job queue for background document processing. (2) Refresh token storage.

**Assessment:** RQ is a reasonable choice for a Python-native job queue. The dual-use of Redis is pragmatic but creates a single point of failure for two unrelated concerns.

**The real risk:** An ElastiCache outage simultaneously kills:
- All active user sessions (refresh tokens gone)
- All queued document processing jobs (lost from queue)

**Mitigation:** Use Redis database namespacing (`SELECT 0` for tokens, `SELECT 1` for queue) and document the dependency clearly. Set `maxmemory-policy: noeviction` on the ElastiCache cluster — the default `volatile-lru` will silently evict active refresh tokens under memory pressure, logging users out randomly.

**ALB + SSE timeout (critical missing config):** ALB has a default idle connection timeout of 60 seconds. An LLM response for a multi-document query over a slow model can take 45–90 seconds. The fix is a single API call: set the ALB load balancer's `idle_timeout.timeout_seconds` attribute to `300`. This is not mentioned in any of the 79 tasks.

---

### ECS + Fargate

**Why it exists:** Serverless container orchestration for API and worker services.

**Assessment:** Correct long-term choice. Wrong starting point for a solo developer.

**The operational burden is significant:**
- Task definitions must be versioned and redeployed for every config change
- Container startup time is 30–60 seconds (cold starts affect rollbacks)
- CloudWatch log streaming must be configured explicitly per task
- IAM task roles must be precisely scoped or tasks fail silently
- Health check misconfiguration causes ECS to deregister all tasks and spin-replace endlessly
- The alembic migration task (one-off ECS run before service update) has no retry mechanism in the plan

**For MVP with zero users:** A single Lightsail instance running Docker Compose delivers the same functional capabilities at 1/10th the operational overhead and 1/5th the cost.

---

### NAT Gateway (Delete Now)

**Why it exists:** Provides internet access for ECS tasks in private subnets (needed to reach OpenAI API, pull ECR images, call Secrets Manager).

**The problem:** You have a NAT Gateway provisioned at $0.045/hour = **$32.40/month**. It has been running since T-04 was marked COMPLETE. With zero application traffic, this is pure waste.

**The alternatives:**
- **VPC Interface Endpoints** for ECR, S3, Secrets Manager, CloudWatch — these keep traffic on the AWS backbone and cost ~$7/month each, but only pay off at sustained traffic
- **Move ECS tasks to public subnets with no public IP** — assign `DISABLED` for auto-assign public IP; tasks pull via the IGW but have no inbound internet access; this eliminates NAT Gateway entirely
- **Delete NAT Gateway entirely for now** — during development, you access RDS via a bastion host or SSM Session Manager

> ⚠️ **Immediate action:** If you are not running ECS tasks right now, delete the NAT Gateway and its Elastic IP. Save $32.40/month. Provision it again when you start Lightsail → ECS migration.

---

### CloudFormation (Missing from Build Plan)

The build plan mentions "migrate to AWS CloudFormation-managed infrastructure later" as a goal, but no task exists for it. Tasks T-03 through T-10 deploy infrastructure manually through the AWS console or CLI. This means your existing infrastructure (VPC, RDS, ElastiCache) is **unmanaged by Infrastructure as Code**.

Before deploying to production, every manually-created resource must be imported into a CloudFormation stack or reproduced by one. Manual infrastructure cannot be reproduced reliably, audited, or rolled back.

---

# PART 3 — Lightsail Development & Testing Strategy

## Recommended Instance

| Attribute | Specification |
|---|---|
| **Plan** | $20/month (2 vCPU, 4GB RAM, 80GB SSD, 4TB transfer) |
| **OS** | Ubuntu 22.04 LTS |
| **Region** | ap-south-1 (same as your RDS instance — eliminates cross-region latency) |
| **Static IP** | Yes — assign a Lightsail static IP ($0/month while attached) |
| **Snapshots** | Weekly automated snapshots ($0.05/GB) |

**Why this instance:** The $10/month plan (1 vCPU, 2GB RAM) is tight for running 4 Docker containers simultaneously. FastAPI + RQ Worker + Redis + Nginx will hit 1.8GB RAM under light load. The $20 plan gives you comfortable headroom, automated snapshot eligibility, and is still 4× cheaper than a comparable EC2 instance.

**Why not the $10 plan:** Redis alone uses ~200MB. A Python FastAPI process with dependencies loaded uses ~300MB. An RQ worker uses another ~300MB. Under a document processing job (PyMuPDF + NumPy + OpenAI SDK loaded), peak usage reaches 700MB–1.2GB. The $10 plan will OOM under normal document processing.

---

## Docker Architecture on Lightsail

### Container Stack

```
nginx          — Reverse proxy, SSL termination, static file serving
api            — FastAPI application (uvicorn)
worker         — RQ worker (ingest queue)
redis          — Redis 7 (job queue + refresh tokens)
```

> 💡 **Note:** Do NOT run PostgreSQL on Lightsail. Use your existing RDS instance. The reasons: (1) RDS is already provisioned and paid for; (2) PostgreSQL data management (backups, failover, upgrades) is non-trivial on a single VM; (3) your Lightsail SSD is not optimized for database I/O; (4) RDS automated backups already cover your data.

### Docker Compose Structure

```yaml
# docker-compose.yml (production-ready Lightsail config)

version: "3.9"

services:
  nginx:
    image: nginx:1.25-alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - ./frontend/out:/usr/share/nginx/html:ro
      - nginx_logs:/var/log/nginx
    depends_on:
      - api
    restart: unless-stopped

  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file: ./backend/.env
    volumes:
      - app_logs:/app/logs
    depends_on:
      - redis
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    env_file: ./backend/.env
    volumes:
      - app_logs:/app/logs
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --appendonly yes
      --maxmemory 512mb
      --maxmemory-policy noeviction
    volumes:
      - redis_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s

volumes:
  redis_data:
  app_logs:
  nginx_logs:
```

### Volume Strategy

| Volume | Data | Backup Strategy |
|---|---|---|
| `redis_data` | Job queue + refresh tokens | Redis AOF persistence; weekly Lightsail snapshot |
| `app_logs` | Structured JSON logs | CloudWatch agent push (optional) or log rotation |
| `nginx_logs` | Access + error logs | Log rotation with `logrotate` |
| `nginx/ssl` | TLS certificates (Let's Encrypt) | Certbot auto-renewal cron |

### Backup Strategy

- **Lightsail automated snapshots:** Enable weekly snapshots ($0.05/GB/month). This captures the entire instance state including Redis AOF files.
- **RDS backups:** Already configured (7-day PITR). This is your primary database safety net.
- **S3 files:** Versioning already enabled. No additional backup needed.
- **Critical:** Before any deployment, manually trigger a Lightsail snapshot. Keep the last 3 snapshots.

### Logging Strategy

```bash
# Centralized log collection from all containers
docker compose logs --follow --tail=100 2>&1 | tee -a /var/log/pdftalk/app.log

# Log rotation (add to /etc/logrotate.d/pdftalk)
/var/log/pdftalk/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

For structured logs from the FastAPI container (structlog JSON output), pipe to CloudWatch Logs using the CloudWatch agent. Cost: ~$0.50/GB ingested + $0.03/GB stored/month. For a dev/staging environment, this is optional — `docker compose logs` is sufficient.

---

## AWS Services During Lightsail Phase

### Use from Day One

| Service | Purpose | Monthly Cost |
|---|---|---|
| **RDS** (already provisioned) | PostgreSQL — primary database | ~$13/month (db.t4g.micro) |
| **S3** (already provisioned) | Document storage | ~$2–5/month |
| **Route 53** | DNS — point your domain to Lightsail static IP | ~$0.50/month |
| **Secrets Manager** | Credentials for RDS, OpenAI, JWT secret | ~$0.40/month per secret |

### Add Later in Lightsail Phase

| Service | Trigger | Cost |
|---|---|---|
| **CloudWatch Logs** | When structured logging is ready | ~$1–3/month |
| **ACM Certificate** | When adding CloudFront or ALB | Free |

### Do NOT Introduce During Lightsail Phase

| Service | Reason to Delay |
|---|---|
| **ECS + Fargate** | Entire point of Lightsail phase is to avoid this |
| **ALB** | Nginx on Lightsail handles load balancing for 1 instance |
| **ElastiCache** | Redis on Lightsail is sufficient for dev/staging |
| **EFS** | Eliminated entirely if you adopt pgvector |
| **NAT Gateway** | Delete it now; reprovision when you move to ECS |
| **CloudFront** | Negligible benefit at 0–100 users; add before Beta launch |
| **ECR** | Use GitHub Container Registry (ghcr.io) for free |

---

## CI/CD During Lightsail Phase

### GitHub Actions Workflow

**CI Pipeline (every PR):**

```yaml
# .github/workflows/ci.yml
on:
  pull_request:
    branches: [main, develop]

jobs:
  test-backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_DB: pdftalk_test
          POSTGRES_PASSWORD: test
        options: --health-cmd pg_isready
      redis:
        image: redis:7
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[test]"
      - run: pytest --cov=app --cov-report=xml
      - run: ruff check .
      - run: mypy app/

  test-frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: pnpm install --frozen-lockfile
      - run: pnpm test
      - run: pnpm type-check
```

**CD Pipeline (push to main → Lightsail):**

```yaml
# .github/workflows/deploy-lightsail.yml
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build images
        run: |
          docker build -t pdftalk-api ./backend
          docker build -t pdftalk-worker -f ./backend/Dockerfile.worker ./backend

      - name: Export and transfer images
        run: |
          docker save pdftalk-api pdftalk-worker | gzip > images.tar.gz
          scp -i ${{ secrets.LIGHTSAIL_KEY }} images.tar.gz ubuntu@${{ secrets.LIGHTSAIL_IP }}:/tmp/

      - name: Deploy on Lightsail
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.LIGHTSAIL_IP }}
          username: ubuntu
          key: ${{ secrets.LIGHTSAIL_KEY }}
          script: |
            docker load < /tmp/images.tar.gz
            cd /opt/pdftalk
            git pull origin main
            docker compose up -d --no-deps api worker
            docker compose exec -T api alembic upgrade head
            docker system prune -f
```

### Rollback Strategy

```bash
# Rollback to previous image (tag images with git SHA)
docker tag pdftalk-api:current pdftalk-api:rollback-$(date +%Y%m%d)
docker tag pdftalk-api:previous pdftalk-api:current
docker compose up -d --no-deps api worker

# Full rollback via Lightsail snapshot
# 1. Stop current instance
# 2. Create new instance from last known good snapshot
# 3. Point static IP to new instance
# Total time: ~5 minutes
```

> ⚠️ **Keep the last 2 Lightsail snapshots at all times.** The snapshot restore is your nuclear rollback option and is faster than any automated rollback pipeline.

---

# PART 4 — Production AWS Architecture

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INTERNET USERS                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │ HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  CloudFront Distribution                                             │
│  ├─ Origin 1: S3 (frontend static assets, OAC)                      │
│  └─ Origin 2: ALB (API requests to /api/*)                          │
│  Cache-Control: HTML no-cache, _next/static/* 1yr                   │
│  WAF: Rate limiting, SQL injection, bot protection                   │
└────────────────┬────────────────────────────────────────────────────┘
                 │ /api/* forwarded
                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Application Load Balancer                                           │
│  ├─ HTTPS listener (443) → Target Group (ECS API tasks)             │
│  ├─ HTTP → HTTPS redirect                                            │
│  ├─ Health check: GET /health, threshold 2/2                        │
│  └─ Idle timeout: 300s (required for SSE streaming)                 │
└────────────────┬────────────────────────────────────────────────────┘
                 │
          ┌──────┴──────┐
          │             │
          ▼             ▼
┌──────────────┐ ┌──────────────┐
│ ECS API Task │ │ ECS API Task │  ← Fargate, 1 vCPU / 2GB
│  FastAPI     │ │  FastAPI     │  ← sg-ecs-api (from ALB only)
│  port 8000   │ │  port 8000   │  ← Auto-scales on CPU ≥ 70%
└──────┬───────┘ └──────┬───────┘
       │                │
       └───────┬────────┘
               │  (shared dependencies)
       ┌───────┼───────────────────────────┐
       │       │                           │
       ▼       ▼                           ▼
┌─────────┐ ┌──────────┐          ┌──────────────┐
│  RDS    │ │  ElastiC.│          │    S3 bucket │
│  PG 15  │ │  Redis 7 │          │  pdftalk-    │
│  Multi-AZ│ │  cluster │          │  documents   │
│  private│ │  private │          │  VPC Endpoint│
└─────────┘ └────┬─────┘          └──────────────┘
                 │ (queue pop)            │
                 ▼                        │
┌──────────────────────────────┐          │
│ ECS Worker Tasks (1–10)      │◄─────────┘
│  RQ Worker                   │  (boto3 download)
│  2 vCPU / 4GB                │
│  extract→chunk→embed→store   │
│  Auto-scales on queue depth  │
└──────────────────────────────┘
       │
       ▼
┌──────────────┐
│  OpenAI API  │  (embeddings + GPT-4o-mini)
│  External    │  Circuit breaker + retry
└──────────────┘
```

**Connection explanations:**

- **CloudFront → S3:** Static frontend served via OAC (Origin Access Control) — no public S3 bucket. Long TTL on hashed assets, no-cache on HTML.
- **CloudFront → ALB:** All `/api/*` requests forwarded to ALB; SSE streaming headers must be preserved (`Cache-Control: no-cache` added at the CloudFront behavior level, disable compression for SSE).
- **ALB → ECS API:** Health check every 30s; deregistration delay 30s (keep short for fast deployments).
- **ECS API → RDS:** SQLAlchemy async pool with PgBouncer sidecar container or RDS Proxy for connection pooling; Fargate scaling can create 10× connections without pooling.
- **ECS API → ElastiCache:** Refresh token lookup and rate limiting; TLS + AUTH token.
- **ECS API → S3:** Via VPC Gateway Endpoint; IAM task role grants `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` on `pdftalk-documents/*` only.
- **ECS API → OpenAI:** Outbound via NAT Gateway (or Interface Endpoint if you want to avoid NAT costs).
- **ElastiCache → ECS Workers:** RQ `blocking_pop` keeps workers subscribed; workers auto-scale based on `ApproximateNumberOfJobsInQueue` CloudWatch metric.
- **ECS Workers → S3:** Download raw files via VPC Gateway Endpoint; no NAT cost.
- **ECS Workers → RDS:** Direct connection (via pgvector if FAISS replaced); chunk metadata writes.

---

## CloudFormation Strategy

### Stack Structure and Deployment Order

Deploy stacks in this exact order. Each stack outputs values consumed by later stacks via `Fn::ImportValue`.

```
1. networking.yml        ← Foundation (VPC, subnets, SGs, IGW)
2. security.yml          ← IAM roles, KMS keys, Secrets Manager secrets
3. storage.yml           ← S3 buckets, (pgvector doesn't need EFS)
4. database.yml          ← RDS, ElastiCache (depends on networking)
5. compute.yml           ← ECS cluster, task defs, services, ALB (depends on 1-4)
6. cdn.yml               ← CloudFront, ACM certificate (depends on compute + storage)
7. monitoring.yml        ← CloudWatch dashboards, alarms, SNS topics (depends on 5)
```

### Stack Breakdown

**1. `networking.yml`**

Why: Everything else depends on VPC, subnets, and security groups. Changing networking resources requires downtime, so it must be isolated and stable.

Exports: VPC ID, private subnet IDs, public subnet IDs, all security group IDs.

```yaml
Resources:
  VPC, PublicSubnetA, PublicSubnetB,
  PrivateSubnetA, PrivateSubnetB,
  InternetGateway, NATGateway (conditional: !If [IsProduction, NATGateway, !Ref AWS::NoValue]),
  SecurityGroupALB, SecurityGroupAPI, SecurityGroupWorker,
  SecurityGroupRDS, SecurityGroupRedis,
  S3VPCEndpoint
```

Note: NAT Gateway as a conditional resource allows staging to omit it and save $32/month.

---

**2. `security.yml`**

Why: IAM roles and KMS keys must exist before compute resources reference them. Secrets Manager secrets must be created before task definitions try to inject them.

Resources: `ECSTaskExecutionRole`, `ECSTaskRole`, `SecretsManagerSecrets` (RDS password, JWT secret, OpenAI key, Redis auth).

---

**3. `storage.yml`**

Why: S3 bucket policies reference the ECS task role (from `security.yml`). Bucket must exist before workers start uploading files.

Resources: `DocumentsBucket` (versioning, SSE-KMS, block public access, bucket policy).

---

**4. `database.yml`**

Why: RDS and ElastiCache subnet groups need the private subnets. These services take 5–15 minutes to provision, so they belong in an early, stable stack.

Resources: `RDSSubnetGroup`, `RDSInstance` (PostgreSQL 15, Multi-AZ), `ElastiCacheSubnetGroup`, `ElastiCacheCluster` (Redis 7), `RDSProxy` (optional — connection pooler managed by AWS, eliminates PgBouncer complexity).

---

**5. `compute.yml`**

Why: ECS depends on networking, security, storage, and database stacks. This is the most frequently updated stack — every deployment updates task definition revisions.

Resources: `ECSCluster`, `APITaskDefinition`, `WorkerTaskDefinition`, `APIService`, `WorkerService`, `ALB`, `ALBTargetGroup`, `ALBListener`, `APIAutoScalingTarget`, `WorkerAutoScalingTarget`, `WorkerAutoScalingPolicy` (queue depth metric).

---

**6. `cdn.yml`**

Why: CloudFront distributions take 10–20 minutes to deploy and rarely change. ACM certificates for CloudFront must be in `us-east-1` regardless of your primary region — this is a common gotcha.

Resources: `FrontendBucket`, `CloudFrontOAC`, `CloudFrontDistribution`, `ACMCertificate` (in us-east-1 via Stack Set or separate stack).

---

**7. `monitoring.yml`**

Why: Alarms and dashboards reference resources from all other stacks. Kept separate to avoid circular dependencies and because monitoring configuration changes frequently.

Resources: `CloudWatchDashboard`, `ALB5xxAlarm`, `RDSCPUAlarm`, `RedisMemoryAlarm`, `QueueDepthAlarm`, `OpenAICostAlarm`, `SNSTopic`, `SlackNotification` (Lambda + SNS subscription).

---

## Migration Plan

### Stage 1 — Local Development

**Infrastructure:** Docker Compose (API + Worker + Redis + Nginx). PostgreSQL on RDS (already provisioned). S3 for file storage.

**What you can do:** Full functional testing of every API endpoint, background job processing, SSE streaming, auth flows.

**Costs:** ~$13–20/month (RDS only + S3). No ECS, no ALB, no NAT.

**Risks:** Local-to-cloud latency adds ~20ms to every DB query. Not a real production simulation. Works for 95% of development.

**Migration effort:** 2–4 hours to set up Docker Compose correctly, `.env` files, and verify RDS connectivity from Docker bridge network.

---

### Stage 2 — Lightsail

**Infrastructure:** Single Lightsail $20/month instance. Docker Compose. RDS + S3 from Stage 1. Let's Encrypt SSL.

**What you can do:** Real HTTPS, real domain, shareable beta URL, real user testing, realistic network conditions.

**Costs:** ~$35–50/month (Lightsail $20 + RDS $13 + S3 $5 + Route53 $1).

**Risks:** Single instance (no redundancy). A crash = downtime until you SSH in. Not suitable for production SLA.

**Migration effort:** 4–8 hours. SSH key setup, Docker install, Docker Compose deploy, Certbot SSL, Route53 DNS record, GitHub Actions deploy workflow.

---

### Stage 3 — Hybrid AWS

**Infrastructure:** Keep Lightsail for the API/worker. Add CloudFront + S3 for frontend. Add ElastiCache to replace the Docker Redis. Migrate to pgvector.

**What you can do:** CDN-served frontend globally, managed Redis with persistence, real-world performance testing.

**Costs:** ~$70–90/month (Lightsail $20 + RDS $13 + ElastiCache $16 + S3 $5 + CloudFront $5 + Route53 $1).

**Risks:** Multi-service dependencies; Lightsail instance is still a single point of failure for the API.

**Migration effort:** 1–2 days. CloudFormation stacks 1–4. Update Docker Compose environment variables to point to ElastiCache instead of local Redis.

---

### Stage 4 — Production AWS

**Infrastructure:** Full CloudFormation-managed stack. ECS Fargate. ALB. CloudFront. Multi-AZ RDS. Managed ElastiCache. All 7 CloudFormation stacks deployed.

**Trigger for this stage:** Paying users, defined SLA requirements, traffic that saturates a single Lightsail instance (>50 concurrent users or >1,000 documents processed/day).

**Costs:** ~$180–280/month (see Part 5).

**Migration effort:** 3–5 days. Deploy all CloudFormation stacks. Blue/green migration: run Lightsail and ECS simultaneously; shift Route53 weight 10/90 → 50/50 → 0/100 over 48 hours. Verify alarms. Decommission Lightsail.

---

# PART 5 — Cost Analysis

## Stage 1: Local Development (MVP)

| Service | Configuration | Monthly Cost |
|---|---|---|
| RDS PostgreSQL | db.t4g.micro, 20GB gp3 | $13 |
| S3 | 10GB storage, minimal requests | $0.23 |
| Secrets Manager | 3 secrets | $1.20 |
| Route 53 | 1 hosted zone (optional) | $0.50 |
| **Total** | | **~$15/month** |

> 💡 Stop RDS when not developing (use RDS start/stop). Saves ~$10/month. Note: RDS auto-starts after 7 days.

---

## Stage 2: Lightsail Development & Staging

| Service | Configuration | Monthly Cost |
|---|---|---|
| Lightsail instance | 2 vCPU, 4GB RAM, $20 plan | $20 |
| Lightsail static IP | Attached (free) | $0 |
| Lightsail snapshots | Weekly, ~30GB | $1.50 |
| RDS PostgreSQL | db.t4g.micro | $13 |
| S3 | 20GB storage | $0.46 |
| Route 53 | 1 hosted zone + A record | $0.50 |
| Secrets Manager | 4 secrets | $1.60 |
| **Total** | | **~$37/month** |

---

## Stage 3: Hybrid AWS (Pre-ECS)

| Service | Configuration | Monthly Cost |
|---|---|---|
| Lightsail | $20 plan | $20 |
| RDS PostgreSQL | db.t4g.micro | $13 |
| ElastiCache | cache.t4g.micro, Redis 7 | $16 |
| S3 | 50GB documents + frontend | $1.30 |
| CloudFront | 10GB transfer, 1M requests | $2–8 |
| Route 53 | 2 records | $0.50 |
| Secrets Manager | 5 secrets | $2 |
| CloudWatch Logs | 5GB/month | $2.50 |
| **Total** | | **~$57–65/month** |

---

## Stage 4: Full Production AWS

| Service | Configuration | Monthly Cost |
|---|---|---|
| ECS Fargate (API) | 1 task min, 1 vCPU/2GB, ~730h | $30 |
| ECS Fargate (Worker) | 1 task min, 2 vCPU/4GB, ~730h | $60 |
| ECS Fargate (burst) | Scale events estimated | $15–40 |
| RDS PostgreSQL | db.t3.small Multi-AZ | $50 |
| ElastiCache | cache.t4g.small | $27 |
| ALB | Minimum LCU charges | $22 |
| NAT Gateway | $0.045/hr + $0.045/GB | $32–45 |
| S3 | 200GB + requests | $5–10 |
| CloudFront | 100GB transfer, 10M requests | $9–15 |
| Secrets Manager | 8 secrets + API calls | $3.50 |
| CloudWatch | Metrics + logs + dashboards | $8–15 |
| Route 53 | 2 hosted zones, health checks | $4 |
| ACM | TLS certificates | $0 |
| ECR | 3 images, 10 versions | $1–3 |
| **Total** | | **~$266–330/month** |

---

## Hidden AWS Costs: What Will Surprise You

| Gotcha | Why It Hurts | Mitigation |
|---|---|---|
| **NAT Gateway data processing** | $0.045/GB processed — every OpenAI API call, every ECR pull, every npm package = egress through NAT | VPC Endpoints for ECR, S3, Secrets Manager; minimize NAT traffic |
| **ALB minimum LCU** | Even with 0 requests, you pay ~$16–22/month minimum | Accept it; part of moving to ECS |
| **ElastiCache minimum** | cache.t4g.micro = $16/month whether you use it or not | Use Upstash Redis free tier in staging |
| **CloudWatch Logs ingestion** | $0.50/GB ingested — verbose JSON logs fill up fast | Set log levels to WARNING in production; use sampling |
| **RDS Multi-AZ** | Doubles the RDS cost (standby instance always running) | Use Single-AZ in staging; Multi-AZ only in production |
| **Data transfer out** | $0.09/GB out of AWS to internet | Use CloudFront in front of ALB to cache API responses (where possible) |
| **EFS throughput** | Default mode throttles; bursting mode hits credit limits | Eliminated by pgvector; this was your most expensive hidden cost |
| **Fargate cold starts** | ECS task start time is 30–60s; poor UX for scale-to-zero | Keep `minCount: 1` for API tasks; never scale to 0 |
| **ECR storage** | $0.10/GB/month; 10 large Python images = several GB | Set lifecycle policy to keep only last 5 images |
| **Secrets Manager API calls** | $0.05/10,000 API calls; ECS tasks call on every start | Use Parameter Store for non-secret config; cache secrets in task startup |

---

# PART 6 — Technical Debt & Risk Register

| Risk | Severity | Likelihood | Impact | Recommendation |
|---|---|---|---|---|
| **FAISS file corruption on concurrent ECS task SIGTERM** | 🔴 Critical | High | Data loss, user's documents become unqueryable | Replace with pgvector; implement atomic rename if keeping FAISS |
| **NAT Gateway billing with no users** | 🟠 High | Certain (already happening) | $32+/month wasted | Delete immediately |
| **ALB idle timeout not configured for SSE** | 🔴 Critical | Certain in production | Silent connection resets mid-response; terrible UX | Set `idle_timeout.timeout_seconds = 300` on ALB |
| **Redis ElastiCache: dual-use single point of failure** | 🟠 High | Low (Redis is reliable) but catastrophic when triggered | All sessions invalidated + all jobs lost simultaneously | Separate Redis DBs; document failure mode; set maxmemory-policy noeviction |
| **No OpenAI spend controls** | 🟠 High | Medium (one viral user) | Unexpected $500+ bill | Per-user daily token limit in Redis; CloudWatch alarm on estimated cost |
| **No email verification** | 🟠 High | Certain (bots) | API abuse, invalid accounts, spam | Add email verification before T-17 ships to production |
| **ECS Fargate cold start = 30–60s rollback delay** | 🟡 Medium | High (every deployment) | Slow rollback in incidents | Blue/green deployment; keep `minHealthyPercent: 100` during deploy |
| **Alembic migration as one-off ECS task has no retry** | 🟡 Medium | Medium | Failed migration blocks deployment silently | Add `--check` before `upgrade head`; alert on non-zero exit |
| **Chunking: no max document size enforcement** | 🟡 Medium | Medium | Dense 50MB PDF = 300K+ tokens = $6+ embedding call per document | Calculate estimated embedding cost before accepting job; reject if over threshold |
| **RDS db.t4g.micro connection limit: 15 max connections** | 🟡 Medium | High (ECS scaling) | Connection exhaustion at 10+ Fargate tasks | Add RDS Proxy or PgBouncer before moving to ECS |
| **JWT secret rotation not tested** | 🟡 Medium | Low (routine maintenance) | All users logged out simultaneously if rotation fails | Test rotation procedure in staging before first production rotation |
| **No IAC for existing resources (VPC, RDS)** | 🟡 Medium | N/A | Cannot reproduce environment; manual recreation in disaster | Import existing resources into CloudFormation before Stage 4 |
| **pgvector index not created** | 🟡 Medium | Certain (if adopted) | Full table scan on vector queries = slow at 10K+ chunks | `CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops)` with `lists = 100` |
| **FAISS IndexFlatIP: no document_id filtering** | 🟡 Medium | Certain at scale | Multi-document queries return chunks from documents user didn't select | T-40 filters post-search; at large scales this means retrieving many more candidates than K |
| **Fargate CPU limits: FAISS index load blocks event loop** | 🟡 Medium | Certain | Synchronous FAISS load in async FastAPI handler starves other requests | Run in `asyncio.run_in_executor()` — not mentioned in build plan |
| **No user-facing API versioning** | 🟢 Low | Low | Breaking changes require frontend coordination | Add `/api/v1/` prefix from day one |
| **CloudFront and SSE streaming** | 🟡 Medium | Certain | CloudFront caches by default; SSE responses must not be cached | Set `Cache-Control: no-cache, no-store` in SSE response headers; configure CloudFront behavior to not cache `/api/query/*` |

---

# PART 7 — Recommended Architecture Stacks

## Option A: MVP Architecture (Weeks 1–4)

> **Goal:** Prove the product works. Validate RAG quality. Get first real users.

**Services:**
- Docker Compose locally (API + Worker + Redis + Nginx)
- PostgreSQL on RDS (existing db.t4g.micro)
- S3 for file storage (existing)
- pgvector extension (replace FAISS entirely)
- Next.js built locally, served via Nginx
- Secrets via `.env` file locally; Secrets Manager for deployed secrets

**Deployment:** Docker Compose on Lightsail $20/month instance

**Operational complexity:** Low. `ssh + docker compose pull && docker compose up -d`. One server. One log stream. One place to look when things go wrong.

**Monthly cost:** ~$37/month

**Scaling capability:** ~50 concurrent users, ~500 documents/day processed

**What you learn:** The entire application stack, data flow, user feedback. Whether your RAG quality is actually good enough to charge for.

---

## Option B: Beta Launch Architecture (Months 2–3)

> **Goal:** Handle real user traffic. Support a small paying cohort. Collect real performance data.

**Services:**
- Lightsail (2× $20 instances — blue/green deployment with DNS switching)
- RDS db.t3.small (upgrade from t4g.micro for more connections)
- ElastiCache cache.t4g.micro (replace Docker Redis with managed service)
- S3 for documents + frontend static
- CloudFront for frontend CDN
- Route 53 with health checks
- GitHub Actions CD to Lightsail
- CloudWatch Logs (structured JSON from structlog)

**Deployment:** Docker Compose on Lightsail; zero-downtime deploys by blue/green DNS switching

**Operational complexity:** Medium. Two servers to manage, managed Redis, RDS. CloudWatch for alerts.

**Monthly cost:** ~$85–100/month

**Scaling capability:** ~200 concurrent users, ~2,000 documents/day

**What you learn:** Multi-service operations, DNS failover, CloudWatch alarms, real user load patterns.

---

## Option C: Production Architecture (Month 4+, with Revenue)

> **Goal:** Production SLA, horizontal scaling, zero-downtime deployments, full observability.

**Services:**
- ECS Fargate (API: 1–5 tasks, Worker: 1–10 tasks)
- RDS PostgreSQL 15 Multi-AZ (db.t3.small → db.t3.medium when needed)
- ElastiCache Redis 7 (cache.t4g.small, single-node until revenue warrants cluster mode)
- ALB (with WAF rules, idle timeout 300s, access logs to S3)
- CloudFront (frontend + API caching where possible)
- S3 (documents + frontend + ALB access logs)
- Secrets Manager (all credentials)
- CloudWatch (dashboards, alarms, X-Ray tracing)
- ECR (private container registry with image scanning)
- GitHub Actions (CI + CD with manual approval gate for production)
- pgvector (→ Pinecone when query P95 > 200ms under load)
- RDS Proxy (eliminates PgBouncer complexity; manages connection pooling)
- CloudFormation (all 7 stacks, version-controlled in repo)

**Deployment:** ECS rolling deploys via GitHub Actions. `minHealthyPercent: 100, maximumPercent: 200`.

**Operational complexity:** High. Requires understanding ECS service events, CloudWatch alarms, task definition versioning, ALB target group health.

**Monthly cost:** ~$266–330/month (before user-driven variable costs)

**Scaling capability:** Hundreds of concurrent users, tens of thousands of documents/day, automatic horizontal scaling.

**Trigger for migration:** Lightsail CPU consistently >70%, OR you have > 100 paying users, OR you need SLA guarantees for B2B customers.

---

# PART 8 — Action Plan

## Immediate Actions (This Week)

- [ ] **Delete the NAT Gateway.** Go to VPC console → NAT Gateways → delete. Save $32/month.
- [ ] **Stop RDS instance when not in active development** (RDS → Stop temporarily). Costs $0 while stopped; auto-starts after 7 days.
- [ ] **Set up pgvector instead of FAISS.** Connect to RDS: `CREATE EXTENSION IF NOT EXISTS vector;`. Remove T-08 (EFS) from the critical path.
- [ ] **Revise T-34:** Replace `faiss_manager.py` with `pgvector_manager.py` using `asyncpg` native vector operations.
- [ ] **Set up Docker Compose locally** with all services running before writing another line of API code.
- [ ] **Add ALB idle timeout to your infrastructure checklist:** `aws elbv2 modify-load-balancer-attributes --attributes Key=idle_timeout.timeout_seconds,Value=300`.
- [ ] **Create a Lightsail instance** in ap-south-1 ($20/month plan). Configure SSH key.
- [ ] **Remove T-08, T-34 (EFS/FAISS)** from the build plan or mark them as deferred. Save 2–3 weeks of complexity.

---

## Next 30 Days

- [ ] Complete T-11 through T-22 (FastAPI scaffold + Auth system). This is the foundation.
- [ ] Complete T-23 through T-31 (File ingestion pipeline). Core product functionality.
- [ ] Complete T-32, T-33, T-35 (OpenAI embeddings + chunk storage). Skip EFS/FAISS tasks.
- [ ] Implement pgvector retrieval (replaces T-34, T-40). 20 lines of SQL.
- [ ] Complete T-42 through T-45 (LLM integration + SSE streaming). The hardest UX problem.
- [ ] Set up GitHub Actions CI pipeline (T-72).
- [ ] Deploy to Lightsail (using Docker Compose deploy workflow above).
- [ ] Get a real user to upload a real document and ask a real question.
- [ ] Add `per_user_daily_embedding_limit` check before accepting ingestion jobs (not in original plan — add it).
- [ ] Add email verification to T-17 (not in original plan — add it).

---

## Before Lightsail Deployment

- [ ] All 5 database tables created via Alembic migrations (T-06)
- [ ] Auth endpoints fully tested with integration tests (T-22)
- [ ] Upload → ingest → query flow works end-to-end locally
- [ ] SSE streaming tested with a real OpenAI call (not mocked)
- [ ] Docker images build successfully without errors
- [ ] `.env` files documented with all required variables
- [ ] RDS accessible from Lightsail (security group allows inbound 5432 from Lightsail static IP)
- [ ] S3 upload tested from Docker container using IAM credentials
- [ ] Nginx config handles HTTPS termination + reverse proxy + SSE streaming headers
- [ ] `GET /health` returns 200 with DB + Redis + S3 checks
- [ ] GitHub Actions CI pipeline runs green on a PR
- [ ] Lightsail automated snapshots enabled

---

## Before Production Deployment (ECS)

- [ ] All existing manually-provisioned resources imported into CloudFormation (VPC, RDS, S3)
- [ ] All 7 CloudFormation stacks deployed and tested in staging
- [ ] ALB idle timeout confirmed at 300s
- [ ] RDS Proxy configured for connection pooling (or PgBouncer sidecar deployed)
- [ ] `maxmemory-policy noeviction` confirmed on ElastiCache
- [ ] Alembic migration one-off ECS task tested with `--check` flag
- [ ] ECS service autoscaling tested (manually push 50+ jobs, verify workers scale)
- [ ] CloudWatch alarms configured for all critical metrics
- [ ] Slack/email alert routing confirmed (test alarm)
- [ ] OpenAI spend alarm configured (CloudWatch custom metric via Lambda)
- [ ] AWS WAF configured on CloudFront with at minimum: rate limiting (1000 req/5min per IP)
- [ ] Blue/green deployment tested (switch ALB target groups, verify 0 dropped connections)
- [ ] Disaster recovery runbook written and tested: RDS point-in-time restore (target: 1 hour RTO)
- [ ] Per-user quotas enforced (document count, daily query count, monthly token usage)
- [ ] Email verification working in production
- [ ] Load test with Locust: 50 concurrent users, verify no 5xx errors under load (T-63)
- [ ] Production smoke test passes (T-79)
- [ ] Secrets rotation procedure documented and tested for all 4 secrets

---

## Architectural Decision Records

### ADR-001: pgvector over FAISS

**Decision:** Use PostgreSQL pgvector extension instead of FAISS + EFS for vector similarity search.

**Context:** FAISS requires a persistent shared filesystem (EFS) across multiple ECS tasks, introduces file locking complexity, adds EFS cost, and has failure modes (index corruption, memory pressure) that are difficult to debug in production.

**Consequences:** Eliminates EFS, filelock dependency, faiss_manager.py complexity, and all concurrent write hazards. Adds a `vector(1536)` column to the chunks table. Query performance is equivalent to FAISS at MVP scale (<100K chunks per user). When pgvector P95 query latency exceeds 200ms under load, migrate to Pinecone using the same interface.

**Status:** Recommended. Implement before T-34.

---

### ADR-002: Lightsail First, ECS Later

**Decision:** Deploy the initial working product on Lightsail before ECS.

**Context:** ECS + Fargate + ALB + NAT Gateway adds ~$100+/month in fixed costs and significant operational complexity. A solo developer needs fast feedback loops and low debugging overhead.

**Consequences:** First deployment is on Lightsail with Docker Compose. ECS migration is triggered by traffic/scaling needs or paying users. Lightsail deployment is a subset of the production architecture, not a throwaway prototype.

**Status:** Recommended. Revise build plan task sequencing accordingly.

---

### ADR-003: Redis Dual-Use Strategy

**Decision:** Continue using ElastiCache Redis for both job queue (RQ) and session storage (refresh tokens), but enforce database separation and correct eviction policy.

**Context:** Splitting into two Redis instances doubles ElastiCache cost. The dual-use risk is manageable with explicit namespacing.

**Consequences:** Set `maxmemory-policy: noeviction` on the ElastiCache cluster. Use `SELECT 0` (or key prefix `token:`) for refresh tokens and `queue:` prefix namespace for RQ. Document that an ElastiCache outage is a total service outage. Add ElastiCache to the health check endpoint.

**Status:** Accept with mitigations. Re-evaluate if queue depth > 10,000 jobs/hour sustained.

---

> **Document maintained by:** Solo Developer
> **Review cadence:** Before each stage migration
> **Next review trigger:** Before Lightsail deployment
