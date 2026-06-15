#!/usr/bin/env python3
"""
backend/scripts/cleanup_s3_orphans.py

Standalone cron script — reconciles the S3 bucket with the Document table.
Deletes any objects in S3 that do not exist in the database, provided they are
older than 1 hour (to avoid deleting objects currently being uploaded).

Usage:
    python -m scripts.cleanup_s3_orphans

Crontab (run from backend/ directory, e.g., daily at 02:00):
    0 2 * * * cd /opt/pdftalk/backend && .venv/bin/python -m scripts.cleanup_s3_orphans >> /var/log/pdftalk-cleanup.log 2>&1
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.document import Document
from app.utils.s3_client import s3_client

# Bootstrap — resolve project root so imports work when run as a module
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Buffer period: don't delete objects uploaded within this time frame
# to prevent deleting files mid-upload before the DB transaction commits.
BUFFER_PERIOD = timedelta(hours=1)


async def get_valid_s3_keys() -> set[str]:
    """Retrieve all known s3_keys from the database."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Document.s3_key))
        return {row[0] for row in result.all()}


async def run_cleanup() -> None:
    logger.info("Starting S3 orphan cleanup job.")

    # 1. Get source of truth from DB
    try:
        valid_keys = await get_valid_s3_keys()
        logger.info("Fetched %d valid document keys from the database.", len(valid_keys))
    except Exception as exc:
        logger.error(
            "Failed to fetch documents from database. Aborting cleanup to prevent accidental deletion. Error: %s",
            exc,
        )
        return

    # 2. Iterate S3 objects using the underlying boto3 client
    paginator = s3_client._client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=settings.S3_BUCKET_NAME)

    now = datetime.now(timezone.utc)
    orphans_deleted = 0
    errors = 0

    try:
        for page in pages:
            if "Contents" not in page:
                continue

            for obj in page["Contents"]:
                key = obj["Key"]
                last_modified = obj["LastModified"]  # timezone aware datetime

                # If the key is tracked in the DB, it's safe
                if key in valid_keys:
                    continue

                # It's not in the DB. Is it older than our safety buffer?
                if now - last_modified > BUFFER_PERIOD:
                    logger.info(
                        "Deleting orphaned object: %s (LastModified: %s)", key, last_modified
                    )
                    try:
                        s3_client.delete_object(s3_key=key)
                        orphans_deleted += 1
                    except Exception as exc:
                        logger.error("Failed to delete object %s: %s", key, exc)
                        errors += 1
                else:
                    logger.debug(
                        "Skipping untracked object %s (too new, might be an active upload)", key
                    )

    except Exception as exc:
        logger.error("Failed to list objects from S3: %s", exc)
        return

    logger.info(
        "S3 orphan cleanup complete. Deleted: %d, Errors: %d", orphans_deleted, errors
    )


if __name__ == "__main__":
    asyncio.run(run_cleanup())
