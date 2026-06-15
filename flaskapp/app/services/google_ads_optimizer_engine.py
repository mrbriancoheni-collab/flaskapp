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
  broad_match      — broad match keywords underperforming vs phrase/exact,
                     or any broad keyword in verticals where broad rarely works
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
BROAD_MIN_SPEND_MICROS = 10_000_000   # $10 broad-match spend before we judge it
BROAD_CPA_MULTIPLIER = 2.0            # broad CPA > 2x phrase/exact CPA → flag

# Verticals where search queries are dominated by product/DIY intent, so broad
# match mostly buys irrelevant clicks ("pool pump", "lawn mower", "bug spray").
# For these we recommend phrase/exact only.
NO_BROAD_INDUSTRIES = {
    "pool", "pools", "pool_service", "pool-service", "pool maintenance",
    "pool_maintenance", "lawn", "lawn_care", "lawn-care", "lawncare",
    "pest", "pest_control", "pest-control",
    "cleaning", "house_cleaning", "house-cleaning",
}


def _load_goals(db, account_id: int) -> Dict[str, Any]:
    """
    Read the owner's stated goals from account_settings (key 'gads_goals').
    Returns {"target_cpl": float|None, "max_monthly_budget": float|None}.
    """
    from sqlalchemy import text

    goals: Dict[str, Any] = {"target_cpl": None, "max_monthly_budget": None}
    try:
        raw = db.session.execute(text(
            "SELECT setting_value FROM account_settings "
            "WHERE account_id = :aid AND setting_key = 'gads_goals' LIMIT 1"
        ), {"aid": account_id}).scalar()
        if raw:
            data = json.loads(raw)
            for key in goals:
                val = data.get(key)
                if val is not None:
                    try:
                        num = float(val)
                        if num > 0:
                            goals[key] = num
                    except (TypeError, ValueError):
                        pass
    except Exception:
        db.session.rollback()
    return goals


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

    # The owner's stated goals steer priority and framing for every pass below.
    goals = _load_goals(db, account_id)
    target_cpl = goals.get("target_cpl")
    max_monthly_budget = goals.get("max_monthly_budget")

    # Projected monthly spend if every enabled campaign hits its daily budget.
    current_monthly_budget = None
    if max_monthly_budget:
        try:
            total_daily_cents = db.session.execute(text(
                "SELECT COALESCE(SUM(daily_budget_cents), 0) FROM ads_campaigns "
                "WHERE account_id = :aid AND status = 'enabled'"
            ), {"aid": account_id}).scalar() or 0
            current_monthly_budget = round(total_daily_cents / 100 * 30.4, 2)
        except Exception:
            db.session.rollback()

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

    # Account benchmark: average cost per conversion across all keywords (30d).
    # Surfaced in the "wasted spend" detail panel so users can compare a
    # zero-conversion keyword against what a typical keyword costs per lead.
    account_avg_cpa = None
    try:
        bench = db.session.execute(text("""
            SELECT SUM(gs.cost_micros) AS cost, SUM(gs.conversions) AS conv
            FROM gads_stats_daily gs
            JOIN keywords k ON k.id = gs.entity_id
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE gs.entity_type = 'keyword'
              AND ac.account_id = :aid
              AND gs.date >= (CURRENT_DATE - INTERVAL 30 DAY)
        """), {"aid": account_id}).mappings().one_or_none()
        if bench and bench["conv"] and float(bench["conv"]) > 0:
            account_avg_cpa = round(
                (bench["cost"] or 0) / 1_000_000 / float(bench["conv"]), 2
            )
    except Exception:
        db.session.rollback()

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
                "campaign_name": r["camp_name"],
                "spend": round(spend, 2),
                "clicks": int(r["total_clicks"] or 0),
                "conversions": 0,
                "account_avg_cpa": account_avg_cpa,
                "goal_target_cpl": target_cpl,
            }
            severity = 1 if spend > 50 else (2 if spend > 20 else 3)
            goal_note = ""
            if target_cpl:
                goal_note = (
                    f' Your goal is leads under ${target_cpl:.2f} each — '
                    f'this spend bought none at all.'
                )
                if spend >= target_cpl:
                    severity = 1
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
                    + goal_note
                ),
                expected_impact=f"Save ~${spend:.2f}/month",
                severity=severity,
                suggested_action_json=json.dumps(action),
            ))
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Wasted spend pass: {exc}")
        logger.exception("Wasted spend analysis failed for account %s", account_id)

    # ── 1b. Cost per lead over goal — converting keywords above 1.5x target ─
    # Wasted-spend only covers zero-conversion keywords, so nothing here
    # duplicates a rec from pass 1.
    if target_cpl:
        try:
            cpa_limit = target_cpl * 1.5
            rows = db.session.execute(text("""
                SELECT gs.entity_id AS kw_local_id,
                       SUM(gs.cost_micros) AS total_cost_micros,
                       SUM(gs.conversions) AS total_conversions,
                       SUM(gs.clicks) AS total_clicks,
                       k.text AS kw_text,
                       k.match_type,
                       ag.id AS ag_id,
                       ac.name AS camp_name
                FROM gads_stats_daily gs
                JOIN keywords k ON k.id = gs.entity_id
                JOIN ad_groups ag ON ag.id = k.ad_group_id
                JOIN ads_campaigns ac ON ac.id = ag.campaign_id
                WHERE gs.entity_type = 'keyword'
                  AND ac.account_id = :aid
                  AND gs.date >= (CURRENT_DATE - INTERVAL 30 DAY)
                  AND k.status = 'enabled'
                GROUP BY gs.entity_id, k.text, k.match_type, ag.id, ac.name
                HAVING total_conversions > 0
                   AND (total_cost_micros / 1000000.0) / total_conversions > :cpa_limit
                ORDER BY total_cost_micros DESC
                LIMIT 50
            """), {"aid": account_id, "cpa_limit": cpa_limit}).mappings().all()

            for r in rows:
                spend = (r["total_cost_micros"] or 0) / 1_000_000
                conv = float(r["total_conversions"])
                kw_cpa = spend / conv
                action = {
                    "type": "pause_keyword",
                    "keyword_id": r["kw_local_id"],
                    "keyword_text": r["kw_text"],
                    "match_type": r["match_type"],
                    "ad_group_id": r["ag_id"],
                    "campaign_name": r["camp_name"],
                    "spend": round(spend, 2),
                    "clicks": int(r["total_clicks"] or 0),
                    "conversions": conv,
                    "keyword_cpa": round(kw_cpa, 2),
                    "account_avg_cpa": account_avg_cpa,
                    "goal_target_cpl": target_cpl,
                    "goal_violation": "cpl_over_goal",
                }
                _save(OptimizerRecommendation(
                    account_id=account_id,
                    scope_type="keyword",
                    scope_id=r["kw_local_id"],
                    category="wasted_spend",
                    title=(
                        f'"{r["kw_text"]}" costs ${kw_cpa:.2f} per lead — '
                        f'your goal is ${target_cpl:.2f}'
                    ),
                    details=(
                        f'This keyword costs ${kw_cpa:.2f} per lead — your goal is '
                        f'${target_cpl:.2f}. Over 30 days, "{r["kw_text"]}" '
                        f'({r["match_type"]}) in campaign "{r["camp_name"]}" spent '
                        f'${spend:.2f} for {conv:.0f} lead(s). Pausing it or lowering '
                        f'its bid will pull your average cost per lead toward your goal.'
                    ),
                    expected_impact=(
                        f"Save ~${(kw_cpa - target_cpl) * conv:.2f}/month vs your goal"
                    ),
                    severity=1,
                    suggested_action_json=json.dumps(action),
                ))
        except Exception as exc:
            db.session.rollback()
            summary["errors"].append(f"CPL over goal pass: {exc}")
            logger.exception("CPL over goal analysis failed for account %s", account_id)

    # ── 1c. Monthly budgets exceed the owner's cap ──────────────────────────
    if max_monthly_budget and current_monthly_budget and current_monthly_budget > max_monthly_budget:
        try:
            overage = round(current_monthly_budget - max_monthly_budget, 2)
            action = {
                "type": "trim_budgets",
                "current_monthly_budget": current_monthly_budget,
                "goal_max_monthly_budget": max_monthly_budget,
                "overage": overage,
            }
            _save(OptimizerRecommendation(
                account_id=account_id,
                scope_type="account",
                scope_id=account_id,
                category="budget",
                title=(
                    f'Campaign budgets add up to ${current_monthly_budget:,.0f}/month — '
                    f'${overage:,.0f} over your ${max_monthly_budget:,.0f} cap'
                ),
                details=(
                    f'Your campaign daily budgets add up to about '
                    f'${current_monthly_budget:,.2f} per month, which is '
                    f'${overage:,.2f} over the ${max_monthly_budget:,.2f}/month cap '
                    f'you set. Trim daily budgets — start with campaigns that get '
                    f'few leads — to stay inside your budget.'
                ),
                expected_impact=f"Keep spend under ${max_monthly_budget:,.0f}/month",
                severity=1,
                suggested_action_json=json.dumps(action),
            ))
        except Exception as exc:
            db.session.rollback()
            summary["errors"].append(f"Budget cap pass: {exc}")
            logger.exception("Budget cap analysis failed for account %s", account_id)

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

        # Headroom left under the owner's monthly cap; each suggested increase
        # below draws it down so the total never goes over.
        remaining_headroom = None
        if max_monthly_budget and current_monthly_budget is not None:
            remaining_headroom = max_monthly_budget - current_monthly_budget

        for r in rows:
            lost_pct = round((r["avg_lost_budget"] or 0) * 100, 1)
            current_budget = (r["daily_budget_cents"] or 0) / 100
            suggested_budget = round(current_budget * 1.30, 2)
            budget_note = None

            if remaining_headroom is not None:
                if remaining_headroom < 1:
                    # No room under the cap — never suggest spending more.
                    continue
                increase_monthly = (suggested_budget - current_budget) * 30.4
                if increase_monthly > remaining_headroom:
                    suggested_budget = round(
                        current_budget + remaining_headroom / 30.4, 2
                    )
                    if suggested_budget <= current_budget:
                        continue
                    increase_monthly = (suggested_budget - current_budget) * 30.4
                    budget_note = (
                        f"kept within your ${max_monthly_budget:,.0f}/month budget"
                    )
                remaining_headroom -= increase_monthly

            action = {
                "type": "increase_budget",
                "campaign_id": r["camp_local_id"],
                "campaign_name": r["camp_name"],
                "current_budget_cents": r["daily_budget_cents"],
                "suggested_budget_cents": int(suggested_budget * 100),
                "lost_is_budget_pct": lost_pct,
                "avg_impression_share_pct": round((r["avg_is"] or 0) * 100, 1),
                "goal_max_monthly_budget": max_monthly_budget,
                "budget_note": budget_note,
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
                    f'Increasing to ${suggested_budget:.2f}/day could recover these impressions'
                    + (f' — {budget_note}.' if budget_note else '.')
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
                "match_type": r["match_type"],
                "campaign_name": r["camp_name"],
                "quality_score": qs,
                "sub_scores": dict(sub_scores),
                "spend": round(spend, 2),
                "impressions": int(r["total_impr"] or 0),
                "fix_hint": fix_hint,
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
                "campaign_name": r["camp_name"],
                "lost_is_rank_pct": lost_pct,
                "avg_impression_share_pct": round((r["avg_is"] or 0) * 100, 1),
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

    # ── 5. Broad match audit ────────────────────────────────────────────────
    # Two layers:
    #   a) Vertical rule — in product/DIY-heavy industries (pool, lawn, pest,
    #      cleaning) broad match mostly buys irrelevant clicks; flag every
    #      enabled broad keyword regardless of performance.
    #   b) Performance rule — in any vertical, a broad keyword that spent
    #      ≥$10 with zero conversions, or whose CPA is >2x the account's
    #      phrase/exact CPA, should be tightened to phrase match.
    try:
        no_broad_vertical = False
        try:
            ind_row = db.session.execute(text(
                "SELECT industry FROM business_profiles WHERE account_id = :aid "
                "ORDER BY id DESC LIMIT 1"
            ), {"aid": account_id}).scalar()
            if ind_row:
                ind_norm = str(ind_row).strip().lower().replace(" ", "_")
                no_broad_vertical = any(tag in ind_norm for tag in (
                    "pool", "lawn", "pest", "cleaning"
                ))
        except Exception:
            db.session.rollback()

        # Account benchmark: CPA of phrase/exact keywords over 30d
        bench = db.session.execute(text("""
            SELECT SUM(gs.cost_micros) AS cost, SUM(gs.conversions) AS conv
            FROM gads_stats_daily gs
            JOIN keywords k ON k.id = gs.entity_id
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE gs.entity_type = 'keyword'
              AND ac.account_id = :aid
              AND gs.date >= (CURRENT_DATE - INTERVAL 30 DAY)
              AND k.match_type IN ('phrase', 'exact')
        """), {"aid": account_id}).mappings().one_or_none()
        bench_cpa = None
        if bench and bench["conv"] and float(bench["conv"]) > 0:
            bench_cpa = (bench["cost"] or 0) / 1_000_000 / float(bench["conv"])

        rows = db.session.execute(text("""
            SELECT k.id AS kw_local_id,
                   k.text AS kw_text,
                   ag.id AS ag_id,
                   ac.name AS camp_name,
                   COALESCE(SUM(gs.cost_micros), 0) AS total_cost_micros,
                   COALESCE(SUM(gs.conversions), 0) AS total_conversions,
                   COALESCE(SUM(gs.clicks), 0) AS total_clicks
            FROM keywords k
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            LEFT JOIN gads_stats_daily gs ON gs.entity_type = 'keyword'
                 AND gs.entity_id = k.id
                 AND gs.date >= (CURRENT_DATE - INTERVAL 30 DAY)
            WHERE ac.account_id = :aid
              AND k.status = 'enabled'
              AND k.match_type = 'broad'
            GROUP BY k.id, k.text, ag.id, ac.name
            ORDER BY total_cost_micros DESC
            LIMIT 50
        """), {"aid": account_id}).mappings().all()

        for r in rows:
            spend = (r["total_cost_micros"] or 0) / 1_000_000
            conv = float(r["total_conversions"] or 0)
            kw_cpa = (spend / conv) if conv > 0 else None

            flagged = False
            reason = ""
            severity = 3

            if no_broad_vertical:
                flagged = True
                reason = (
                    "Your industry sees heavy product/DIY search traffic, so broad "
                    "match tends to buy clicks from shoppers and DIYers instead of "
                    "service customers. Phrase or exact match keeps your ads on "
                    "hire-intent searches."
                )
                severity = 2 if spend > 20 else 3
            elif spend >= BROAD_MIN_SPEND_MICROS / 1_000_000 and conv == 0:
                flagged = True
                reason = (
                    f"This broad keyword has spent ${spend:.2f} over 30 days with "
                    f"{int(r['total_clicks'])} clicks and zero conversions — broad "
                    f"match is likely pulling in irrelevant searches."
                )
                severity = 2
            elif bench_cpa and kw_cpa and kw_cpa > bench_cpa * BROAD_CPA_MULTIPLIER:
                flagged = True
                reason = (
                    f"This broad keyword's cost per lead (${kw_cpa:.2f}) is more than "
                    f"double your phrase/exact average (${bench_cpa:.2f})."
                )
                severity = 2

            if not flagged:
                continue

            if target_cpl and kw_cpa and kw_cpa > target_cpl * 1.5:
                severity = 1
                reason += (
                    f" At ${kw_cpa:.2f} per lead it is also well over your "
                    f"${target_cpl:.2f} goal."
                )

            action = {
                "type": "change_match_type",
                "keyword_id": r["kw_local_id"],
                "keyword_text": r["kw_text"],
                "from": "broad",
                "to": "phrase",
                "ad_group_id": r["ag_id"],
                "campaign_name": r["camp_name"],
                "spend": round(spend, 2),
                "clicks": int(r["total_clicks"] or 0),
                "conversions": conv,
                "keyword_cpa": round(kw_cpa, 2) if kw_cpa else None,
                "benchmark_cpa": round(bench_cpa, 2) if bench_cpa else None,
                "goal_target_cpl": target_cpl,
                "reason": reason,
            }
            _save(OptimizerRecommendation(
                account_id=account_id,
                scope_type="keyword",
                scope_id=r["kw_local_id"],
                category="broad_match",
                title=f'Switch "{r["kw_text"]}" from broad to phrase match',
                details=(
                    f'Keyword "{r["kw_text"]}" (broad) in campaign "{r["camp_name"]}". '
                    + reason
                    + ' Switching to phrase match keeps the reach for relevant '
                      'searches while filtering out loosely related queries.'
                ),
                expected_impact=(
                    f"Save up to ${spend:.2f}/month in off-target clicks"
                    if spend > 0 else "Prevent off-target spend before it starts"
                ),
                severity=severity,
                suggested_action_json=json.dumps(action),
            ))
    except Exception as exc:
        db.session.rollback()
        summary["errors"].append(f"Broad match pass: {exc}")
        logger.exception("Broad match analysis failed for account %s", account_id)

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
