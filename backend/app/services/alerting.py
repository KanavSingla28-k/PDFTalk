"""
app/services/alerting.py

Receives fired Prometheus alerts from Alertmanager and dispatches
notifications to Resend (email) and Slack.

Called from POST /internal/alerts/webhook via asyncio.create_task()
so the webhook response is immediate and dispatch is fire-and-forget.
"""

import structlog
from typing import Any

import httpx
import resend

from app.core.config import settings

log = structlog.get_logger(__name__)


async def dispatch_alert(payload: dict[str, Any]) -> None:
    """
    Process an Alertmanager webhook payload.
    Dispatches each alert to email (Resend) and Slack (webhook).
    Errors in either channel are logged and swallowed — a failed
    notification must never crash the API process.
    """
    alerts = payload.get("alerts", [])
    if not alerts:
        return

    for alert in alerts:
        name        = alert["labels"].get("alertname", "UnknownAlert")
        severity    = alert["labels"].get("severity", "unknown")
        summary     = alert["annotations"].get("summary", name)
        description = alert["annotations"].get("description", "")
        status      = alert["status"]  # "firing" | "resolved"
        emoji       = "🔴" if status == "firing" else "✅"

        subject = f"{emoji} [{severity.upper()}] {summary}"
        body    = f"{description}\n\nStatus: {status}\nAlert: {name}"

        await _send_email(subject, body, name)
        await _send_slack(emoji, subject, description, name)


async def _send_email(subject: str, body: str, alert_name: str) -> None:
    if not settings.ALERT_EMAIL_TO or not settings.RESEND_API_KEY:
        return
    try:
        resend.api_key = settings.RESEND_API_KEY
        if settings.EMAIL_FROM_DOMAIN and "<" in settings.EMAIL_FROM_DOMAIN and ">" in settings.EMAIL_FROM_DOMAIN:
            alert_sender = settings.EMAIL_FROM_DOMAIN
        else:
            alert_sender = f"PDFTalk Alerts <alerts@{settings.EMAIL_FROM_DOMAIN}>"
            
        resend.Emails.send({
            "from":    alert_sender,
            "to":      [settings.ALERT_EMAIL_TO],
            "subject": subject,
            "text":    body,
        })
    except Exception as e:
        log.warning("alert_email_failed", error=str(e), alert=alert_name)


async def _send_slack(emoji: str, subject: str, description: str, alert_name: str) -> None:
    if not settings.SLACK_WEBHOOK_URL:
        return
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
        log.warning("alert_slack_failed", error=str(e), alert=alert_name)
