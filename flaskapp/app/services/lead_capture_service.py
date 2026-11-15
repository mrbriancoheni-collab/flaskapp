"""Fire-and-forget lead capture from free tools. Never raises."""
import hashlib
import logging

from app import db

log = logging.getLogger(__name__)


def save_lead(email, tool_name=None, detected_trade=None, service_area=None,
              result_summary=None, source='free_tool', ip=None):
    try:
        from sqlalchemy import text
        ip_hash = hashlib.sha256((ip or '').encode()).hexdigest()[:32] if ip else None
        with db.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO captured_leads
                  (email, tool_name, detected_trade, service_area, result_summary, source, ip_hash)
                VALUES (:email, :tool, :trade, :area, :summary, :source, :ip)
            """), {
                "email":   email[:254],
                "tool":    (tool_name or "")[:100] or None,
                "trade":   (detected_trade or "")[:100] or None,
                "area":    (service_area or "")[:200] or None,
                "summary": (result_summary or "")[:500] or None,
                "source":  (source or "free_tool")[:100],
                "ip":      ip_hash,
            })
        try:
            from app.services.event_tracker import log_event
            log_event(
                "lead_capture",
                event_source="free_tool",
                tool_name=tool_name,
                detected_trade=detected_trade,
                properties={"email_domain": email.split("@")[-1] if "@" in email else ""},
            )
        except Exception:
            pass
    except Exception as e:
        log.warning("save_lead failed: %s", e)
