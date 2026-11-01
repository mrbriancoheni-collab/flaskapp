"""Twilio SMS — fire-and-forget, never raises."""
import logging
import os

log = logging.getLogger(__name__)


def send_sms(to: str, body: str) -> bool:
    """Send an SMS via Twilio. Returns True on success."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token  = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_number = os.getenv("TWILIO_FROM_NUMBER", "")
    if not (account_sid and auth_token and from_number and to):
        log.debug("SMS not configured or no recipient; skipping")
        return False
    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        client.messages.create(body=body[:1600], from_=from_number, to=to)
        log.info("SMS sent to %s", to[:6] + "****")
        return True
    except Exception as e:
        log.warning("SMS send failed: %s", e)
        return False


def notify_action_ready(account_id: int, action_title: str, count: int = 1) -> None:
    """Notify account owner when AI actions need approval."""
    try:
        from sqlalchemy import text
        from app import db
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT phone FROM accounts WHERE id = :aid"),
                {"aid": account_id},
            ).fetchone()
        if not row or not row[0]:
            return
        body = (
            f"RevForge: {count} action{'s' if count > 1 else ''} ready for your review.\n"
            f"Latest: {action_title[:80]}\n"
            f"Approve at getrevforge.io/account/actions"
        )
        send_sms(row[0], body)
    except Exception as e:
        log.warning("notify_action_ready failed: %s", e)


def notify_cpl_spike(account_id: int, trade: str, current_cpl: float, avg_cpl: float) -> None:
    """Alert when CPL spikes >40% above recent average."""
    try:
        from sqlalchemy import text
        from app import db
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT phone FROM accounts WHERE id = :aid"),
                {"aid": account_id},
            ).fetchone()
        if not row or not row[0]:
            return
        pct = int(((current_cpl - avg_cpl) / avg_cpl) * 100) if avg_cpl > 0 else 0
        body = (
            f"RevForge Alert: Your {trade} CPL spiked {pct}%"
            f" (${current_cpl:.0f} vs ${avg_cpl:.0f} avg).\n"
            f"Check your campaigns: getrevforge.io/account/performance"
        )
        send_sms(row[0], body)
    except Exception as e:
        log.warning("notify_cpl_spike failed: %s", e)
