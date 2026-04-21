# app/budget_forecast/__init__.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import Blueprint, current_app, render_template, jsonify, request
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

budget_forecast_bp = Blueprint("budget_forecast_bp", __name__, url_prefix="/account/budget-forecast")

# Seasonal demand index for home-service businesses (index 0 = January)
_SEASON_INDEX = [0.82, 0.78, 0.90, 1.05, 1.12, 1.18, 1.20, 1.15, 1.05, 1.00, 0.95, 0.80]
_MONTH_NAMES  = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def _get_historical_performance(aid: int) -> Dict[str, Any]:
    """
    Return performance metrics for the account.
    Primary source: google_ads_campaigns (live sync).
    Fallback: latest GoogleAdsGraderReport.
    """
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT SUM(cost_micros)/1e6 AS total_cost,
                           SUM(clicks)          AS total_clicks,
                           SUM(impressions)     AS total_impressions,
                           SUM(conversions)     AS total_conversions,
                           COUNT(DISTINCT id)   AS campaign_count
                    FROM google_ads_campaigns
                    WHERE account_id = :aid AND status = 'ENABLED'
                """),
                {"aid": aid},
            ).mappings().first()
            if row and float(row.get("total_cost") or 0) > 0:
                cost   = float(row["total_cost"])
                clicks = int(row.get("total_clicks") or 0)
                convs  = float(row.get("total_conversions") or 0)
                return {
                    "total_cost": cost,
                    "total_clicks": clicks,
                    "total_impressions": int(row.get("total_impressions") or 0),
                    "total_conversions": convs,
                    "campaign_count": int(row.get("campaign_count") or 0),
                    "avg_cpc": cost / clicks if clicks else 0,
                    "avg_cpa": cost / convs  if convs  else 0,
                    "avg_monthly_spend": cost / 3,
                    "conversion_rate": convs / clicks * 100 if clicks else 0,
                    "quality_score": 6.0,
                    "wasted_spend_90d": 0,
                    "source": "live",
                }
    except Exception as e:
        current_app.logger.warning("budget_forecast live query: %s", e)

    # Fallback to grader report
    try:
        from app.models_ads_grader import GoogleAdsGraderReport
        rpt = (GoogleAdsGraderReport.query
               .filter_by(account_id=aid)
               .order_by(GoogleAdsGraderReport.created_at.desc())
               .first())
        if rpt:
            monthly = float(rpt.avg_monthly_spend or 0)
            clicks  = int(rpt.clicks_90d or 0)
            convs   = int(rpt.conversions_90d or 0)
            cost90  = monthly * 3
            return {
                "total_cost": cost90,
                "total_clicks": clicks,
                "total_impressions": 0,
                "total_conversions": convs,
                "campaign_count": int(rpt.active_campaigns or 0),
                "avg_cpc": cost90 / clicks if clicks else 0,
                "avg_cpa": cost90 / convs  if convs  else 0,
                "avg_monthly_spend": monthly,
                "conversion_rate": convs / clicks * 100 if clicks else 0,
                "quality_score": float(rpt.quality_score_avg or 6.0),
                "wasted_spend_90d": float(rpt.wasted_spend_90d or 0),
                "source": "grader_report",
            }
    except Exception as e:
        current_app.logger.warning("budget_forecast grader fallback: %s", e)

    return {
        "total_cost": 0, "total_clicks": 0, "total_impressions": 0,
        "total_conversions": 0, "campaign_count": 0,
        "avg_cpc": 0, "avg_cpa": 0, "avg_monthly_spend": 0,
        "conversion_rate": 0, "quality_score": 6.0,
        "wasted_spend_90d": 0, "source": "none",
    }


def _get_monthly_trend(aid: int, months: int = 6) -> List[Dict[str, Any]]:
    """Month-by-month spend trend built from grader report history."""
    try:
        from app.models_ads_grader import GoogleAdsGraderReport
        cutoff = datetime.utcnow() - timedelta(days=months * 30)
        reports = (GoogleAdsGraderReport.query
                   .filter(GoogleAdsGraderReport.account_id == aid,
                           GoogleAdsGraderReport.created_at >= cutoff)
                   .order_by(GoogleAdsGraderReport.created_at.asc())
                   .all())
        return [
            {
                "month": r.created_at.strftime("%b %Y"),
                "cost": float(r.avg_monthly_spend or 0),
                "conversions": int((r.conversions_90d or 0) // 3),
                "score": float(r.overall_score or 0),
            }
            for r in reports
        ]
    except Exception:
        return []


def _get_current_budget(aid: int) -> float:
    """Current monthly budget from campaigns table, then grader fallback."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT SUM(daily_budget_micros)/1e6*30 AS monthly_budget
                    FROM google_ads_campaigns
                    WHERE account_id = :aid AND status = 'ENABLED'
                """),
                {"aid": aid},
            ).mappings().first()
            val = float(row.get("monthly_budget") or 0) if row else 0
            if val > 0:
                return val
    except Exception:
        pass
    try:
        from app.models_ads_grader import GoogleAdsGraderReport
        rpt = (GoogleAdsGraderReport.query
               .filter_by(account_id=aid)
               .order_by(GoogleAdsGraderReport.created_at.desc())
               .first())
        if rpt and rpt.avg_monthly_spend:
            return float(rpt.avg_monthly_spend)
    except Exception:
        pass
    return 0


def forecast_results(
    current_budget: float,
    new_budget: float,
    avg_cpc: float,
    conversion_rate: float,
    avg_cpa: float,
    quality_score: float = 6.0,
    wasted_pct: float = 0.0,
    season_month: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Project clicks, conversions, and CPA for a given monthly budget.

    Model factors:
    - Diminishing returns: +50% spend → +32.5% clicks on excess (0.65 efficiency)
    - Quality Score: each QS point above 5 adds 3% click efficiency
    - Wasted spend recapture: reduces effective CPC by up to 15%
    - Seasonal index: note only (not applied numerically to avoid over-confidence)
    """
    if current_budget <= 0 or avg_cpc <= 0:
        return {
            "predicted_clicks": 0, "predicted_conversions": 0,
            "predicted_cost": new_budget, "predicted_cpa": 0,
            "change_percent": 0, "season_note": "",
        }

    ratio = new_budget / current_budget

    # Diminishing returns curve
    if ratio <= 1.5:
        eff_ratio = ratio
    elif ratio <= 2.0:
        eff_ratio = 1.5 + (ratio - 1.5) * 0.65
    else:
        eff_ratio = 1.825 + (ratio - 2.0) * 0.45

    # Quality score efficiency bonus
    qs_bonus = 1.0 + max(0.0, quality_score - 5.0) * 0.03

    # Partial wasted-spend recapture (up to 15% CPC improvement)
    waste_recapture = 1.0 + min(wasted_pct / 100, 0.40) * 0.15

    effective_cpc = avg_cpc / (qs_bonus * waste_recapture)
    current_clicks = current_budget / effective_cpc
    predicted_clicks = int(current_clicks * eff_ratio)
    predicted_convs  = round(predicted_clicks * conversion_rate / 100, 1) if conversion_rate > 0 else 0
    predicted_cpa    = round(new_budget / predicted_convs, 2) if predicted_convs > 0 else 0

    season_note = ""
    if season_month:
        si = _SEASON_INDEX[season_month - 1]
        mn = _MONTH_NAMES[season_month - 1]
        if si >= 1.10:
            season_note = f"Peak season ({mn}): expect higher CPCs and more competition."
        elif si <= 0.85:
            season_note = f"Off-peak ({mn}): budget typically goes further this time of year."

    return {
        "predicted_clicks": predicted_clicks,
        "predicted_conversions": predicted_convs,
        "predicted_cost": new_budget,
        "predicted_cpa": predicted_cpa,
        "change_percent": int((ratio - 1) * 100),
        "effective_ratio": round(eff_ratio, 2),
        "season_note": season_note,
    }


def generate_recommendations(
    performance: Dict[str, Any],
    current_budget: float,
) -> List[Dict[str, Any]]:
    avg_cpa   = performance.get("avg_cpa", 0)
    cvr       = performance.get("conversion_rate", 0)
    avg_cpc   = performance.get("avg_cpc") or 2.5
    qs        = performance.get("quality_score", 6.0)
    cost90    = performance.get("total_cost", 1) or 1
    wasted    = performance.get("wasted_spend_90d", 0)
    wasted_pct = wasted / cost90 * 100

    now_month = datetime.utcnow().month

    def _fc(mult):
        return forecast_results(
            current_budget, current_budget * mult,
            avg_cpc, cvr, avg_cpa,
            quality_score=qs, wasted_pct=wasted_pct,
            season_month=now_month,
        )

    recs: List[Dict] = []

    if wasted_pct > 12 and current_budget > 0:
        savings = current_budget * wasted_pct / 100 * 0.5
        recs.append({
            "type": "eliminate_waste",
            "title": "Cut Wasted Spend First",
            "description": (
                f"~{wasted_pct:.0f}% of budget is wasted on low-quality clicks. "
                f"Recapturing half (~${savings:.0f}/mo) improves CPA without raising spend."
            ),
            "current_budget": current_budget,
            "suggested_budget": current_budget,
            "potential_savings": round(savings, 2),
            "predicted_conversions": performance.get("total_conversions", 0),
            "confidence": "high", "icon": "fa-scissors", "color": "red",
            "action_url": "/ads-grader/quick-wins",
        })

    if avg_cpa > 0 and avg_cpa < 100 and cvr >= 2:
        fc = _fc(1.25)
        recs.append({
            "type": "scale",
            "title": "Scale — You're Efficient",
            "description": (
                f"CPA ${avg_cpa:.0f} and {cvr:.1f}% CVR are strong. "
                "A 25% budget lift should yield proportional leads."
            ),
            "current_budget": current_budget,
            "suggested_budget": round(current_budget * 1.25, 2),
            "predicted_conversions": fc["predicted_conversions"],
            "predicted_change": "+25%", "confidence": "high",
            "icon": "fa-chart-line", "color": "green",
        })

    if current_budget > 0:
        fc = _fc(1.10)
        recs.append({
            "type": "conservative",
            "title": "Safe Growth (+10%)",
            "description": "Low-risk test to validate performance at a higher spend level.",
            "current_budget": current_budget,
            "suggested_budget": round(current_budget * 1.10, 2),
            "predicted_conversions": fc["predicted_conversions"],
            "predicted_change": "+10%", "confidence": "high",
            "icon": "fa-shield-halved", "color": "blue",
        })

    if avg_cpa > 150:
        recs.append({
            "type": "optimize",
            "title": "Optimize Before Scaling",
            "description": (
                f"CPA ${avg_cpa:.0f} is high. Fix Quality Score and negatives "
                "before adding budget to avoid scaling wasted spend."
            ),
            "current_budget": current_budget,
            "suggested_budget": current_budget,
            "predicted_conversions": performance.get("total_conversions", 0),
            "predicted_change": "0%", "confidence": "medium",
            "icon": "fa-wrench", "color": "yellow",
            "action_url": "/account/google/ads/opportunities",
        })

    if avg_cpa > 0 and avg_cpa < 60 and cvr > 4:
        fc = _fc(2.0)
        recs.append({
            "type": "aggressive",
            "title": "Accelerate — Double Budget",
            "description": (
                f"Exceptional CPA ${avg_cpa:.0f} and {cvr:.1f}% CVR. "
                "Doubling budget is viable with moderate diminishing returns."
            ),
            "current_budget": current_budget,
            "suggested_budget": round(current_budget * 2.0, 2),
            "predicted_conversions": fc["predicted_conversions"],
            "predicted_change": f"{fc['change_percent']:+d}% effective clicks",
            "confidence": "medium", "icon": "fa-rocket", "color": "purple",
        })

    return recs[:4]


# -------------------- Routes --------------------

@budget_forecast_bp.route("/", methods=["GET"])
@login_required
def index():
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    performance    = _get_historical_performance(aid)
    current_budget = _get_current_budget(aid)
    recommendations = generate_recommendations(performance, current_budget)
    trend          = _get_monthly_trend(aid, months=6)

    avg_cpc  = performance.get("avg_cpc") or 2.5
    cvr      = performance.get("conversion_rate") or 3.0
    avg_cpa  = performance.get("avg_cpa") or 50.0
    qs       = performance.get("quality_score", 6.0)
    cost90   = performance.get("total_cost", 1) or 1
    wasted_pct = performance.get("wasted_spend_90d", 0) / cost90 * 100
    now_month  = datetime.utcnow().month

    scenarios = []
    for mult, label in [(0.5, "−50%"), (0.75, "−25%"), (1.0, "Current"),
                         (1.25, "+25%"), (1.5, "+50%"), (2.0, "+100%")]:
        budget = current_budget * mult
        fc = forecast_results(budget, budget, avg_cpc, cvr, avg_cpa,
                               quality_score=qs, wasted_pct=wasted_pct,
                               season_month=now_month)
        if mult == 1.0:
            fc["predicted_clicks"]      = performance.get("total_clicks", 0) // 3
            fc["predicted_conversions"] = round(performance.get("total_conversions", 0) / 3, 1)
        scenarios.append({
            "label": label, "budget": round(budget, 2),
            "clicks": fc["predicted_clicks"],
            "conversions": fc["predicted_conversions"],
            "cpa": fc["predicted_cpa"],
            "is_current": mult == 1.0,
        })

    si = _SEASON_INDEX[now_month - 1]
    mn = _MONTH_NAMES[now_month - 1]
    season_note = ""
    if si >= 1.10:
        season_note = f"Peak season ({mn}) — expect higher CPCs and more competition."
    elif si <= 0.85:
        season_note = f"Off-peak ({mn}) — budget typically goes further this time of year."

    return render_template(
        "budget_forecast/index.html",
        performance=performance,
        current_budget=current_budget,
        recommendations=recommendations,
        scenarios=scenarios,
        trend=trend,
        season_note=season_note,
        is_paid=is_paid_account(),
    )


@budget_forecast_bp.route("/api/forecast", methods=["POST"])
@login_required
def api_forecast():
    """Interactive slider endpoint — returns forecast JSON for a given budget."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Account not found"}), 404

    data       = request.get_json() or {}
    new_budget = float(data.get("budget", 0))
    if new_budget <= 0:
        return jsonify({"error": "budget must be > 0"}), 400

    performance    = _get_historical_performance(aid)
    current_budget = _get_current_budget(aid)
    cost90         = performance.get("total_cost", 1) or 1
    wasted_pct     = performance.get("wasted_spend_90d", 0) / cost90 * 100

    fc = forecast_results(
        current_budget, new_budget,
        performance.get("avg_cpc") or 2.5,
        performance.get("conversion_rate") or 3.0,
        performance.get("avg_cpa") or 50.0,
        quality_score=performance.get("quality_score", 6.0),
        wasted_pct=wasted_pct,
        season_month=datetime.utcnow().month,
    )
    fc["current_budget"] = current_budget
    return jsonify(fc)
