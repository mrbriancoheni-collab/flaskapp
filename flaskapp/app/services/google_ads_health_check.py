# app/services/google_ads_health_check.py
"""
Onboarding Account Health Check.

A one-time (re-runnable) scan that runs when a Google Ads account connects
and flags common setup problems in plain English, with one-click fixes where
an existing tool can help. Reads only local DB tables that the daily sync
populates (gads_stats_daily, keywords, ad_groups, ads_campaigns, ads,
negative_keywords) plus the account_settings key/value store.

Result shape:
    {
        "score": 0-100,
        "ran_at": ISO timestamp,
        "checks": [
            {"id", "status": "pass"|"warn"|"fail", "title", "explanation",
             "fix_action": {"type": "link"|"sync", ...} (optional)},
            ...
        ]
    }

The latest result is stored in account_settings under key "gads_health_check".
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

HEALTH_CHECK_SETTING_KEY = "gads_health_check"

OPTIMIZER_TAB_HREF = "/account/google/ads/?tab=optimizer"
SEARCH_TERMS_HREF = "/account/google/ads/search-terms"

BROAD_FAIL_PCT = 50.0
BROAD_WARN_PCT = 25.0
BUDGET_LIMITED_THRESHOLD = 0.10  # avg 10%+ impression share lost to budget
STALE_DAYS = 7

_STATUS_POINTS = {"pass": 1.0, "warn": 0.5, "fail": 0.0}


def _check(check_id: str, status: str, title: str, explanation: str,
           fix_action: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": check_id,
        "status": status,
        "title": title,
        "explanation": explanation,
    }
    if fix_action:
        out["fix_action"] = fix_action
    return out


def _check_conversion_tracking(session, account_id: int) -> Optional[Dict[str, Any]]:
    thirty_ago = dt.date.today() - dt.timedelta(days=30)
    row = session.execute(text("""
        SELECT SUM(gs.cost_micros) AS spend_micros_ever,
               SUM(gs.conversions) AS conv_ever,
               SUM(CASE WHEN gs.date >= :d THEN gs.conversions ELSE 0 END) AS conv_30d
        FROM gads_stats_daily gs
        JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
        WHERE gs.entity_type = 'campaign'
    """), {"aid": account_id, "d": thirty_ago}).mappings().one_or_none()

    spend_ever = float(row["spend_micros_ever"] or 0) / 1_000_000 if row else 0.0
    conv_ever = float(row["conv_ever"] or 0) if row else 0.0
    conv_30d = float(row["conv_30d"] or 0) if row else 0.0

    if spend_ever > 0 and conv_ever == 0:
        return _check(
            "conversion_tracking", "fail",
            "We can't see your leads",
            "Without conversion tracking, neither you nor Google knows which "
            "clicks become customers. You've spent money on ads but zero leads "
            "have ever been recorded — that usually means conversion tracking "
            "isn't set up yet.",
            {"type": "link", "label": "Set up leads tracking",
             "href": "/account/google/ads/conversions"},
        )
    if conv_30d > 0:
        return _check(
            "conversion_tracking", "pass",
            "Lead tracking is working",
            f"{conv_30d:.0f} lead{'s' if conv_30d != 1 else ''} recorded in the "
            "last 30 days, so we can tell which clicks turn into customers.",
        )
    if conv_ever > 0:
        return _check(
            "conversion_tracking", "warn",
            "No leads recorded in the last 30 days",
            "Lead tracking has worked before, but nothing has come through in "
            "the last 30 days. That could mean slow business — or tracking "
            "quietly broke.",
            {"type": "link", "label": "Check leads tracking",
             "href": "/account/google/ads/conversions"},
        )
    return _check(
        "conversion_tracking", "pass",
        "No spend yet — nothing to check",
        "Once your ads start spending, we'll make sure your leads are being "
        "counted.",
    )


def _check_broad_match(session, account_id: int) -> Optional[Dict[str, Any]]:
    row = session.execute(text("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN k.match_type = 'broad' THEN 1 ELSE 0 END) AS broad
        FROM keywords k
        JOIN ad_groups ag ON ag.id = k.ad_group_id
        JOIN ads_campaigns ac ON ac.id = ag.campaign_id
        WHERE ac.account_id = :aid AND k.status = 'enabled'
    """), {"aid": account_id}).mappings().one_or_none()

    total = int(row["total"] or 0) if row else 0
    broad = int(row["broad"] or 0) if row else 0

    if total == 0:
        return _check(
            "broad_match", "pass",
            "No active keywords yet",
            "Once you add keywords, we'll keep an eye on how loosely Google is "
            "allowed to match them.",
        )

    pct = broad / total * 100
    if pct > BROAD_FAIL_PCT:
        status = "fail"
    elif pct > BROAD_WARN_PCT:
        status = "warn"
    else:
        status = "pass"

    if status == "pass":
        return _check(
            "broad_match", "pass",
            "Keyword matching is under control",
            f"Only {broad} of your {total} keywords are broad match, so Google "
            "mostly shows your ads for searches you actually chose.",
        )
    return _check(
        "broad_match", status,
        "Too many broad match keywords",
        "Broad match lets Google guess what's relevant — and it guesses "
        f"loosely. {broad} of your {total} keywords are broad, which often "
        "means paying for searches that have nothing to do with your business.",
        {"type": "link", "label": "Review broad keywords",
         "href": OPTIMIZER_TAB_HREF},
    )


def _check_negative_keywords(session, account_id: int) -> Optional[Dict[str, Any]]:
    count = session.execute(text("""
        SELECT COUNT(*)
        FROM negative_keywords nk
        LEFT JOIN ads_campaigns ac ON ac.id = nk.campaign_id
        LEFT JOIN ad_groups ag ON ag.id = nk.ad_group_id
        LEFT JOIN ads_campaigns ac2 ON ac2.id = ag.campaign_id
        WHERE ac.account_id = :aid OR ac2.account_id = :aid
    """), {"aid": account_id}).scalar() or 0

    if count == 0:
        return _check(
            "negative_keywords", "fail",
            "No negative keywords",
            "Negative keywords block junk searches. Without any, you're paying "
            "for searches like 'free' and 'DIY' that will never become "
            "customers.",
            {"type": "link", "label": "Block junk searches",
             "href": SEARCH_TERMS_HREF},
        )
    return _check(
        "negative_keywords", "pass",
        "Junk searches are being blocked",
        f"You have {count} negative keyword{'s' if count != 1 else ''} "
        "filtering out searches that waste money.",
    )


def _check_single_ad_groups(session, account_id: int) -> Optional[Dict[str, Any]]:
    row = session.execute(text("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN ad_count < 2 THEN 1 ELSE 0 END) AS single
        FROM (
            SELECT ag.id,
                   (SELECT COUNT(*) FROM ads a
                    WHERE a.ad_group_id = ag.id AND a.status != 'removed') AS ad_count
            FROM ad_groups ag
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE ac.account_id = :aid AND ag.status = 'enabled'
        ) t
    """), {"aid": account_id}).mappings().one_or_none()

    total = int(row["total"] or 0) if row else 0
    single = int(row["single"] or 0) if row else 0

    if total == 0:
        return _check(
            "single_ad_groups", "pass",
            "No active ad groups yet",
            "Once your campaigns have ad groups, we'll check that each one has "
            "enough ads to test.",
        )
    if single > 0:
        return _check(
            "single_ad_groups", "warn",
            f"{single} ad group{'s' if single != 1 else ''} with only one ad",
            "Google works best when it can test 2–3 ads against each other and "
            f"show the winner more often. {single} of your {total} ad groups "
            "only have one ad, so there's nothing to compare.",
            {"type": "link", "label": "Add more ads",
             "href": "/account/google/ads/?tab=ads"},
        )
    return _check(
        "single_ad_groups", "pass",
        "Every ad group has ads to test",
        f"All {total} of your ad groups have at least two ads, so Google can "
        "find the message that works best.",
    )


def _check_budget_limited(session, account_id: int) -> Optional[Dict[str, Any]]:
    fourteen_ago = dt.date.today() - dt.timedelta(days=14)
    rows = session.execute(text("""
        SELECT ac.name AS camp_name,
               AVG(gs.lost_is_budget) AS avg_lost
        FROM gads_stats_daily gs
        JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
        WHERE gs.entity_type = 'campaign'
          AND gs.date >= :d
          AND gs.lost_is_budget IS NOT NULL
        GROUP BY gs.entity_id, ac.name
        HAVING AVG(gs.lost_is_budget) >= :threshold
        ORDER BY avg_lost DESC
        LIMIT 5
    """), {"aid": account_id, "d": fourteen_ago,
           "threshold": BUDGET_LIMITED_THRESHOLD}).mappings().all()

    if rows:
        parts = [f'"{r["camp_name"]}" misses {round((r["avg_lost"] or 0) * 100)}% '
                 "of its chances to show" for r in rows]
        return _check(
            "budget_limited", "warn",
            f"{len(rows)} campaign{'s' if len(rows) != 1 else ''} running out of budget",
            "These campaigns hit their daily budget before the day is over, so "
            "Google stops showing your ads while people are still searching: "
            f"{'; '.join(parts)}.",
            {"type": "link", "label": "Review budgets",
             "href": "/account/google/ads/budget"},
        )
    return _check(
        "budget_limited", "pass",
        "Budgets aren't holding you back",
        "None of your campaigns are missing meaningful traffic because the "
        "daily budget ran out.",
    )


def _check_data_freshness(session, account_id: int) -> Optional[Dict[str, Any]]:
    raw = session.execute(text(
        "SELECT setting_value FROM account_settings "
        "WHERE account_id = :aid AND setting_key = 'gads_last_synced_at' LIMIT 1"
    ), {"aid": account_id}).scalar()

    last_synced = None
    if raw:
        try:
            last_synced = dt.datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            last_synced = None

    if last_synced is None:
        return _check(
            "data_freshness", "warn",
            "Your account data has never been synced",
            "We haven't pulled any data from Google Ads yet, so the other "
            "checks may be running on an empty picture. Run a sync to get "
            "current numbers.",
            {"type": "sync", "label": "Sync now"},
        )

    age_days = (dt.datetime.utcnow() - last_synced).days
    if age_days > STALE_DAYS:
        return _check(
            "data_freshness", "warn",
            f"Your data is {age_days} days old",
            "The numbers we're checking were last pulled from Google Ads "
            f"{age_days} days ago. Run a sync so you're looking at what's "
            "happening now, not last week.",
            {"type": "sync", "label": "Sync now"},
        )
    return _check(
        "data_freshness", "pass",
        "Your data is fresh",
        "Your Google Ads data was synced within the last week.",
    )


def run_health_check(account_id: int) -> Dict[str, Any]:
    """Run all health checks for an account and return the scored result."""
    from app import db

    check_fns = [
        _check_conversion_tracking,
        _check_broad_match,
        _check_negative_keywords,
        _check_single_ad_groups,
        _check_budget_limited,
        _check_data_freshness,
    ]

    checks: List[Dict[str, Any]] = []
    for fn in check_fns:
        try:
            result = fn(db.session, account_id)
            if result:
                checks.append(result)
        except Exception:
            db.session.rollback()
            logger.exception("Health check %s failed for account %s",
                             fn.__name__, account_id)

    if checks:
        points = sum(_STATUS_POINTS.get(c["status"], 0.0) for c in checks)
        score = round(points / len(checks) * 100)
    else:
        score = 0

    return {
        "score": score,
        "ran_at": dt.datetime.utcnow().isoformat(),
        "checks": checks,
    }


def store_health_check(account_id: int, result: Dict[str, Any]) -> None:
    """Persist the latest health check result in account_settings."""
    from app.google.autonomous_routes import _save_setting
    _save_setting(account_id, HEALTH_CHECK_SETTING_KEY, json.dumps(result))


def get_stored_health_check(account_id: int) -> Optional[Dict[str, Any]]:
    """Return the last stored health check result, or None if never run."""
    from app import db
    try:
        raw = db.session.execute(text(
            "SELECT setting_value FROM account_settings "
            "WHERE account_id = :aid AND setting_key = :key LIMIT 1"
        ), {"aid": account_id, "key": HEALTH_CHECK_SETTING_KEY}).scalar()
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        db.session.rollback()
        logger.exception("Could not load stored health check for account %s",
                         account_id)
        return None
