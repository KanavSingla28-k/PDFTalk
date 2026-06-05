"""
Email transport layer. Wraps the Resend SDK.

All outbound emails go through this module. If you ever swap providers
(e.g. AWS SES, Postmark), change only this file — callers are unchanged.

Usage:
    await send_verification_email(
        to_email="user@example.com",
        verification_url="https://pdftalk.com/verify-email?token=...",
    )
"""

import asyncio
from functools import partial

import resend
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

# Initialise Resend with the API key once at import time.
# The SDK uses this globally — no per-call auth needed.
resend.api_key = settings.RESEND_API_KEY

# ── Sender identity ───────────────────────────────────────────────────────────
# Must match a verified domain in your Resend dashboard.
# For local dev you can use Resend's sandbox: onboarding@resend.dev
SENDER = "PDFTalk <noreply@pdftalk.com>"


# ── Public API ────────────────────────────────────────────────────────────────


async def send_verification_email(to_email: str, verification_url: str) -> None:
    """
    Send an account verification email to the given address.

    Args:
        to_email:         The recipient's email address.
        verification_url: The fully-qualified URL the user must click to verify.
                          e.g. "https://pdftalk.com/verify-email?token=abc123"

    Raises:
        RuntimeError: If Resend returns an error. The caller (registration
                      endpoint) should catch this and return 500 — the user
                      row is already created, so they can request a resend.
    """
    html_body = _build_verification_html(verification_url)
    text_body = _build_verification_text(verification_url)

    params: resend.Emails.SendParams = {
        "from": SENDER,
        "to": [to_email],
        "subject": "Verify your PDFTalk account",
        "html": html_body,
        "text": text_body,
    }

    try:
        # Resend's Python SDK is synchronous. Run it in a thread pool so we
        # don't block the asyncio event loop during the HTTP round-trip.
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, partial(resend.Emails.send, params))
        log.info("verification_email_sent", to=to_email, resend_id=response.get("id"))
    except Exception as exc:
        # Log the full error but don't expose provider details to callers.
        log.error("verification_email_failed", to=to_email, error=str(exc))
        raise RuntimeError("Failed to send verification email") from exc


# ── Email templates ───────────────────────────────────────────────────────────


def _build_verification_html(verification_url: str) -> str:
    """Minimal, readable HTML email. No external images or tracking pixels."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Verify your PDFTalk account</title>
</head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:system-ui,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:40px 0;">
    <tr>
      <td align="center">
        <table width="480" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:8px;
                      border:1px solid #e5e7eb;padding:40px;">
          <tr>
            <td>
              <h1 style="margin:0 0 8px;font-size:22px;color:#111827;">
                Welcome to PDFTalk
              </h1>
              <p style="margin:0 0 24px;font-size:15px;color:#4b5563;line-height:1.6;">
                Click the button below to verify your email address.
                This link expires in <strong>24 hours</strong>.
              </p>
              <a href="{verification_url}"
                 style="display:inline-block;padding:12px 24px;
                        background:#2563eb;color:#ffffff;
                        text-decoration:none;border-radius:6px;
                        font-size:15px;font-weight:600;">
                Verify email address
              </a>
              <p style="margin:32px 0 0;font-size:13px;color:#9ca3af;">
                If you didn't create a PDFTalk account, you can safely ignore this email.
              </p>
              <hr style="margin:24px 0;border:none;border-top:1px solid #e5e7eb;" />
              <p style="margin:0;font-size:12px;color:#9ca3af;">
                Or copy this link into your browser:<br/>
                <span style="color:#4b5563;word-break:break-all;">{verification_url}</span>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
""".strip()


def _build_verification_text(verification_url: str) -> str:
    """Plain-text fallback for email clients that don't render HTML."""
    return (
        "Welcome to PDFTalk\n\n"
        "Click the link below to verify your email address.\n"
        "This link expires in 24 hours.\n\n"
        f"{verification_url}\n\n"
        "If you didn't create a PDFTalk account, you can safely ignore this email."
    )
