# app/services/action_generator.py
"""
Rule-based action generator: queries Google Ads metrics and produces
AgentDecision rows for the account action-approval queue.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import text

from app import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def _has_metrics(account_id: int) -> bool:
    """Return True if the account has any google_ads_metrics rows."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM google_ads_metrics WHERE account_id=:aid LIMIT 1"),
                {"aid": account_id},
            ).fetchone()
        return row is not None
    except Exception as e:
        logger.warning("action_generator._has_metrics error: %s", e)
        return False


def _log(decision_dict: Dict[str, Any]) -> None:
    """Insert one action into agent_decisions, skipping if an identical pending row exists."""
    try:
        dedup = text("""
            SELECT id FROM agent_decisions
            WHERE account_id = :account_id
              AND title = :title
              AND (campaign_id = :campaign_id
                   OR (campaign_id IS NULL AND :campaign_id IS NULL))
              AND status = 'pending'
            LIMIT 1
        """)
        with db.engine.connect() as conn:
            existing = conn.execute(dedup, {
                "account_id": decision_dict["account_id"],
                "title": decision_dict["title"],
                "campaign_id": decision_dict.get("campaign_id"),
            }).fetchone()
            if existing:
                return

            conn.execute(text("""
                INSERT INTO agent_decisions (
                    agent_id, agent_type, decision_type,
                    title, description, reasoning,
                    account_id, customer_id, campaign_id, ad_group_id,
                    action_data, risk_level, requires_approval, confidence,
                    expected_monthly_savings, expected_monthly_leads,
                    expected_improvement_pct, status, created_at
                ) VALUES (
                    :agent_id, :agent_type, :decision_type,
                    :title, :description, :reasoning,
                    :account_id, :customer_id, :campaign_id, :ad_group_id,
                    :action_data, :risk_level, :requires_approval, :confidence,
                    :expected_monthly_savings, :expected_monthly_leads,
                    :expected_improvement_pct, 'pending', NOW()
                )
            """), {
                "agent_id":                "action_generator",
                "agent_type":              "ActionGeneratorService",
                "decision_type":           decision_dict["decision_type"],
                "title":                   decision_dict["title"],
                "description":             decision_dict.get("description", ""),
                "reasoning":               decision_dict.get("reasoning", ""),
                "account_id":              decision_dict["account_id"],
                "customer_id":             decision_dict.get("customer_id", str(decision_dict["account_id"])),
                "campaign_id":             decision_dict.get("campaign_id"),
                "ad_group_id":             decision_dict.get("ad_group_id"),
                "action_data":             decision_dict.get("action_data", "{}"),
                "risk_level":              decision_dict.get("risk_level", "medium"),
                "requires_approval":       True,
                "confidence":              decision_dict.get("confidence", 0.8),
                "expected_monthly_savings":    decision_dict.get("expected_monthly_savings"),
                "expected_monthly_leads":      decision_dict.get("expected_monthly_leads"),
                "expected_improvement_pct":    decision_dict.get("expected_improvement_pct"),
            })
            conn.commit()
    except Exception as e:
        logger.error("action_generator._log error: %s", e)


# ---------------------------------------------------------------------------
# Rule 1 — Pause zero-conversion keywords
# ---------------------------------------------------------------------------

def _rule_pause_zero_conv(account_id: int) -> None:
    sql = text("""
        SELECT
            keyword_text,
            campaign_id,
            ad_group_id,
            SUM(clicks)       AS total_clicks,
            SUM(cost_micros)  AS total_cost
        FROM google_ads_metrics
        WHERE account_id = :aid
          AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
          AND keyword_text IS NOT NULL
          AND keyword_text <> ''
        GROUP BY keyword_text, campaign_id, ad_group_id
        HAVING total_clicks >= 30
           AND SUM(conversions) = 0
        ORDER BY total_cost DESC
        LIMIT 10
    """)
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id}).fetchall()
        for row in rows:
            kw       = row[0]
            camp_id  = row[1]
            ag_id    = row[2]
            clicks   = int(row[3])
            cost     = float(row[4]) / 1_000_000
            savings  = round(cost * 0.8, 2)
            _log({
                "account_id":    account_id,
                "decision_type": "pause_keyword",
                "risk_level":    "medium",
                "campaign_id":   str(camp_id) if camp_id else None,
                "ad_group_id":   str(ag_id)   if ag_id   else None,
                "title":         f"Pause '{kw}' — 0 conversions from {clicks} clicks",
                "description":   (
                    f"'{kw}' has received {clicks} clicks over the last 30 days "
                    f"at a cost of ${cost:.2f} with zero conversions. "
                    f"Pausing it could recover approximately ${savings:.2f}/month."
                ),
                "reasoning": (
                    "Keywords with 30+ clicks and no conversions are wasting budget "
                    "without generating leads. Pausing recovers spend for better-performing terms."
                ),
                "confidence":              0.85,
                "expected_monthly_savings": savings,
                "action_data": f'{{"keyword": "{kw}", "campaign_id": "{camp_id}"}}',
            })
    except Exception as e:
        logger.error("_rule_pause_zero_conv error: %s", e)


# ---------------------------------------------------------------------------
# Rule 2 — Bid schedule opportunity (best day-of-week)
# ---------------------------------------------------------------------------

def _rule_bid_schedule(account_id: int) -> None:
    sql = text("""
        SELECT
            DAYOFWEEK(date)             AS dow,
            SUM(conversions)            AS convs,
            SUM(cost_micros) / 1000000  AS spend
        FROM google_ads_metrics
        WHERE account_id = :aid
          AND date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
          AND conversions > 0
        GROUP BY DAYOFWEEK(date)
        HAVING convs > 0
    """)
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id}).fetchall()
        if len(rows) < 3:
            return
        cpls = [(int(r[0]), float(r[2]) / float(r[1])) for r in rows]
        avg_cpl = sum(c for _, c in cpls) / len(cpls)
        if avg_cpl <= 0:
            return
        for dow, cpl in cpls:
            ratio = cpl / avg_cpl
            if ratio < 0.70:
                improvement = round((1 - ratio) * 100, 1)
                day_name = _DAYS[dow - 1] if 1 <= dow <= 7 else f"day {dow}"
                _log({
                    "account_id":    account_id,
                    "decision_type": "adjust_bid_schedule",
                    "risk_level":    "low",
                    "title":         f"Increase {day_name} bids — CPL is {improvement:.0f}% below average",
                    "description":   (
                        f"{day_name}s have a cost-per-lead of ${cpl:.2f}, which is "
                        f"{improvement:.0f}% below your 30-day average of ${avg_cpl:.2f}. "
                        f"Increasing bids by 20–30% on {day_name}s could capture more "
                        f"high-converting traffic at a similar CPL."
                    ),
                    "reasoning": (
                        "Day-of-week bid adjustments let you concentrate budget on days that "
                        "historically convert better, reducing average CPL without cutting reach."
                    ),
                    "confidence":               0.75,
                    "expected_improvement_pct": improvement,
                    "action_data": f'{{"dow": {dow}, "suggested_modifier": 0.25}}',
                })
    except Exception as e:
        logger.error("_rule_bid_schedule error: %s", e)


# ---------------------------------------------------------------------------
# Rule 3 — Budget cap likely hit
# ---------------------------------------------------------------------------

def _rule_budget_cap(account_id: int) -> None:
    sql = text("""
        SELECT
            campaign_id,
            DATE(date)                       AS d,
            SUM(cost_micros) / 1000000       AS daily_spend,
            SUM(impressions)                 AS impressions
        FROM google_ads_metrics
        WHERE account_id = :aid
          AND date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
        GROUP BY campaign_id, DATE(date)
        ORDER BY campaign_id, d DESC
    """)
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id}).fetchall()

        from collections import defaultdict
        by_camp: Dict[str, List] = defaultdict(list)
        for r in rows:
            by_camp[str(r[0])].append((r[1], float(r[2]), int(r[3])))

        for camp_id, daily in by_camp.items():
            if len(daily) < 3:
                continue
            recent_three = [d[1] for d in daily[:3]]
            max_spend = max(recent_three)
            if max_spend == 0:
                continue
            variance = (max(recent_three) - min(recent_three)) / max_spend
            if variance < 0.03:
                avg_impr = sum(d[2] for d in daily[:3]) / 3
                _log({
                    "account_id":    account_id,
                    "decision_type": "increase_budget",
                    "risk_level":    "high",
                    "campaign_id":   camp_id,
                    "title":         f"Campaign {camp_id} may be hitting daily budget",
                    "description":   (
                        f"This campaign has spent almost exactly ${max_spend:.2f} per day "
                        f"for the last 3 days (variance < 3%), a pattern that strongly suggests "
                        f"the daily budget cap is being reached. "
                        f"Average daily impressions: {avg_impr:,.0f}. "
                        f"Increasing the budget could capture additional impressions and leads."
                    ),
                    "reasoning": (
                        "When daily spend is nearly identical across multiple days, Google "
                        "is throttling delivery at the budget ceiling. Budget increases on "
                        "capped campaigns typically yield proportional lead increases."
                    ),
                    "confidence":    0.70,
                    "action_data":   f'{{"campaign_id": "{camp_id}", "current_daily_spend": {max_spend:.2f}}}',
                })
    except Exception as e:
        logger.error("_rule_budget_cap error: %s", e)


# ---------------------------------------------------------------------------
# Rule 4 — Stale ad copy refresh
# ---------------------------------------------------------------------------

def _rule_ad_copy_refresh(account_id: int) -> None:
    sql = text("""
        SELECT
            m.ad_group_id,
            m.campaign_id,
            MIN(m.date)              AS earliest_date,
            SUM(m.cost_micros) / 1000000 AS spend_30d
        FROM google_ads_metrics m
        WHERE m.account_id = :aid
          AND m.date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
          AND m.ad_group_id IS NOT NULL
        GROUP BY m.ad_group_id, m.campaign_id
        HAVING spend_30d >= 200
    """)
    recent_refresh_sql = text("""
        SELECT 1 FROM agent_decisions
        WHERE account_id   = :aid
          AND ad_group_id  = :ag_id
          AND decision_type = 'ad_copy_refresh'
          AND created_at   >= DATE_SUB(NOW(), INTERVAL 45 DAY)
        LIMIT 1
    """)
    try:
        with db.engine.connect() as conn:
            groups = conn.execute(sql, {"aid": account_id}).fetchall()
        for row in groups:
            ag_id    = str(row[0])
            camp_id  = str(row[1]) if row[1] else None
            earliest = row[2]
            spend    = float(row[3])
            days_old = (datetime.utcnow().date() - earliest).days if earliest else 45

            with db.engine.connect() as conn:
                already = conn.execute(recent_refresh_sql, {
                    "aid":   account_id,
                    "ag_id": ag_id,
                }).fetchone()
            if already:
                continue

            _log({
                "account_id":    account_id,
                "decision_type": "ad_copy_refresh",
                "risk_level":    "low",
                "campaign_id":   camp_id,
                "ad_group_id":   ag_id,
                "title":         f"Refresh ad copy for ad group {ag_id} — running {days_old} days unchanged",
                "description":   (
                    f"Ad group {ag_id} has spent ${spend:.2f} in the last 30 days "
                    f"without a copy refresh in the last 45 days. "
                    f"Fresh RSA headlines and descriptions typically lift CTR by 10–20% "
                    f"and improve Quality Score."
                ),
                "reasoning": (
                    "Ad fatigue sets in after 4–6 weeks. Rotating in new headlines keeps "
                    "CTR high, which signals relevance to Google and holds Quality Score up."
                ),
                "confidence":    0.80,
                "action_data":   f'{{"ad_group_id": "{ag_id}", "spend_30d": {spend:.2f}}}',
            })
    except Exception as e:
        logger.error("_rule_ad_copy_refresh error: %s", e)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_pending_actions(account_id: int, customer_id: str | None = None) -> List[Dict[str, Any]]:
    """
    Run all rules for account_id and insert new pending decisions.
    Returns the list of pending agent_decisions rows for this account.
    """
    if not _has_metrics(account_id):
        return []

    _rule_pause_zero_conv(account_id)
    _rule_bid_schedule(account_id)
    _rule_budget_cap(account_id)
    _rule_ad_copy_refresh(account_id)

    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, decision_type, title, description, risk_level,
                       expected_monthly_savings, expected_monthly_leads,
                       expected_improvement_pct, confidence, campaign_id, ad_group_id,
                       created_at
                FROM agent_decisions
                WHERE account_id = :aid
                  AND status = 'pending'
                  AND requires_approval = TRUE
                ORDER BY created_at DESC
                LIMIT 20
            """), {"aid": account_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.error("generate_pending_actions fetch error: %s", e)
        return []


def get_sample_actions(account_id: int) -> List[Dict[str, Any]]:
    """
    Returns 4 realistic HVAC-themed sample action dicts for accounts
    with no Google Ads data connected yet.
    """
    return [
        {
            "id":               -1,
            "decision_type":    "pause_keyword",
            "risk_level":       "medium",
            "title":            "Pause 'hvac repair diy' — 0 conversions from 47 clicks",
            "description":      (
                "'hvac repair diy' has received 47 clicks over the last 30 days at a "
                "cost of $141.00 with zero conversions. Pausing it could recover "
                "approximately $112.80/month."
            ),
            "expected_monthly_savings":  112.80,
            "expected_monthly_leads":    None,
            "expected_improvement_pct":  None,
            "confidence":                0.85,
            "campaign_id":               "sample_camp_1",
            "ad_group_id":               "sample_ag_1",
            "created_at":                datetime.utcnow(),
        },
        {
            "id":               -2,
            "decision_type":    "adjust_bid_schedule",
            "risk_level":       "low",
            "title":            "Increase Monday bids — CPL is 34% below average",
            "description":      (
                "Mondays have a cost-per-lead of $68.20, which is 34% below your "
                "30-day average of $103.30. Increasing bids by 25% on Mondays could "
                "capture more high-converting traffic at a similar CPL."
            ),
            "expected_monthly_savings":  None,
            "expected_monthly_leads":    None,
            "expected_improvement_pct":  34.0,
            "confidence":                0.75,
            "campaign_id":               "sample_camp_1",
            "ad_group_id":               None,
            "created_at":                datetime.utcnow(),
        },
        {
            "id":               -3,
            "decision_type":    "ad_copy_refresh",
            "risk_level":       "low",
            "title":            "Refresh ad copy for 'AC Installation' — running 52 days unchanged",
            "description":      (
                "The 'AC Installation' ad group has spent $387.50 in the last 30 days "
                "without a copy refresh in the last 45 days. Fresh RSA headlines and "
                "descriptions typically lift CTR by 10–20% and improve Quality Score."
            ),
            "expected_monthly_savings":  None,
            "expected_monthly_leads":    3,
            "expected_improvement_pct":  15.0,
            "confidence":                0.80,
            "campaign_id":               "sample_camp_2",
            "ad_group_id":               "sample_ag_2",
            "created_at":                datetime.utcnow(),
        },
        {
            "id":               -4,
            "decision_type":    "increase_budget",
            "risk_level":       "high",
            "title":            "'Emergency HVAC' campaign may be hitting daily budget",
            "description":      (
                "This campaign has spent almost exactly $85.00 per day for the last "
                "3 days (variance < 3%), a pattern that strongly suggests the daily "
                "budget cap is being reached. Increasing the budget could capture "
                "additional impressions and leads during peak demand."
            ),
            "expected_monthly_savings":  None,
            "expected_monthly_leads":    5,
            "expected_improvement_pct":  None,
            "confidence":                0.70,
            "campaign_id":               "sample_camp_3",
            "ad_group_id":               None,
            "created_at":                datetime.utcnow(),
        },
    ]
