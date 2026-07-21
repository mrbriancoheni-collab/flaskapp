# app/services/lsa_archive_service.py
"""
Local Services Ads history archiver.

Google is migrating LSA into Google Ads (Performance Max pay-per-lead) starting
August 2026, and **historical performance reports will not transfer**. This
service snapshots a connected LSA account's full lead history — monthly volume,
spend, bookings, and job-type breakdown — into a durable archive so the client
keeps their year-over-year data after migration.

Snapshots are read from the same GLSALead data the dashboard uses. All DB work
fails soft: table creation and reads never raise into the request.

Public API:
    build_snapshot(account_id) -> dict
    create_archive(account_id) -> int | None        (persists a snapshot)
    list_archives(account_id) -> list[dict]
    get_archive(archive_id, account_id=None, share_token=None) -> dict | None
    set_share(archive_id, account_id, enable) -> str | None
"""
from __future__ import annotations

import json
import logging
import secrets
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

log = logging.getLogger(__name__)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS glsa_archives (
  id INT AUTO_INCREMENT PRIMARY KEY,
  account_id INT NOT NULL,
  glsa_account_id BIGINT NULL,
  business_name VARCHAR(255) NULL,
  period_start DATE NULL,
  period_end DATE NULL,
  total_leads INT NOT NULL DEFAULT 0,
  total_spend DECIMAL(12,2) NOT NULL DEFAULT 0,
  booked_leads INT NOT NULL DEFAULT 0,
  snapshot_json LONGTEXT NULL,
  share_token VARCHAR(64) NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX ix_glsa_arch_account (account_id),
  UNIQUE KEY uq_glsa_arch_share (share_token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_table_ready = False


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    from app import db
    try:
        with db.engine.begin() as conn:
            conn.execute(text(_TABLE_DDL))
        _table_ready = True
    except Exception as exc:
        log.warning("glsa_archives table creation failed: %s", exc)


def _month_key(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m") if dt else None


def build_snapshot(account_id: int) -> Dict[str, Any]:
    """
    Aggregate the account's full LSA lead history into a snapshot dict.
    Returns a well-formed (possibly empty) structure even with no data.
    """
    snapshot: Dict[str, Any] = {
        "business_name": None,
        "period_start": None,
        "period_end": None,
        "total_leads": 0,
        "total_spend": 0.0,
        "booked_leads": 0,
        "avg_cost_per_lead": 0.0,
        "monthly": [],
        "job_types": [],
        "lead_types": {},
        "generated_at": datetime.utcnow().isoformat(),
    }
    try:
        from app.models_glsa import GLSALead, GLSAAccount, GLSAProfile
    except Exception:
        log.warning("GLSA models unavailable for snapshot")
        return snapshot

    try:
        glsa_account = GLSAAccount.query.filter_by(account_id=account_id).first()
        if not glsa_account:
            return snapshot

        profile = GLSAProfile.query.filter_by(account_id=account_id).first()
        if profile is not None:
            snapshot["business_name"] = getattr(profile, "business_name", None)

        leads = (
            GLSALead.query
            .filter(GLSALead.glsa_account_id == glsa_account.id)
            .order_by(GLSALead.lead_ts.asc())
            .all()
        )
        snapshot["glsa_account_id"] = glsa_account.id

        monthly = defaultdict(lambda: {"leads": 0, "spend": 0.0, "booked": 0})
        job_types = defaultdict(lambda: {"count": 0, "spend": 0.0})
        lead_types = defaultdict(int)
        total_spend = 0.0
        booked = 0
        first_ts = last_ts = None

        for lead in leads:
            ts = lead.lead_ts
            if ts:
                first_ts = first_ts or ts
                last_ts = ts
            mk = _month_key(ts) or "unknown"
            monthly[mk]["leads"] += 1

            amount = 0.0
            status = ""
            lead_type = "PHONE_CALL"
            if lead.notes and isinstance(lead.notes, dict):
                charged = lead.notes.get("charged_price") or {}
                if charged:
                    try:
                        amount = float(charged.get("units", 0) or 0)
                    except (TypeError, ValueError):
                        amount = 0.0
                status = lead.notes.get("lead_status", "") or ""
                lead_type = lead.notes.get("lead_type", "PHONE_CALL") or "PHONE_CALL"

            total_spend += amount
            monthly[mk]["spend"] += amount
            lead_types[lead_type] += 1
            if status in ("BOOKED", "ACTIVE"):
                booked += 1
                monthly[mk]["booked"] += 1
            if lead.job_type:
                job_types[lead.job_type]["count"] += 1
                job_types[lead.job_type]["spend"] += amount

        total_leads = len(leads)
        snapshot.update({
            "total_leads": total_leads,
            "total_spend": round(total_spend, 2),
            "booked_leads": booked,
            "avg_cost_per_lead": round(total_spend / total_leads, 2) if total_leads else 0.0,
            "period_start": first_ts.date().isoformat() if first_ts else None,
            "period_end": last_ts.date().isoformat() if last_ts else None,
            "monthly": [
                {"month": k, **v, "spend": round(v["spend"], 2)}
                for k, v in sorted(monthly.items()) if k != "unknown"
            ],
            "job_types": sorted(
                [{"name": k, "count": v["count"], "spend": round(v["spend"], 2)}
                 for k, v in job_types.items()],
                key=lambda x: x["count"], reverse=True,
            ),
            "lead_types": dict(lead_types),
        })
    except Exception:
        log.exception("build_snapshot failed for account %s", account_id)
    return snapshot


def create_archive(account_id: int) -> Optional[int]:
    """Build and persist a snapshot. Returns the new archive id, or None."""
    _ensure_table()
    from app import db
    snap = build_snapshot(account_id)
    try:
        with db.engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO glsa_archives
                    (account_id, glsa_account_id, business_name, period_start,
                     period_end, total_leads, total_spend, booked_leads, snapshot_json)
                VALUES
                    (:aid, :gaid, :bn, :ps, :pe, :tl, :ts, :bl, :sj)
            """), {
                "aid": account_id,
                "gaid": snap.get("glsa_account_id"),
                "bn": snap.get("business_name"),
                "ps": snap.get("period_start"),
                "pe": snap.get("period_end"),
                "tl": snap.get("total_leads", 0),
                "ts": snap.get("total_spend", 0),
                "bl": snap.get("booked_leads", 0),
                "sj": json.dumps(snap),
            })
            return int(result.lastrowid)
    except Exception:
        log.exception("create_archive failed for account %s", account_id)
        return None


def _row_to_dict(row) -> Dict[str, Any]:
    d = dict(row._mapping)
    if d.get("snapshot_json"):
        try:
            d["snapshot"] = json.loads(d["snapshot_json"])
        except Exception:
            d["snapshot"] = None
    d.pop("snapshot_json", None)
    return d


def list_archives(account_id: int) -> List[Dict[str, Any]]:
    _ensure_table()
    from app import db
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, business_name, period_start, period_end,
                       total_leads, total_spend, booked_leads, share_token, created_at
                FROM glsa_archives
                WHERE account_id = :aid
                ORDER BY created_at DESC
            """), {"aid": account_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        log.warning("list_archives failed for account %s", account_id, exc_info=True)
        return []


def get_archive(archive_id: Optional[int] = None, account_id: Optional[int] = None,
                share_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch one archive by (id + account_id) for owners, or by share_token for public view."""
    _ensure_table()
    from app import db
    try:
        if share_token:
            sql = text("SELECT * FROM glsa_archives WHERE share_token = :tok")
            params = {"tok": share_token}
        else:
            sql = text("SELECT * FROM glsa_archives WHERE id = :id AND account_id = :aid")
            params = {"id": archive_id, "aid": account_id}
        with db.engine.connect() as conn:
            row = conn.execute(sql, params).first()
        return _row_to_dict(row) if row else None
    except Exception:
        log.warning("get_archive failed (id=%s token=%s)", archive_id, bool(share_token), exc_info=True)
        return None


def set_share(archive_id: int, account_id: int, enable: bool) -> Optional[str]:
    """Enable (generate) or disable (clear) a public share token. Returns the token or None."""
    _ensure_table()
    from app import db
    token = secrets.token_urlsafe(16) if enable else None
    try:
        with db.engine.begin() as conn:
            conn.execute(text("""
                UPDATE glsa_archives SET share_token = :tok
                WHERE id = :id AND account_id = :aid
            """), {"tok": token, "id": archive_id, "aid": account_id})
        return token
    except Exception:
        log.exception("set_share failed for archive %s", archive_id)
        return None
