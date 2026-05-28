# app/services/google_ads_health_score.py
"""
7-dimension Google Ads health score service.

compute_health_score(account_id, aid_goals=None) -> dict
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


def _grade(overall: int) -> str:
    if overall >= 90: return "A+"
    if overall >= 85: return "A"
    if overall >= 80: return "A-"
    if overall >= 75: return "B+"
    if overall >= 70: return "B"
    if overall >= 65: return "B-"
    if overall >= 60: return "C+"
    if overall >= 55: return "C"
    if overall >= 50: return "C-"
    if overall >= 40: return "D"
    return "F"


def _color(score: int) -> str:
    if score >= 75:
        return "green"
    if score >= 50:
        return "yellow"
    return "red"


def compute_health_score(account_id: int, aid_goals=None) -> dict:
    """
    Compute a 7-dimension health score for a Google Ads account.

    Parameters
    ----------
    account_id : int
        The account to score.
    aid_goals : optional dict or AdsAccountGoal model instance
        If provided, goal_performance section is populated.

    Returns
    -------
    dict with keys: overall, grade, dimensions, top_issues, goal_performance (optional)
    """
    from app import db
    from sqlalchemy import text

    today = date.today()
    thirty_ago = today - timedelta(days=30)

    def _safe_scalar(sql, params=None):
        try:
            result = db.session.execute(text(sql), params or {}).scalar()
            return result if result is not None else 0
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return 0

    def _safe_query(sql, params=None):
        try:
            return db.session.execute(text(sql), params or {}).mappings().one_or_none()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return None

    # ------------------------------------------------------------------ #
    # Dimension 1: Waste Control (weight 20%)
    # Ratio of negative keywords to active keywords
    # ------------------------------------------------------------------ #
    waste_score = 50  # default
    waste_detail = "No data available for waste control analysis."
    try:
        kw_count = _safe_scalar(
            """SELECT COUNT(*) FROM keywords k
               JOIN ad_groups ag ON ag.id = k.ad_group_id
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND k.status != 'removed'""",
            {"aid": account_id}
        )
        neg_count = _safe_scalar(
            """SELECT COUNT(*) FROM negative_keywords nk
               LEFT JOIN ads_campaigns ac ON ac.id = nk.campaign_id
               WHERE (ac.account_id = :aid OR nk.campaign_id IS NULL) AND nk.id IS NOT NULL""",
            {"aid": account_id}
        )
        if kw_count == 0:
            waste_score = 10
            waste_detail = "No active keywords found. Add keywords before blocking negative searches."
        elif neg_count == 0:
            waste_score = 10
            waste_detail = "You have no negative keywords — your ads may be showing for irrelevant searches and wasting budget."
        else:
            # 0 negatives = 10, 1:1 ratio = 100, scale linearly up to 1:2.5
            ratio = neg_count / max(kw_count, 1)
            waste_score = min(100, int((ratio / 2.5) * 100))
            if waste_score < 30:
                waste_detail = f"You have only {neg_count} negative keywords blocking irrelevant searches — add more to protect your budget."
            elif waste_score < 60:
                waste_detail = f"You have {neg_count} negative keywords. Adding more will block wasted clicks and reduce cost."
            else:
                waste_detail = f"You have {neg_count} negative keywords blocking irrelevant searches — good job protecting your budget."
    except Exception:
        pass

    # ------------------------------------------------------------------ #
    # Dimension 2: Account Structure (weight 15%)
    # ------------------------------------------------------------------ #
    struct_score = 20  # base
    struct_detail = "No campaign data found."
    try:
        camp_count = _safe_scalar(
            "SELECT COUNT(*) FROM ads_campaigns WHERE account_id = :aid AND status != 'removed'",
            {"aid": account_id}
        )
        ag_count = _safe_scalar(
            """SELECT COUNT(*) FROM ad_groups ag
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND ag.status != 'removed'""",
            {"aid": account_id}
        )
        ad_count = _safe_scalar(
            """SELECT COUNT(*) FROM ads a
               JOIN ad_groups ag ON ag.id = a.ad_group_id
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND a.status != 'removed'""",
            {"aid": account_id}
        )
        kw_count_struct = _safe_scalar(
            """SELECT COUNT(*) FROM keywords k
               JOIN ad_groups ag ON ag.id = k.ad_group_id
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE ac.account_id = :aid AND k.status != 'removed'""",
            {"aid": account_id}
        )

        ads_per_ag = ad_count / max(ag_count, 1)
        kw_per_ag = kw_count_struct / max(ag_count, 1)

        struct_score = 20
        detail_parts = []

        if 2 <= camp_count <= 10:
            struct_score += 20
        else:
            if camp_count < 2:
                detail_parts.append(f"You only have {camp_count} campaign — consider adding more to organize your targeting better.")
            else:
                detail_parts.append(f"You have {camp_count} campaigns — having fewer well-structured campaigns is usually more effective.")

        if 3 <= ads_per_ag <= 5:
            struct_score += 30
        elif ads_per_ag >= 2:
            struct_score += 15
            detail_parts.append(f"Some ad groups have only {int(ads_per_ag)} ads. Aim for 3–5 ads per ad group to improve testing.")
        else:
            ads_needed = max(0, 3 - int(ads_per_ag)) * max(ag_count, 1)
            detail_parts.append(f"Many ad groups have fewer than 3 ads. Add at least {ads_needed} more ads to improve coverage.")

        if 5 <= kw_per_ag <= 20:
            struct_score += 30
        elif kw_per_ag >= 3:
            struct_score += 15
            detail_parts.append(f"Ad groups average {kw_per_ag:.0f} keywords — aim for 5–20 for best relevance.")
        else:
            detail_parts.append(f"Ad groups average only {kw_per_ag:.0f} keyword(s) each — add more tightly themed keywords.")

        struct_score = min(100, struct_score)

        if not detail_parts:
            struct_detail = (
                f"Your structure looks solid: {camp_count} campaigns, "
                f"{ag_count} ad groups, averaging {ads_per_ag:.1f} ads and {kw_per_ag:.0f} keywords per ad group."
            )
        else:
            struct_detail = " ".join(detail_parts)
    except Exception:
        pass

    # ------------------------------------------------------------------ #
    # Dimension 3: Click Performance (weight 20%)
    # Avg CTR over last 30 days
    # ------------------------------------------------------------------ #
    ctr_score = 50
    ctr_detail = "No click data available for the last 30 days."
    try:
        ctr_row = _safe_query(
            """SELECT SUM(gs.clicks) AS clicks, SUM(gs.impressions) AS impressions
               FROM gads_stats_daily gs
               JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
               WHERE gs.entity_type = 'campaign' AND gs.date >= :d""",
            {"aid": account_id, "d": thirty_ago}
        )
        if ctr_row and (ctr_row["impressions"] or 0) > 0:
            ctr_val = (ctr_row["clicks"] or 0) / ctr_row["impressions"] * 100
            if ctr_val < 1:
                ctr_score = 10
            elif ctr_val < 2:
                ctr_score = 30
            elif ctr_val < 3:
                ctr_score = 50
            elif ctr_val < 4:
                ctr_score = 65
            elif ctr_val < 5:
                ctr_score = 75
            elif ctr_val < 6:
                ctr_score = 85
            else:
                ctr_score = 95

            if ctr_val >= 5:
                ctr_detail = f"Your click-through rate of {ctr_val:.1f}% is above average for home services — great job writing compelling ads."
            elif ctr_val >= 3:
                ctr_detail = f"Your click-through rate of {ctr_val:.1f}% is decent. Improving ad headlines could push this higher."
            else:
                ctr_detail = f"Your click-through rate is only {ctr_val:.1f}%. Rewriting your ad headlines to be more specific can double clicks without spending more."
    except Exception:
        pass

    # ------------------------------------------------------------------ #
    # Dimension 4: Quality Scores (weight 15%)
    # Avg quality score from gads_stats_daily keyword rows last 30 days
    # ------------------------------------------------------------------ #
    qs_score = 50
    qs_detail = "No quality score data available — sync your account to get keyword grades."
    try:
        qs_row = _safe_query(
            """SELECT AVG(gs.quality_score) AS avg_qs,
                      SUM(CASE WHEN gs.quality_score < 5 THEN 1 ELSE 0 END) AS low_qs_count
               FROM gads_stats_daily gs
               JOIN keywords k ON k.id = gs.entity_id
               JOIN ad_groups ag ON ag.id = k.ad_group_id
               JOIN ads_campaigns ac ON ac.id = ag.campaign_id
               WHERE gs.entity_type = 'keyword' AND ac.account_id = :aid
                 AND gs.date >= :d AND gs.quality_score IS NOT NULL""",
            {"aid": account_id, "d": thirty_ago}
        )
        if qs_row and qs_row["avg_qs"] is not None:
            avg_qs = float(qs_row["avg_qs"])
            low_qs = int(qs_row["low_qs_count"] or 0)
            if avg_qs < 5:
                qs_score = 20
            elif avg_qs < 6:
                qs_score = 45
            elif avg_qs < 7:
                qs_score = 65
            elif avg_qs < 8:
                qs_score = 80
            elif avg_qs < 9:
                qs_score = 90
            else:
                qs_score = 100

            if low_qs > 0:
                qs_detail = (
                    f"{low_qs} keyword(s) have quality scores below 5. "
                    f"Improve ad copy relevance and landing pages to lower your cost per click. "
                    f"Your average quality score is {avg_qs:.1f}/10."
                )
            else:
                qs_detail = f"Your average keyword quality score is {avg_qs:.1f}/10 — Google considers your ads highly relevant to your keywords."
        else:
            qs_score = 50
            qs_detail = "No quality score data for the last 30 days. Sync your account to see keyword grades."
    except Exception:
        pass

    # ------------------------------------------------------------------ #
    # Dimension 5: Conversion Efficiency (weight 15%)
    # CVR (conversions/clicks) last 30 days
    # ------------------------------------------------------------------ #
    conv_score = 50
    conv_detail = "No conversion data available for the last 30 days."
    try:
        conv_row = _safe_query(
            """SELECT SUM(gs.clicks) AS clicks, SUM(gs.conversions) AS conversions
               FROM gads_stats_daily gs
               JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
               WHERE gs.entity_type = 'campaign' AND gs.date >= :d""",
            {"aid": account_id, "d": thirty_ago}
        )
        if conv_row and (conv_row["clicks"] or 0) > 0:
            cvr = (conv_row["conversions"] or 0) / conv_row["clicks"] * 100
            if cvr < 2:
                conv_score = 20
            elif cvr < 4:
                conv_score = 50
            elif cvr < 6:
                conv_score = 65
            elif cvr < 8:
                conv_score = 75
            elif cvr < 10:
                conv_score = 85
            else:
                conv_score = 95

            if cvr >= 8:
                conv_detail = f"You're converting {cvr:.1f}% of clicks into leads — solid. Industry average is 6–8%."
            elif cvr >= 5:
                conv_detail = f"You're converting {cvr:.1f}% of clicks into leads — close to average. Improving your landing page could push this higher."
            else:
                conv_detail = f"Only {cvr:.1f}% of your clicks turn into leads. Review your landing page — it may not match what your ads promise."
    except Exception:
        pass

    # ------------------------------------------------------------------ #
    # Dimension 6: Budget Efficiency (weight 10%)
    # Avg lost impression share due to budget, last 30 days (campaign stats)
    # ------------------------------------------------------------------ #
    budget_score = 70
    budget_detail = "No budget loss data available for the last 30 days."
    try:
        budget_row = _safe_query(
            """SELECT AVG(gs.lost_is_budget) AS avg_lost,
                      AVG(gs.cost_micros) / 1000000.0 AS avg_daily_cost,
                      SUM(gs.conversions) AS total_conv,
                      COUNT(DISTINCT gs.date) AS days
               FROM gads_stats_daily gs
               JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
               WHERE gs.entity_type = 'campaign' AND gs.date >= :d""",
            {"aid": account_id, "d": thirty_ago}
        )
        if budget_row and budget_row["avg_lost"] is not None:
            loss = float(budget_row["avg_lost"])
            if loss <= 0:
                budget_score = 100
                budget_detail = "Your budget is not limiting your ad delivery — you're capturing all available impressions."
            elif loss <= 0.10:
                budget_score = 85
                budget_detail = f"You're losing about {loss*100:.0f}% of impressions to budget limits — minor, but worth monitoring."
            elif loss <= 0.20:
                budget_score = 65
                avg_cost = float(budget_row["avg_daily_cost"] or 0)
                budget_detail = f"You're losing {loss*100:.0f}% of ad impressions due to budget. A small daily budget increase could add more leads."
            elif loss <= 0.30:
                budget_score = 45
                total_conv = float(budget_row["total_conv"] or 0)
                days = int(budget_row["days"] or 30)
                avg_cost = float(budget_row["avg_daily_cost"] or 0)
                cpa = (avg_cost * days / total_conv) if total_conv > 0 else 0
                extra_leads = round(loss * 4) if loss > 0 else 0
                extra_budget = round(extra_leads * cpa) if cpa > 0 else 0
                budget_detail = (
                    f"You're losing {loss*100:.0f}% of impressions due to budget. "
                    f"Increasing budget by ${extra_budget}/day could add ~{extra_leads} more leads/month."
                    if extra_budget > 0 else
                    f"You're losing {loss*100:.0f}% of ad impressions due to budget."
                )
            else:
                budget_score = 20
                budget_detail = (
                    f"You're losing {loss*100:.0f}% of ad impressions because your budget runs out. "
                    "This is significantly limiting your reach — consider increasing your daily budget."
                )
    except Exception:
        pass

    # ------------------------------------------------------------------ #
    # Dimension 7: Search Coverage (weight 5%)
    # Avg search impression share from campaign stats
    # ------------------------------------------------------------------ #
    coverage_score = 50
    coverage_detail = "No search impression share data available."
    try:
        cov_row = _safe_query(
            """SELECT AVG(gs.search_impr_share) AS avg_share
               FROM gads_stats_daily gs
               JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
               WHERE gs.entity_type = 'campaign' AND gs.date >= :d
                 AND gs.search_impr_share IS NOT NULL""",
            {"aid": account_id, "d": thirty_ago}
        )
        if cov_row and cov_row["avg_share"] is not None:
            share = float(cov_row["avg_share"])
            share_pct = share * 100
            if share < 0.20:
                coverage_score = 20
                coverage_detail = f"You're capturing only {share_pct:.0f}% of available searches. Many potential customers aren't seeing your ads."
            elif share < 0.35:
                coverage_score = 40
                coverage_detail = f"You're capturing {share_pct:.0f}% of available searches. Expanding to phrase match could reach more buyers."
            elif share < 0.50:
                coverage_score = 60
                coverage_detail = f"You're capturing {share_pct:.0f}% of available searches — decent, but there's room to grow."
            elif share < 0.65:
                coverage_score = 75
                coverage_detail = f"You're capturing {share_pct:.0f}% of searches — good coverage in your target area."
            elif share < 0.80:
                coverage_score = 88
                coverage_detail = f"You're capturing {share_pct:.0f}% of searches — strong coverage."
            else:
                coverage_score = 100
                coverage_detail = f"Excellent — you're capturing {share_pct:.0f}% of available searches in your market."
    except Exception:
        pass

    # ------------------------------------------------------------------ #
    # Weighted overall score
    # ------------------------------------------------------------------ #
    overall = int(
        waste_score    * 0.20 +
        struct_score   * 0.15 +
        ctr_score      * 0.20 +
        qs_score       * 0.15 +
        conv_score     * 0.15 +
        budget_score   * 0.10 +
        coverage_score * 0.05
    )
    overall = max(0, min(100, overall))
    grade = _grade(overall)

    dimensions = {
        "waste_control": {
            "score": waste_score,
            "label": "Waste Control",
            "detail": waste_detail,
            "color": _color(waste_score),
        },
        "account_structure": {
            "score": struct_score,
            "label": "Account Structure",
            "detail": struct_detail,
            "color": _color(struct_score),
        },
        "click_performance": {
            "score": ctr_score,
            "label": "Click Performance",
            "detail": ctr_detail,
            "color": _color(ctr_score),
        },
        "quality_scores": {
            "score": qs_score,
            "label": "Ad Quality",
            "detail": qs_detail,
            "color": _color(qs_score),
        },
        "conversion_efficiency": {
            "score": conv_score,
            "label": "Conversion Efficiency",
            "detail": conv_detail,
            "color": _color(conv_score),
        },
        "budget_efficiency": {
            "score": budget_score,
            "label": "Budget Efficiency",
            "detail": budget_detail,
            "color": _color(budget_score),
        },
        "search_coverage": {
            "score": coverage_score,
            "label": "Search Coverage",
            "detail": coverage_detail,
            "color": _color(coverage_score),
        },
    }

    # ------------------------------------------------------------------ #
    # Top Issues
    # ------------------------------------------------------------------ #
    top_issues = []
    # Sort dimensions by score ascending to surface the worst
    sorted_dims = sorted(dimensions.items(), key=lambda x: x[1]["score"])
    for key, dim in sorted_dims[:4]:
        if dim["score"] < 70:
            impact = "High" if dim["score"] < 40 else ("Medium" if dim["score"] < 60 else "Low")
            top_issues.append({
                "title": dim["detail"].split(".")[0] + ".",
                "impact": impact,
                "action": key,
            })

    result: dict = {
        "overall": overall,
        "grade": grade,
        "dimensions": dimensions,
        "top_issues": top_issues,
    }

    # ------------------------------------------------------------------ #
    # Goal Performance (optional)
    # ------------------------------------------------------------------ #
    if aid_goals is not None:
        try:
            # Support both dict and model instance
            if hasattr(aid_goals, "__dict__"):
                target_leads = getattr(aid_goals, "target_monthly_leads", None)
                target_cpa_cents = getattr(aid_goals, "target_cpa_cents", None)
            else:
                target_leads = aid_goals.get("target_monthly_leads")
                target_cpa_cents = aid_goals.get("target_cpa_cents")

            if target_leads:
                # Get actual leads this month
                month_start = today.replace(day=1)
                actual_row = _safe_query(
                    """SELECT SUM(gs.conversions) AS conv,
                              SUM(gs.cost_micros) / 1000000.0 AS spend
                       FROM gads_stats_daily gs
                       JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
                       WHERE gs.entity_type = 'campaign' AND gs.date >= :d""",
                    {"aid": account_id, "d": month_start}
                )
                actual_leads = int(float((actual_row or {}).get("conv") or 0))
                actual_spend = float((actual_row or {}).get("spend") or 0)

                on_track = actual_leads >= target_leads
                gap = max(0, target_leads - actual_leads)
                cpa = (actual_spend / actual_leads) if actual_leads > 0 else (
                    target_cpa_cents / 100 if target_cpa_cents else 0
                )

                if on_track:
                    gap_message = f"You've already hit your monthly lead goal of {target_leads}. Excellent!"
                elif gap > 0 and cpa > 0:
                    extra_budget = round(gap * cpa)
                    gap_message = (
                        f"You need {gap} more leads to hit your monthly goal. "
                        f"At your current CPA of ${cpa:.0f}, that's about ${extra_budget} more in budget."
                    )
                else:
                    gap_message = f"You need {gap} more leads to hit your monthly goal of {target_leads}."

                result["goal_performance"] = {
                    "target_leads": target_leads,
                    "actual_leads": actual_leads,
                    "on_track": on_track,
                    "gap_message": gap_message,
                }
        except Exception:
            pass

    return result
