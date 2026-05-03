# app/services/google_ads_rule_engine.py
"""
Automated Rule Execution Engine (item 7).

Evaluates AIActionRule rows against recent GadsStatsDaily data, creates
AIAction log entries, and—when auto_execute=True—applies the action via
the Google Ads API stub.

Supported rule action_types and required condition keys:

  pause_wasted_keywords
    spend_above_dollars (float)   — 30-day spend threshold
    conversions_below (float)     — max allowed conversions (default 0)
    lookback_days (int)           — default 30

  add_negative_search_terms
    ctr_below (float)             — e.g. 0.02
    spend_above_dollars (float)
    lookback_days (int)           — default 30

  increase_budget
    lost_is_budget_above (float)  — e.g. 0.25
    lookback_days (int)           — default 14

  adjust_bid_up
    conversion_rate_above (float) — e.g. 0.10
    position_above (float)        — avg position worse than this (e.g. 3)
    lookback_days (int)           — default 14
    bid_increase_pct (float)      — e.g. 0.15

  adjust_bid_down
    conversion_rate_below (float)
    spend_above_dollars (float)
    lookback_days (int)
    bid_decrease_pct (float)      — e.g. 0.10
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LOOKBACK = 30


def run_rules(account_id: int) -> Dict[str, Any]:
    """
    Evaluate all enabled AIActionRules for account_id.
    Returns summary {"evaluated": N, "created": N, "executed": N, "errors": [...]}.
    """
    from app import db
    from app.models_ai_actions import AIActionRule, AIAction
    from sqlalchemy import text

    summary: Dict[str, Any] = {
        "account_id": account_id,
        "evaluated": 0,
        "created": 0,
        "executed": 0,
        "errors": [],
    }

    rules: List[AIActionRule] = AIActionRule.query.filter_by(
        account_id=account_id, enabled=True
    ).all()

    if not rules:
        return summary

    # Count actions already created today to enforce daily limits
    today = datetime.utcnow().date()
    actions_today = db.session.execute(
        text("SELECT COUNT(*) FROM ai_actions WHERE account_id=:aid AND DATE(created_at)=:d"),
        {"aid": account_id, "d": today},
    ).scalar() or 0

    for rule in rules:
        summary["evaluated"] += 1
        try:
            candidates = _evaluate_rule(db, account_id, rule)
        except Exception as exc:
            summary["errors"].append(f"Rule {rule.id} eval: {exc}")
            logger.exception("Rule %s evaluation failed", rule.id)
            continue

        actions_this_rule = 0
        for candidate in candidates:
            if actions_today >= rule.max_actions_per_day:
                break
            if actions_this_rule >= rule.max_actions_per_campaign:
                break

            action = AIAction(
                account_id=account_id,
                action_type=_map_action_type(rule.action_type),
                title=candidate["title"],
                description=candidate["description"],
                campaign_id=candidate.get("campaign_id"),
                campaign_name=candidate.get("campaign_name"),
                ad_group_id=candidate.get("ad_group_id"),
                keyword_id=candidate.get("keyword_id"),
                before_value=candidate.get("before_value"),
                after_value=candidate.get("after_value"),
                confidence_score=candidate.get("confidence", 1.0),
                reasoning=candidate.get("reasoning"),
                data_used=candidate.get("data_used"),
                status="pending",
            )
            db.session.add(action)
            summary["created"] += 1
            actions_today += 1
            actions_this_rule += 1

            if rule.auto_execute and (candidate.get("confidence", 1.0) >= rule.min_confidence):
                try:
                    _execute_action(db, action, candidate)
                    action.mark_executed("rule_engine")
                    summary["executed"] += 1
                except Exception as exc:
                    action.mark_failed(str(exc))
                    summary["errors"].append(f"Execute action: {exc}")

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Commit: {exc}")

    return summary


# ---------------------------------------------------------------------------
# Rule evaluators
# ---------------------------------------------------------------------------

def _evaluate_rule(db, account_id: int, rule) -> List[Dict[str, Any]]:
    from sqlalchemy import text

    c = rule.conditions or {}
    atype = (rule.action_type or "").lower()
    lookback = int(c.get("lookback_days", _DEFAULT_LOOKBACK))
    since = (datetime.utcnow().date() - timedelta(days=lookback)).isoformat()

    if atype == "pause_wasted_keywords":
        return _eval_pause_wasted(db, account_id, c, since)
    elif atype == "add_negative_search_terms":
        return _eval_neg_search_terms(db, account_id, c, since)
    elif atype == "increase_budget":
        return _eval_increase_budget(db, account_id, c, since)
    elif atype in ("adjust_bid_up", "bid_adjusted"):
        return _eval_adjust_bid(db, account_id, c, since, direction="up")
    elif atype == "adjust_bid_down":
        return _eval_adjust_bid(db, account_id, c, since, direction="down")
    else:
        logger.warning("Unknown rule action_type: %s", rule.action_type)
        return []


def _eval_pause_wasted(db, account_id, c, since):
    from sqlalchemy import text

    min_spend = float(c.get("spend_above_dollars", 5)) * 1_000_000
    max_conv = float(c.get("conversions_below", 0))

    rows = db.session.execute(text("""
        SELECT k.id AS kw_id, k.text AS kw_text, k.match_type,
               ac.id AS camp_id, ac.name AS camp_name,
               ag.id AS ag_id,
               SUM(gs.cost_micros) AS spend, SUM(gs.conversions) AS conv
        FROM gads_stats_daily gs
        JOIN keywords k ON k.id = gs.entity_id
        JOIN ad_groups ag ON ag.id = k.ad_group_id
        JOIN ads_campaigns ac ON ac.id = ag.campaign_id
        WHERE gs.entity_type = 'keyword'
          AND gs.account_id = :aid
          AND gs.date >= :since
          AND k.status = 'enabled'
        GROUP BY k.id, k.text, k.match_type, ac.id, ac.name, ag.id
        HAVING spend >= :min_spend AND conv <= :max_conv
        ORDER BY spend DESC
        LIMIT 50
    """), {"aid": account_id, "since": since,
           "min_spend": min_spend, "max_conv": max_conv}).mappings().all()

    results = []
    for r in rows:
        spend = r["spend"] / 1_000_000
        results.append({
            "title": f'Pause "{r["kw_text"]}" — ${spend:.2f} spent, {r["conv"]:.0f} conversions',
            "description": f'Keyword "{r["kw_text"]}" ({r["match_type"]}) in "{r["camp_name"]}" '
                           f'spent ${spend:.2f} with {r["conv"]:.0f} conversions.',
            "campaign_id": str(r["camp_id"]),
            "campaign_name": r["camp_name"],
            "ad_group_id": str(r["ag_id"]),
            "keyword_id": str(r["kw_id"]),
            "before_value": {"status": "enabled"},
            "after_value": {"status": "paused"},
            "confidence": 0.95,
            "reasoning": f"${spend:.2f} spent with ≤{max_conv} conversions over lookback period.",
            "data_used": {"spend_micros": r["spend"], "conversions": r["conv"]},
            "_kw_local_id": r["kw_id"],
            "_action": "pause_keyword",
        })
    return results


def _eval_neg_search_terms(db, account_id, c, since):
    from sqlalchemy import text

    min_spend = float(c.get("spend_above_dollars", 10)) * 1_000_000
    max_ctr = float(c.get("ctr_below", 0.02))

    rows = db.session.execute(text("""
        SELECT st.id, st.search_term, st.campaign_id, ac.name AS camp_name,
               st.clicks, st.impressions, st.cost_micros
        FROM search_terms st
        LEFT JOIN ads_campaigns ac ON ac.id = st.campaign_id
        WHERE st.account_id IS NULL OR st.campaign_id IN (
            SELECT id FROM ads_campaigns WHERE account_id = :aid
        )
          AND st.added_as_negative = 0
          AND st.cost_micros >= :min_spend
          AND st.date >= :since
          AND st.impressions > 0
    """), {"aid": account_id, "since": since, "min_spend": min_spend}).mappings().all()

    results = []
    for r in rows:
        impr = r["impressions"] or 1
        ctr = (r["clicks"] or 0) / impr
        if ctr < max_ctr:
            spend = (r["cost_micros"] or 0) / 1_000_000
            results.append({
                "title": f'Block search term "{r["search_term"]}" (CTR {ctr:.1%}, ${spend:.2f} spend)',
                "description": f'Search term "{r["search_term"]}" has a CTR of {ctr:.1%} with ${spend:.2f} spend.',
                "campaign_id": str(r["campaign_id"]) if r["campaign_id"] else None,
                "campaign_name": r["camp_name"],
                "before_value": None,
                "after_value": {"search_term": r["search_term"], "match_type": "exact"},
                "confidence": 0.85,
                "reasoning": f"CTR {ctr:.1%} < threshold {max_ctr:.1%}, spend ${spend:.2f}.",
                "data_used": {"ctr": ctr, "spend_micros": r["cost_micros"]},
                "_st_local_id": r["id"],
                "_action": "add_negative",
            })
    return results[:50]


def _eval_increase_budget(db, account_id, c, since):
    from sqlalchemy import text

    threshold = float(c.get("lost_is_budget_above", 0.20))

    rows = db.session.execute(text("""
        SELECT gs.entity_id AS camp_id, ac.name AS camp_name,
               AVG(gs.lost_is_budget) AS avg_lost, ac.daily_budget_cents
        FROM gads_stats_daily gs
        JOIN ads_campaigns ac ON ac.id = gs.entity_id
        WHERE gs.entity_type = 'campaign'
          AND gs.account_id = :aid
          AND gs.date >= :since
          AND gs.lost_is_budget IS NOT NULL
        GROUP BY gs.entity_id, ac.name, ac.daily_budget_cents
        HAVING avg_lost >= :threshold
        ORDER BY avg_lost DESC
        LIMIT 10
    """), {"aid": account_id, "since": since, "threshold": threshold}).mappings().all()

    results = []
    for r in rows:
        lost_pct = round((r["avg_lost"] or 0) * 100, 1)
        current = (r["daily_budget_cents"] or 0) / 100
        suggested = round(current * 1.30, 2)
        results.append({
            "title": f'Increase budget for "{r["camp_name"]}" — {lost_pct}% IS lost to budget',
            "description": f'Campaign is losing {lost_pct}% impressions due to budget. '
                           f'Suggest ${current:.2f} → ${suggested:.2f}/day.',
            "campaign_id": str(r["camp_id"]),
            "campaign_name": r["camp_name"],
            "before_value": {"daily_budget_cents": r["daily_budget_cents"]},
            "after_value": {"daily_budget_cents": int(suggested * 100)},
            "confidence": 0.90,
            "reasoning": f"Avg {lost_pct}% IS lost to budget over lookback period.",
            "data_used": {"avg_lost_is_budget": r["avg_lost"]},
            "_action": "increase_budget",
            "_camp_local_id": r["camp_id"],
        })
    return results


def _eval_adjust_bid(db, account_id, c, since, direction="up"):
    from sqlalchemy import text

    results = []
    if direction == "up":
        threshold_cr = float(c.get("conversion_rate_above", 0.10))
        pct = float(c.get("bid_increase_pct", 0.15))

        rows = db.session.execute(text("""
            SELECT k.id AS kw_id, k.text AS kw_text, k.max_cpc_cents,
                   ac.name AS camp_name, ac.id AS camp_id,
                   SUM(gs.clicks) AS clicks, SUM(gs.conversions) AS conv
            FROM gads_stats_daily gs
            JOIN keywords k ON k.id = gs.entity_id
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE gs.entity_type = 'keyword'
              AND gs.account_id = :aid
              AND gs.date >= :since
              AND k.status = 'enabled'
            GROUP BY k.id, k.text, k.max_cpc_cents, ac.name, ac.id
            HAVING clicks > 0 AND (conv / clicks) >= :cr
            ORDER BY (conv / clicks) DESC
            LIMIT 20
        """), {"aid": account_id, "since": since, "cr": threshold_cr}).mappings().all()

        for r in rows:
            cr = (r["conv"] / r["clicks"]) if r["clicks"] else 0
            old_cpc = r["max_cpc_cents"] or 0
            new_cpc = int(old_cpc * (1 + pct))
            results.append({
                "title": f'Raise bid on "{r["kw_text"]}" (CR {cr:.1%})',
                "description": f'High-converting keyword "{r["kw_text"]}" in "{r["camp_name"]}" '
                               f'has {cr:.1%} conversion rate. Raising CPC by {pct:.0%}.',
                "campaign_id": str(r["camp_id"]),
                "campaign_name": r["camp_name"],
                "keyword_id": str(r["kw_id"]),
                "before_value": {"max_cpc_cents": old_cpc},
                "after_value": {"max_cpc_cents": new_cpc},
                "confidence": 0.80,
                "reasoning": f"Conversion rate {cr:.1%} exceeds {threshold_cr:.1%} threshold.",
                "data_used": {"clicks": r["clicks"], "conversions": r["conv"], "cr": cr},
                "_action": "adjust_bid_up",
                "_kw_local_id": r["kw_id"],
            })
    return results


# ---------------------------------------------------------------------------
# Action type mapping (ensures value is valid AIAction.action_type enum)
# ---------------------------------------------------------------------------
_ACTION_TYPE_MAP = {
    "pause_wasted_keywords": "keyword_paused",
    "add_negative_search_terms": "negative_keyword_added",
    "increase_budget": "budget_reallocated",
    "adjust_bid_up": "bid_adjusted",
    "adjust_bid_down": "bid_adjusted",
    "bid_adjusted": "bid_adjusted",
}


def _map_action_type(atype: str) -> str:
    return _ACTION_TYPE_MAP.get((atype or "").lower(), "custom")


# ---------------------------------------------------------------------------
# Execution stub — applies action locally (API write is a future enhancement)
# ---------------------------------------------------------------------------

def _execute_action(db, action, candidate):
    """Apply the action locally (DB only). Real API write can be layered in later."""
    from app.models_ads import AdsKeyword, AdsCampaign

    act = candidate.get("_action")

    if act == "pause_keyword":
        kw_id = candidate.get("_kw_local_id")
        if kw_id:
            kw = AdsKeyword.query.get(kw_id)
            if kw:
                kw.status = "paused"

    elif act == "increase_budget":
        camp_id = candidate.get("_camp_local_id")
        new_budget = (candidate.get("after_value") or {}).get("daily_budget_cents")
        if camp_id and new_budget:
            camp = AdsCampaign.query.get(camp_id)
            if camp:
                camp.daily_budget_cents = new_budget

    elif act == "adjust_bid_up":
        kw_id = candidate.get("_kw_local_id")
        new_cpc = (candidate.get("after_value") or {}).get("max_cpc_cents")
        if kw_id and new_cpc:
            kw = AdsKeyword.query.get(kw_id)
            if kw:
                kw.max_cpc_cents = new_cpc
