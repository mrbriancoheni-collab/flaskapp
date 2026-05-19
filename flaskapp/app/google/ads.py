# app/google/ads.py
from __future__ import annotations

from typing import Optional

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    flash,
    current_app,
)
from sqlalchemy import text

from app import db
from app.models_ads import (
    OptimizerRecommendation,
    OptimizerAction,
    AdsCampaign,
    AdsAdGroup,
    AdsAd,
    AdsKeyword,
    NegativeKeyword,
    SharedNegativeMap,
    GadsStatsDaily,
    SearchTerm,
    ConversionAction,
)
from app.models_ai_actions import AIActionRule, AIAction
from app.auth.utils import login_required, is_paid_account, current_account_id

# Keep this exactly once (don't also pass url_prefix again at register time)
gads_bp = Blueprint("gads_bp", __name__, url_prefix="/account/google/ads")


# ---------------------------
# Helpers
# ---------------------------
def _back_to(tab: Optional[str] = None):
    if not tab:
        tab = request.args.get("tab") or request.form.get("tab") or "campaigns"
    return redirect(url_for("gads_bp.optimize", tab=tab))


# ---------------------------
# UI: Optimize page
# ---------------------------
@gads_bp.get("/")
@login_required
def optimize():
    """
    Renders the Google Ads Optimize UI (tabs driven by ?tab=).
    Template: templates/google/ads/optimize.html
    """
    from app.models_ads import AdsCampaign, AdsAd, GadsStatsDaily
    AdsCampaign.ensure_columns()
    AdsAd.ensure_columns()
    GadsStatsDaily.ensure_columns()
    # Check if user has paid plan
    if not is_paid_account():
        flash("Google Ads Optimizer is available on paid plans. Upgrade to access optimization tools.", "warning")
        return redirect(url_for("account_bp.pricing"))

    tab = request.args.get("tab", "cockpit")
    aid = current_account_id()

    connected = False
    try:
        from app.google import _is_connected
        connected = _is_connected(aid, "ads")
    except Exception:
        pass

    # ---- Command Center (cockpit) data ----
    cockpit: dict = {}
    if tab == "cockpit" and aid:
        try:
            from datetime import date, timedelta
            today = date.today()
            thirty_ago = today - timedelta(days=30)

            # KPIs: campaign-level stats scoped to THIS account via the
            # ads_campaigns join. Isolated try/except so if this single query
            # fails the rest of the cockpit (health score, badges) still loads.
            try:
                kpi_rows = db.session.execute(text("""
                    SELECT SUM(gs.cost_micros)/1000000.0 AS spend,
                           SUM(gs.clicks)               AS clicks,
                           SUM(gs.conversions)          AS conversions,
                           SUM(gs.impressions)          AS impressions
                    FROM gads_stats_daily gs
                    JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
                    WHERE gs.entity_type = 'campaign'
                      AND gs.date >= :d
                """), {"aid": aid, "d": thirty_ago}).mappings().one_or_none()
            except Exception:
                current_app.logger.exception("cockpit KPI query failed")
                db.session.rollback()
                kpi_rows = None

            # Quick health score from DB — each count wrapped individually so a
            # missing table or column doesn't zero out the whole cockpit.
            def _safe_scalar(sql, params):
                try:
                    return db.session.execute(text(sql), params).scalar() or 0
                except Exception:
                    db.session.rollback()
                    return 0

            kw_count = _safe_scalar(
                "SELECT COUNT(*) FROM keywords k JOIN ad_groups ag ON ag.id=k.ad_group_id JOIN ads_campaigns ac ON ac.id=ag.campaign_id WHERE ac.account_id=:aid AND k.status!='removed'",
                {"aid": aid})
            neg_count = _safe_scalar(
                "SELECT COUNT(*) FROM negative_keywords nk LEFT JOIN ads_campaigns ac ON ac.id=nk.campaign_id WHERE (ac.account_id=:aid OR nk.campaign_id IS NULL) AND nk.id IS NOT NULL",
                {"aid": aid})
            ad_count = _safe_scalar(
                "SELECT COUNT(*) FROM ads a JOIN ad_groups ag ON ag.id=a.ad_group_id JOIN ads_campaigns ac ON ac.id=ag.campaign_id WHERE ac.account_id=:aid AND a.status!='removed'",
                {"aid": aid})
            camp_count = _safe_scalar(
                "SELECT COUNT(*) FROM ads_campaigns WHERE account_id=:aid AND status!='removed'",
                {"aid": aid})
            ag_count = _safe_scalar(
                "SELECT COUNT(*) FROM ad_groups ag JOIN ads_campaigns ac ON ac.id=ag.campaign_id WHERE ac.account_id=:aid",
                {"aid": aid})

            neg_ratio = neg_count / max(kw_count, 1)
            waste_score = min(100, int((neg_ratio / 2.5) * 100))
            ads_per_ag = ad_count / max(ag_count, 1)
            kw_per_ag = kw_count / max(ag_count, 1)
            struct_score = 40
            if 2 <= camp_count <= 10: struct_score += 15
            if 3 <= ads_per_ag <= 5: struct_score += 20
            elif ads_per_ag >= 2: struct_score += 10
            if 5 <= kw_per_ag <= 20: struct_score += 20
            elif kw_per_ag >= 3: struct_score += 10
            struct_score = min(100, struct_score)

            spend = float(kpi_rows["spend"] or 0) if kpi_rows else 0
            clicks = int(kpi_rows["clicks"] or 0) if kpi_rows else 0
            conversions = float(kpi_rows["conversions"] or 0) if kpi_rows else 0
            impressions = int(kpi_rows["impressions"] or 0) if kpi_rows else 0
            has_stats = spend > 0 or clicks > 0 or impressions > 0

            ctr = (clicks / impressions * 100) if impressions else 0
            # When we have NO stats data the health score defaults are meaningful:
            # structure score still reflects actual DB structure, ctr defaults to 50
            ctr_score = (90 if ctr >= 6 else (80 if ctr >= 5 else (70 if ctr >= 4 else (55 if ctr >= 3 else (40 if ctr >= 2 else 25))))) if ctr > 0 else (50 if has_stats else 0)
            # If no stats at all, show 0/N/A so user knows sync is needed
            if not has_stats and not camp_count:
                overall, grade = 0, "N/A"
            else:
                overall = int(waste_score * 0.35 + struct_score * 0.30 + ctr_score * 0.35)
                grade = "A+" if overall >= 90 else ("A" if overall >= 85 else ("A-" if overall >= 80 else ("B+" if overall >= 75 else ("B" if overall >= 70 else ("B-" if overall >= 65 else ("C+" if overall >= 60 else ("C" if overall >= 55 else ("C-" if overall >= 50 else ("D" if overall >= 40 else "F")))))))))

            # Top pending actions / counts — each isolated so a missing table
            # or column never blanks out the whole cockpit.
            def _safe_list(fn, default=None):
                try:
                    return fn()
                except Exception:
                    db.session.rollback()
                    return default if default is not None else []

            top_actions = _safe_list(lambda: OptimizerRecommendation.query.filter_by(
                account_id=aid, status="open"
            ).order_by(OptimizerRecommendation.severity.asc()).limit(8).all())

            active_rules = _safe_list(
                lambda: AIActionRule.query.filter_by(account_id=aid, enabled=True).count(),
                default=0)
            actions_today = _safe_list(lambda: AIAction.query.filter(
                AIAction.account_id == aid, AIAction.created_at >= today
            ).count(), default=0)

            pending_optimizer = _safe_list(lambda: OptimizerRecommendation.query.filter_by(
                account_id=aid, status="open").count(), default=0)
            pending_terms = _safe_scalar(
                "SELECT COUNT(*) FROM search_terms st JOIN ads_campaigns ac ON ac.id=st.campaign_id "
                "WHERE ac.account_id=:aid AND st.added_as_keyword=0 AND st.added_as_negative=0",
                {"aid": aid})
            ab_running = _safe_scalar(
                "SELECT COUNT(DISTINCT variant_group) FROM ads a "
                "JOIN ad_groups ag ON ag.id=a.ad_group_id "
                "JOIN ads_campaigns ac ON ac.id=ag.campaign_id "
                "WHERE ac.account_id=:aid AND a.variant_group IS NOT NULL",
                {"aid": aid})

            recent_actions = _safe_list(lambda: AIAction.query.filter_by(account_id=aid).order_by(
                AIAction.created_at.desc()
            ).limit(10).all())

            cockpit = {
                "health": {"overall": overall, "grade": grade, "waste": waste_score, "structure": struct_score, "ctr": ctr_score},
                "kpis": {"spend": round(spend, 2), "clicks": clicks, "conversions": round(conversions, 1), "impressions": impressions, "ctr": round(ctr, 2), "cpa": round(spend / conversions, 2) if conversions else 0},
                "needs_sync": not has_stats,
                "top_actions": top_actions,
                "active_rules": active_rules,
                "actions_today": actions_today,
                "badges": {"optimizer": pending_optimizer, "rules": active_rules, "search_terms": pending_terms, "ab_tests": ab_running},
                "recent_actions": recent_actions,
                "connected": connected,
            }
        except Exception:
            current_app.logger.exception("Error loading cockpit data")
            cockpit = {"health": {"overall": 0, "grade": "N/A"}, "kpis": {}, "top_actions": [], "badges": {}, "recent_actions": [], "connected": connected}

    keywords_data: list = []
    negatives_data: list = []
    campaigns_list: list = []
    adgroups_list: list = []
    campaigns_tab_data: list = []
    adgroups_tab_data: list = []
    ads_tab_data: list = []

    # Always load campaigns/adgroups lists for filter dropdowns on all relevant tabs
    if aid:
        try:
            campaigns_list = [
                {"id": c.id, "name": c.name}
                for c in AdsCampaign.query.filter_by(account_id=aid)
                .order_by(AdsCampaign.name)
                .all()
            ]
            camp_ids = [c["id"] for c in campaigns_list]
            if camp_ids:
                adgroups_list = [
                    {"id": ag.id, "name": ag.name, "campaign_id": ag.campaign_id}
                    for ag in AdsAdGroup.query.filter(
                        AdsAdGroup.campaign_id.in_(camp_ids)
                    )
                    .order_by(AdsAdGroup.name)
                    .all()
                ]
        except Exception:
            current_app.logger.exception("Error loading campaigns/adgroups for tab=%s", tab)

    if tab == "keywords" and aid:
        try:
            rows = db.session.execute(
                text("""
                    SELECT k.id, k.text, k.match_type, k.status, k.max_cpc_cents,
                           ag.name as adgroup_name, ag.campaign_id,
                           ac.name as campaign_name
                    FROM keywords k
                    JOIN ad_groups ag ON ag.id = k.ad_group_id
                    JOIN ads_campaigns ac ON ac.id = ag.campaign_id
                    WHERE ac.account_id = :aid AND k.status != 'removed'
                    ORDER BY ac.name, ag.name, k.text
                    LIMIT 1000
                """),
                {"aid": aid},
            ).mappings().all()
            keywords_data = [dict(r) for r in rows]
        except Exception:
            current_app.logger.exception("Error loading keywords for optimize tab")

    if tab == "negatives" and aid:
        try:
            rows = db.session.execute(
                text("""
                    SELECT nk.id, nk.text, nk.match_type, nk.scope,
                           nk.campaign_id, nk.ad_group_id,
                           ac.name as campaign_name,
                           ag.name as adgroup_name
                    FROM negative_keywords nk
                    LEFT JOIN ads_campaigns ac ON ac.id = nk.campaign_id
                    LEFT JOIN ad_groups ag ON ag.id = nk.ad_group_id
                    WHERE (ac.account_id = :aid OR (nk.campaign_id IS NULL AND nk.ad_group_id IS NULL))
                    ORDER BY nk.scope, ac.name, nk.text
                    LIMIT 1000
                """),
                {"aid": aid},
            ).mappings().all()
            negatives_data = [dict(r) for r in rows]
        except Exception:
            current_app.logger.exception("Error loading negatives for optimize tab")

    if tab == "campaigns" and aid:
        # Try Google Ads snapshot first (live/cached data), fall back to local DB
        if connected:
            try:
                from app.google import _get_ads_state
                ads_state = _get_ads_state(aid)
                if ads_state and ads_state.get("campaigns"):
                    for c in ads_state["campaigns"]:
                        campaigns_tab_data.append({
                            "id": c.get("id"),
                            "name": c.get("name", ""),
                            "status": (c.get("status") or "enabled").lower(),
                            "daily_budget_cents": int((c.get("daily_budget") or 0) * 100),
                            "network": c.get("network") or c.get("advertising_channel_type", ""),
                            "google_campaign_id": c.get("id"),
                            "start_date": None,
                            "adgroup_count": 0,
                            "keyword_count": 0,
                            "spend_30d": c.get("monthly_spend") or c.get("cost_30d") or 0,
                            "conversions_30d": c.get("conversions", 0),
                            "clicks_30d": c.get("clicks", 0),
                            "source": "google_ads",
                        })
            except Exception:
                current_app.logger.exception("Error loading campaigns from Google Ads state")

        if not campaigns_tab_data:
            # Fall back to local DB (includes manually created / draft campaigns)
            try:
                rows = db.session.execute(text("""
                    SELECT ac.id, ac.name, ac.status, ac.daily_budget_cents, ac.network,
                           ac.google_campaign_id, ac.start_date,
                           COUNT(DISTINCT ag.id) AS adgroup_count,
                           COUNT(DISTINCT k.id) AS keyword_count,
                           COALESCE(SUM(gs.cost_micros),0)/1000000.0 AS spend_30d,
                           COALESCE(SUM(gs.conversions),0) AS conversions_30d,
                           COALESCE(SUM(gs.clicks),0) AS clicks_30d,
                           AVG(gs.search_impr_share) AS avg_impr_share,
                           AVG(gs.lost_is_budget) AS avg_lost_is_budget,
                           AVG(gs.lost_is_rank) AS avg_lost_is_rank
                    FROM ads_campaigns ac
                    LEFT JOIN ad_groups ag ON ag.campaign_id = ac.id
                    LEFT JOIN keywords k ON k.ad_group_id = ag.id
                    LEFT JOIN gads_stats_daily gs ON gs.entity_type = 'campaign'
                        AND gs.entity_id = ac.id
                        AND gs.date >= (CURRENT_DATE - INTERVAL 30 DAY)
                    WHERE ac.account_id = :aid AND ac.status != 'removed'
                    GROUP BY ac.id
                    ORDER BY ac.name
                """), {"aid": aid}).mappings().all()
                campaigns_tab_data = [dict(r) for r in rows]
            except Exception:
                current_app.logger.exception("Error loading campaigns from DB")

    if tab == "adgroups" and aid:
        try:
            rows = db.session.execute(text("""
                SELECT ag.id, ag.name, ag.status, ag.max_cpc_cents,
                       ac.id AS campaign_id, ac.name AS campaign_name,
                       COUNT(DISTINCT k.id) AS keyword_count,
                       COUNT(DISTINCT a.id) AS ad_count,
                       COALESCE(SUM(gs.cost_micros),0)/1000000.0 AS spend_30d,
                       COALESCE(SUM(gs.conversions),0) AS conversions_30d,
                       COALESCE(SUM(gs.clicks),0) AS clicks_30d
                FROM ad_groups ag
                JOIN ads_campaigns ac ON ac.id = ag.campaign_id
                LEFT JOIN keywords k ON k.ad_group_id = ag.id
                LEFT JOIN ads a ON a.ad_group_id = ag.id
                LEFT JOIN gads_stats_daily gs ON gs.entity_type = 'ad_group'
                    AND gs.entity_id = ag.id
                    AND gs.date >= (CURRENT_DATE - INTERVAL 30 DAY)
                WHERE ac.account_id = :aid AND ag.status != 'removed'
                GROUP BY ag.id
                ORDER BY ac.name, ag.name
            """), {"aid": aid}).mappings().all()
            adgroups_tab_data = [dict(r) for r in rows]
        except Exception:
            current_app.logger.exception("Error loading adgroups tab")

    if tab == "ads" and aid:
        try:
            rows = db.session.execute(text("""
                SELECT a.id, a.status, a.headline1, a.headline2, a.headline3,
                       a.description1, a.final_url, a.path1, a.path2,
                       ag.id AS adgroup_id, ag.name AS adgroup_name,
                       ac.id AS campaign_id, ac.name AS campaign_name
                FROM ads a
                JOIN ad_groups ag ON ag.id = a.ad_group_id
                JOIN ads_campaigns ac ON ac.id = ag.campaign_id
                WHERE ac.account_id = :aid AND a.status != 'removed'
                ORDER BY ac.name, ag.name, a.id
                LIMIT 500
            """), {"aid": aid}).mappings().all()
            ads_tab_data = [dict(r) for r in rows]
        except Exception:
            current_app.logger.exception("Error loading ads tab")

    # Pass cockpit KPIs to top bar so it shows real numbers instead of hardcoded fallback
    kpis = cockpit.get("kpis", {}) if cockpit else {}
    gads_stats = None
    if kpis and (kpis.get("spend") or kpis.get("clicks") or kpis.get("impressions")):
        gads_stats = {
            "period": "Last 30 days",
            "spend": kpis.get("spend", 0),
            "impr": kpis.get("impressions", 0),
            "clicks": kpis.get("clicks", 0),
            "conv": kpis.get("conversions", 0),
            "cpa": kpis.get("cpa", 0),
        }

    return render_template(
        "google/ads/optimize.html",
        tab=tab,
        connected=connected,
        gads_stats=gads_stats,
        keywords_data=keywords_data,
        negatives_data=negatives_data,
        campaigns_list=campaigns_list,
        adgroups_list=adgroups_list,
        campaigns_tab_data=campaigns_tab_data,
        adgroups_tab_data=adgroups_tab_data,
        ads_tab_data=ads_tab_data,
        cockpit=cockpit,
    )


# ---------------------------
# JSON: Overview KPIs
# ---------------------------
@gads_bp.get("/overview")
@login_required
def overview():
    """
    Account-level KPI snapshot from gads_stats_daily.
    Query params: ?days=30 (default 30)
    Tries account-level rows first, then falls back to summing campaign rows.
    """
    from datetime import date as _date, timedelta as _td
    from app.models_ads import AdsCampaign, GadsStatsDaily
    AdsCampaign.ensure_columns()
    GadsStatsDaily.ensure_columns()

    aid = current_account_id()
    days = max(1, min(int(request.args.get("days", 30)), 365))
    cutoff = _date.today() - _td(days=days)

    # Scope strictly to this account via the ads_campaigns join. We compute the
    # cutoff date in Python instead of `INTERVAL :days DAY` because MySQL can't
    # parameterize the value inside an INTERVAL expression — the parameterized
    # form silently returned no rows, which is why KPIs were all zero.
    row = db.session.execute(text("""
        SELECT
          COALESCE(SUM(gs.impressions), 0)   AS impressions,
          COALESCE(SUM(gs.clicks), 0)        AS clicks,
          COALESCE(SUM(gs.cost_micros), 0)   AS cost_micros,
          COALESCE(SUM(gs.conversions), 0)   AS conversions,
          CASE WHEN COALESCE(SUM(gs.clicks), 0) > 0
               THEN COALESCE(SUM(gs.cost_micros), 0)/1000000.0/COALESCE(SUM(gs.clicks), 0)
               ELSE 0 END                    AS avg_cpc
        FROM gads_stats_daily gs
        JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
        WHERE gs.entity_type = 'campaign'
          AND gs.date >= :cutoff
    """), {"aid": aid, "cutoff": cutoff}).mappings().first() or {}

    return jsonify(dict(row))


# ---------------------------
# JSON: Debug diagnostics
# ---------------------------
@gads_bp.get("/debug/stats")
@login_required
def debug_stats():
    """Temporary diagnostic: raw row counts to diagnose zero-KPI issue."""
    from datetime import date as _date, timedelta as _td
    aid = current_account_id()
    cutoff_30 = _date.today() - _td(days=30)
    cutoff_90 = _date.today() - _td(days=90)

    out = {"account_id": aid, "errors": {}}

    def _safe(key, fn):
        try:
            out[key] = fn()
        except Exception as e:
            db.session.rollback()
            out["errors"][key] = f"{type(e).__name__}: {e}"

    # 1. Total rows in gads_stats_daily for this account (direct account_id col)
    _safe("gads_stats_total_by_account_id", lambda: db.session.execute(
        text("SELECT COUNT(*) FROM gads_stats_daily WHERE account_id = :aid"),
        {"aid": aid}
    ).scalar())

    # 1b. Total rows in gads_stats_daily without account filter (entire table)
    _safe("gads_stats_total_alltable", lambda: db.session.execute(
        text("SELECT COUNT(*) FROM gads_stats_daily")
    ).scalar())

    # 1c. Distinct account_ids in gads_stats_daily
    _safe("gads_stats_distinct_account_ids", lambda: [
        r[0] for r in db.session.execute(
            text("SELECT DISTINCT account_id FROM gads_stats_daily LIMIT 20")
        ).fetchall()
    ])

    # 2. Campaigns for this account
    _safe("ads_campaigns_count", lambda: db.session.execute(
        text("SELECT COUNT(*) FROM ads_campaigns WHERE account_id = :aid"),
        {"aid": aid}
    ).scalar())

    # 3. Campaign rows with stats (the JOIN used by /overview)
    _safe("stats_30d_via_join", lambda: db.session.execute(
        text("""
            SELECT COUNT(*) FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
            WHERE gs.entity_type = 'campaign' AND gs.date >= :cutoff
        """),
        {"aid": aid, "cutoff": cutoff_30}
    ).scalar())

    # 4. Stats without the date filter (all-time)
    _safe("stats_alltime_via_join", lambda: db.session.execute(
        text("""
            SELECT COUNT(*) FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
            WHERE gs.entity_type = 'campaign'
        """),
        {"aid": aid}
    ).scalar())

    # 5. Min/max date range of stats for this account (via JOIN)
    def _date_range():
        r = db.session.execute(
            text("""
                SELECT MIN(gs.date), MAX(gs.date)
                FROM gads_stats_daily gs
                JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
                WHERE gs.entity_type = 'campaign'
            """),
            {"aid": aid}
        ).first()
        return {"min": str(r[0]) if r and r[0] else None, "max": str(r[1]) if r and r[1] else None}
    _safe("stats_date_range_via_join", _date_range)

    # 5b. Min/max date range via account_id column directly
    def _date_range_direct():
        r = db.session.execute(
            text("SELECT MIN(date), MAX(date), COUNT(*) FROM gads_stats_daily WHERE account_id = :aid"),
            {"aid": aid}
        ).first()
        return {"min": str(r[0]) if r and r[0] else None,
                "max": str(r[1]) if r and r[1] else None,
                "count": r[2] if r else 0}
    _safe("stats_date_range_direct", _date_range_direct)

    # 6. Sample campaign IDs (local) and their google_campaign_id
    _safe("campaigns_sample", lambda: [
        {"id": r[0], "google_campaign_id": r[1], "name": r[2], "account_id": r[3]}
        for r in db.session.execute(
            text("SELECT id, google_campaign_id, name, account_id FROM ads_campaigns WHERE account_id = :aid LIMIT 5"),
            {"aid": aid}
        ).fetchall()
    ])

    # 7. Sample gads_stats_daily rows for this account (by account_id)
    _safe("stats_sample_by_account_id", lambda: [
        {"entity_type": r[0], "entity_id": r[1], "google_entity_id": r[2],
         "date": str(r[3]), "impressions": r[4], "clicks": r[5], "account_id": r[6]}
        for r in db.session.execute(
            text("SELECT entity_type, entity_id, google_entity_id, date, impressions, clicks, account_id FROM gads_stats_daily WHERE account_id = :aid ORDER BY date DESC LIMIT 5"),
            {"aid": aid}
        ).fetchall()
    ])

    # 7b. Sample any rows from the table at all
    _safe("stats_sample_any", lambda: [
        {"entity_type": r[0], "entity_id": r[1], "google_entity_id": r[2],
         "date": str(r[3]), "impressions": r[4], "clicks": r[5], "account_id": r[6]}
        for r in db.session.execute(
            text("SELECT entity_type, entity_id, google_entity_id, date, impressions, clicks, account_id FROM gads_stats_daily ORDER BY date DESC LIMIT 5")
        ).fetchall()
    ])

    # 8. List columns in gads_stats_daily (so we can confirm schema)
    _safe("gads_stats_columns", lambda: [
        r[0] for r in db.session.execute(
            text("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'gads_stats_daily'")
        ).fetchall()
    ])

    return jsonify(out)


# ---------------------------
# JSON: Optimizer
# ---------------------------
@gads_bp.get("/optimizer/data")
@login_required
def optimizer_data():
    """
    Returns optimizer recommendations (ranked).
    """
    # Check if user has paid plan
    if not is_paid_account():
        return jsonify({"error": "Paid plan required"}), 403

    rows = db.session.execute(
        text(
            """
            SELECT id, scope_type, scope_id, category, title, details,
                   expected_impact, severity, status, created_at
            FROM optimizer_recommendations
            ORDER BY severity ASC, created_at DESC
            LIMIT 200
            """
        )
    ).mappings().all()
    return jsonify(list(rows))


@gads_bp.post("/optimizer/apply")
@login_required
def optimizer_apply():
    """
    Apply optimizer recommendations:
    1. Mark recommendation as applied in DB
    2. Attempt real Google Ads API mutation via GoogleAdsAutoExecutor
    3. Fall back gracefully if Google Ads credentials unavailable
    """
    try:
        if not is_paid_account():
            return jsonify({"error": "Paid plan required"}), 403

        payload = request.get_json(force=True)
        aid = current_account_id()

        # Normalise to a list of IDs (supports both single and bulk calls)
        if "recommendation_ids" in payload:
            rec_ids = [int(x) for x in payload["recommendation_ids"]]
        elif "recommendation_id" in payload:
            rec_ids = [int(payload["recommendation_id"])]
        else:
            return jsonify({"error": "No recommendation_id(s) provided"}), 400

        applied = []
        errors = []

        # Try to instantiate the Google Ads executor (loads creds internally)
        executor = None
        try:
            from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor
            executor = GoogleAdsAutoExecutor(account_id=aid)
        except Exception:
            current_app.logger.info("Google Ads executor unavailable — applying locally only")

        for rec_id in rec_ids:
            try:
                rec = OptimizerRecommendation.query.filter_by(id=rec_id, account_id=aid).first()
                if not rec:
                    errors.append({"id": rec_id, "error": "Not found or unauthorized"})
                    continue
                if rec.status == "applied":
                    applied.append(rec_id)
                    continue

                import json as _json
                suggested = _json.loads(rec.suggested_action_json) if isinstance(rec.suggested_action_json, str) else (rec.suggested_action_json or {})

                api_result = None
                api_status = "local_only"
                action_type = suggested.get("action_type") or rec.category

                # --- Local DB mutations (always attempted) ---
                if action_type in ("budget", "increase_budget") and suggested.get("new_budget_micros"):
                    camp = AdsCampaign.query.get(suggested.get("campaign_id"))
                    if camp:
                        camp.daily_budget_cents = int(suggested["new_budget_micros"] / 10000)
                        api_status = "local_db"
                elif action_type in ("pause_keyword", "keyword_paused") and suggested.get("keyword_id"):
                    kw = AdsKeyword.query.get(suggested["keyword_id"])
                    if kw:
                        kw.status = "paused"
                        api_status = "local_db"

                # --- Attempt real Google Ads API mutation via executor ---
                if executor and action_type in ("negative_keyword", "wasted_spend") and suggested.get("negatives"):
                    try:
                        # Get customer_id from the executor's internal lookup
                        client = executor._get_google_ads_client()
                        cid = getattr(executor, "_resolved_customer_id", None)
                        if not cid:
                            # Fall back to DB lookup
                            cid_row = db.session.execute(text(
                                "SELECT google_ads_customer_id FROM accounts WHERE id=:aid"
                            ), {"aid": aid}).scalar()
                            cid = str(cid_row) if cid_row else None
                        if cid:
                            for neg in suggested["negatives"][:5]:
                                executor._execute_negative_keyword_add(
                                    action=None,
                                    customer_id=cid,
                                    search_term=neg.get("text", ""),
                                    campaign_id=int(suggested.get("campaign_id", 0)),
                                    match_type=neg.get("match_type", "PHRASE"),
                                )
                            api_status = "pushed_to_google"
                    except Exception as api_err:
                        current_app.logger.warning(f"API mutation failed for rec {rec_id}: {api_err}")
                        api_status = "api_error"

                api_result = {"status": api_status}

                # Record the action
                action = OptimizerAction(
                    recommendation_id=rec_id,
                    applied_by=getattr(current_account_id, '__self__', None) and aid or aid,
                    change_set_json=_json.dumps(suggested),
                    result_json=_json.dumps(api_result) if api_result else None,
                    status="success",
                )
                db.session.add(action)

                # Mark recommendation applied
                rec.status = "applied"
                applied.append(rec_id)

            except Exception as e:
                current_app.logger.exception(f"Error applying rec {rec_id}")
                errors.append({"id": rec_id, "error": str(e)})

        db.session.commit()
        return jsonify({
            "applied": len(applied),
            "applied_ids": applied,
            "errors": errors,
            "api_status": "pushed_to_google" if executor else "local_only",
        })

    except Exception as e:
        current_app.logger.exception("Error in optimizer_apply")
        db.session.rollback()
        return jsonify({"error": f"Failed to apply: {str(e)}"}), 500


# ---------------------------
# JSON: Drafts & Publish
# ---------------------------
@gads_bp.post("/drafts")
def create_draft():
    """
    Accepts a draft payload for validation/preview.
    {
      "campaign": {...},
      "ad_groups": [
        {
          "name": "...",
          "cpc_bid_cents": 125,
          "ads": [{"final_url": "...", "headlines": [...], "descriptions": [...], "path1": "...", "path2": "..."}],
          "keywords": [{"text": "...", "match_type": "EXACT"}, ...],
          "negatives": [{"text": "...", "match_type": "PHRASE"}, ...]
        }
      ],
      "shared_negative_list_ids": [1,2]
    }
    """
    payload = request.get_json(force=True)
    # TODO: add deeper validation if needed
    return jsonify({"status": "ok", "draft": payload})


@gads_bp.post("/publish")
def publish():
    """
    Persists campaign → ad groups → ads/keywords/negatives and attaches shared negative lists.
    """
    payload = request.get_json(force=True)
    try:
        c = payload["campaign"]
        # Campaign
        campaign = AdsCampaign(
            name=c["name"],
            status=c.get("status", "enabled"),
            daily_budget_cents=c.get("daily_budget_cents", 0),
            objective=c.get("objective"),
            network=c.get("network"),
            language=c.get("language", "en"),
            geo_targets=c.get("geo_targets")
            if isinstance(c.get("geo_targets"), str)
            else None,  # store raw JSON string if you prefer; otherwise serialize upstream
            start_date=c.get("start_date"),
            end_date=c.get("end_date"),
        )
        db.session.add(campaign)
        db.session.flush()

        # Ad Groups, Ads, Keywords, Negatives
        for ag in payload.get("ad_groups", []):
            ag_row = AdsAdGroup(
                campaign_id=campaign.id,
                name=ag["name"],
                status=ag.get("status", "enabled"),
                max_cpc_cents=ag.get("cpc_bid_cents"),
            )
            db.session.add(ag_row)
            db.session.flush()

            # Ads (RSA-like payload support)
            for ad in ag.get("ads", []):
                headlines = ad.get("headlines") or []
                descriptions = ad.get("descriptions") or []
                ad_row = AdsAd(
                    ad_group_id=ag_row.id,
                    status=ad.get("status", "enabled"),
                    ad_type=ad.get("ad_type", "text"),
                    final_url=ad["final_url"],
                    path1=ad.get("path1"),
                    path2=ad.get("path2"),
                    headline1=(headlines[0] if len(headlines) > 0 else ad.get("headline1", ""))[:30],
                    headline2=(headlines[1] if len(headlines) > 1 else ad.get("headline2"))[:30]
                    if (len(headlines) > 1 or ad.get("headline2"))
                    else None,
                    headline3=(headlines[2] if len(headlines) > 2 else ad.get("headline3"))[:30]
                    if (len(headlines) > 2 or ad.get("headline3"))
                    else None,
                    description1=(descriptions[0] if len(descriptions) > 0 else ad.get("description1"))[:90]
                    if (len(descriptions) > 0 or ad.get("description1"))
                    else None,
                    description2=(descriptions[1] if len(descriptions) > 1 else ad.get("description2"))[:90]
                    if (len(descriptions) > 1 or ad.get("description2"))
                    else None,
                )
                db.session.add(ad_row)

            # Keywords
            for kw in ag.get("keywords", []):
                kw_row = AdsKeyword(
                    ad_group_id=ag_row.id,
                    text=kw["text"],
                    match_type=(kw.get("match_type") or "EXACT").lower(),
                    status=kw.get("status", "enabled"),
                    max_cpc_cents=kw.get("max_cpc_cents"),
                )
                db.session.add(kw_row)

            # Ad group–level negatives
            for neg in ag.get("negatives", []):
                db.session.add(
                    NegativeKeyword(
                        scope="ad_group",
                        ad_group_id=ag_row.id,
                        text=neg["text"],
                        match_type=neg.get("match_type", "PHRASE"),
                    )
                )

        # Shared negative list attachments (campaign scope)
        for list_id in payload.get("shared_negative_list_ids", []):
            db.session.add(SharedNegativeMap(list_id=list_id, campaign_id=campaign.id))

        db.session.commit()
        return jsonify({"status": "created", "campaign_id": campaign.id}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


# ---------------------------
# (Optional) Legacy UI form posts (keep redirects to tabbed UI)
# If your template posts to these, leave them; otherwise remove safely.
# ---------------------------
@gads_bp.post("/campaigns/<int:cid>/status")
@login_required
def campaign_toggle_status(cid):
    aid = current_account_id()
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")  # "enabled" or "paused"
    if new_status not in ("enabled", "paused"):
        return jsonify({"error": "Invalid status"}), 400
    c = AdsCampaign.query.filter_by(id=cid, account_id=aid).first_or_404()
    c.status = new_status
    db.session.commit()
    return jsonify({"ok": True, "status": new_status})


@gads_bp.post("/campaigns/<int:cid>/budget")
@login_required
def campaign_update_budget(cid):
    aid = current_account_id()
    data = request.get_json(silent=True) or {}
    try:
        budget_cents = int(float(data.get("daily_budget", 0)) * 100)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid budget"}), 400
    if budget_cents < 0:
        return jsonify({"error": "Budget cannot be negative"}), 400
    c = AdsCampaign.query.filter_by(id=cid, account_id=aid).first_or_404()
    c.daily_budget_cents = budget_cents
    db.session.commit()
    return jsonify({"ok": True, "daily_budget_cents": budget_cents})


@gads_bp.post("/adgroups/<int:agid>/status")
@login_required
def adgroup_toggle_status(agid):
    aid = current_account_id()
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    if new_status not in ("enabled", "paused"):
        return jsonify({"error": "Invalid status"}), 400
    ag = AdsAdGroup.query.join(AdsCampaign).filter(
        AdsAdGroup.id == agid, AdsCampaign.account_id == aid
    ).first_or_404()
    ag.status = new_status
    db.session.commit()
    return jsonify({"ok": True, "status": new_status})


@gads_bp.post("/ads/<int:adid>/status")
@login_required
def ad_toggle_status(adid):
    aid = current_account_id()
    data = request.get_json(silent=True) or {}
    new_status = data.get("status")
    if new_status not in ("enabled", "paused"):
        return jsonify({"error": "Invalid status"}), 400
    ad = AdsAd.query.join(AdsAdGroup).join(AdsCampaign).filter(
        AdsAd.id == adid, AdsCampaign.account_id == aid
    ).first_or_404()
    ad.status = new_status
    db.session.commit()
    return jsonify({"ok": True, "status": new_status})


# ---------------------------
# (Optional) Legacy UI form posts (keep redirects to tabbed UI)
# If your template posts to these, leave them; otherwise remove safely.
# ---------------------------
@gads_bp.post("/update/campaigns")
def update_campaigns():
    return _back_to("campaigns")


@gads_bp.post("/update/ad_groups")
def update_ad_groups():
    return _back_to("adgroups")


@gads_bp.post("/update/ads")
def update_ads():
    return _back_to("ads")


@gads_bp.post("/update/keywords")
def update_keywords():
    return _back_to("keywords")


@gads_bp.post("/update/search_terms")
def update_search_terms():
    return _back_to("searchterms")


@gads_bp.post("/update/conversions")
def update_conversions():
    return _back_to("conversions")


@gads_bp.post("/update/ad_rotation")
def update_ad_rotation():
    return _back_to("adrotation")


@gads_bp.route("/apply_suggestions", methods=["GET", "POST"])
def apply_suggestions():
    # just bounce back to whatever tab (default: campaigns)
    return _back_to(request.args.get("tab"))


# ---------------------------
# Keyword management API
# ---------------------------

def _verify_keyword_ownership(keyword_id: int, aid: int) -> "AdsKeyword | None":
    """Return keyword if it belongs to the current account, else None."""
    row = db.session.execute(
        text("""
            SELECT k.id FROM keywords k
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE k.id = :kid AND ac.account_id = :aid
        """),
        {"kid": keyword_id, "aid": aid},
    ).fetchone()
    if not row:
        return None
    return AdsKeyword.query.get(keyword_id)


@gads_bp.post("/keywords/bulk-action")
@login_required
def keywords_bulk_action():
    """
    Pause, enable, or delete a list of keyword IDs.
    Body: {"action": "pause"|"enable"|"delete", "ids": [1,2,3]}
    """
    if not is_paid_account():
        return jsonify({"error": "Paid plan required"}), 403

    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    payload = request.get_json(force=True) or {}
    action = payload.get("action", "")
    ids = [int(i) for i in (payload.get("ids") or []) if str(i).isdigit()]

    if action not in ("pause", "enable", "delete") or not ids:
        return jsonify({"error": "Invalid action or empty ids"}), 400

    updated = 0
    try:
        for kid in ids:
            kw = _verify_keyword_ownership(kid, aid)
            if not kw:
                continue
            if action == "pause":
                kw.status = "paused"
            elif action == "enable":
                kw.status = "enabled"
            elif action == "delete":
                kw.status = "removed"
            updated += 1
        db.session.commit()
        return jsonify({"ok": True, "updated": updated})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("keywords_bulk_action error")
        return jsonify({"error": str(e)}), 500


@gads_bp.post("/keywords/add")
@login_required
def keywords_add():
    """
    Add a keyword to an ad group.
    Body: {"text": "...", "match_type": "broad|phrase|exact", "max_cpc_cents": 100, "ad_group_id": 5}
    """
    if not is_paid_account():
        return jsonify({"error": "Paid plan required"}), 403

    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    payload = request.get_json(force=True) or {}
    kw_text = (payload.get("text") or "").strip()
    match_type = (payload.get("match_type") or "broad").lower()
    ad_group_id = payload.get("ad_group_id")
    max_cpc_cents = payload.get("max_cpc_cents")

    if not kw_text or not ad_group_id:
        return jsonify({"error": "text and ad_group_id are required"}), 400
    if match_type not in ("broad", "phrase", "exact"):
        return jsonify({"error": "match_type must be broad, phrase, or exact"}), 400

    # Verify ad group belongs to this account
    ag_check = db.session.execute(
        text("""
            SELECT ag.id FROM ad_groups ag
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE ag.id = :agid AND ac.account_id = :aid
        """),
        {"agid": int(ad_group_id), "aid": aid},
    ).fetchone()
    if not ag_check:
        return jsonify({"error": "Ad group not found"}), 404

    try:
        kw = AdsKeyword(
            ad_group_id=int(ad_group_id),
            text=kw_text,
            match_type=match_type,
            status="enabled",
            max_cpc_cents=int(max_cpc_cents) if max_cpc_cents is not None else None,
        )
        db.session.add(kw)
        db.session.commit()
        return jsonify({"ok": True, "id": kw.id}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("keywords_add error")
        return jsonify({"error": str(e)}), 500


# ---------------------------
# Negative keyword management API
# ---------------------------

@gads_bp.post("/negatives/add")
@login_required
def negatives_add():
    """
    Add a negative keyword.
    Body: {"text": "...", "match_type": "PHRASE", "scope": "campaign|ad_group",
           "campaign_id": 1, "ad_group_id": null}
    """
    if not is_paid_account():
        return jsonify({"error": "Paid plan required"}), 403

    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    payload = request.get_json(force=True) or {}
    neg_text = (payload.get("text") or "").strip()
    match_type = (payload.get("match_type") or "PHRASE").upper()
    scope = (payload.get("scope") or "campaign").lower()
    campaign_id = payload.get("campaign_id")
    ad_group_id = payload.get("ad_group_id")

    if not neg_text:
        return jsonify({"error": "text is required"}), 400
    if match_type not in ("BROAD", "PHRASE", "EXACT"):
        return jsonify({"error": "match_type must be BROAD, PHRASE, or EXACT"}), 400
    if scope not in ("campaign", "ad_group"):
        return jsonify({"error": "scope must be campaign or ad_group"}), 400
    if scope == "campaign" and not campaign_id:
        return jsonify({"error": "campaign_id required for campaign scope"}), 400
    if scope == "ad_group" and not ad_group_id:
        return jsonify({"error": "ad_group_id required for ad_group scope"}), 400

    # Ownership checks
    if campaign_id:
        camp_check = db.session.execute(
            text("SELECT id FROM ads_campaigns WHERE id = :cid AND account_id = :aid"),
            {"cid": int(campaign_id), "aid": aid},
        ).fetchone()
        if not camp_check:
            return jsonify({"error": "Campaign not found"}), 404

    if ad_group_id:
        ag_check = db.session.execute(
            text("""
                SELECT ag.id FROM ad_groups ag
                JOIN ads_campaigns ac ON ac.id = ag.campaign_id
                WHERE ag.id = :agid AND ac.account_id = :aid
            """),
            {"agid": int(ad_group_id), "aid": aid},
        ).fetchone()
        if not ag_check:
            return jsonify({"error": "Ad group not found"}), 404

    try:
        neg = NegativeKeyword(
            scope=scope,
            text=neg_text,
            match_type=match_type,
            campaign_id=int(campaign_id) if campaign_id else None,
            ad_group_id=int(ad_group_id) if ad_group_id else None,
        )
        db.session.add(neg)
        db.session.commit()
        return jsonify({"ok": True, "id": neg.id}), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("negatives_add error")
        return jsonify({"error": str(e)}), 500


@gads_bp.route("/negatives/<int:neg_id>", methods=["DELETE"])
@login_required
def negatives_delete(neg_id: int):
    """Remove a negative keyword by ID (must belong to current account)."""
    if not is_paid_account():
        return jsonify({"error": "Paid plan required"}), 403

    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    # Verify ownership via campaign or ad_group linkage
    row = db.session.execute(
        text("""
            SELECT nk.id FROM negative_keywords nk
            LEFT JOIN ads_campaigns ac ON ac.id = nk.campaign_id
            LEFT JOIN ad_groups ag ON ag.id = nk.ad_group_id
            LEFT JOIN ads_campaigns ac2 ON ac2.id = ag.campaign_id
            WHERE nk.id = :nid
              AND (ac.account_id = :aid OR ac2.account_id = :aid)
        """),
        {"nid": neg_id, "aid": aid},
    ).fetchone()

    if not row:
        return jsonify({"error": "Negative keyword not found"}), 404

    try:
        neg = NegativeKeyword.query.get(neg_id)
        if neg:
            db.session.delete(neg)
            db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("negatives_delete error")
        return jsonify({"error": str(e)}), 500


# ---------------------------
# Cron: daily data sync
# ---------------------------
@gads_bp.post("/sync")
@login_required
def sync():
    """
    Trigger a full Google Ads data sync for the current account.
    Pulls campaign / ad group / keyword stats + search terms from the API,
    upserts GadsStatsDaily and SearchTerm, then re-runs the optimizer engine.
    Returns JSON summary.
    """
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    days = int(request.args.get("days", 30))
    result = {"sync": {}, "optimizer": {}, "errors": []}

    try:
        from app.services.google_ads_sync import sync_account
        result["sync"] = sync_account(aid, days=days)
    except Exception as exc:
        current_app.logger.exception("Google Ads sync failed for account %s", aid)
        result["errors"].append(f"Sync: {exc}")

    try:
        from app.services.google_ads_optimizer_engine import generate_recommendations
        result["optimizer"] = generate_recommendations(aid)
    except Exception as exc:
        current_app.logger.exception("Optimizer engine failed for account %s", aid)
        result["errors"].append(f"Optimizer: {exc}")

    try:
        from app.services.google_ads_sync import sync_conversions
        result["conversions"] = sync_conversions(aid)
    except Exception as exc:
        current_app.logger.warning("Conversions sync failed for account %s: %s", aid, exc)

    status = 200 if not result["errors"] else 207
    return jsonify(result), status


# ---------------------------
# Search Terms tab
# ---------------------------
@gads_bp.get("/search-terms")
@login_required
def search_terms():
    """
    Render the search terms tab — shows the latest search term report
    with one-click Add as Keyword / Add as Negative actions.
    """
    aid = current_account_id()
    if not aid:
        return redirect(url_for("gads_bp.optimize"))

    try:
        rows = db.session.execute(text("""
            SELECT st.id, st.search_term, st.clicks, st.impressions,
                   st.cost_micros, st.conversions,
                   st.added_as_keyword, st.added_as_negative,
                   ac.name AS campaign_name, ac.id AS campaign_id,
                   ag.name AS adgroup_name, ag.id AS adgroup_id
            FROM search_terms st
            LEFT JOIN ads_campaigns ac ON ac.id = st.campaign_id
            LEFT JOIN ad_groups ag ON ag.id = st.ad_group_id
            WHERE (ac.account_id = :aid OR st.campaign_id IS NULL)
              AND st.date >= (CURRENT_DATE - INTERVAL 30 DAY)
            ORDER BY st.cost_micros DESC, st.clicks DESC
            LIMIT 500
        """), {"aid": aid}).mappings().all()
        terms_data = [dict(r) for r in rows]
    except Exception:
        current_app.logger.exception("Error loading search terms")
        terms_data = []

    campaigns_list = [
        {"id": c.id, "name": c.name}
        for c in AdsCampaign.query.filter_by(account_id=aid).order_by(AdsCampaign.name).all()
    ]

    return render_template(
        "google/ads/search_terms.html",
        terms_data=terms_data,
        campaigns_list=campaigns_list,
    )


@gads_bp.post("/search-terms/<int:term_id>/add-keyword")
@login_required
def search_term_add_keyword(term_id: int):
    """Add a search term as an exact-match keyword in its ad group."""
    from app.models_ads import SearchTerm, AdsKeyword
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    st = SearchTerm.query.get_or_404(term_id)

    # Verify account ownership via campaign link
    if st.campaign_id:
        camp = AdsCampaign.query.filter_by(id=st.campaign_id, account_id=aid).first()
        if not camp:
            return jsonify({"error": "Forbidden"}), 403

    if not st.ad_group_id:
        return jsonify({"error": "No ad group associated with this search term"}), 400

    match_type = request.json.get("match_type", "exact") if request.is_json else "exact"

    try:
        # Check for duplicate
        existing = AdsKeyword.query.filter_by(
            ad_group_id=st.ad_group_id,
            text=st.search_term,
            match_type=match_type,
        ).first()
        if existing:
            st.added_as_keyword = True
            db.session.commit()
            return jsonify({"ok": True, "duplicate": True, "keyword_id": existing.id})

        kw = AdsKeyword(
            ad_group_id=st.ad_group_id,
            text=st.search_term,
            match_type=match_type,
            status="enabled",
        )
        db.session.add(kw)
        st.added_as_keyword = True
        db.session.commit()
        return jsonify({"ok": True, "keyword_id": kw.id}), 201
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("search_term_add_keyword error")
        return jsonify({"error": str(exc)}), 500


@gads_bp.post("/search-terms/<int:term_id>/add-negative")
@login_required
def search_term_add_negative(term_id: int):
    """Add a search term as a campaign-level negative keyword."""
    from app.models_ads import SearchTerm
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    st = SearchTerm.query.get_or_404(term_id)

    if st.campaign_id:
        camp = AdsCampaign.query.filter_by(id=st.campaign_id, account_id=aid).first()
        if not camp:
            return jsonify({"error": "Forbidden"}), 403

    scope = request.json.get("scope", "campaign") if request.is_json else "campaign"
    match_type = request.json.get("match_type", "exact") if request.is_json else "exact"

    try:
        neg = NegativeKeyword(
            scope=scope,
            campaign_id=st.campaign_id if scope == "campaign" else None,
            ad_group_id=st.ad_group_id if scope == "ad_group" else None,
            text=st.search_term,
            match_type=match_type.upper(),
        )
        db.session.add(neg)
        st.added_as_negative = True
        db.session.commit()
        return jsonify({"ok": True, "negative_id": neg.id}), 201
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("search_term_add_negative error")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Item 6: Conversion Tracking
# ---------------------------------------------------------------------------
@gads_bp.get("/conversions")
@login_required
def conversions():
    """List conversion actions synced from Google Ads."""
    aid = current_account_id()
    if not aid:
        return redirect(url_for("gads_bp.optimize"))

    from app.models_ads import ConversionAction
    actions = ConversionAction.query.filter_by(account_id=aid).order_by(
        ConversionAction.conversions_30d.desc()
    ).all()

    return render_template(
        "google/ads/conversions.html",
        conversions=actions,
    )


@gads_bp.post("/conversions/sync")
@login_required
def conversions_sync():
    """Sync conversion actions from Google Ads API."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        from app.services.google_ads_sync import sync_conversions
        result = sync_conversions(aid)
        return jsonify({"ok": True, **result}), 200
    except Exception as exc:
        current_app.logger.exception("conversions_sync error")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Item 7: Automated Rule Engine
# ---------------------------------------------------------------------------
@gads_bp.get("/rules")
@login_required
def rules_list():
    """Manage automation rules."""
    aid = current_account_id()
    if not aid:
        return redirect(url_for("gads_bp.optimize"))

    from app.models_ai_actions import AIActionRule, AIAction
    rules = AIActionRule.query.filter_by(account_id=aid).order_by(
        AIActionRule.enabled.desc(), AIActionRule.created_at.desc()
    ).all()
    recent_actions = AIAction.query.filter_by(account_id=aid).order_by(
        AIAction.created_at.desc()
    ).limit(50).all()

    return render_template(
        "google/ads/rules.html",
        rules=rules,
        recent_actions=recent_actions,
    )


@gads_bp.post("/rules")
@login_required
def rules_create():
    """Create a new automation rule."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    from app.models_ai_actions import AIActionRule
    data = request.get_json(force=True)

    try:
        conditions_raw = data.get("conditions", {})
        if isinstance(conditions_raw, str):
            import json as _json
            conditions_raw = _json.loads(conditions_raw)

        rule = AIActionRule(
            account_id=aid,
            rule_name=data["rule_name"],
            action_type=data["action_type"],
            conditions=conditions_raw,
            auto_execute=bool(data.get("auto_execute", False)),
            min_confidence=float(data.get("min_confidence", 0.8)),
            enabled=bool(data.get("enabled", True)),
            max_actions_per_day=int(data.get("max_actions_per_day", 50)),
            max_actions_per_campaign=int(data.get("max_actions_per_campaign", 10)),
        )
        db.session.add(rule)
        db.session.commit()
        return jsonify({"ok": True, "id": rule.id}), 201
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("rules_create error")
        return jsonify({"error": str(exc)}), 500


@gads_bp.post("/rules/<int:rule_id>/toggle")
@login_required
def rules_toggle(rule_id: int):
    """Enable or disable a rule."""
    from app.models_ai_actions import AIActionRule
    aid = current_account_id()
    rule = AIActionRule.query.filter_by(id=rule_id, account_id=aid).first_or_404()
    rule.enabled = not rule.enabled
    db.session.commit()
    return jsonify({"ok": True, "enabled": rule.enabled})


@gads_bp.delete("/rules/<int:rule_id>")
@login_required
def rules_delete(rule_id: int):
    """Delete a rule."""
    from app.models_ai_actions import AIActionRule
    aid = current_account_id()
    rule = AIActionRule.query.filter_by(id=rule_id, account_id=aid).first_or_404()
    db.session.delete(rule)
    db.session.commit()
    return jsonify({"ok": True})


@gads_bp.post("/rules/run")
@login_required
def rules_run():
    """Evaluate and (optionally) execute all enabled rules now."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    try:
        from app.services.google_ads_rule_engine import run_rules
        result = run_rules(aid)
        return jsonify({"ok": True, **result}), 200
    except Exception as exc:
        current_app.logger.exception("rules_run error")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Item 8: Campaign Cloning
# ---------------------------------------------------------------------------
@gads_bp.post("/campaigns/<int:cid>/clone")
@login_required
def campaign_clone(cid: int):
    """Deep-copy a campaign (ad groups → ads + keywords + negatives)."""
    import copy
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    src = AdsCampaign.query.filter_by(id=cid, account_id=aid).first_or_404()

    data = request.get_json(force=True) or {}
    new_name = data.get("name") or f"{src.name} (Copy)"
    new_budget = data.get("daily_budget_cents", src.daily_budget_cents)

    try:
        clone = AdsCampaign(
            account_id=aid,
            name=new_name,
            objective=src.objective,
            status="paused",  # clones start paused
            daily_budget_cents=new_budget,
            network=src.network,
            language=src.language,
            geo_targets=src.geo_targets,
            bid_strategy=src.bid_strategy,
            target_cpa_micros=src.target_cpa_micros,
            target_roas=src.target_roas,
        )
        db.session.add(clone)
        db.session.flush()  # get clone.id

        for ag in src.ad_groups:
            new_ag = AdsAdGroup(
                campaign_id=clone.id,
                name=ag.name,
                status="paused",
                max_cpc_cents=ag.max_cpc_cents,
            )
            db.session.add(new_ag)
            db.session.flush()

            for ad in ag.ads:
                db.session.add(AdsAd(
                    ad_group_id=new_ag.id,
                    status="paused",
                    ad_type=ad.ad_type,
                    headline1=ad.headline1,
                    headline2=ad.headline2,
                    headline3=ad.headline3,
                    description1=ad.description1,
                    description2=ad.description2,
                    path1=ad.path1,
                    path2=ad.path2,
                    final_url=ad.final_url,
                ))

            for kw in ag.keywords:
                db.session.add(AdsKeyword(
                    ad_group_id=new_ag.id,
                    text=kw.text,
                    match_type=kw.match_type,
                    status="paused",
                    max_cpc_cents=kw.max_cpc_cents,
                ))

            # Copy ad group–level negatives
            neg_rows = NegativeKeyword.query.filter_by(
                scope="ad_group", ad_group_id=ag.id
            ).all()
            for neg in neg_rows:
                db.session.add(NegativeKeyword(
                    scope="ad_group",
                    ad_group_id=new_ag.id,
                    text=neg.text,
                    match_type=neg.match_type,
                ))

        # Copy campaign-level negatives
        camp_negs = NegativeKeyword.query.filter_by(
            scope="campaign", campaign_id=src.id
        ).all()
        for neg in camp_negs:
            db.session.add(NegativeKeyword(
                scope="campaign",
                campaign_id=clone.id,
                text=neg.text,
                match_type=neg.match_type,
            ))

        db.session.commit()
        return jsonify({"ok": True, "clone_id": clone.id, "name": clone.name}), 201

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("campaign_clone error")
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Item 9: Bid Strategy — update route
# ---------------------------------------------------------------------------
@gads_bp.post("/campaigns/<int:cid>/bid-strategy")
@login_required
def campaign_bid_strategy(cid: int):
    """Set bid strategy and optional target values for a campaign."""
    aid = current_account_id()
    camp = AdsCampaign.query.filter_by(id=cid, account_id=aid).first_or_404()

    data = request.get_json(force=True) or {}
    valid = {"manual_cpc", "target_cpa", "target_roas",
             "maximize_conversions", "maximize_conversion_value", "enhanced_cpc"}
    strategy = data.get("bid_strategy", "manual_cpc")
    if strategy not in valid:
        return jsonify({"error": f"Unknown strategy: {strategy}"}), 400

    camp.bid_strategy = strategy
    camp.target_cpa_micros = (
        int(float(data["target_cpa"]) * 1_000_000)
        if data.get("target_cpa") else None
    )
    camp.target_roas = float(data["target_roas"]) if data.get("target_roas") else None

    try:
        db.session.commit()
        return jsonify({"ok": True, "bid_strategy": strategy})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Item 10: A/B Ad Testing
# ---------------------------------------------------------------------------
@gads_bp.get("/ab-tests")
@login_required
def ab_tests():
    """List A/B ad tests for this account."""
    from app.models_ads import AdsAd
    AdsAd.ensure_columns()
    aid = current_account_id()
    if not aid:
        return redirect(url_for("gads_bp.optimize"))

    rows = db.session.execute(text("""
        SELECT
            a.variant_group,
            a.test_name,
            COUNT(*) AS variant_count,
            MAX(CASE WHEN a.is_control THEN a.headline1 END) AS control_headline,
            ag.name AS adgroup_name,
            ac.name AS camp_name,
            SUM(gs.impressions) AS total_impr,
            SUM(gs.clicks) AS total_clicks,
            SUM(gs.conversions) AS total_conv,
            SUM(gs.cost_micros) AS total_cost
        FROM ads a
        JOIN ad_groups ag ON ag.id = a.ad_group_id
        JOIN ads_campaigns ac ON ac.id = ag.campaign_id
        LEFT JOIN gads_stats_daily gs ON gs.entity_id = a.id
            AND gs.entity_type = 'ad'
            AND gs.account_id = :aid
            AND gs.date >= (CURRENT_DATE - INTERVAL 30 DAY)
        WHERE a.variant_group IS NOT NULL
          AND ac.account_id = :aid
        GROUP BY a.variant_group, a.test_name, ag.name, ac.name
        ORDER BY total_impr DESC
    """), {"aid": aid}).mappings().all()

    tests = [dict(r) for r in rows]

    # For each test, load variant details
    for t in tests:
        variants = AdsAd.query.join(AdsAdGroup).join(AdsCampaign).filter(
            AdsAd.variant_group == t["variant_group"],
            AdsCampaign.account_id == aid,
        ).all()
        t["variants"] = [
            {
                "id": v.id,
                "headline1": v.headline1,
                "headline2": v.headline2,
                "description1": v.description1,
                "is_control": v.is_control,
                "status": v.status,
            }
            for v in variants
        ]

    return render_template("google/ads/ab_tests.html", tests=tests)


@gads_bp.post("/ab-tests")
@login_required
def ab_tests_create():
    """Create a new A/B test from two ad variants in the same ad group."""
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(force=True) or {}
    ad_group_id = data.get("ad_group_id")
    test_name = data.get("test_name", "Ad Test")
    variants = data.get("variants", [])  # list of {headline1, headline2, headline3, description1, description2, final_url, is_control}

    if len(variants) < 2:
        return jsonify({"error": "At least 2 variants required"}), 400

    ag = AdsAdGroup.query.join(AdsCampaign).filter(
        AdsAdGroup.id == ad_group_id,
        AdsCampaign.account_id == aid,
    ).first_or_404()

    import uuid
    group_id = str(uuid.uuid4())[:16]

    try:
        for v in variants:
            db.session.add(AdsAd(
                ad_group_id=ag.id,
                status="enabled",
                ad_type="text",
                headline1=v.get("headline1", ""),
                headline2=v.get("headline2"),
                headline3=v.get("headline3"),
                description1=v.get("description1"),
                description2=v.get("description2"),
                path1=v.get("path1"),
                path2=v.get("path2"),
                final_url=v.get("final_url", ""),
                variant_group=group_id,
                is_control=bool(v.get("is_control", False)),
                test_name=test_name,
            ))
        db.session.commit()
        return jsonify({"ok": True, "variant_group": group_id}), 201
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("ab_tests_create error")
        return jsonify({"error": str(exc)}), 500


@gads_bp.post("/ab-tests/<string:group_id>/pick-winner")
@login_required
def ab_test_pick_winner(group_id: str):
    """
    Pause all non-winning variants in a test.
    Accepts JSON: {winner_ad_id: int}
    """
    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json(force=True) or {}
    winner_id = data.get("winner_ad_id")

    variants = AdsAd.query.join(AdsAdGroup).join(AdsCampaign).filter(
        AdsAd.variant_group == group_id,
        AdsCampaign.account_id == aid,
    ).all()

    if not variants:
        return jsonify({"error": "No variants found"}), 404

    paused = []
    for v in variants:
        if v.id != winner_id:
            v.status = "paused"
            paused.append(v.id)

    try:
        db.session.commit()
        return jsonify({"ok": True, "winner_id": winner_id, "paused": paused})
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Google Ads Tool — Analysis Document
# ---------------------------------------------------------------------------
@gads_bp.get("/analysis")
@login_required
def analysis_doc():
    """Render the Google Ads Tool analysis & architecture document."""
    import datetime
    return render_template(
        "google/ads/analysis_doc.html",
        now=datetime.datetime.utcnow().strftime("%B %d, %Y"),
    )
