"""
Tests for Item 4: Credit Gap service.

No MySQL connection needed — all DB calls are mocked.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from app.services.credit_gap_service import (
    NEW_CUSTOMER_PCT_THRESHOLD,
    _flag_largest_gap,
    build_credit_gap,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_mappings(rows: list[dict]):
    """Return a mock execute() result whose .mappings().all() yields dicts."""
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _mock_fetchall(rows: list):
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


def _mock_fetchone(row):
    result = MagicMock()
    result.fetchone.return_value = row
    return result


def _make_db(
    campaigns=None,
    job_rows=None,
    repeat_customers=None,
    matched_customers=None,
):
    """
    Build a mock db whose execute() returns controlled data for each query.
    Call sequence:
      1. gads_stats_daily (campaigns)   → mappings().all()
      2. servicetitan_jobs (period)     → mappings().all()
      3. servicetitan_jobs (prior)      → fetchall()
      4. servicetitan_customers + lead_ingest (match) → fetchall()
    """
    db = MagicMock()
    session = MagicMock()
    db.session = session
    session.commit = MagicMock()
    session.rollback = MagicMock()

    call_count = [0]

    def side_effect(sql_obj, params=None):
        sql = str(sql_obj)
        c = call_count[0]
        call_count[0] += 1

        if "gads_stats_daily" in sql:
            return _mock_mappings(campaigns or [])
        if "servicetitan_jobs" in sql and "completed_date >= :s" in sql:
            return _mock_mappings(job_rows or [])
        if "servicetitan_jobs" in sql and "completed_date < :s" in sql:
            rows = [(cid,) for cid in (repeat_customers or [])]
            return _mock_fetchall(rows)
        if "servicetitan_customers" in sql:
            rows = [(cid,) for cid in (matched_customers or [])]
            return _mock_fetchall(rows)
        return _mock_mappings([])

    session.execute.side_effect = side_effect
    return db


# ── 1. No data ────────────────────────────────────────────────────────────────

def test_no_data_returns_zeros():
    db = _make_db()
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["ad_spend"] == 0.0
    assert result["st_revenue"] == 0.0
    assert result["revenue_gap"] == 0.0
    assert result["roas"] is None
    assert result["total_jobs"] == 0
    assert not result["has_st_data"]
    assert not result["has_ad_data"]


# ── 2. ROAS calculation ───────────────────────────────────────────────────────

def test_roas_calculated_correctly():
    campaigns = [{"campaign_id": 1, "campaign_name": "HVAC", "spend": 1000.0, "conversions": 10}]
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 5000.0, "completed_date": "2024-01-10"},
    ]
    db = _make_db(campaigns=campaigns, job_rows=jobs)
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["roas"] == 5.0
    assert result["ad_spend"] == 1000.0
    assert result["st_revenue"] == 5000.0


# ── 3. New vs repeat split ────────────────────────────────────────────────────

def test_new_vs_repeat_split():
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 1000.0, "completed_date": "2024-01-10"},
        {"id": 2, "st_customer_id": 102, "job_number": "J2", "revenue": 2000.0, "completed_date": "2024-01-15"},
    ]
    # Customer 102 is a repeat (had a prior job)
    db = _make_db(job_rows=jobs, repeat_customers=[102])
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["new_cust_rev"] == 1000.0
    assert result["repeat_cust_rev"] == 2000.0
    assert result["new_cust_pct"] == round(1000 / 3000 * 100, 1)


def test_all_new_customers():
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 500.0, "completed_date": "2024-01-10"},
        {"id": 2, "st_customer_id": 102, "job_number": "J2", "revenue": 500.0, "completed_date": "2024-01-15"},
    ]
    db = _make_db(job_rows=jobs, repeat_customers=[])
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["new_cust_rev"] == 1000.0
    assert result["repeat_cust_rev"] == 0.0
    assert result["new_cust_pct"] == 100.0


# ── 4. Retention-leaning label ────────────────────────────────────────────────

def test_retention_leaning_when_new_cust_pct_below_threshold():
    jobs = [
        {"id": i, "st_customer_id": i + 100, "job_number": f"J{i}",
         "revenue": 100.0, "completed_date": "2024-01-10"}
        for i in range(10)
    ]
    # Only 1 of 10 customers is new → new_cust_pct = 10%
    repeat_ids = [i + 100 for i in range(1, 10)]  # customers 101-109 are repeat
    db = _make_db(job_rows=jobs, repeat_customers=repeat_ids)
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["retention_leaning"] is True
    assert result["new_cust_pct"] == 10.0


def test_not_retention_leaning_when_new_cust_pct_above_threshold():
    jobs = [
        {"id": i, "st_customer_id": i + 100, "job_number": f"J{i}",
         "revenue": 100.0, "completed_date": "2024-01-10"}
        for i in range(10)
    ]
    # 8 of 10 are new → new_cust_pct = 80%
    db = _make_db(job_rows=jobs, repeat_customers=[100, 101])
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["retention_leaning"] is False


def test_configurable_threshold():
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 400.0, "completed_date": "2024-01-10"},
        {"id": 2, "st_customer_id": 102, "job_number": "J2", "revenue": 600.0, "completed_date": "2024-01-15"},
    ]
    db = _make_db(job_rows=jobs, repeat_customers=[102])
    # At 35% threshold: new_cust_pct = 40% → not retention-leaning
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31), new_customer_threshold=35.0)
    assert result["retention_leaning"] is False
    # At 50% threshold: new_cust_pct = 40% → retention-leaning
    result2 = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31), new_customer_threshold=50.0)
    assert result2["retention_leaning"] is True


# ── 5. Unmatched job share ────────────────────────────────────────────────────

def test_unmatched_jobs_counted():
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 500.0, "completed_date": "2024-01-10"},
        {"id": 2, "st_customer_id": 102, "job_number": "J2", "revenue": 500.0, "completed_date": "2024-01-15"},
        {"id": 3, "st_customer_id": 103, "job_number": "J3", "revenue": 500.0, "completed_date": "2024-01-20"},
    ]
    # Only customer 101 has a matching lead_ingest record
    db = _make_db(job_rows=jobs, matched_customers=[101])
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["unmatched_jobs"] == 2
    assert result["unmatched_pct"] == round(2 / 3 * 100, 1)


def test_all_jobs_matched():
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 500.0, "completed_date": "2024-01-10"},
    ]
    db = _make_db(job_rows=jobs, matched_customers=[101])
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["unmatched_jobs"] == 0
    assert result["unmatched_pct"] == 0.0


# ── 6. Largest gap campaign ───────────────────────────────────────────────────

def test_flag_largest_gap_no_conversions():
    campaigns = [
        {"campaign_id": 1, "campaign_name": "Brand", "spend": 500.0, "conversions": 0},
        {"campaign_id": 2, "campaign_name": "HVAC",  "spend": 1000.0, "conversions": 10},
    ]
    result = _flag_largest_gap(campaigns, st_revenue=5000.0, total_spend=1500.0)
    # Brand has 0 conversions → 100% gap ratio
    assert result is not None
    assert result["campaign_name"] == "Brand"
    assert result["gap_ratio"] == 1.0
    assert result["estimated_revenue"] == 0.0


def test_flag_largest_gap_proportional():
    campaigns = [
        {"campaign_id": 1, "campaign_name": "A", "spend": 1000.0, "conversions": 10},
        {"campaign_id": 2, "campaign_name": "B", "spend": 500.0,  "conversions": 2},
    ]
    # Total conversions = 12; st_revenue = 6000
    # A: attr_rev = 6000 * 10/12 = 5000; gap = 1000 - 5000 = -4000; ratio = -4.0
    # B: attr_rev = 6000 * 2/12  = 1000; gap = 500 - 1000 = -500;  ratio = -1.0
    result = _flag_largest_gap(campaigns, st_revenue=6000.0, total_spend=1500.0)
    # B has the higher ratio (less negative) → worst performer
    assert result["campaign_name"] == "B"


def test_flag_largest_gap_empty():
    assert _flag_largest_gap([], st_revenue=1000.0, total_spend=0.0) is None


def test_full_build_includes_largest_gap_campaign():
    campaigns = [
        {"campaign_id": 1, "campaign_name": "HVAC", "spend": 1000.0, "conversions": 5},
        {"campaign_id": 2, "campaign_name": "Brand", "spend": 200.0, "conversions": 0},
    ]
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 3000.0, "completed_date": "2024-01-10"},
    ]
    db = _make_db(campaigns=campaigns, job_rows=jobs)
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["largest_gap_campaign"] is not None
    assert result["largest_gap_campaign"]["campaign_name"] == "Brand"


# ── 7. Revenue gap sign ───────────────────────────────────────────────────────

def test_positive_revenue_gap_when_revenue_exceeds_spend():
    campaigns = [{"campaign_id": 1, "campaign_name": "HVAC", "spend": 1000.0, "conversions": 5}]
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 8000.0, "completed_date": "2024-01-10"},
    ]
    db = _make_db(campaigns=campaigns, job_rows=jobs)
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["revenue_gap"] == 7000.0  # 8000 - 1000


def test_negative_revenue_gap_when_spend_exceeds_revenue():
    campaigns = [{"campaign_id": 1, "campaign_name": "HVAC", "spend": 5000.0, "conversions": 1}]
    jobs = [
        {"id": 1, "st_customer_id": 101, "job_number": "J1", "revenue": 1000.0, "completed_date": "2024-01-10"},
    ]
    db = _make_db(campaigns=campaigns, job_rows=jobs)
    result = build_credit_gap(db, 1, date(2024, 1, 1), date(2024, 1, 31))
    assert result["revenue_gap"] == -4000.0  # 1000 - 5000
