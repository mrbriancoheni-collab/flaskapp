# app/services/performance_memory.py
"""
Performance Memory Service — stores and retrieves learned performance patterns.

Two pattern types
-----------------
seasonal  — month-over-month CPL multiplier vs. account annual average.
            e.g. "June CPL is 1.4× the annual average for HVAC accounts"

geo       — CPL and conversion_rate per city/zip extracted from search terms
            that contain geo signals (stored when location report data available).

Table schema (created on first use)
------------------------------------
performance_memory (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    account_id    INT NOT NULL,
    entity_type   VARCHAR(32),   -- 'account', 'campaign'
    entity_id     VARCHAR(64),   -- campaign_id or NULL for account-level
    pattern_type  VARCHAR(32),   -- 'seasonal', 'geo'
    period_key    VARCHAR(32),   -- '01'–'12' (month), or geo identifier
    metric_key    VARCHAR(32),   -- 'cpl_multiplier', 'conversion_rate', 'ctr'
    value         FLOAT,
    sample_count  INT  DEFAULT 1,
    confidence    FLOAT DEFAULT 0.5,   -- 0–1; rises with more data
    last_updated  DATE,
    UNIQUE KEY uq_mem (account_id, entity_type, entity_id, pattern_type, period_key, metric_key)
)

Public API
----------
update_seasonal_memory(account_id)   — recompute month multipliers from DB stats
get_seasonal_context(account_id)     — dict usable in agent context
get_memory_summary(account_id)       — human-readable summary for debugging
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

log = logging.getLogger(__name__)

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS performance_memory (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    account_id   INT          NOT NULL,
    entity_type  VARCHAR(32)  NOT NULL DEFAULT 'account',
    entity_id    VARCHAR(64)  NOT NULL DEFAULT '',
    pattern_type VARCHAR(32)  NOT NULL,
    period_key   VARCHAR(32)  NOT NULL,
    metric_key   VARCHAR(32)  NOT NULL,
    value        FLOAT        NOT NULL,
    sample_count INT          NOT NULL DEFAULT 1,
    confidence   FLOAT        NOT NULL DEFAULT 0.5,
    last_updated DATE,
    UNIQUE KEY uq_mem (account_id, entity_type, entity_id, pattern_type, period_key, metric_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

MIN_MONTHS_FOR_CONFIDENCE = 3   # months of data needed for confidence > 0.5
HIGH_CONFIDENCE_MONTHS    = 12  # months needed for confidence = 1.0


# ── Table bootstrap ───────────────────────────────────────────────────────────

def _ensure_table() -> None:
    from app import db
    try:
        with db.engine.begin() as conn:
            conn.execute(text(TABLE_DDL))
    except Exception as exc:
        log.warning("performance_memory table creation failed: %s", exc)


# ── Upsert helper ─────────────────────────────────────────────────────────────

def _upsert(
    account_id: int,
    entity_type: str,
    entity_id: str,
    pattern_type: str,
    period_key: str,
    metric_key: str,
    value: float,
    sample_count: int,
    confidence: float,
) -> None:
    from app import db
    sql = text("""
        INSERT INTO performance_memory
            (account_id, entity_type, entity_id, pattern_type,
             period_key, metric_key, value, sample_count, confidence, last_updated)
        VALUES
            (:aid, :etype, :eid, :ptype, :pkey, :mkey, :val, :cnt, :conf, CURDATE())
        ON DUPLICATE KEY UPDATE
            value        = VALUES(value),
            sample_count = VALUES(sample_count),
            confidence   = VALUES(confidence),
            last_updated = CURDATE()
    """)
    with db.engine.begin() as conn:
        conn.execute(sql, {
            "aid": account_id, "etype": entity_type, "eid": entity_id,
            "ptype": pattern_type, "pkey": period_key, "mkey": metric_key,
            "val": value, "cnt": sample_count, "conf": confidence,
        })


# ── Seasonal memory ───────────────────────────────────────────────────────────

def update_seasonal_memory(account_id: int) -> Dict[str, Any]:
    """
    Compute month-over-month CPL multipliers for the account and store them.

    Algorithm:
    1. Pull daily cost + conversions from gads_stats_daily (entity_type='account')
       for all available history.
    2. Aggregate by month (1-12) across all years.
    3. Compute monthly avg CPL, divide by annual avg CPL → multiplier.
    4. Upsert into performance_memory.

    Returns a summary dict for logging.
    """
    _ensure_table()
    from app import db

    try:
        sql = text("""
            SELECT
                MONTH(date)                       AS month_num,
                YEAR(date)                        AS year_num,
                SUM(cost_micros) / 1000000        AS monthly_cost,
                SUM(conversions)                  AS monthly_conversions
            FROM gads_stats_daily
            WHERE account_id  = :aid
              AND entity_type  = 'account'
              AND conversions  > 0
            GROUP BY YEAR(date), MONTH(date)
            ORDER BY year_num, month_num
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id}).fetchall()
    except Exception as exc:
        log.error("seasonal memory query failed for account %d: %s", account_id, exc)
        return {"account_id": account_id, "error": str(exc)}

    if len(rows) < MIN_MONTHS_FOR_CONFIDENCE:
        log.info("account %d: only %d months of data — skipping seasonal memory", account_id, len(rows))
        return {"account_id": account_id, "months_available": len(rows), "skipped": True}

    # Group CPL values by month number (averaging across years)
    from collections import defaultdict
    month_cpls: Dict[int, List[float]] = defaultdict(list)
    for row in rows:
        cost = float(row.monthly_cost or 0)
        conv = float(row.monthly_conversions or 0)
        if conv > 0:
            month_cpls[int(row.month_num)].append(cost / conv)

    if not month_cpls:
        return {"account_id": account_id, "skipped": True, "reason": "no conversion data"}

    # Overall (annual) average CPL across all months
    all_cpls = [v for vals in month_cpls.values() for v in vals]
    annual_avg_cpl = sum(all_cpls) / len(all_cpls)
    if annual_avg_cpl == 0:
        return {"account_id": account_id, "skipped": True, "reason": "zero CPL"}

    stored = 0
    for month_num, cpl_list in month_cpls.items():
        avg_cpl = sum(cpl_list) / len(cpl_list)
        multiplier = avg_cpl / annual_avg_cpl
        sample_count = len(cpl_list)
        confidence = min(1.0, sample_count / HIGH_CONFIDENCE_MONTHS)

        _upsert(
            account_id=account_id,
            entity_type="account",
            entity_id="",
            pattern_type="seasonal",
            period_key=f"{month_num:02d}",
            metric_key="cpl_multiplier",
            value=round(multiplier, 4),
            sample_count=sample_count,
            confidence=round(confidence, 3),
        )
        stored += 1

    log.info("account %d: stored %d seasonal CPL multipliers", account_id, stored)
    return {
        "account_id": account_id,
        "months_stored": stored,
        "annual_avg_cpl": round(annual_avg_cpl, 2),
    }


# ── Geo memory (keyword-level proxy) ─────────────────────────────────────────

def update_geo_memory(account_id: int) -> Dict[str, Any]:
    """
    Build geo performance signals from search terms that contain
    city/zip-like tokens (simple heuristic until location reports are added).

    Stores conversion_rate per detected geo token into performance_memory.
    Returns a summary dict.
    """
    _ensure_table()
    from app import db

    # Pull search terms with cost/conversions for this account via campaign join
    try:
        sql = text("""
            SELECT
                st.query,
                SUM(st.cost)        AS total_cost,
                SUM(st.conversions) AS total_conversions,
                SUM(st.clicks)      AS total_clicks
            FROM search_terms st
            JOIN ads_campaigns ac ON ac.google_campaign_id = st.campaign_id
            WHERE ac.account_id = :aid
              AND st.clicks > 0
            GROUP BY st.query
            HAVING total_clicks >= 5
            ORDER BY total_cost DESC
            LIMIT 500
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id}).fetchall()
    except Exception as exc:
        log.warning("geo memory query failed for account %d: %s", account_id, exc)
        return {"account_id": account_id, "error": str(exc)}

    # Very lightweight geo extraction: last token if it looks like a city/state or zip
    import re
    geo_stats: Dict[str, Dict[str, float]] = {}
    zip_pat  = re.compile(r'\b\d{5}\b')
    # Common US state abbreviations as a signal
    state_pat = re.compile(
        r'\b(al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|'
        r'mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|'
        r'ut|vt|va|wa|wv|wi|wy)\b', re.I
    )

    for row in rows:
        query = (row.query or "").lower().strip()
        cost  = float(row.total_cost or 0)
        conv  = float(row.total_conversions or 0)
        clicks = float(row.total_clicks or 0)

        # Detect geo token
        geo_token = None
        zip_match = zip_pat.search(query)
        if zip_match:
            geo_token = zip_match.group()
        elif state_pat.search(query):
            # Use last two words as city+state proxy
            tokens = query.split()
            if len(tokens) >= 2:
                geo_token = " ".join(tokens[-2:])

        if not geo_token:
            continue

        if geo_token not in geo_stats:
            geo_stats[geo_token] = {"cost": 0.0, "conv": 0.0, "clicks": 0.0}
        geo_stats[geo_token]["cost"]   += cost
        geo_stats[geo_token]["conv"]   += conv
        geo_stats[geo_token]["clicks"] += clicks

    stored = 0
    for geo_token, stats in geo_stats.items():
        if stats["clicks"] < 10:
            continue
        conv_rate = stats["conv"] / stats["clicks"] if stats["clicks"] > 0 else 0
        confidence = min(1.0, stats["clicks"] / 200)

        _upsert(
            account_id=account_id,
            entity_type="geo",
            entity_id=geo_token,
            pattern_type="geo",
            period_key="all_time",
            metric_key="conversion_rate",
            value=round(conv_rate, 6),
            sample_count=int(stats["clicks"]),
            confidence=round(confidence, 3),
        )
        stored += 1

    log.info("account %d: stored %d geo performance entries", account_id, stored)
    return {"account_id": account_id, "geo_entries": stored}


# ── Read helpers for agent context ────────────────────────────────────────────

def get_seasonal_context(account_id: int) -> Dict[str, Any]:
    """
    Return seasonal multipliers ready to drop into agent context.

    Returns:
    {
        "available": True/False,
        "current_month_multiplier": 1.23,
        "next_month_multiplier": 0.95,
        "high_season_months": ["06", "07"],   # months with multiplier >= 1.2
        "low_season_months":  ["01", "02"],   # months with multiplier <= 0.8
        "months": {"01": 0.9, "02": 0.85, ...}
    }
    """
    from app import db
    try:
        sql = text("""
            SELECT period_key, value, confidence, sample_count
            FROM performance_memory
            WHERE account_id  = :aid
              AND pattern_type = 'seasonal'
              AND metric_key   = 'cpl_multiplier'
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id}).fetchall()
    except Exception:
        return {"available": False}

    if not rows:
        return {"available": False}

    months = {r.period_key: round(float(r.value), 3) for r in rows}
    today = date.today()
    cur_key  = f"{today.month:02d}"
    next_key = f"{(today.month % 12) + 1:02d}"

    high_season = [k for k, v in months.items() if v >= 1.20]
    low_season  = [k for k, v in months.items() if v <= 0.80]

    return {
        "available": True,
        "current_month_multiplier": months.get(cur_key, 1.0),
        "next_month_multiplier":    months.get(next_key, 1.0),
        "high_season_months":       sorted(high_season),
        "low_season_months":        sorted(low_season),
        "months": months,
    }


def get_top_geo_performers(account_id: int, limit: int = 10) -> List[Dict]:
    """Return top geo performers by conversion rate."""
    from app import db
    try:
        sql = text("""
            SELECT entity_id AS geo, value AS conversion_rate,
                   sample_count, confidence
            FROM performance_memory
            WHERE account_id  = :aid
              AND pattern_type = 'geo'
              AND metric_key   = 'conversion_rate'
              AND confidence  >= 0.3
            ORDER BY value DESC
            LIMIT :lim
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id, "lim": limit}).fetchall()
    except Exception:
        return []

    return [
        {"geo": r.geo, "conversion_rate": round(float(r.conversion_rate), 4),
         "clicks": r.sample_count, "confidence": round(float(r.confidence), 2)}
        for r in rows
    ]


def get_memory_summary(account_id: int) -> Dict[str, Any]:
    """Human-readable summary used by the control panel and for debugging."""
    seasonal = get_seasonal_context(account_id)
    geo      = get_top_geo_performers(account_id, limit=5)
    return {
        "seasonal": seasonal,
        "top_geo_performers": geo,
    }


# ── Main entry point for cron ─────────────────────────────────────────────────

def update_all_memory(account_id: int) -> Dict[str, Any]:
    """Update both seasonal and geo memory for an account."""
    seasonal_result = update_seasonal_memory(account_id)
    geo_result      = update_geo_memory(account_id)
    return {"seasonal": seasonal_result, "geo": geo_result}
