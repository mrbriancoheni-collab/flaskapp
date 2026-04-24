# app/services/call_tracking_service.py
"""
Call Tracking Service.

Bridges Twilio call events with Google Ads campaign attribution to produce
real CPL (cost per lead) instead of the modeled/estimated value agents
previously used.

Key functions
-------------
record_call_event(account_id, payload)
    Persist a Twilio StatusCallback payload as a CallEvent.
    Automatically attributes the call to a campaign via the dialled
    tracking number.

get_call_metrics(account_id, days=30)
    Return a metrics dict suitable for dropping into agent context:
    {
        "total_calls":        int,
        "qualified_leads":    int,
        "real_cpl":           float,   # ad spend / qualified calls (None if no spend)
        "answer_rate":        float,   # 0–1
        "avg_duration_secs":  float,
        "by_campaign": [
            {"campaign_id": ..., "campaign_name": ..., "qualified_leads": ...,
             "spend_30d": ..., "real_cpl": ...},
            ...
        ]
    }

get_or_create_tracking_number(account_id, phone_number, **kwargs)
    Upsert a CallTrackingNumber entry.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

DEFAULT_QUALIFIED_SECS = 60   # calls longer than 60 s = qualified lead


# ── Record incoming call event ─────────────────────────────────────────────────

def record_call_event(account_id: int, payload: Dict[str, Any]) -> Optional[int]:
    """
    Persist a Twilio StatusCallback payload as a CallEvent.

    Returns the new CallEvent.id or None on failure.
    Idempotent — if call_sid already exists, silently returns the existing id.
    """
    from app import db
    from app.models_calls import CallEvent, CallTrackingNumber

    call_sid = payload.get("CallSid") or payload.get("call_sid", "")
    if not call_sid:
        log.warning("record_call_event: no CallSid in payload")
        return None

    # Idempotency: don't double-insert
    existing = CallEvent.query.filter_by(call_sid=call_sid).first()
    if existing:
        return existing.id

    to_number   = payload.get("To") or payload.get("Called", "")
    from_number = payload.get("From") or payload.get("Caller", "")
    status      = (payload.get("CallStatus") or "").lower()
    duration    = _int(payload.get("CallDuration") or payload.get("Duration", 0))

    # Attribution via tracking number
    tracking_num_obj: Optional[CallTrackingNumber] = None
    campaign_id   = None
    campaign_name = None
    if to_number:
        tracking_num_obj = CallTrackingNumber.query.filter_by(
            phone_number=to_number, is_active=True
        ).first()
        if tracking_num_obj:
            campaign_id   = tracking_num_obj.campaign_id
            campaign_name = tracking_num_obj.campaign_name

    # Qualified lead threshold
    threshold = DEFAULT_QUALIFIED_SECS
    if tracking_num_obj:
        threshold = tracking_num_obj.qualified_duration_secs or DEFAULT_QUALIFIED_SECS

    is_qualified = (status == "completed") and (duration >= threshold)

    # Timestamps
    started_at = _parse_twilio_ts(payload.get("StartTime"))
    ended_at   = _parse_twilio_ts(payload.get("EndTime"))

    event = CallEvent(
        account_id=account_id,
        call_sid=call_sid,
        parent_call_sid=payload.get("ParentCallSid"),
        from_number=from_number,
        to_number=to_number,
        tracking_number_id=tracking_num_obj.id if tracking_num_obj else None,
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        call_status=status,
        call_duration=duration,
        is_qualified_lead=is_qualified,
        caller_city=payload.get("CallerCity") or payload.get("FromCity"),
        caller_state=payload.get("CallerState") or payload.get("FromState"),
        caller_zip=payload.get("CallerZip") or payload.get("FromZip"),
        call_started_at=started_at,
        call_ended_at=ended_at,
        raw_payload=payload,
    )

    try:
        db.session.add(event)
        db.session.commit()
        log.info("CallEvent stored: sid=%s qualified=%s duration=%ds",
                 call_sid, is_qualified, duration)
        return event.id
    except Exception as exc:
        db.session.rollback()
        log.error("Failed to store CallEvent %s: %s", call_sid, exc)
        return None


# ── Metrics for agent context ──────────────────────────────────────────────────

def get_call_metrics(account_id: int, days: int = 30) -> Dict[str, Any]:
    """
    Aggregate call metrics for the last N days.

    Merges with gads_stats_daily to produce a real CPL where possible.
    """
    from app import db
    from app.models_calls import CallEvent
    from sqlalchemy import func

    since = datetime.utcnow() - timedelta(days=days)

    # Basic call aggregates
    rows = (
        db.session.query(
            CallEvent.campaign_id,
            CallEvent.campaign_name,
            func.count(CallEvent.id).label("total"),
            func.sum(
                db.case((CallEvent.is_qualified_lead == True, 1), else_=0)
            ).label("qualified"),
            func.sum(
                db.case((CallEvent.call_status == "completed", 1), else_=0)
            ).label("answered"),
            func.avg(CallEvent.call_duration).label("avg_duration"),
        )
        .filter(
            CallEvent.account_id == account_id,
            CallEvent.created_at >= since,
        )
        .group_by(CallEvent.campaign_id, CallEvent.campaign_name)
        .all()
    )

    total_calls     = sum(int(r.total or 0)     for r in rows)
    qualified_leads = sum(int(r.qualified or 0) for r in rows)
    answered        = sum(int(r.answered or 0)  for r in rows)
    answer_rate     = answered / total_calls if total_calls > 0 else 0
    avg_dur         = (
        sum(float(r.avg_duration or 0) * int(r.total or 0) for r in rows) / total_calls
        if total_calls > 0 else 0
    )

    # Spend per campaign from gads_stats_daily
    spend_by_campaign = _get_campaign_spend(account_id, days)

    # Account-level spend for overall CPL
    total_spend = sum(spend_by_campaign.values())
    real_cpl = round(total_spend / qualified_leads, 2) if qualified_leads > 0 else None

    by_campaign = []
    for r in rows:
        cid = r.campaign_id or ""
        spend = spend_by_campaign.get(cid, 0.0)
        q = int(r.qualified or 0)
        by_campaign.append({
            "campaign_id":    cid,
            "campaign_name":  r.campaign_name or "",
            "total_calls":    int(r.total or 0),
            "qualified_leads": q,
            "spend_30d":      round(spend, 2),
            "real_cpl":       round(spend / q, 2) if q > 0 else None,
        })

    by_campaign.sort(key=lambda x: x["qualified_leads"], reverse=True)

    return {
        "total_calls":       total_calls,
        "qualified_leads":   qualified_leads,
        "answer_rate":       round(answer_rate, 3),
        "avg_duration_secs": round(avg_dur, 1),
        "real_cpl":          real_cpl,
        "total_spend_30d":   round(total_spend, 2),
        "by_campaign":       by_campaign,
        "period_days":       days,
        "has_data":          total_calls > 0,
    }


def _get_campaign_spend(account_id: int, days: int) -> Dict[str, float]:
    """Return {campaign_id: spend_dollars} for the last N days."""
    from app import db
    from sqlalchemy import text

    since = datetime.utcnow() - timedelta(days=days)
    try:
        sql = text("""
            SELECT
                s.entity_id AS campaign_id,
                SUM(s.cost_micros) / 1000000 AS spend
            FROM gads_stats_daily s
            JOIN ads_campaigns c ON c.id = s.entity_id
            WHERE c.account_id  = :aid
              AND s.entity_type  = 'campaign'
              AND s.date        >= :since
            GROUP BY s.entity_id
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id, "since": since.date()}).fetchall()
        return {str(r.campaign_id): float(r.spend or 0) for r in rows}
    except Exception as exc:
        log.warning("_get_campaign_spend failed: %s", exc)
        return {}


# ── Tracking number management ─────────────────────────────────────────────────

def get_or_create_tracking_number(
    account_id: int,
    phone_number: str,
    label: str = "",
    campaign_id: Optional[str] = None,
    campaign_name: Optional[str] = None,
    qualified_duration_secs: int = DEFAULT_QUALIFIED_SECS,
) -> "CallTrackingNumber":
    """Upsert a CallTrackingNumber entry."""
    from app import db
    from app.models_calls import CallTrackingNumber

    obj = CallTrackingNumber.query.filter_by(
        account_id=account_id, phone_number=phone_number
    ).first()

    if not obj:
        obj = CallTrackingNumber(account_id=account_id, phone_number=phone_number)
        db.session.add(obj)

    obj.label       = label or obj.label
    obj.campaign_id = campaign_id or obj.campaign_id
    obj.campaign_name = campaign_name or obj.campaign_name
    obj.qualified_duration_secs = qualified_duration_secs
    obj.is_active   = True

    db.session.commit()
    return obj


# ── Helpers ────────────────────────────────────────────────────────────────────

def _int(val: Any) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _parse_twilio_ts(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(val, fmt)
            # strip tzinfo so SQLAlchemy stores as naive UTC
            return dt.replace(tzinfo=None)
        except ValueError:
            continue
    return None
