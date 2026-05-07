# app/google/consolidated_routes.py
"""
Consolidated Google Ads pages.

Provides three aggregated views that replace the previous fragmented pages:

  /account/google/ads/ai-control    — autonomous mode + agents + approval queue (tabbed)
  /account/google/ads/budget-plan   — budget groups + auto-budget + forecasting (tabbed)
  /account/google/ads/intelligence  — competitive + alerts (tabbed)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date

from flask import Blueprint, render_template, jsonify, request, current_app
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id

log = logging.getLogger(__name__)

consolidated_bp = Blueprint(
    "consolidated_bp",
    __name__,
    url_prefix="/account/google/ads",
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:
        log.debug("consolidated_routes safe-call failed: %s", exc)
        return default


def _is_ads_connected(account_id: int) -> bool:
    try:
        from app.google import _is_connected
        return _is_connected(account_id, "ads")
    except Exception:
        return False


# ── AI Control ─────────────────────────────────────────────────────────────────

@consolidated_bp.route("/ai-control", endpoint="ai_control")
@login_required
def ai_control():
    """Autonomous Mode + Agents Dashboard + Approval Queue in one tabbed page."""
    account_id = current_account_id()
    tab = request.args.get("tab", "autonomous")

    # ── autonomous settings ──
    from app.google.autonomous_routes import _get_settings, _get_7day_summary, _get_recent_feed
    settings = _safe(lambda: _get_settings(account_id), {
        "autonomous_mode_enabled": "0",
        "autonomy_level": "2",
        "growth_mode": "balanced",
        "target_cpl": "80",
        "monthly_budget": "1500",
        "services_priority": "",
        "geo_targets": "",
    })
    summary = _safe(lambda: _get_7day_summary(account_id), {
        "total_actions": 0, "total_savings": 0, "additional_leads": 0, "by_type": {}
    })
    feed = _safe(lambda: _get_recent_feed(account_id, limit=20), [])

    # ── agent stats ──
    agent_stats = _safe(lambda: _load_agent_stats(account_id), [])
    total_decisions = sum(s.get("total_decisions", 0) for s in agent_stats)
    total_executed  = sum(s.get("executed_count", 0)  for s in agent_stats)
    total_savings   = sum(float(s.get("total_expected_savings") or 0) for s in agent_stats)
    total_leads     = sum(float(s.get("total_expected_leads") or 0) for s in agent_stats)

    # ── approval queue ──
    pending_decisions, decisions_by_risk = _safe(
        lambda: _load_pending_decisions(account_id), ([], {"high": [], "low": []})
    )

    # ── change log ──
    cl_total_actions = cl_total_saved = cl_total_optimizations = cl_total_blocks = 0
    cl_recent_actions = []
    try:
        from app.models_ai_actions import AIAction
        from sqlalchemy import func as _func
        from datetime import datetime as _dt, timedelta as _td

        # Count only DISTINCT titles to avoid inflating numbers from pre-dedup duplicates
        cl_total_actions = db.session.execute(text(
            "SELECT COUNT(DISTINCT title) FROM ai_actions "
            "WHERE account_id=:aid AND status='executed'"
        ), {"aid": account_id}).scalar() or 0

        # Sum savings from only the first occurrence of each unique action title
        cl_total_saved = db.session.execute(text(
            "SELECT COALESCE(SUM(s),0) FROM ("
            "  SELECT MIN(estimated_monthly_savings) AS s FROM ai_actions "
            "  WHERE account_id=:aid AND status='executed' AND estimated_monthly_savings IS NOT NULL "
            "  GROUP BY title"
            ") AS deduped"
        ), {"aid": account_id}).scalar() or 0

        cl_total_blocks = db.session.execute(text(
            "SELECT COUNT(DISTINCT title) FROM ai_actions "
            "WHERE account_id=:aid AND status='executed' AND action_type='negative_keyword_added'"
        ), {"aid": account_id}).scalar() or 0

        cl_total_optimizations = cl_total_actions - cl_total_blocks

        # Show only the most recent occurrence of each unique action in the feed
        cl_recent_actions = AIAction.query.filter(
            AIAction.account_id == account_id,
            AIAction.status == 'executed',
            AIAction.created_at >= _dt.utcnow() - _td(days=30)
        ).order_by(AIAction.created_at.desc()).limit(200).all()

        # Deduplicate the feed by title, keeping only the latest
        seen_titles = set()
        deduped = []
        for a in cl_recent_actions:
            if a.title not in seen_titles:
                seen_titles.add(a.title)
                deduped.append(a)
            if len(deduped) >= 50:
                break
        cl_recent_actions = deduped
    except Exception:
        pass

    return render_template(
        "google/ai_control.html",
        tab=tab,
        # Autonomous
        settings=settings,
        summary=summary,
        feed=feed,
        # Agents
        agent_stats=agent_stats,
        total_decisions=total_decisions,
        total_executed=total_executed,
        total_savings=total_savings,
        total_leads=total_leads,
        # Approval
        pending_decisions=pending_decisions,
        decisions_by_risk=decisions_by_risk,
        total_pending=len(pending_decisions),
        # Change log
        cl_total_actions=cl_total_actions,
        cl_total_saved=round(cl_total_saved, 2),
        cl_total_optimizations=cl_total_optimizations,
        cl_total_blocks=cl_total_blocks,
        cl_recent_actions=cl_recent_actions,
    )


def _load_agent_stats(account_id: int) -> list:
    rows = db.session.execute(text("""
        SELECT
            agent_type,
            COUNT(*) as total_decisions,
            SUM(CASE WHEN status = 'executed' THEN 1 ELSE 0 END) as executed_count,
            AVG(confidence) as avg_confidence,
            SUM(expected_monthly_savings) as total_expected_savings,
            SUM(expected_monthly_leads) as total_expected_leads
        FROM agent_decisions
        WHERE account_id = :aid
        GROUP BY agent_type
        ORDER BY total_decisions DESC
    """), {"aid": account_id}).mappings().all()
    return [dict(r) for r in rows]


def _load_pending_decisions(account_id: int):
    rows = db.session.execute(text("""
        SELECT
            id, agent_id, agent_type, decision_type,
            title, description, reasoning,
            campaign_id, ad_group_id,
            risk_level, confidence,
            expected_monthly_savings, expected_monthly_leads, expected_improvement_pct,
            created_at
        FROM agent_decisions
        WHERE account_id = :aid AND status = 'pending'
        ORDER BY
            CASE risk_level
                WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4
            END,
            created_at DESC
    """), {"aid": account_id}).mappings().all()
    pending = [dict(r) for r in rows]
    by_risk: dict = {"high": [], "low": []}
    for d in pending:
        level = d.get("risk_level") or "high"
        if level not in by_risk:
            level = "high"
        by_risk[level].append(d)
    return pending, by_risk


# ── Budget & Forecast ──────────────────────────────────────────────────────────

@consolidated_bp.route("/api/budget-groups", methods=["POST"])
@login_required
def api_create_budget_group():
    """Create a new budget group (used by the inline modal on the budget-plan page)."""
    account_id = current_account_id()
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    monthly_budget = float(data.get("monthly_budget_target") or 0)
    description = (data.get("description") or "").strip()

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if monthly_budget <= 0:
        return jsonify({"error": "Monthly budget must be greater than 0"}), 400

    customer_id = (data.get("customer_id") or "").strip()
    if not customer_id:
        try:
            from app.google.utils_ads import resolve_ads_context
            ctx = resolve_ads_context(account_id) or {}
            customer_id = ctx.get("customer_id") or ""
        except Exception:
            pass
    if not customer_id:
        try:
            row = db.session.execute(text(
                "SELECT google_customer_id FROM ads_campaigns "
                "WHERE account_id=:aid AND google_customer_id IS NOT NULL LIMIT 1"
            ), {"aid": account_id}).mappings().first()
            if row:
                customer_id = row["google_customer_id"] or ""
        except Exception:
            pass

    try:
        db.session.execute(text("""
            INSERT INTO budget_groups
                (account_id, customer_id, name, description,
                 monthly_budget_target, min_daily_budget, max_daily_budget,
                 enabled, adjustment_frequency,
                 performance_weight, seasonality_weight, capacity_weight,
                 industry, send_notifications, color)
            VALUES
                (:aid, :cid, :name, :desc,
                 :budget, 10, 1000,
                 1, 'daily',
                 0.70, 0.20, 0.10,
                 'hvac_heating', 1, '#3B82F6')
        """), {
            "aid": account_id,
            "cid": customer_id,
            "name": name,
            "desc": description,
            "budget": monthly_budget,
        })
        db.session.commit()
        return jsonify({"success": True})
    except Exception as exc:
        log.exception("api_create_budget_group failed")
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500


@consolidated_bp.route("/budget-plan", endpoint="budget_planning")
@login_required
def budget_planning():
    """Budget Groups + Auto-Budget Settings + Forecasting in one tabbed page."""
    account_id = current_account_id()
    tab = request.args.get("tab", "groups")
    is_connected = _is_ads_connected(account_id)

    # ── budget groups ──
    budget_groups, unassigned_campaigns, all_campaigns = _safe(
        lambda: _load_budget_groups(account_id), ([], [], [])
    )

    # Auto-create a default group when none exist so the page is immediately useful
    if not budget_groups:
        _safe(lambda: _create_default_budget_group(account_id), None)
        budget_groups, unassigned_campaigns, all_campaigns = _safe(
            lambda: _load_budget_groups(account_id), ([], [], [])
        )

    # ── auto-budget settings ──
    auto_budget_settings = _safe(lambda: _load_auto_budget_settings(account_id), {})
    auto_budget_history  = _safe(lambda: _load_auto_budget_history(account_id), [])

    # ── forecasting campaigns ──
    forecast_campaigns = _safe(lambda: _load_forecast_campaigns(account_id), [])

    # ── ads customer_id + detected budget for the create-group modal ──
    ads_customer_id = ""
    try:
        from app.google.utils_ads import resolve_ads_context
        ctx = resolve_ads_context(account_id) or {}
        ads_customer_id = ctx.get("customer_id") or ""
    except Exception:
        pass
    if not ads_customer_id and budget_groups:
        ads_customer_id = budget_groups[0].get("customer_id") or ""

    detected_budget = _safe(lambda: _detect_monthly_budget(account_id), 0.0)

    return render_template(
        "google/budget_planning.html",
        tab=tab,
        is_connected=is_connected,
        # Budget groups
        budget_groups=budget_groups,
        unassigned_campaigns=unassigned_campaigns,
        all_campaigns=all_campaigns,
        current_month=date.today(),
        ads_customer_id=ads_customer_id,
        detected_budget=detected_budget,
        # Auto-budget
        auto_budget_settings=auto_budget_settings,
        auto_budget_history=auto_budget_history,
        # Forecasting
        forecast_campaigns=forecast_campaigns,
    )


def _detect_monthly_budget(account_id: int) -> float:
    """
    Return the best estimate of the account's total monthly Google Ads budget.

    Priority:
      1. auto_budget_settings.total_monthly_budget_cents  (user-set explicit cap)
      2. SUM(ads_campaigns.daily_budget_cents) * 30       (synced from Google Ads)
      3. account_settings.monthly_budget                  (autonomous mode setting)
    Returns 0.0 if nothing is found so the caller can decide the fallback.
    """
    # 1 – explicit cap set in auto-budget settings
    try:
        row = db.session.execute(text(
            "SELECT total_monthly_budget_cents FROM auto_budget_settings "
            "WHERE account_id=:aid LIMIT 1"
        ), {"aid": account_id}).mappings().first()
        if row and row["total_monthly_budget_cents"]:
            return float(row["total_monthly_budget_cents"]) / 100.0
    except Exception:
        pass

    # 2 – sum of campaign daily budgets × 30
    try:
        row = db.session.execute(text(
            "SELECT SUM(daily_budget_cents) AS total "
            "FROM ads_campaigns WHERE account_id=:aid AND status != 'removed'"
        ), {"aid": account_id}).mappings().first()
        if row and row["total"]:
            return float(row["total"]) * 30 / 100.0
    except Exception:
        pass

    # 3 – autonomous mode monthly_budget setting
    try:
        row = db.session.execute(text(
            "SELECT setting_value FROM account_settings "
            "WHERE account_id=:aid AND setting_key='monthly_budget' LIMIT 1"
        ), {"aid": account_id}).mappings().first()
        if row and row["setting_value"]:
            return float(row["setting_value"])
    except Exception:
        pass

    return 0.0


def _create_default_budget_group(account_id: int) -> None:
    """Insert a starter 'Main Budget' group seeded with the account's real budget."""
    # Resolve customer_id
    customer_id = ""
    try:
        from app.google.utils_ads import resolve_ads_context
        ctx = resolve_ads_context(account_id) or {}
        customer_id = ctx.get("customer_id") or ""
    except Exception:
        pass
    if not customer_id:
        try:
            row = db.session.execute(text(
                "SELECT google_customer_id FROM ads_campaigns "
                "WHERE account_id=:aid AND google_customer_id IS NOT NULL LIMIT 1"
            ), {"aid": account_id}).mappings().first()
            if row:
                customer_id = row["google_customer_id"] or ""
        except Exception:
            pass

    monthly_budget = _detect_monthly_budget(account_id)
    # Derive sensible daily bounds from the monthly total
    daily_avg = monthly_budget / 30.0 if monthly_budget else 0.0
    min_daily = max(10.0, round(daily_avg * 0.5, 2)) if daily_avg else 10.0
    max_daily = max(min_daily * 2, round(daily_avg * 1.5, 2)) if daily_avg else 1000.0

    db.session.execute(text("""
        INSERT INTO budget_groups
            (account_id, customer_id, name, description,
             monthly_budget_target, min_daily_budget, max_daily_budget,
             enabled, adjustment_frequency,
             performance_weight, seasonality_weight, capacity_weight,
             industry, send_notifications, color)
        VALUES
            (:aid, :cid, 'Main Budget', 'Default budget group',
             :budget, :min_d, :max_d,
             1, 'daily',
             0.70, 0.20, 0.10,
             'hvac_heating', 1, '#3B82F6')
    """), {
        "aid": account_id, "cid": customer_id,
        "budget": monthly_budget, "min_d": min_daily, "max_d": max_daily,
    })
    db.session.commit()


def _load_budget_groups(account_id: int):
    from datetime import date as _date
    today = _date.today()
    month_start = today.replace(day=1)

    groups = db.session.execute(text("""
        SELECT bg.*,
               COUNT(DISTINCT ac.id) AS campaign_count,
               COALESCE(SUM(ac.daily_budget_cents * 30), 0) AS estimated_monthly_cents,
               COALESCE((
                 SELECT SUM(gs.cost_micros) / 1000000.0
                 FROM gads_stats_daily gs
                 JOIN ads_campaigns ac2 ON ac2.google_campaign_id = gs.campaign_id
                 WHERE ac2.budget_group_id = bg.id
                   AND gs.entity_type = 'campaign'
                   AND gs.date >= :month_start
               ), 0) AS current_spend_dollars
        FROM budget_groups bg
        LEFT JOIN ads_campaigns ac ON ac.budget_group_id = bg.id AND ac.account_id = :aid
        WHERE bg.account_id = :aid
        GROUP BY bg.id
        ORDER BY bg.name
    """), {"aid": account_id, "month_start": month_start}).mappings().all()

    campaigns = db.session.execute(text("""
        SELECT ac.*, bg.name AS group_name
        FROM ads_campaigns ac
        LEFT JOIN budget_groups bg ON bg.id = ac.budget_group_id
        WHERE ac.account_id = :aid
        ORDER BY ac.name
    """), {"aid": account_id}).mappings().all()

    all_c = [dict(c) for c in campaigns]
    groups_l = [dict(g) for g in groups]
    unassigned = [c for c in all_c if not c.get("budget_group_id")]
    return groups_l, unassigned, all_c


def _load_auto_budget_settings(account_id: int) -> dict:
    row = db.session.execute(text("""
        SELECT * FROM auto_budget_settings WHERE account_id = :aid LIMIT 1
    """), {"aid": account_id}).mappings().first()
    return dict(row) if row else {
        "enabled": False,
        "total_monthly_budget_cents": 0,
        "min_daily_budget_cents": 0,
        "max_daily_budget_cents": 0,
        "max_adjustment_pct": 20,
        "enable_weather_adjustments": False,
        "enable_capacity_adjustments": False,
        "enable_competitive_adjustments": False,
        "enable_seasonality_adjustments": False,
        "notification_enabled": False,
    }


def _load_auto_budget_history(account_id: int) -> list:
    rows = db.session.execute(text("""
        SELECT abh.*, ac.name AS campaign_name
        FROM auto_budget_history abh
        JOIN ads_campaigns ac ON ac.id = abh.campaign_id
        WHERE ac.account_id = :aid
        ORDER BY abh.adjustment_date DESC
        LIMIT 30
    """), {"aid": account_id}).mappings().all()
    return [dict(r) for r in rows]


def _load_forecast_campaigns(account_id: int) -> list:
    from flask import session as _session
    try:
        from app.google import _get_ads_state, _is_connected
        if _is_connected(account_id, "ads"):
            ads_data = _get_ads_state(account_id)
            if ads_data and ads_data.get("campaigns"):
                return [
                    {
                        "id": c.get("id"),
                        "name": c.get("name", ""),
                        "status": c.get("status", ""),
                        "daily_budget_cents": int((c.get("daily_budget") or 0) * 100),
                        "cost_30d": c.get("monthly_spend", 0),
                        "conversions": c.get("conversions", 0),
                        "clicks": c.get("clicks", 0),
                        "impressions": c.get("impressions", 0),
                    }
                    for c in ads_data["campaigns"]
                ]
    except Exception:
        pass

    # Fallback: DB campaigns
    rows = db.session.execute(text("""
        SELECT id, name, status, daily_budget_cents, google_campaign_id
        FROM ads_campaigns WHERE account_id = :aid ORDER BY name
    """), {"aid": account_id}).mappings().all()
    return [dict(r) for r in rows]


# ── Intelligence ───────────────────────────────────────────────────────────────

@consolidated_bp.route("/intelligence", endpoint="intelligence")
@login_required
def intelligence():
    """Competitive Intelligence + Google Ads Alerts in one tabbed page."""
    account_id = current_account_id()
    tab = request.args.get("tab", "competitive")
    is_connected = _is_ads_connected(account_id)

    # ── competitive campaigns ──
    comp_campaigns = _safe(lambda: _load_competitive_campaigns(account_id), [])

    # ── competitive alerts ──
    comp_alerts = _safe(lambda: _load_competitive_alerts(account_id), [])

    # ── Google Ads recommendations / alerts ──
    gads_recommendations, gads_account_alerts, change_history = _safe(
        lambda: _load_gads_alerts(account_id), ([], [], [])
    )

    return render_template(
        "google/intelligence.html",
        tab=tab,
        is_connected=is_connected,
        # Competitive
        campaigns=comp_campaigns,
        comp_alerts=comp_alerts,
        # G Ads alerts
        recommendations=gads_recommendations,
        account_alerts=gads_account_alerts,
        change_history=change_history,
    )


def _load_competitive_campaigns(account_id: int) -> list:
    from flask import session as _session
    try:
        from app.google import _get_ads_state, _is_connected
        if _is_connected(account_id, "ads"):
            ads_data = _get_ads_state(account_id)
            if ads_data and ads_data.get("campaigns"):
                return [
                    {
                        "id": c.get("id"),
                        "name": c.get("name", ""),
                        "google_campaign_id": c.get("id"),
                        "status": c.get("status", ""),
                    }
                    for c in ads_data["campaigns"]
                ]
    except Exception:
        pass
    rows = db.session.execute(text("""
        SELECT id, name, google_campaign_id, status
        FROM ads_campaigns WHERE account_id = :aid ORDER BY name
    """), {"aid": account_id}).mappings().all()
    return [dict(r) for r in rows]


def _load_competitive_alerts(account_id: int) -> list:
    try:
        rows = db.session.execute(text("""
            SELECT ca.*, ac.name as campaign_name
            FROM competitive_alerts ca
            JOIN ads_campaigns ac ON ac.id = ca.campaign_id
            WHERE ca.account_id = :aid AND ca.is_acknowledged = FALSE
            ORDER BY ca.severity DESC, ca.alert_date DESC
            LIMIT 20
        """), {"aid": account_id}).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _load_gads_alerts(account_id: int):
    try:
        from app.services.google_ads_alerts_service import (
            get_account_recommendations, get_account_alerts, get_change_history
        )
        recs = get_account_recommendations(account_id) or []
        alerts = get_account_alerts(account_id) or []
        history = get_change_history(account_id, limit=20) or []
        return recs, alerts, history
    except Exception:
        return [], [], []
