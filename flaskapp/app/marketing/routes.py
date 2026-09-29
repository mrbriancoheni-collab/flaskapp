"""
Marketing Command Center — routes.
Covers: cross-channel CAC dashboard, offline channel management,
budget pacing, growth optimizer, revenue/LTV, reputation impact,
seasonal planner, aggregator lead management.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from calendar import monthrange

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, is_paid_account, current_account_id

marketing_bp = Blueprint("marketing_bp", __name__, url_prefix="/account/marketing")

# ── helpers ────────────────────────────────────────────────────────────────

def _safe_models():
    """Import marketing models inside try/except to degrade gracefully before migration."""
    try:
        from app.models_marketing import (
            MarketingChannel, ChannelSpendEntry, ChannelLeadEntry,
            AggregatorAccount, AggregatorLead, MarketingBudget, LeadAttribution,
        )
        return dict(
            MarketingChannel=MarketingChannel,
            ChannelSpendEntry=ChannelSpendEntry,
            ChannelLeadEntry=ChannelLeadEntry,
            AggregatorAccount=AggregatorAccount,
            AggregatorLead=AggregatorLead,
            MarketingBudget=MarketingBudget,
            LeadAttribution=LeadAttribution,
        )
    except Exception as e:
        current_app.logger.warning(f"Marketing models not yet migrated: {e}")
        return {}


def _safe_attribution():
    try:
        from app.services.marketing_attribution import (
            get_all_channel_stats, get_budget_pacing,
            get_growth_recommendations, compute_attribution, get_ltv_by_channel,
        )
        return dict(
            get_all_channel_stats=get_all_channel_stats,
            get_budget_pacing=get_budget_pacing,
            get_growth_recommendations=get_growth_recommendations,
            compute_attribution=compute_attribution,
            get_ltv_by_channel=get_ltv_by_channel,
        )
    except Exception as e:
        current_app.logger.warning(f"Attribution service unavailable: {e}")
        return {}


CHANNEL_TYPE_LABELS = {
    "google_ads": ("Google Search Ads", "fa-brands fa-google", "indigo"),
    "lsa": ("Google LSA", "fa-solid fa-shield-halved", "blue"),
    "facebook": ("Facebook / Instagram", "fa-brands fa-facebook", "blue"),
    "yelp": ("Yelp", "fa-brands fa-yelp", "red"),
    "angi": ("Angi / HomeAdvisor", "fa-solid fa-house-chimney-crack", "orange"),
    "homeadvisor": ("HomeAdvisor", "fa-solid fa-house", "orange"),
    "thumbtack": ("Thumbtack", "fa-solid fa-thumbtack", "teal"),
    "nextdoor": ("Nextdoor", "fa-solid fa-people-roof", "green"),
    "billboard": ("Billboard / OOH", "fa-solid fa-rectangle-ad", "yellow"),
    "direct_mail": ("Direct Mail / EDDM", "fa-solid fa-envelope-open-text", "amber"),
    "print": ("Print / Magazine", "fa-solid fa-newspaper", "gray"),
    "radio": ("Radio", "fa-solid fa-radio", "purple"),
    "tv": ("TV / Streaming", "fa-solid fa-tv", "slate"),
    "door_hangers": ("Door Hangers / Flyers", "fa-solid fa-door-open", "lime"),
    "organic": ("Organic / SEO", "fa-solid fa-seedling", "green"),
    "referral": ("Referral Program", "fa-solid fa-people-arrows", "cyan"),
    "other": ("Other", "fa-solid fa-circle-dot", "gray"),
}


# ── Command Center ──────────────────────────────────────────────────────────

@marketing_bp.get("/")
@login_required
def command_center():
    aid = current_account_id()
    m = _safe_models()
    svc = _safe_attribution()

    now = date.today()
    channel_stats = []
    budget_pacing = {}
    growth_recs = []
    attribution = {}

    if m and svc:
        try:
            channel_stats = svc["get_all_channel_stats"](aid, lookback_months=3)
        except Exception:
            current_app.logger.exception("Error loading channel stats")

        try:
            budget_pacing = svc["get_budget_pacing"](aid)
        except Exception:
            current_app.logger.exception("Error loading budget pacing")

        try:
            growth_recs = svc["get_growth_recommendations"](aid)
        except Exception:
            current_app.logger.exception("Error loading growth recs")

        try:
            attribution = svc["compute_attribution"](aid, days=90)
        except Exception:
            current_app.logger.exception("Error loading attribution")

    # Aggregator lead counts (last 30d)
    agg_leads_30d = 0
    if m:
        try:
            AggLead = m["AggregatorLead"]
            cutoff = datetime.utcnow() - timedelta(days=30)
            agg_leads_30d = AggLead.query.filter(
                AggLead.account_id == aid,
                AggLead.created_at >= cutoff
            ).count()
        except Exception:
            pass

    # Total leads last 30d from LeadIngest
    total_leads_30d = 0
    try:
        total_leads_30d = db.session.execute(text(
            "SELECT COUNT(*) FROM lead_ingest WHERE account_id=:aid "
            "AND occurred_at >= :cutoff"
        ), {"aid": aid, "cutoff": datetime.utcnow() - timedelta(days=30)}).scalar() or 0
    except Exception:
        pass

    # Total revenue last 30d from ServiceTitan
    revenue_30d = 0
    try:
        row = db.session.execute(text(
            "SELECT COALESCE(SUM(total_amount),0) FROM servicetitan_jobs "
            "WHERE account_id=:aid AND job_status='Completed' "
            "AND completed_date >= :cutoff"
        ), {"aid": aid, "cutoff": datetime.utcnow() - timedelta(days=30)}).scalar()
        revenue_30d = float(row or 0)
    except Exception:
        pass

    return render_template(
        "marketing/command_center.html",
        channel_stats=channel_stats,
        budget_pacing=budget_pacing,
        growth_recs=growth_recs,
        attribution=attribution,
        agg_leads_30d=agg_leads_30d,
        total_leads_30d=total_leads_30d,
        revenue_30d=round(revenue_30d, 2),
        channel_type_labels=CHANNEL_TYPE_LABELS,
        now=now,
    )


# ── Channels ────────────────────────────────────────────────────────────────

@marketing_bp.get("/channels")
@login_required
def channels():
    aid = current_account_id()
    m = _safe_models()
    channel_list = []
    if m:
        try:
            MC = m["MarketingChannel"]
            channel_list = MC.query.filter_by(account_id=aid).order_by(MC.channel_type, MC.name).all()
        except Exception:
            current_app.logger.exception("Error loading channels")
    return render_template(
        "marketing/channels.html",
        channel_list=channel_list,
        channel_type_labels=CHANNEL_TYPE_LABELS,
        channel_types=list(CHANNEL_TYPE_LABELS.keys()),
    )


@marketing_bp.post("/channels")
@login_required
def channels_create():
    aid = current_account_id()
    m = _safe_models()
    if not m:
        return jsonify({"error": "Marketing models not yet available"}), 503
    try:
        MC = m["MarketingChannel"]
        data = request.get_json(force=True)
        channel = MC(
            account_id=aid,
            name=data["name"],
            channel_type=data["channel_type"],
            monthly_budget_cents=int(float(data.get("monthly_budget", 0)) * 100) if data.get("monthly_budget") else None,
            notes=data.get("notes"),
            tracking_phone=data.get("tracking_phone"),
            promo_code=data.get("promo_code"),
            vendor_name=data.get("vendor_name"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
        )
        db.session.add(channel)
        db.session.commit()
        return jsonify({"id": channel.id, "name": channel.name})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


@marketing_bp.put("/channels/<int:cid>")
@login_required
def channels_update(cid):
    aid = current_account_id()
    m = _safe_models()
    if not m:
        return jsonify({"error": "Marketing models not yet available"}), 503
    try:
        MC = m["MarketingChannel"]
        channel = MC.query.filter_by(id=cid, account_id=aid).first_or_404()
        data = request.get_json(force=True)
        for field in ("name", "channel_type", "notes", "tracking_phone", "promo_code", "vendor_name", "start_date", "end_date"):
            if field in data:
                setattr(channel, field, data[field])
        if "monthly_budget" in data:
            channel.monthly_budget_cents = int(float(data["monthly_budget"]) * 100) if data["monthly_budget"] else None
        if "is_active" in data:
            channel.is_active = bool(data["is_active"])
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


@marketing_bp.delete("/channels/<int:cid>")
@login_required
def channels_delete(cid):
    aid = current_account_id()
    m = _safe_models()
    if not m:
        return jsonify({"error": "Not available"}), 503
    try:
        MC = m["MarketingChannel"]
        channel = MC.query.filter_by(id=cid, account_id=aid).first_or_404()
        db.session.delete(channel)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


# ── Offline Spend & Lead Entry ───────────────────────────────────────────────

@marketing_bp.post("/channels/<int:cid>/spend")
@login_required
def log_spend(cid):
    aid = current_account_id()
    m = _safe_models()
    if not m:
        return jsonify({"error": "Not available"}), 503
    try:
        from app.services.marketing_attribution import record_offline_spend
        data = request.get_json(force=True)
        year = int(data.get("year", date.today().year))
        month = int(data.get("month", date.today().month))
        amount = float(data.get("amount", 0))
        record_offline_spend(aid, cid, year, month, amount, data.get("notes"))
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


@marketing_bp.post("/channels/<int:cid>/leads")
@login_required
def log_leads(cid):
    aid = current_account_id()
    m = _safe_models()
    if not m:
        return jsonify({"error": "Not available"}), 503
    try:
        from app.services.marketing_attribution import record_offline_leads
        data = request.get_json(force=True)
        year = int(data.get("year", date.today().year))
        month = int(data.get("month", date.today().month))
        record_offline_leads(
            aid, cid, year, month,
            lead_count=int(data.get("lead_count", 0)),
            booked_count=int(data.get("booked_count", 0)),
            revenue_dollars=float(data.get("revenue", 0)),
            notes=data.get("notes"),
        )
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


# ── Budget Pacing ────────────────────────────────────────────────────────────

@marketing_bp.get("/budget")
@login_required
def budget():
    aid = current_account_id()
    m = _safe_models()
    svc = _safe_attribution()
    pacing = {}
    budget_list = []
    if m and svc:
        try:
            pacing = svc["get_budget_pacing"](aid)
        except Exception:
            current_app.logger.exception("Error loading budget pacing")
        try:
            MB = m["MarketingBudget"]
            now = date.today()
            budget_list = MB.query.filter_by(account_id=aid).order_by(
                MB.period_year.desc(), MB.period_month.desc()
            ).limit(12).all()
        except Exception:
            pass
    return render_template("marketing/budget.html", pacing=pacing, budget_list=budget_list)


@marketing_bp.post("/budget")
@login_required
def budget_set():
    aid = current_account_id()
    m = _safe_models()
    if not m:
        return jsonify({"error": "Not available"}), 503
    try:
        MB = m["MarketingBudget"]
        data = request.get_json(force=True)
        year = int(data.get("year", date.today().year))
        month = int(data.get("month", date.today().month))
        amount_cents = int(float(data["amount"]) * 100)
        budget = MB.query.filter_by(account_id=aid, period_year=year, period_month=month).first()
        if budget:
            budget.total_budget_cents = amount_cents
        else:
            budget = MB(account_id=aid, period_year=year, period_month=month,
                        total_budget_cents=amount_cents, notes=data.get("notes"))
            db.session.add(budget)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


# ── Growth Optimizer ─────────────────────────────────────────────────────────

@marketing_bp.get("/growth")
@login_required
def growth():
    aid = current_account_id()
    svc = _safe_attribution()
    channel_stats = []
    growth_recs = []
    if svc:
        try:
            channel_stats = svc["get_all_channel_stats"](aid, lookback_months=3)
        except Exception:
            current_app.logger.exception("Error loading channel stats for growth")
        try:
            growth_recs = svc["get_growth_recommendations"](aid)
        except Exception:
            current_app.logger.exception("Error loading growth recs")
    return render_template(
        "marketing/growth.html",
        channel_stats=channel_stats,
        growth_recs=growth_recs,
        channel_type_labels=CHANNEL_TYPE_LABELS,
    )


# ── Revenue & LTV ────────────────────────────────────────────────────────────

@marketing_bp.get("/revenue")
@login_required
def revenue():
    aid = current_account_id()
    svc = _safe_attribution()
    ltv_data = []
    attribution = {}
    monthly_revenue = []

    if svc:
        try:
            ltv_data = svc["get_ltv_by_channel"](aid)
        except Exception:
            current_app.logger.exception("Error loading LTV data")
        try:
            attribution = svc["compute_attribution"](aid, days=365)
        except Exception:
            current_app.logger.exception("Error loading attribution")

    # Monthly revenue trend from ServiceTitan (last 12 months)
    try:
        rows = db.session.execute(text("""
            SELECT YEAR(completed_date) AS yr, MONTH(completed_date) AS mo,
                   COUNT(*) AS jobs, COALESCE(SUM(total_amount),0) AS revenue
            FROM servicetitan_jobs
            WHERE account_id=:aid AND job_status='Completed'
              AND completed_date >= :cutoff
            GROUP BY YEAR(completed_date), MONTH(completed_date)
            ORDER BY yr, mo
        """), {"aid": aid, "cutoff": date.today() - timedelta(days=365)}).mappings().all()
        monthly_revenue = [dict(r) for r in rows]
    except Exception:
        pass

    # Top job types by revenue
    top_job_types = []
    try:
        rows = db.session.execute(text("""
            SELECT job_type_name, COUNT(*) AS jobs,
                   COALESCE(SUM(total_amount),0) AS revenue,
                   COALESCE(AVG(total_amount),0) AS avg_ticket
            FROM servicetitan_jobs
            WHERE account_id=:aid AND job_status='Completed'
              AND completed_date >= :cutoff
            GROUP BY job_type_name
            ORDER BY revenue DESC LIMIT 10
        """), {"aid": aid, "cutoff": date.today() - timedelta(days=365)}).mappings().all()
        top_job_types = [dict(r) for r in rows]
    except Exception:
        pass

    # Repeat customer rate
    repeat_rate = 0
    avg_jobs_per_customer = 0
    try:
        row = db.session.execute(text("""
            SELECT COUNT(*) AS total_customers,
                   SUM(CASE WHEN job_count > 1 THEN 1 ELSE 0 END) AS repeat_customers,
                   AVG(job_count) AS avg_jobs
            FROM (
                SELECT st_customer_id, COUNT(*) AS job_count
                FROM servicetitan_jobs
                WHERE account_id=:aid AND job_status='Completed'
                GROUP BY st_customer_id
            ) sub
        """), {"aid": aid}).mappings().one_or_none()
        if row and row["total_customers"]:
            repeat_rate = round(row["repeat_customers"] / row["total_customers"] * 100, 1)
            avg_jobs_per_customer = round(float(row["avg_jobs"] or 1), 2)
    except Exception:
        pass

    return render_template(
        "marketing/revenue.html",
        ltv_data=ltv_data,
        attribution=attribution,
        monthly_revenue=monthly_revenue,
        top_job_types=top_job_types,
        repeat_rate=repeat_rate,
        avg_jobs_per_customer=avg_jobs_per_customer,
        channel_type_labels=CHANNEL_TYPE_LABELS,
    )


# ── Aggregator Leads ─────────────────────────────────────────────────────────

@marketing_bp.get("/leads")
@login_required
def leads():
    aid = current_account_id()
    m = _safe_models()
    agg_accounts = []
    recent_leads = []
    lead_counts = {}
    if m:
        try:
            AA = m["AggregatorAccount"]
            AL = m["AggregatorLead"]
            agg_accounts = AA.query.filter_by(account_id=aid).all()
            recent_leads = AL.query.filter_by(account_id=aid).order_by(
                AL.created_at.desc()
            ).limit(100).all()
            # Count by platform last 30d
            cutoff = datetime.utcnow() - timedelta(days=30)
            rows = db.session.execute(text(
                "SELECT platform, COUNT(*) AS cnt FROM aggregator_leads "
                "WHERE account_id=:aid AND created_at>=:cutoff GROUP BY platform"
            ), {"aid": aid, "cutoff": cutoff}).mappings().all()
            lead_counts = {r["platform"]: r["cnt"] for r in rows}
        except Exception:
            current_app.logger.exception("Error loading aggregator leads")
    return render_template(
        "marketing/leads.html",
        agg_accounts=agg_accounts,
        recent_leads=recent_leads,
        lead_counts=lead_counts,
        platforms=["angi", "homeadvisor", "thumbtack", "nextdoor", "bark", "houzz"],
        channel_type_labels=CHANNEL_TYPE_LABELS,
    )


@marketing_bp.post("/leads/<int:lid>/status")
@login_required
def lead_update_status(lid):
    aid = current_account_id()
    m = _safe_models()
    if not m:
        return jsonify({"error": "Not available"}), 503
    try:
        AL = m["AggregatorLead"]
        lead = AL.query.filter_by(id=lid, account_id=aid).first_or_404()
        data = request.get_json(force=True)
        lead.status = data.get("status", lead.status)
        if "revenue" in data:
            lead.booked_revenue_cents = int(float(data["revenue"]) * 100)
        if "dispute_reason" in data:
            lead.dispute_reason = data["dispute_reason"]
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


@marketing_bp.post("/aggregators")
@login_required
def aggregators_create():
    aid = current_account_id()
    m = _safe_models()
    if not m:
        return jsonify({"error": "Not available"}), 503
    try:
        AA = m["AggregatorAccount"]
        data = request.get_json(force=True)
        existing = AA.query.filter_by(account_id=aid, platform=data["platform"]).first()
        if existing:
            existing.api_key = data.get("api_key", existing.api_key)
            existing.webhook_secret = data.get("webhook_secret", existing.webhook_secret)
            existing.monthly_budget_cents = int(float(data.get("monthly_budget", 0)) * 100) if data.get("monthly_budget") else existing.monthly_budget_cents
            existing.cost_per_lead_cents = int(float(data.get("cost_per_lead", 0)) * 100) if data.get("cost_per_lead") else existing.cost_per_lead_cents
            existing.is_active = data.get("is_active", existing.is_active)
        else:
            aa = AA(
                account_id=aid,
                platform=data["platform"],
                api_key=data.get("api_key"),
                webhook_secret=data.get("webhook_secret"),
                monthly_budget_cents=int(float(data.get("monthly_budget", 0)) * 100) if data.get("monthly_budget") else None,
                cost_per_lead_cents=int(float(data.get("cost_per_lead", 0)) * 100) if data.get("cost_per_lead") else None,
            )
            db.session.add(aa)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


# ── Reputation Impact ────────────────────────────────────────────────────────

@marketing_bp.get("/reputation")
@login_required
def reputation():
    aid = current_account_id()
    now = date.today()

    # Google rating + review count trend
    review_trend = []
    try:
        rows = db.session.execute(text("""
            SELECT DATE_FORMAT(created_at, '%Y-%m') AS period,
                   COUNT(*) AS review_count,
                   AVG(rating) AS avg_rating
            FROM gmb_reviews
            WHERE account_id=:aid AND created_at >= :cutoff
            GROUP BY period ORDER BY period
        """), {"aid": aid, "cutoff": now - timedelta(days=365)}).mappings().all()
        review_trend = [dict(r) for r in rows]
    except Exception:
        pass

    # Lead volume trend (same axis as reviews)
    lead_trend = []
    try:
        rows = db.session.execute(text("""
            SELECT DATE_FORMAT(occurred_at, '%Y-%m') AS period,
                   COUNT(*) AS lead_count
            FROM lead_ingest
            WHERE account_id=:aid AND occurred_at >= :cutoff
            GROUP BY period ORDER BY period
        """), {"aid": aid, "cutoff": now - timedelta(days=365)}).mappings().all()
        lead_trend = [dict(r) for r in rows]
    except Exception:
        pass

    # Current rating from GMB
    current_rating = None
    total_reviews = 0
    try:
        row = db.session.execute(text(
            "SELECT rating, total_reviews FROM gmb_accounts WHERE account_id=:aid LIMIT 1"
        ), {"aid": aid}).mappings().one_or_none()
        if row:
            current_rating = float(row.get("rating") or 0)
            total_reviews = int(row.get("total_reviews") or 0)
    except Exception:
        pass

    # Competitor comparison (from competitive intelligence if available)
    competitor_ratings = []
    try:
        rows = db.session.execute(text("""
            SELECT competitor_name, competitor_rating, competitor_reviews
            FROM competitive_insights
            WHERE account_id=:aid ORDER BY competitor_reviews DESC LIMIT 5
        """), {"aid": aid}).mappings().all()
        competitor_ratings = [dict(r) for r in rows]
    except Exception:
        pass

    return render_template(
        "marketing/reputation.html",
        review_trend=review_trend,
        lead_trend=lead_trend,
        current_rating=current_rating,
        total_reviews=total_reviews,
        competitor_ratings=competitor_ratings,
    )


# ── Seasonal Planner ─────────────────────────────────────────────────────────

@marketing_bp.get("/seasonal")
@login_required
def seasonal():
    aid = current_account_id()

    # Historical monthly revenue/jobs to detect seasonality
    seasonal_data = []
    try:
        rows = db.session.execute(text("""
            SELECT MONTH(completed_date) AS mo,
                   AVG(monthly_rev) AS avg_revenue,
                   AVG(monthly_jobs) AS avg_jobs
            FROM (
                SELECT YEAR(completed_date) AS yr, MONTH(completed_date) AS mo,
                       SUM(total_amount) AS monthly_rev, COUNT(*) AS monthly_jobs
                FROM servicetitan_jobs
                WHERE account_id=:aid AND job_status='Completed'
                  AND completed_date >= :cutoff
                GROUP BY yr, mo
            ) sub
            GROUP BY mo ORDER BY mo
        """), {"aid": aid, "cutoff": date.today() - timedelta(days=730)}).mappings().all()
        seasonal_data = [dict(r) for r in rows]
    except Exception:
        pass

    # Current monthly channel spend
    current_channel_spend = []
    try:
        now = date.today()
        rows = db.session.execute(text("""
            SELECT mc.name, mc.channel_type, mc.monthly_budget_cents,
                   COALESCE(cse.amount_cents, 0) AS actual_spend_cents
            FROM marketing_channels mc
            LEFT JOIN channel_spend_entries cse
              ON cse.channel_id=mc.id
              AND cse.period_year=:yr AND cse.period_month=:mo
            WHERE mc.account_id=:aid AND mc.is_active=1
        """), {"aid": aid, "yr": now.year, "mo": now.month}).mappings().all()
        current_channel_spend = [dict(r) for r in rows]
    except Exception:
        pass

    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

    return render_template(
        "marketing/seasonal.html",
        seasonal_data=seasonal_data,
        current_channel_spend=current_channel_spend,
        months=months,
        channel_type_labels=CHANNEL_TYPE_LABELS,
    )


# ── Attribution detail ───────────────────────────────────────────────────────

@marketing_bp.get("/attribution")
@login_required
def attribution_view():
    aid = current_account_id()
    svc = _safe_attribution()
    m = _safe_models()
    attribution = {}
    recent_attributions = []

    if svc:
        try:
            attribution = svc["compute_attribution"](aid, days=90)
        except Exception:
            current_app.logger.exception("Error computing attribution")

    if m:
        try:
            LA = m["LeadAttribution"]
            recent_attributions = LA.query.filter_by(account_id=aid).order_by(
                LA.created_at.desc()
            ).limit(50).all()
        except Exception:
            pass

    return render_template(
        "marketing/attribution.html",
        attribution=attribution,
        recent_attributions=recent_attributions,
        channel_type_labels=CHANNEL_TYPE_LABELS,
    )


# ── AI Pricing Intelligence ──────────────────────────────────────────────────

@marketing_bp.get("/pricing-intelligence")
@login_required
def pricing_intelligence():
    aid = current_account_id()
    job_types = []
    signals = []
    has_data = False

    try:
        rows = db.session.execute(text("""
            SELECT job_type_name,
                   COUNT(*)                          AS job_count,
                   COALESCE(AVG(total_amount), 0)   AS avg_ticket,
                   COALESCE(SUM(total_amount), 0)   AS total_revenue,
                   COALESCE(MIN(total_amount), 0)   AS min_ticket,
                   COALESCE(MAX(total_amount), 0)   AS max_ticket
            FROM servicetitan_jobs
            WHERE account_id=:aid AND job_status='Completed'
              AND total_amount > 0
              AND completed_date >= :cutoff
            GROUP BY job_type_name
            ORDER BY total_revenue DESC
            LIMIT 20
        """), {"aid": aid, "cutoff": date.today() - timedelta(days=365)}).mappings().all()
        job_types = [dict(r) for r in rows]
        has_data = bool(job_types)
    except Exception:
        current_app.logger.exception("pricing_intelligence: job_types query failed")

    if has_data:
        overall_avg = (
            sum(float(j["avg_ticket"]) * int(j["job_count"]) for j in job_types)
            / max(sum(int(j["job_count"]) for j in job_types), 1)
        )
        for j in job_types:
            avg = float(j["avg_ticket"])
            cnt = int(j["job_count"])
            spread = float(j["max_ticket"]) - float(j["min_ticket"])
            j["avg_ticket"] = round(avg, 2)
            j["total_revenue"] = round(float(j["total_revenue"]), 2)
            j["min_ticket"] = round(float(j["min_ticket"]), 2)
            j["max_ticket"] = round(float(j["max_ticket"]), 2)

            # Generate pricing signals
            if avg < overall_avg * 0.7 and cnt >= 5:
                signals.append({
                    "type": "underpriced",
                    "job_type": j["job_type_name"],
                    "message": (
                        f"{j['job_type_name']} averages ${avg:,.0f}/job — "
                        f"${overall_avg - avg:,.0f} below your overall average. "
                        "High volume at low ticket often indicates pricing opportunity."
                    ),
                    "recommendation": f"Test raising price by 10–15% on next {min(cnt//3, 20)} jobs.",
                    "severity": "high" if avg < overall_avg * 0.5 else "medium",
                })
            elif spread > avg * 1.5 and cnt >= 3:
                signals.append({
                    "type": "inconsistent",
                    "job_type": j["job_type_name"],
                    "message": (
                        f"{j['job_type_name']} tickets range from ${float(j['min_ticket']):,.0f} "
                        f"to ${float(j['max_ticket']):,.0f} — a {round(spread/avg*100)}% spread."
                    ),
                    "recommendation": "Standardize pricing tiers or document when premium pricing applies.",
                    "severity": "low",
                })

    # Generate AI narrative if data exists
    ai_summary = None
    if has_data and job_types:
        try:
            from app.ai_clients import get_claude_client
            client = get_claude_client()
            if client:
                top_types = job_types[:8]
                lines = "\n".join(
                    f"- {j['job_type_name']}: {j['job_count']} jobs, avg ${j['avg_ticket']:,.0f}, "
                    f"total ${j['total_revenue']:,.0f}"
                    for j in top_types
                )
                prompt = (
                    f"You are a pricing strategist for home service businesses. "
                    f"Analyze this company's job data from the last 12 months:\n\n{lines}\n\n"
                    f"In 2–3 concise paragraphs:\n"
                    f"1. Identify 1–2 specific pricing opportunities (where they're likely leaving money on the table)\n"
                    f"2. Flag any service lines that may be priced too high (if conversion data suggests it)\n"
                    f"3. Give one concrete action they can take this week\n\n"
                    f"Be specific with numbers. No generic advice."
                )
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=400,
                    messages=[{"role": "user", "content": prompt}],
                )
                ai_summary = msg.content[0].text if msg.content else None
        except Exception:
            current_app.logger.debug("AI pricing summary skipped")

    return render_template(
        "marketing/pricing_intelligence.html",
        job_types=job_types,
        signals=signals,
        ai_summary=ai_summary,
        has_data=has_data,
    )


@marketing_bp.get("/pricing-intelligence/api")
@login_required
def pricing_intelligence_api():
    """AJAX endpoint returning the same pricing data as JSON."""
    aid = current_account_id()
    try:
        rows = db.session.execute(text("""
            SELECT job_type_name,
                   COUNT(*)                          AS job_count,
                   COALESCE(AVG(total_amount), 0)   AS avg_ticket,
                   COALESCE(SUM(total_amount), 0)   AS total_revenue
            FROM servicetitan_jobs
            WHERE account_id=:aid AND job_status='Completed'
              AND total_amount > 0
              AND completed_date >= :cutoff
            GROUP BY job_type_name ORDER BY total_revenue DESC LIMIT 20
        """), {"aid": aid, "cutoff": date.today() - timedelta(days=365)}).mappings().all()
        return jsonify({"ok": True, "job_types": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
