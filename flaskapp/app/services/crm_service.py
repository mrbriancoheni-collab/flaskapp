# app/services/crm_service.py
"""
CRM Service — OPTIONAL component.

Connects to ServiceTitan (and later Jobber, HouseCall Pro) to pull booked
jobs and compute CPJ (cost per job) — the metric that completes the loop:

    Ad spend → Call → Booked job → Revenue

All public functions return safe defaults and never raise.
If no CRM is connected, get_crm_metrics() returns has_data=False and
agents continue using CPL (cost per lead) as before.

ServiceTitan OAuth flow
-----------------------
1. Register your app at developer.servicetitan.io
2. User authorises: POST /crm/connect   (saves CRMConnection)
3. Periodic sync:   crm_service.sync_jobs(account_id)
   - Pulls completed jobs from the last 90 days
   - Attributes jobs to campaigns via matching call_events by phone number

Env vars required (only if ServiceTitan is used)
------------------------------------------------
SERVICETITAN_APP_KEY     — your app's application key
SERVICETITAN_CLIENT_ID   — OAuth client_id
SERVICETITAN_CLIENT_SECRET
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional

from sqlalchemy import text

log = logging.getLogger(__name__)

# ── Safe empty return values ───────────────────────────────────────────────────

_EMPTY_METRICS: Dict[str, Any] = {
    "has_data":          False,
    "total_jobs":        0,
    "completed_jobs":    0,
    "total_revenue":     0.0,
    "real_cpj":          None,   # cost per job — None = not available
    "close_rate":        None,   # qualified calls that became jobs — None = not available
    "avg_job_revenue":   None,
    "by_campaign":       [],
    "period_days":       30,
}


# ── Table bootstrap ────────────────────────────────────────────────────────────

def _ensure_tables() -> bool:
    from app import db
    try:
        with db.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS crm_connections (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    account_id INT NOT NULL,
                    provider VARCHAR(64) NOT NULL,
                    is_active TINYINT(1) NOT NULL DEFAULT 1,
                    tenant_id VARCHAR(128),
                    credentials_json JSON,
                    last_sync_at DATETIME,
                    last_sync_status VARCHAR(32),
                    last_sync_error TEXT,
                    created_at DATETIME NOT NULL DEFAULT NOW(),
                    updated_at DATETIME NOT NULL DEFAULT NOW() ON UPDATE NOW(),
                    INDEX idx_crm_account (account_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS crm_jobs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    account_id INT NOT NULL,
                    crm_connection_id INT NOT NULL,
                    external_job_id VARCHAR(128) NOT NULL,
                    external_customer_id VARCHAR(128),
                    job_type VARCHAR(255),
                    job_status VARCHAR(64),
                    revenue_cents INT DEFAULT 0,
                    job_date DATE,
                    lead_source VARCHAR(128),
                    call_event_id INT,
                    campaign_id VARCHAR(64),
                    campaign_name VARCHAR(255),
                    created_at DATETIME NOT NULL DEFAULT NOW(),
                    synced_at DATETIME NOT NULL DEFAULT NOW(),
                    UNIQUE KEY uq_crm_job (crm_connection_id, external_job_id),
                    INDEX idx_cj_account (account_id),
                    INDEX idx_cj_campaign (campaign_id),
                    INDEX idx_cj_date (job_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """))
        return True
    except Exception as exc:
        log.debug("CRM _ensure_tables: %s", exc)
        return False


# ── Connection helpers ─────────────────────────────────────────────────────────

def get_active_connection(account_id: int) -> Optional[Any]:
    """Return the active CRMConnection for an account, or None."""
    try:
        from app.models_crm import CRMConnection
        return CRMConnection.query.filter_by(
            account_id=account_id, is_active=True
        ).first()
    except Exception:
        return None


def is_crm_connected(account_id: int) -> bool:
    return get_active_connection(account_id) is not None


# ── ServiceTitan OAuth ────────────────────────────────────────────────────────

def servicetitan_get_token(tenant_id: str, client_id: str,
                            client_secret: str, app_key: str) -> Optional[Dict]:
    """
    Obtain a ServiceTitan client-credentials access token.
    Returns token dict or None on failure.
    """
    import requests as _req
    try:
        resp = _req.post(
            "https://auth.servicetitan.io/connect/token",
            data={
                "grant_type":    "client_credentials",
                "client_id":     client_id,
                "client_secret": client_secret,
            },
            headers={"ST-App-Key": app_key},
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json()
        token["obtained_at"] = datetime.utcnow().isoformat()
        return token
    except Exception as exc:
        log.error("ServiceTitan token request failed: %s", exc)
        return None


def _st_headers(connection: Any) -> Optional[Dict[str, str]]:
    """Build ServiceTitan API request headers with a fresh token."""
    creds = connection.credentials_json or {}
    app_key       = os.getenv("SERVICETITAN_APP_KEY", "")
    client_id     = os.getenv("SERVICETITAN_CLIENT_ID", "")
    client_secret = os.getenv("SERVICETITAN_CLIENT_SECRET", "")

    # Check if token is still valid (expires_in - 60s buffer)
    obtained_at = creds.get("obtained_at")
    expires_in  = int(creds.get("expires_in", 0))
    access_token = creds.get("access_token", "")

    token_expired = True
    if obtained_at and access_token:
        elapsed = (datetime.utcnow() - datetime.fromisoformat(obtained_at)).total_seconds()
        token_expired = elapsed > (expires_in - 60)

    if token_expired:
        new_token = servicetitan_get_token(
            connection.tenant_id, client_id, client_secret, app_key
        )
        if not new_token:
            return None
        # Persist refreshed token
        try:
            from app import db
            connection.credentials_json = {**creds, **new_token}
            db.session.commit()
            access_token = new_token["access_token"]
        except Exception:
            access_token = new_token.get("access_token", "")

    return {
        "Authorization": f"Bearer {access_token}",
        "ST-App-Key":    app_key,
        "Content-Type":  "application/json",
    }


# ── Job sync ──────────────────────────────────────────────────────────────────

def sync_jobs(account_id: int, days_back: int = 90) -> Dict[str, Any]:
    """
    Pull completed jobs from ServiceTitan for the last N days.
    Upserts them into crm_jobs and attempts campaign attribution via call_events.
    Returns a summary dict. Never raises.
    """
    if not _ensure_tables():
        return {"ok": False, "error": "tables unavailable"}

    connection = get_active_connection(account_id)
    if not connection:
        return {"ok": False, "error": "no CRM connected"}

    if connection.provider != "servicetitan":
        return {"ok": False, "error": f"provider {connection.provider} sync not implemented"}

    headers = _st_headers(connection)
    if not headers:
        _update_sync_status(connection, "error", "token refresh failed")
        return {"ok": False, "error": "authentication failed"}

    since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
    tenant_id = connection.tenant_id

    import requests as _req
    jobs_created = 0
    jobs_updated = 0
    page = 1

    try:
        while True:
            url = (
                f"https://api.servicetitan.io/jpm/v2/tenant/{tenant_id}/jobs"
                f"?modifiedOnOrAfter={since}&pageSize=50&page={page}"
                f"&status=Completed,Scheduled"
            )
            resp = _req.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])

            if not items:
                break

            for item in items:
                created, updated = _upsert_job(account_id, connection.id, item)
                jobs_created += created
                jobs_updated += updated

            if not data.get("hasMore"):
                break
            page += 1

        _update_sync_status(connection, "ok", None)
        log.info("ServiceTitan sync account=%d: +%d new, %d updated",
                 account_id, jobs_created, jobs_updated)
        return {"ok": True, "created": jobs_created, "updated": jobs_updated}

    except Exception as exc:
        log.error("ServiceTitan sync failed for account %d: %s", account_id, exc)
        _update_sync_status(connection, "error", str(exc))
        return {"ok": False, "error": str(exc)}


def _upsert_job(account_id: int, connection_id: int, item: Dict) -> tuple[int, int]:
    """Upsert one ST job record. Returns (created, updated)."""
    from app import db
    from sqlalchemy import text as _t

    external_id = str(item.get("id", ""))
    if not external_id:
        return 0, 0

    status  = (item.get("status") or {}).get("name", "")
    revenue = int(float(item.get("total", 0) or 0) * 100)  # dollars → cents
    job_type = (item.get("type") or {}).get("name", "")
    job_date_raw = item.get("completedOn") or item.get("scheduledDate") or ""
    job_date = job_date_raw[:10] if job_date_raw else None

    # Try to attribute to a campaign via the customer's phone number
    campaign_id, campaign_name, call_event_id = _attribute_job(account_id, item)

    try:
        check = db.session.execute(
            _t("SELECT id FROM crm_jobs WHERE crm_connection_id=:cid AND external_job_id=:eid"),
            {"cid": connection_id, "eid": external_id}
        ).first()

        if check:
            db.session.execute(_t("""
                UPDATE crm_jobs SET job_status=:status, revenue_cents=:rev,
                    campaign_id=:cid2, campaign_name=:cname,
                    call_event_id=:cevid, synced_at=NOW()
                WHERE id=:id
            """), {"status": status, "rev": revenue, "cid2": campaign_id,
                   "cname": campaign_name, "cevid": call_event_id, "id": check.id})
            db.session.commit()
            return 0, 1
        else:
            db.session.execute(_t("""
                INSERT INTO crm_jobs
                    (account_id, crm_connection_id, external_job_id, job_type,
                     job_status, revenue_cents, job_date,
                     campaign_id, campaign_name, call_event_id)
                VALUES
                    (:aid, :cid, :eid, :jtype, :status, :rev, :jdate,
                     :camp_id, :camp_name, :cevid)
            """), {
                "aid": account_id, "cid": connection_id, "eid": external_id,
                "jtype": job_type, "status": status, "rev": revenue,
                "jdate": job_date, "camp_id": campaign_id,
                "camp_name": campaign_name, "cevid": call_event_id,
            })
            db.session.commit()
            return 1, 0
    except Exception as exc:
        db.session.rollback()
        log.warning("_upsert_job failed for %s: %s", external_id, exc)
        return 0, 0


def _attribute_job(account_id: int, item: Dict) -> tuple:
    """
    Try to link a job to a Google Ads campaign via call_events.
    Matches on the customer's phone number within a 30-day window.
    Returns (campaign_id, campaign_name, call_event_id) — all may be None.
    """
    try:
        from app import db
        # Extract customer phone from ST payload
        contacts = item.get("customer", {}).get("contacts", []) or []
        phones = [c.get("value", "") for c in contacts if c.get("type") == "Phone"]
        if not phones:
            return None, None, None

        phone = phones[0].replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not phone.startswith("+"):
            phone = "+1" + phone.lstrip("1") if len(phone) == 10 else phone

        job_date_raw = item.get("completedOn") or item.get("scheduledDate", "")
        job_date = job_date_raw[:10] if job_date_raw else None

        sql = text("""
            SELECT id, campaign_id, campaign_name
            FROM call_events
            WHERE account_id  = :aid
              AND from_number  = :phone
              AND is_qualified_lead = 1
              AND (:jdate IS NULL OR ABS(DATEDIFF(DATE(call_started_at), :jdate)) <= 30)
            ORDER BY call_started_at DESC
            LIMIT 1
        """)
        with db.engine.connect() as conn:
            row = conn.execute(sql, {"aid": account_id, "phone": phone,
                                     "jdate": job_date}).first()

        if row:
            return row.campaign_id, row.campaign_name, row.id
    except Exception:
        pass
    return None, None, None


def _update_sync_status(connection: Any, status: str, error: Optional[str]) -> None:
    try:
        from app import db
        connection.last_sync_at     = datetime.utcnow()
        connection.last_sync_status = status
        connection.last_sync_error  = error
        db.session.commit()
    except Exception:
        pass


# ── Metrics for agent context ──────────────────────────────────────────────────

def get_crm_metrics(account_id: int, days: int = 30) -> Dict[str, Any]:
    """
    Aggregate CRM job metrics for the last N days.

    Always returns a valid dict — never raises.
    Returns _EMPTY_METRICS if CRM is not connected or no data exists.
    """
    try:
        return _get_crm_metrics_inner(account_id, days)
    except Exception as exc:
        log.debug("get_crm_metrics failed gracefully for account %d: %s", account_id, exc)
        return dict(_EMPTY_METRICS)


def _get_crm_metrics_inner(account_id: int, days: int) -> Dict[str, Any]:
    from app import db

    since = date.today() - timedelta(days=days)

    rows = db.session.execute(text("""
        SELECT
            campaign_id,
            campaign_name,
            COUNT(*)                                         AS total_jobs,
            SUM(CASE WHEN job_status = 'Completed' THEN 1 ELSE 0 END) AS completed_jobs,
            SUM(CASE WHEN job_status = 'Completed' THEN revenue_cents ELSE 0 END) AS revenue_cents
        FROM crm_jobs
        WHERE account_id = :aid
          AND (job_date IS NULL OR job_date >= :since)
        GROUP BY campaign_id, campaign_name
    """), {"aid": account_id, "since": since}).fetchall()

    if not rows:
        return dict(_EMPTY_METRICS)

    total_jobs     = sum(int(r.total_jobs or 0)     for r in rows)
    completed_jobs = sum(int(r.completed_jobs or 0) for r in rows)
    total_revenue  = sum(int(r.revenue_cents or 0)  for r in rows) / 100

    # Spend per campaign (from gads_stats_daily)
    spend_by_campaign = _get_campaign_spend(account_id, days)
    total_spend = sum(spend_by_campaign.values())

    real_cpj = round(total_spend / completed_jobs, 2) if completed_jobs > 0 else None
    avg_revenue = round(total_revenue / completed_jobs, 2) if completed_jobs > 0 else None

    # Close rate: completed jobs / qualified calls
    close_rate = None
    try:
        call_row = db.session.execute(text("""
            SELECT COUNT(*) AS qleads FROM call_events
            WHERE account_id = :aid AND is_qualified_lead = 1
              AND created_at >= :since
        """), {"aid": account_id, "since": datetime.utcnow() - timedelta(days=days)}).first()
        if call_row and call_row.qleads > 0:
            close_rate = round(completed_jobs / call_row.qleads, 3)
    except Exception:
        pass

    by_campaign = []
    for r in rows:
        cid   = r.campaign_id or ""
        spend = spend_by_campaign.get(cid, 0.0)
        comp  = int(r.completed_jobs or 0)
        rev   = int(r.revenue_cents or 0) / 100
        by_campaign.append({
            "campaign_id":    cid,
            "campaign_name":  r.campaign_name or "",
            "total_jobs":     int(r.total_jobs or 0),
            "completed_jobs": comp,
            "revenue":        round(rev, 2),
            "spend":          round(spend, 2),
            "real_cpj":       round(spend / comp, 2) if comp > 0 else None,
            "roas":           round(rev / spend, 2)  if spend > 0 else None,
        })

    by_campaign.sort(key=lambda x: x["completed_jobs"], reverse=True)

    return {
        "has_data":        True,
        "total_jobs":      total_jobs,
        "completed_jobs":  completed_jobs,
        "total_revenue":   round(total_revenue, 2),
        "real_cpj":        real_cpj,
        "close_rate":      close_rate,
        "avg_job_revenue": avg_revenue,
        "by_campaign":     by_campaign,
        "period_days":     days,
    }


def _get_campaign_spend(account_id: int, days: int) -> Dict[str, float]:
    from app import db
    since = date.today() - timedelta(days=days)
    try:
        rows = db.session.execute(text("""
            SELECT s.entity_id AS campaign_id,
                   SUM(s.cost_micros) / 1000000 AS spend
            FROM gads_stats_daily s
            JOIN ads_campaigns c ON c.id = s.entity_id
            WHERE c.account_id = :aid
              AND s.entity_type = 'campaign'
              AND s.date >= :since
            GROUP BY s.entity_id
        """), {"aid": account_id, "since": since}).fetchall()
        return {str(r.campaign_id): float(r.spend or 0) for r in rows}
    except Exception:
        return {}


# ── CRM connect/disconnect routes (called from a Flask blueprint) ──────────────

def create_connection(account_id: int, provider: str,
                       tenant_id: str, credentials: Dict) -> "CRMConnection":
    """Create or update a CRM connection for an account."""
    _ensure_tables()
    from app import db
    from app.models_crm import CRMConnection

    obj = CRMConnection.query.filter_by(
        account_id=account_id, provider=provider
    ).first()

    if not obj:
        obj = CRMConnection(account_id=account_id, provider=provider)
        db.session.add(obj)

    obj.tenant_id        = tenant_id
    obj.credentials_json = credentials
    obj.is_active        = True
    db.session.commit()
    return obj
