#!/usr/bin/env bash
set -euo pipefail

cd /opt/pdftalk

echo "==> Starting database backup"

# We assume POSTGRES_USER and POSTGRES_DB are available inside the container.
# If not, they default to pdftalk.
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILENAME="backup_${TIMESTAMP}.dump.gz"

echo "Running pg_dump..."
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c | gzip > "/var/lib/postgresql/data/'"$BACKUP_FILENAME"'"' < /dev/null

echo "Cleaning up local backups older than 7 days..."
docker compose exec -T postgres sh -c "find /var/lib/postgresql/data -name 'backup_*.dump.gz' -mtime +7 -delete" < /dev/null

# T-62 S3 upload placeholder
# echo "Uploading to S3..."
# aws s3 cp "/var/lib/postgresql/data/$BACKUP_FILENAME" s3://YOUR_S3_BUCKET_NAME/

echo "==> Backup successful, updating textfile metric"
TEXTFILE_DIR="/opt/pdftalk/textfile_collector"
mkdir -p "$TEXTFILE_DIR"

echo "pdftalk_last_backup_success_timestamp $(date +%s)" > "$TEXTFILE_DIR/backup.prom.tmp"
mv "$TEXTFILE_DIR/backup.prom.tmp" "$TEXTFILE_DIR/backup.prom"

echo "==> Done"
