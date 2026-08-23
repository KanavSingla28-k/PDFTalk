# Infrastructure AGENTS.md

Context for infrastructure configurations (`infra/`).

## Purpose

Contains operational and deployment configurations for the PDFTalk stack.

## Nginx configuration (`nginx/nginx.prod.conf`)

- Functions as a reverse proxy for both `frontend` (port 3000) and `api` (port 8000).
- **HTTP / HTTPS**: Listens on 80 (redirects all traffic to 443 except ACME Let's Encrypt challenges) and 443.
- **Rate Limiting**:
  - Global API: 30 requests/second per IP.
  - Auth Endpoints (`/api/auth/*`): 5 requests/minute per IP (burst 3).
  - Upload Endpoints (`/api/documents/initiate-upload`, `/api/documents/confirm-upload`): 5 requests/minute per IP (burst 2).
- **Security Headers**: HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, and Permissions-Policy are all set by Nginx. Do NOT duplicate HSTS in the FastAPI middleware.
- **SSE Streaming**: For `/api/query/ask`, `proxy_buffering` and `proxy_cache` are turned `off`. This is critical for Server-Sent Events to work properly.
- **Internal Only**: Blocks public access to `/prometheus/`, `/api/metrics`, `/api/docs`, `/api/redoc`, and `/api/openapi.json` by returning a 404 (revealing nothing). The `/api/internal/alerts/` route is restricted to the internal Docker network.

## Related Context

- Root Architecture: `../AGENTS.md`
