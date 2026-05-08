# app/services/google_ads_optimizer_engine.py
"""
Google Ads Optimizer Engine.

Analyzes GadsStatsDaily to generate OptimizerRecommendation rows.
Designed to run after every daily sync.  Clears stale 'open' recommendations
before re-generating so the list stays current.

Recommendation categories:
  wasted_spend     — keywords with spend but zero conversions over 30d
  budget           — campaigns losing IS due to budget (lost_is_budget > 20%)
  low_qs           — keywords with quality score ≤ 4
  impression_share — campaigns losing IS due to rank (lost_is_rank > 30%)
  paused_performer — keywords paused but historically had conversions
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Thresholds
WASTED_SPEND_MIN_MICROS = 5_000_000   # $5 spend with 0 conversions → wasted
LOW_QS_THRESHOLD = 4                  # QS ≤ 4 is actionable
BUDGET_IS_LOSS_THRESHOLD = 0.20       # >20% IS lost to budget
RANK_IS_LOSS_THRESHOLD = 0.30         # >30% IS lost to rank
MIN_IMPRESSIONS = 100                 # ignore low-traffic keywords for QS


def generate_recommendations(account_id: int) -> Dict[str, Any]:
    """
    Run all analysis passes and upsert OptimizerRecommendation rows.
    Returns summary: {created, skipped, errors}.
    """
    from app import db
    from app.models_ads import (
        OptimizerRecommendation, GadsStatsDaily,
        AdsCampaign, AdsKeyword, AdsAdGroup,
    )
    from sqlalchemy import text

    summary = {"account_id": account_id, "created": 0, "errors": []}

    # ── Clear stale open recommendations for this account ──────────────────
    try:
        db.session.execute(
            text("DELETE FROM optimizer_recommendations WHERE account_id = :aid AND status = 'open'"),
            {"aid": account_id},
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Clear stale recs: {exc}")

    def _save(rec: OptimizerRecommendation):
        db.session.add(rec)
        summary["created"] += 1

    # ── 1. Wasted spend — keywords with spend but 0 conversions (30d) ──────
    try:
        rows = db.session.execute(text("""
            SELECT gs.entity_id AS kw_local_id,
                   SUM(gs.cost_micros) AS total_cost_micros,
                   SUM(gs.conversions) AS total_conversions,
                   SUM(gs.clicks) AS total_clicks,
                   k.text AS kw_text,
                   k.match_type,
                   ag.id AS ag_id,
                   ac.id AS camp_id,
                   ac.name AS camp_name
            FROM gads_stats_daily gs
            JOIN keywords k ON k.id = gs.entity_id
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE gs.entity_type = 'keyword'
              AND ac.account_id = :aid
              AND gs.date >= (CURRENT_DATE - INTERVAL 30 DAY)
              AND k.status = 'enabled'
            GROUP BY gs.entity_id, k.text, k.match_type, ag.id, ac.id, ac.name
            HAVING total_cost_micros >= :min_micros AND total_conversions = 0
            ORDER BY total_cost_micros DESC
            LIMIT 50
        """), {"aid": account_id, "min_micros": WASTED_SPEND_MIN_MICROS}).mappings().all()

        for r in rows:
            spend = r["total_cost_micros"] / 1_000_000
            action = {
                "type": "pause_keyword",
                "keyword_id": r["kw_local_id"],
                "keyword_text": r["kw_text"],
                "match_type": r["match_type"],
                "ad_group_id": r["ag_id"],
            }
            severity = 1 if spend > 50 else (2 if spend > 20 else 3)
            _save(OptimizerRecommendation(
                account_id=account_id,
                scope_type="keyword",
                scope_id=r["kw_local_id"],
                category="wasted_spend",
                title=f'Pause "{r["kw_text"]}" — ${spend:.2f} spent, 0 conversions (30d)',
                details=(
                    f'Keyword "{r["kw_text"]}" ({r["match_type"]}) in campaign '
                    f'"{r["camp_name"]}" has spent ${spend:.2f} over 30 days with '
                    f'{int(r["total_clicks"])} clicks and zero conversions. '
                    f'Pausing it will free budget for better-performing keywords.'
                ),
                expected_impact=f"Save ~${spend:.2f}/month",
                severity=severity,
                suggested_action_json=json.dumps(action),
            ))
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Wasted spend pass: {exc}")
        logger.exception("Wasted spend analysis failed for account %s", account_id)

    # ── 2. Budget-constrained campaigns (lost IS > 20% due to budget) ──────
    try:
        rows = db.session.execute(text("""
            SELECT gs.entity_id AS camp_local_id,
                   ac.name AS camp_name,
                   AVG(gs.lost_is_budget) AS avg_lost_budget,
                   AVG(gs.search_impr_share) AS avg_is,
                   SUM(gs.cost_micros) AS total_cost_micros,
                   ac.daily_budget_cents
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id
            WHERE gs.entity_type = 'campaign'
              AND ac.account_id = :aid
              AND gs.date >= (CURRENT_DATE - INTERVAL 14 DAY)
              AND gs.lost_is_budget IS NOT NULL
            GROUP BY gs.entity_id, ac.name, ac.daily_budget_cents
            HAVING avg_lost_budget >= :threshold
            ORDER BY avg_lost_budget DESC
            LIMIT 20
        """), {"aid": account_id, "threshold": BUDGET_IS_LOSS_THRESHOLD}).mappings().all()

        for r in rows:
            lost_pct = round((r["avg_lost_budget"] or 0) * 100, 1)
            current_budget = (r["daily_budget_cents"] or 0) / 100
            suggested_budget = round(current_budget * 1.30, 2)
            action = {
                "type": "increase_budget",
                "campaign_id": r["camp_local_id"],
                "current_budget_cents": r["daily_budget_cents"],
                "suggested_budget_cents": int(suggested_budget * 100),
            }
            _save(OptimizerRecommendation(
                account_id=account_id,
                scope_type="campaign",
                scope_id=r["camp_local_id"],
                category="budget",
                title=f'Increase budget for "{r["camp_name"]}" — {lost_pct}% IS lost to budget',
                details=(
                    f'Campaign "{r["camp_name"]}" is losing {lost_pct}% of available '
                    f'impressions because the daily budget of ${current_budget:.2f} runs out. '
                    f'Increasing to ${suggested_budget:.2f}/day (+30%) could recover these impressions.'
                ),
                expected_impact=f"Recover ~{lost_pct}% impression share",
                severity=2 if lost_pct > 40 else 3,
                suggested_action_json=json.dumps(action),
            ))
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Budget IS pass: {exc}")
        logger.exception("Budget IS analysis failed for account %s", account_id)

    # ── 3. Low Quality Score keywords (QS ≤ 4, meaningful traffic) ─────────
    try:
        rows = db.session.execute(text("""
            SELECT gs.entity_id AS kw_local_id,
                   k.text AS kw_text,
                   k.match_type,
                   MIN(gs.quality_score) AS qs,
                   gs.landing_page_exp,
                   gs.ad_relevance,
                   gs.expected_ctr,
                   SUM(gs.impressions) AS total_impr,
                   SUM(gs.cost_micros) AS total_cost,
                   ac.name AS camp_name,
                   ac.id AS camp_id
            FROM gads_stats_daily gs
            JOIN keywords k ON k.id = gs.entity_id
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE gs.entity_type = 'keyword'
              AND ac.account_id = :aid
              AND gs.quality_score IS NOT NULL
              AND gs.quality_score <= :qs_thresh
              AND gs.date >= (CURRENT_DATE - INTERVAL 14 DAY)
              AND k.status = 'enabled'
            GROUP BY gs.entity_id, k.text, k.match_type, gs.landing_page_exp,
                     gs.ad_relevance, gs.expected_ctr, ac.name, ac.id
            HAVING total_impr >= :min_impr
            ORDER BY qs ASC, total_cost DESC
            LIMIT 30
        """), {
            "aid": account_id,
            "qs_thresh": LOW_QS_THRESHOLD,
            "min_impr": MIN_IMPRESSIONS,
        }).mappings().all()

        for r in rows:
            qs = r["qs"] or 0
            spend = (r["total_cost"] or 0) / 1_000_000

            # Build targeted fix based on lowest sub-score
            sub_scores = {
                "Landing Page": r["landing_page_exp"],
                "Ad Relevance": r["ad_relevance"],
                "Expected CTR": r["expected_ctr"],
            }
            worst = [k for k, v in sub_scores.items() if v == "BELOW_AVERAGE"]
            fix_hint = ""
            if "Landing Page" in worst:
                fix_hint = "Improve landing page relevance and load speed."
            elif "Ad Relevance" in worst:
                fix_hint = "Add the keyword to your ad headlines and descriptions."
            elif "Expected CTR" in worst:
                fix_hint = "Write more compelling ad copy with a clear CTA."

            action = {
                "type": "fix_quality_score",
                "keyword_id": r["kw_local_id"],
                "keyword_text": r["kw_text"],
                "quality_score": qs,
                "sub_scores": dict(sub_scores),
            }
            _save(OptimizerRecommendation(
                account_id=account_id,
                scope_type="keyword",
                scope_id=r["kw_local_id"],
                category="qs",
                title=f'Low Quality Score ({qs}/10) — "{r["kw_text"]}"',
                details=(
                    f'Keyword "{r["kw_text"]}" ({r["match_type"]}) in "{r["camp_name"]}" has '
                    f'a Quality Score of {qs}/10 with {int(r["total_impr"]):,} impressions. '
                    f'Low QS raises your CPC and lowers ad position. '
                    + (f'Weakest area: {", ".join(worst)}. {fix_hint}' if worst else "")
                ),
                expected_impact=f"Reduce CPC by up to {(10 - qs) * 8}%",
                severity=1 if qs <= 2 else (2 if qs <= 3 else 3),
                suggested_action_json=json.dumps(action),
            ))
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Low QS pass: {exc}")
        logger.exception("Low QS analysis failed for account %s", account_id)

    # ── 4. Impression share lost to rank (>30%) ─────────────────────────────
    try:
        rows = db.session.execute(text("""
            SELECT gs.entity_id AS camp_local_id,
                   ac.name AS camp_name,
                   AVG(gs.lost_is_rank) AS avg_lost_rank,
                   AVG(gs.search_impr_share) AS avg_is,
                   SUM(gs.cost_micros) AS total_cost
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id
            WHERE gs.entity_type = 'campaign'
              AND ac.account_id = :aid
              AND gs.date >= (CURRENT_DATE - INTERVAL 14 DAY)
              AND gs.lost_is_rank IS NOT NULL
            GROUP BY gs.entity_id, ac.name
            HAVING avg_lost_rank >= :threshold
            ORDER BY avg_lost_rank DESC
            LIMIT 15
        """), {"aid": account_id, "threshold": RANK_IS_LOSS_THRESHOLD}).mappings().all()

        for r in rows:
            lost_pct = round((r["avg_lost_rank"] or 0) * 100, 1)
            action = {
                "type": "improve_ad_rank",
                "campaign_id": r["camp_local_id"],
                "lost_is_rank_pct": lost_pct,
            }
            _save(OptimizerRecommendation(
                account_id=account_id,
                scope_type="campaign",
                scope_id=r["camp_local_id"],
                category="impression_share",
                title=f'"{r["camp_name"]}" losing {lost_pct}% IS to Ad Rank',
                details=(
                    f'Campaign "{r["camp_name"]}" is losing {lost_pct}% of eligible impressions '
                    f'due to Ad Rank. This is caused by low Quality Scores or bids that are too '
                    f'low. Fix low-QS keywords first; then consider raising bids on top performers.'
                ),
                expected_impact=f"Recover up to {lost_pct}% impression share",
                severity=2 if lost_pct > 50 else 3,
                suggested_action_json=json.dumps(action),
            ))
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Rank IS pass: {exc}")
        logger.exception("Rank IS analysis failed for account %s", account_id)

    # ── Commit all recommendations ──────────────────────────────────────────
    try:
        db.session.commit()
        logger.info(
            "Optimizer: %d recommendations created for account %s",
            summary["created"], account_id,
        )
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Commit: {exc}")
        logger.exception("Optimizer commit failed for account %s", account_id)

    return summary
