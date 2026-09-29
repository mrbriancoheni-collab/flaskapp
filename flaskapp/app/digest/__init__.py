# app/digest/__init__.py
"""
Daily Health Digest — sends a morning SMS/email summary to the business owner.

Routes:
  GET  /account/digest          — preview today's digest
  GET  /account/digest/settings — redirect to marketing notification settings
  POST /account/digest/send     — manually trigger a digest send (admin/test)
  POST /internal/digest/send-all — internal cron endpoint (send to all accounts)
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any, Dict, Optional

from flask import (
    Blueprint, jsonify, redirect, render_template,
    request, session, url_for,
)
from sqlalchemy import text

from app import db

log = logging.getLogger(__name__)

digest_bp = Blueprint("digest_bp", __name__, url_prefix="/account/digest")


# ── Auth ───────────────────────────────────────────────────────────────────────

def _account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        row = db.session.execute(
            text("SELECT account_id FROM users WHERE id=:id"), {"id": uid}
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not _account_id():
            return redirect(url_for("auth_bp.login", next=request.path))
        return f(*a, **kw)
    return wrapper


# ── Digest data assembly ───────────────────────────────────────────────────────

def _build_digest(aid: int, for_date: date = None) -> Dict[str, Any]:
    """Assemble yesterday's metrics for the daily digest."""
    today = for_date or date.today()
    yesterday_start = str(today - timedelta(days=1)) + " 00:00:00"
    yesterday_end   = str(today - timedelta(days=1)) + " 23:59:59"
    week_start      = str(today - timedelta(days=7)) + " 00:00:00"

    data: Dict[str, Any] = {
        "date": (today - timedelta(days=1)).strftime("%A, %B %-d"),
        "leads_yesterday": 0,
        "leads_week": 0,
        "missed_calls": 0,
        "revenue_yesterday": 0,
        "revenue_week": 0,
        "unanswered_reviews": 0,
        "google_cpl": None,
        "top_channel": None,
        "pacing_alerts": [],
        "renewing_agreements": 0,
    }

    # Leads yesterday
    try:
        row = db.session.execute(text("""
            SELECT COUNT(*) FROM lead_ingest
            WHERE account_id=:a AND created_at BETWEEN :s AND :e
        """), {"a": aid, "s": yesterday_start, "e": yesterday_end}).scalar()
        data["leads_yesterday"] = int(row or 0)
    except Exception:
        pass

    # Leads this week
    try:
        row = db.session.execute(text("""
            SELECT COUNT(*) FROM lead_ingest
            WHERE account_id=:a AND created_at >= :s
        """), {"a": aid, "s": week_start}).scalar()
        data["leads_week"] = int(row or 0)
    except Exception:
        pass

    # Missed calls yesterday
    try:
        row = db.session.execute(text("""
            SELECT COUNT(*) FROM call_events
            WHERE account_id=:a AND call_status IN ('no-answer','busy','failed')
              AND call_started_at BETWEEN :s AND :e
        """), {"a": aid, "s": yesterday_start, "e": yesterday_end}).scalar()
        data["missed_calls"] = int(row or 0)
    except Exception:
        pass

    # Revenue yesterday (ServiceTitan)
    try:
        row = db.session.execute(text("""
            SELECT COALESCE(SUM(total), 0)
            FROM servicetitan_jobs
            WHERE account_id=:a AND completed_on BETWEEN :s AND :e
              AND status IN ('Completed','Done')
        """), {"a": aid, "s": yesterday_start[:10], "e": yesterday_end[:10]}).scalar()
        data["revenue_yesterday"] = float(row or 0)

        row2 = db.session.execute(text("""
            SELECT COALESCE(SUM(total), 0)
            FROM servicetitan_jobs
            WHERE account_id=:a AND completed_on >= :s
              AND status IN ('Completed','Done')
        """), {"a": aid, "s": week_start[:10]}).scalar()
        data["revenue_week"] = float(row2 or 0)
    except Exception:
        pass

    # Unanswered reviews
    try:
        row = db.session.execute(text("""
            SELECT COUNT(*) FROM gmb_reviews
            WHERE account_id=:a AND (response IS NULL OR response='')
        """), {"a": aid}).scalar()
        data["unanswered_reviews"] = int(row or 0)
    except Exception:
        pass

    # Google Ads CPL (last 7 days)
    try:
        spend = db.session.execute(text("""
            SELECT COALESCE(SUM(amount), 0) FROM ad_spend
            WHERE account_id=:a AND source='google_ads' AND spend_date >= :s
        """), {"a": aid, "s": (today - timedelta(days=7)).isoformat()}).scalar() or 0
        leads = db.session.execute(text("""
            SELECT COUNT(*) FROM lead_ingest
            WHERE account_id=:a AND source='google_ads' AND created_at >= :s
        """), {"a": aid, "s": week_start}).scalar() or 0
        if spend and leads:
            data["google_cpl"] = round(float(spend) / int(leads), 0)
    except Exception:
        pass

    # Budget pacing alerts (channels overpacing by > 20%)
    try:
        today_obj = today
        month_start = today_obj.replace(day=1)
        from calendar import monthrange
        _, days_in_month = monthrange(today_obj.year, today_obj.month)
        expected_pct = today_obj.day / days_in_month

        budgets = db.session.execute(text("""
            SELECT b.channel, b.budget_cents,
                   COALESCE(SUM(s.amount), 0) as spent
            FROM channel_monthly_budgets b
            LEFT JOIN ad_spend s ON s.account_id=b.account_id
              AND s.source=b.channel AND s.spend_date >= :ms
            WHERE b.account_id=:a AND b.budget_month=:m
            GROUP BY b.channel, b.budget_cents
        """), {"a": aid, "m": month_start.isoformat(), "ms": month_start.isoformat()}).fetchall()

        for r in budgets:
            budget = float(r[1] or 0) / 100.0
            spent = float(r[2] or 0)
            if budget > 0:
                expected = budget * expected_pct
                if expected > 0 and spent / expected > 1.2:
                    data["pacing_alerts"].append({
                        "channel": r[0],
                        "spent": spent,
                        "budget": budget,
                        "pace_pct": round(spent / expected * 100),
                    })
    except Exception:
        pass

    # Agreements renewing in 7 days
    try:
        row = db.session.execute(text("""
            SELECT COUNT(*) FROM service_agreements
            WHERE account_id=:a AND status='active'
              AND renewal_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 7 DAY)
        """), {"a": aid}).scalar()
        data["renewing_agreements"] = int(row or 0)
    except Exception:
        pass

    return data


def _format_sms_digest(data: Dict[str, Any], business_name: str = "Your business") -> str:
    """Format digest as a short SMS (160 chars max per segment)."""
    lines = [f"📊 {data['date']} digest for {business_name}:"]
    lines.append(f"Leads: {data['leads_yesterday']} yesterday • {data['leads_week']} this week")
    if data["revenue_yesterday"] > 0:
        lines.append(f"Revenue: ${data['revenue_yesterday']:,.0f} yesterday")
    if data["missed_calls"] > 0:
        lines.append(f"⚠️ {data['missed_calls']} missed call(s)")
    if data["unanswered_reviews"] > 0:
        lines.append(f"⭐ {data['unanswered_reviews']} review(s) need reply")
    if data["pacing_alerts"]:
        top = data["pacing_alerts"][0]
        lines.append(f"🔴 {top['channel']} at {top['pace_pct']}% of budget pace")
    if data["renewing_agreements"] > 0:
        lines.append(f"📋 {data['renewing_agreements']} agreement(s) renew this week")
    return "\n".join(lines)


def _send_digest_to_account(aid: int) -> bool:
    """Send the daily digest to an account via SMS and/or email."""
    try:
        settings = db.session.execute(text("""
            SELECT daily_digest_enabled, daily_digest_channel, daily_digest_phone,
                   daily_digest_email
            FROM account_notification_settings WHERE account_id=:a
        """), {"a": aid}).fetchone()
        if not settings or not settings[0]:
            return False

        channel = settings[1] or "sms"
        phone = settings[2]
        email = settings[3]

        # Get business name
        try:
            bp = db.session.execute(text(
                "SELECT business_name FROM business_profiles WHERE account_id=:a LIMIT 1"
            ), {"a": aid}).fetchone()
            biz_name = bp[0] if bp else "Your business"
        except Exception:
            biz_name = "Your business"

        data = _build_digest(aid)
        today = date.today()
        today_str = today.isoformat()

        # Send SMS
        if channel in ("sms", "both") and phone:
            import requests as req
            sid = os.getenv("TWILIO_ACCOUNT_SID")
            tok = os.getenv("TWILIO_AUTH_TOKEN")
            from_num = os.getenv("TWILIO_FROM_NUMBER")
            body = _format_sms_digest(data, biz_name)
            if sid and tok and from_num:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
                req.post(url, data={"From": from_num, "To": phone, "Body": body},
                         auth=(sid, tok), timeout=10)
                log.info("Digest SMS sent to account %d (%s)", aid, phone)
            else:
                log.info("Simulated digest SMS to %s:\n%s", phone, body)

            # Log send
            try:
                db.session.execute(text("""
                    INSERT IGNORE INTO digest_send_log (account_id, digest_date, channel, recipient)
                    VALUES (:a, :dt, 'sms', :r)
                """), {"a": aid, "dt": today_str, "r": phone})
                db.session.commit()
            except Exception:
                pass

        return True
    except Exception:
        log.exception("Failed to send digest to account %d", aid)
        return False


# ── Routes ─────────────────────────────────────────────────────────────────────

@digest_bp.get("/")
@login_required
def preview():
    """Preview today's digest."""
    aid = _account_id()
    data = _build_digest(aid)
    try:
        settings = db.session.execute(text("""
            SELECT daily_digest_enabled, daily_digest_channel, daily_digest_phone,
                   daily_digest_email, daily_digest_hour
            FROM account_notification_settings WHERE account_id=:a
        """), {"a": aid}).fetchone()
        s = dict(settings._mapping) if settings else {}
    except Exception:
        s = {}
    return render_template("digest/preview.html", data=data, settings=s)


@digest_bp.post("/send")
@login_required
def send_manual():
    """Manually trigger a digest send for the current account."""
    aid = _account_id()
    success = _send_digest_to_account(aid)
    if success:
        return jsonify({"ok": True, "message": "Digest sent."})
    return jsonify({"ok": False, "message": "Digest not configured or send failed."}), 400


@digest_bp.post("/internal/send-all")
def send_all():
    """
    Internal cron endpoint — sends digests to all eligible accounts.
    Protected by a shared secret (DIGEST_CRON_SECRET env var).
    """
    secret = request.headers.get("X-Cron-Secret", "")
    expected = os.getenv("DIGEST_CRON_SECRET", "")
    if not expected or secret != expected:
        return jsonify({"error": "unauthorized"}), 401

    current_hour = datetime.utcnow().hour
    try:
        accounts = db.session.execute(text("""
            SELECT account_id FROM account_notification_settings
            WHERE daily_digest_enabled=1 AND daily_digest_hour=:h
        """), {"h": current_hour}).fetchall()
    except Exception:
        accounts = []

    sent = 0
    for row in accounts:
        if _send_digest_to_account(row[0]):
            sent += 1

    log.info("Digest cron: sent %d/%d digests", sent, len(accounts))
    return jsonify({"ok": True, "sent": sent, "total": len(accounts)})
