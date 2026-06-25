#!/usr/bin/env bash
# infra/scripts/remote_deploy.sh
#
# Runs ON the Lightsail instance. Invoked by .github/workflows/deploy.yml via
# ssh ... bash -s < remote_deploy.sh with GIT_SHA, GH_REPO, GITHUB_TOKEN,
# and GITHUB_ACTOR exported as real environment variables on the SSH command
# line (not interpolated into a heredoc string). This avoids the multi-layer
# quoting/escaping that previously caused silent truncation when this logic
# lived inline inside an unquoted heredoc in the workflow file.
set -euo pipefail
set -x

trap 'echo "MARKER:TRAP_EXIT code=$? line=$LINENO"' EXIT

: "${GIT_SHA:?GIT_SHA must be set}"
: "${GH_REPO:?GH_REPO must be set}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN must be set}"
: "${GITHUB_ACTOR:?GITHUB_ACTOR must be set}"

cd /opt/pdftalk

echo "MARKER:START"

echo "==> Logging into GHCR"
set +x
echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
set -x
echo "MARKER:LOGIN_DONE"

echo "==> Pruning old images and builder cache to free up space"
docker system prune -af --volumes || true
echo "MARKER:PRUNE_DONE"

echo "==> Pulling Docker images (SHA: $GIT_SHA)"
docker compose pull api worker frontend \
  || { echo "ERROR: docker compose pull failed — aborting deploy"; exit 1; }
echo "MARKER:PULL_DONE"

echo "==> Backing up database"
# POSTGRES_USER / POSTGRES_DB live inside the postgres container's own
# environment, set via the environment block for that service in
# docker-compose.yml, so they only need to be expanded by the innermost
# sh -c running inside the container -- never by this script's shell. Single-quoting the
# whole sh -c argument is sufficient and correct here because this script is
# no longer passed through a heredoc; there is only one layer of shell left
# to defer past.
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c -f "/var/lib/postgresql/data/backup_'"$GIT_SHA"'.dump"' \
  || { echo "ERROR: pg_dump backup failed — aborting deploy"; exit 1; }
echo "MARKER:PGDUMP_DONE"

docker compose exec -T postgres sh -c "find /var/lib/postgresql/data -name 'backup_*.dump' -mtime +7 -delete" \
  || echo "WARNING: backup cleanup failed — continuing deploy"
echo "MARKER:BACKUP_CLEANUP_DONE"

echo "==> Running DB migrations"
docker compose run -T --rm --no-deps api alembic upgrade head \
  || { echo "ERROR: alembic migration failed — aborting deploy"; exit 1; }
echo "MARKER:MIGRATIONS_DONE"

echo "==> Fixing prometheus_multiproc volume permissions (B-1 fix for existing volume)"
docker compose run -T --rm --no-deps --user root api chown -R appuser:appuser /tmp/prometheus_multiproc \
  || { echo "ERROR: prometheus_multiproc permission fix failed — aborting deploy"; exit 1; }
echo "MARKER:PERMFIX_DONE"

echo "==> Restarting API, worker, and frontend"
docker compose up -d --no-deps --force-recreate api worker frontend \
  || { echo "ERROR: container recreate failed — aborting deploy"; exit 1; }
echo "MARKER:RECREATE_DONE"

echo "==> Reloading nginx (picks up any config changes)"
docker compose exec -T nginx nginx -s reload || docker compose up -d --no-deps nginx
echo "MARKER:NGINX_RELOAD_DONE"

echo "==> Verifying frontend container is on the expected SHA"
RUNNING_IMAGE=$(docker inspect pdftalk-frontend-prod --format '{{.Config.Image}}')
echo "Running frontend image: $RUNNING_IMAGE"
case "$RUNNING_IMAGE" in
  *"$GIT_SHA"*)
    echo "OK: frontend container is running the expected SHA ($GIT_SHA)"
    ;;
  *)
    echo "ERROR: frontend container image ($RUNNING_IMAGE) does not match expected SHA ($GIT_SHA) — aborting deploy"
    exit 1
    ;;
esac

echo "==> Deploy complete"
echo "MARKER:DEPLOY_COMPLETE"
trap - EXIT
