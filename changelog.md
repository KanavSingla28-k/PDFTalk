# Changelog

All notable changes to PDFTalk are documented here.
Format: [Semantic Versioning](https://semver.org)

---

## [1.0.0] — 2026-06-14

### Added
- Full RAG pipeline: PDF upload → chunking → embedding → pgvector retrieval
- Streaming Q&A via SSE (gpt-4o-mini)
- Email verification + password reset auth flow
- Per-user document quota and daily token quota
- Docker Compose production deployment on AWS Lightsail
- GitHub Actions CI/CD pipeline with SSH deploy
- Automated PostgreSQL backups to S3
- Nginx with TLS 1.3, HSTS, rate limiting
