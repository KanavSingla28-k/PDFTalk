#!/usr/bin/env python3
"""
backend/scripts/daily_quota_report.py

Standalone cron script — runs outside uvicorn, imports Settings directly.
Scans all quota:tokens:*:TODAY keys in Redis, posts a Slack alert for any
user whose usage has crossed the 80% warn or 100% alert threshold.

Usage:
    python -m scripts.daily_quota_report

Crontab (run from backend/ directory, once per day at 08:00):
    0 8 * * * cd /opt/pdftalk/backend && .venv/bin/python -m scripts.daily_quota_report >> /var/log/pdftalk-quota-report.log 2>&1

Environment:
    Reads from .env.local by default. Set ENV_FILE to override:
        ENV_FILE=.env.docker python -m scripts.daily_quota_report
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.core.config import settings

# ---------------------------------------------------------------------------
# Bootstrap — resolve project root so imports work when run as a module
# ---------------------------------------------------------------------------

# backend/scripts/daily_quota_report.py → backend/ is two levels up from __file__
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

WARN_THRESHOLD = 0.80  # 80%  → warning
ALERT_THRESHOLD = 1.00  # 100% → alert (quota hit)


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------


async def _get_redis() -> aioredis.Redis:
    """Create a fresh Redis connection for the script."""
    return await aioredis.from_url(  # type: ignore[no-any-return]
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
    )


async def _scan_token_quota_keys(r: aioredis.Redis, date_str: str) -> list[str]:
    """
    Return all quota:tokens:*:{date_str} keys present in Redis.
    Uses SCAN (not KEYS) to avoid blocking the server.
    """
    pattern = f"quota:tokens:*:{date_str}"
    keys: list[str] = []
    async for key in r.scan_iter(pattern, count=100):
        keys.append(key)
    return keys


async def _scan_query_quota_keys(r: aioredis.Redis, date_str: str) -> list[str]:
    pattern = f"quota:queries:*:{date_str}"
    keys: list[str] = []
    async for key in r.scan_iter(pattern, count=100):
        keys.append(key)
    return keys


# ---------------------------------------------------------------------------
# Slack helper
# ---------------------------------------------------------------------------


async def _post_slack(client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
    """POST a message payload to the configured Slack webhook URL."""
    if not settings.SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL is not set — skipping Slack notification.")
        return

    try:
        resp = await client.post(
            settings.SLACK_WEBHOOK_URL,
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        # Never crash the whole script over a failed Slack call
        logger.error("Failed to post Slack alert: %s", exc)


def _build_slack_payload(
    level: str,  # "WARNING" or "ALERT"
    quota_type: str,  # "token" or "query"
    user_id: str,
    used: int,
    limit: int,
    pct: float,
) -> dict[str, Any]:
    """Build a simple Slack Block Kit message."""
    emoji = ":warning:" if level == "WARNING" else ":rotating_light:"
    color = "#FFA500" if level == "WARNING" else "#FF0000"
    type_label = "Token" if quota_type == "token" else "Query"

    text = (
        f"{emoji} *{level}: {type_label} quota {pct:.0%}* for user `{user_id}`\n"
        f"Used: {used:,} / {limit:,}"
    )

    return {
        "attachments": [
            {
                "color": color,
                "text": text,
                "footer": f"PDFTalk · {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            }
        ]
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run_report() -> None:
    today = datetime.now(UTC).strftime("%Y%m%d")
    logger.info("Starting daily quota report for %s", today)

    r = await _get_redis()

    token_keys = await _scan_token_quota_keys(r, today)
    query_keys = await _scan_query_quota_keys(r, today)

    logger.info(
        "Found %d token quota keys and %d query quota keys",
        len(token_keys),
        len(query_keys),
    )

    alerts: list[dict[str, Any]] = []

    # ---- Token quota -------------------------------------------------------
    for key in token_keys:
        # key format: quota:tokens:{user_id}:{date}
        parts = key.split(":")
        if len(parts) != 4:
            logger.warning("Unexpected key format, skipping: %s", key)
            continue
        user_id = parts[2]

        raw = await r.get(key)
        if raw is None:
            continue
        used = int(raw)
        limit = settings.MAX_DAILY_TOKENS_PER_USER
        pct = used / limit

        if pct >= ALERT_THRESHOLD:
            logger.error(
                "ALERT  token quota: user=%s used=%d limit=%d (%.0f%%)",
                user_id,
                used,
                limit,
                pct * 100,
            )
            alerts.append(_build_slack_payload("ALERT", "token", user_id, used, limit, pct))
        elif pct >= WARN_THRESHOLD:
            logger.warning(
                "WARN   token quota: user=%s used=%d limit=%d (%.0f%%)",
                user_id,
                used,
                limit,
                pct * 100,
            )
            alerts.append(_build_slack_payload("WARNING", "token", user_id, used, limit, pct))
        else:
            logger.info(
                "OK     token quota: user=%s used=%d limit=%d (%.0f%%)",
                user_id,
                used,
                limit,
                pct * 100,
            )

    # ---- Query quota -------------------------------------------------------
    for key in query_keys:
        # key format: quota:queries:{user_id}:{date}
        parts = key.split(":")
        if len(parts) != 4:
            logger.warning("Unexpected key format, skipping: %s", key)
            continue
        user_id = parts[2]

        raw = await r.get(key)
        if raw is None:
            continue
        used = int(raw)
        limit = settings.MAX_DAILY_QUERIES_PER_USER
        pct = used / limit

        if pct >= ALERT_THRESHOLD:
            logger.error(
                "ALERT  query quota: user=%s used=%d limit=%d (%.0f%%)",
                user_id,
                used,
                limit,
                pct * 100,
            )
            alerts.append(_build_slack_payload("ALERT", "query", user_id, used, limit, pct))
        elif pct >= WARN_THRESHOLD:
            logger.warning(
                "WARN   query quota: user=%s used=%d limit=%d (%.0f%%)",
                user_id,
                used,
                limit,
                pct * 100,
            )
            alerts.append(_build_slack_payload("WARNING", "query", user_id, used, limit, pct))
        else:
            logger.info(
                "OK     query quota: user=%s used=%d limit=%d (%.0f%%)",
                user_id,
                used,
                limit,
                pct * 100,
            )

    await r.aclose()

    # ---- Post alerts -------------------------------------------------------
    if not alerts:
        logger.info("No quota thresholds breached. Nothing to post to Slack.")
        return

    logger.info("Posting %d alert(s) to Slack.", len(alerts))
    async with httpx.AsyncClient() as client:
        for payload in alerts:
            await _post_slack(client, payload)

    logger.info("Daily quota report complete.")


if __name__ == "__main__":
    asyncio.run(run_report())
