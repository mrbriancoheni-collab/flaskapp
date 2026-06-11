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
    AdsAccountGoal,
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
    days = int(request.args.get("days", 30))
    if days not in (7, 30, 90):
        days = 30
    aid = current_account_id()

    connected = False
    try:
        from app.google import _is_connected
        connected = _is_connected(aid, "ads")
    except Exception:
        pass

    # Data freshness — when did the last sync complete?
    last_synced_at = None
    last_synced_stale = False
    if aid:
        try:
            from datetime import datetime as _dt, timedelta as _td
            raw = db.session.execute(text(
                "SELECT setting_value FROM account_settings "
                "WHERE account_id = :aid AND setting_key = 'gads_last_synced_at' LIMIT 1"
            ), {"aid": aid}).scalar()
            if raw:
                last_synced_at = _dt.fromisoformat(raw)
                last_synced_stale = (_dt.utcnow() - last_synced_at) > _td(hours=24)
        except Exception:
            db.session.rollback()

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

            spend = float(kpi_rows["spend"] or 0) if kpi_rows else 0
            clicks = int(kpi_rows["clicks"] or 0) if kpi_rows else 0
            conversions = float(kpi_rows["conversions"] or 0) if kpi_rows else 0
            impressions = int(kpi_rows["impressions"] or 0) if kpi_rows else 0
            has_stats = spend > 0 or clicks > 0 or impressions > 0
            ctr = (clicks / impressions * 100) if impressions else 0

            # Load account goals for health score goal_performance section
            aid_goals = None
            try:
                aid_goals = AdsAccountGoal.query.filter_by(account_id=aid).first()
            except Exception:
                pass

            # Rich 7-dimension health score via dedicated service
            health = {"overall": 0, "grade": "N/A"}
            try:
                from app.services.google_ads_health_score import compute_health_score
                health = compute_health_score(aid, aid_goals=aid_goals)
            except Exception:
                current_app.logger.exception("Health score computation failed")

            def _safe_scalar(sql, params):
                try:
                    return db.session.execute(text(sql), params).scalar() or 0
                except Exception:
                    db.session.rollback()
                    return 0

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
                "health": health,
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
                           ac.name as campaign_name,
                           (
                               SELECT gs.quality_score
                               FROM gads_stats_daily gs
                               WHERE gs.entity_type = 'keyword'
                                 AND gs.entity_id = k.id
                                 AND gs.quality_score IS NOT NULL
                               ORDER BY gs.date DESC
                               LIMIT 1
                           ) AS quality_score
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
        days=days,
        connected=connected,
        gads_stats=gads_stats,
        keywords_data=keywords_data,
        keywords_truncated=len(keywords_data) >= 1000,
        negatives_data=negatives_data,
        negatives_truncated=len(negatives_data) >= 1000,
        campaigns_list=campaigns_list,
        adgroups_list=adgroups_list,
        campaigns_tab_data=campaigns_tab_data,
        adgroups_tab_data=adgroups_tab_data,
        ads_tab_data=ads_tab_data,
        ads_truncated=len(ads_tab_data) >= 500,
        cockpit=cockpit,
        last_synced_at=last_synced_at,
        last_synced_stale=last_synced_stale,
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
                   expected_impact, severity, status, created_at,
                   suggested_action_json
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
                    applied.append({"id": rec_id, "api_status": "already_applied"})
                    continue

                import json as _json
                suggested = _json.loads(rec.suggested_action_json) if isinstance(rec.suggested_action_json, str) else (rec.suggested_action_json or {})

                api_result = None
                api_status = "local_only"
                action_type = suggested.get("action_type") or rec.category

                # --- Google Ads API mutation first, local DB mirror second ---
                # The local row is only updated when the API push succeeds (or
                # when no executor is available, in which case we surface
                # "local_only" so the UI can warn the user).
                if action_type in ("budget", "increase_budget"):
                    new_micros = suggested.get("new_budget_micros") or (
                        int(suggested["suggested_budget_cents"]) * 10000
                        if suggested.get("suggested_budget_cents") else None
                    )
                    camp_id = suggested.get("campaign_id")
                    if new_micros and camp_id:
                        if executor:
                            try:
                                executor.execute_update_budget(int(camp_id), int(new_micros))
                                api_status = "pushed_to_google"
                            except Exception as api_err:
                                current_app.logger.warning(f"Budget push failed for rec {rec_id}: {api_err}")
                                errors.append({"id": rec_id, "error": f"Google Ads push failed: {api_err}"})
                                continue
                        camp = AdsCampaign.query.get(camp_id)
                        if camp:
                            camp.daily_budget_cents = int(new_micros / 10000)
                            if api_status != "pushed_to_google":
                                api_status = "local_db"
                elif action_type in ("pause_keyword", "keyword_paused") and suggested.get("keyword_id"):
                    if executor:
                        try:
                            executor.execute_pause_keyword(int(suggested["keyword_id"]))
                            api_status = "pushed_to_google"
                        except Exception as api_err:
                            current_app.logger.warning(f"Keyword pause push failed for rec {rec_id}: {api_err}")
                            errors.append({"id": rec_id, "error": f"Google Ads push failed: {api_err}"})
                            continue
                    kw = AdsKeyword.query.get(suggested["keyword_id"])
                    if kw:
                        kw.status = "paused"
                        if api_status != "pushed_to_google":
                            api_status = "local_db"
                elif action_type in ("change_match_type", "broad_match") and suggested.get("keyword_id"):
                    to_match = (suggested.get("to") or "phrase").lower()
                    if executor:
                        try:
                            executor.execute_change_match_type(int(suggested["keyword_id"]), to=to_match)
                            api_status = "pushed_to_google"
                        except Exception as api_err:
                            current_app.logger.warning(f"Match type push failed for rec {rec_id}: {api_err}")
                            errors.append({"id": rec_id, "error": f"Google Ads push failed: {api_err}"})
                            continue
                    kw = AdsKeyword.query.get(suggested["keyword_id"])
                    if kw:
                        # In Google a match-type change = new keyword + pause old;
                        # locally we mirror the end state on the same row.
                        kw.match_type = to_match
                        if api_status != "pushed_to_google":
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
                applied.append({"id": rec_id, "api_status": api_status})

            except Exception as e:
                current_app.logger.exception(f"Error applying rec {rec_id}")
                errors.append({"id": rec_id, "error": str(e)})

        db.session.commit()
        pushed = sum(1 for a in applied if a["api_status"] == "pushed_to_google")
        local_only = len(applied) - pushed
        return jsonify({
            "applied": len(applied),
            "applied_ids": [a["id"] for a in applied],
            "pushed_to_google": pushed,
            "local_only": local_only,
            "errors": errors,
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
    # Default to phrase — broad match must be an explicit choice, since it
    # routinely pulls in product/DIY queries for home-service advertisers.
    match_type = (payload.get("match_type") or "phrase").lower()
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
# Smart Bulk Actions
# ---------------------------

@gads_bp.post("/bulk-pause-wasted")
@login_required
def bulk_pause_wasted():
    """
    Pause all enabled keywords with spend > $5 and 0 conversions in the given date window.
    Query param: ?days=7|30|90 (default 30)
    Returns {"paused": N, "saved_micros": M}
    """
    if not is_paid_account():
        return jsonify({"error": "Paid plan required"}), 403

    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    days = int(request.args.get("days", 30))
    if days not in (7, 30, 90):
        days = 30
    preview = request.args.get("preview") == "1"

    from datetime import date as _date, timedelta as _td
    cutoff = _date.today() - _td(days=days)

    try:
        rows = db.session.execute(text("""
            SELECT gs.entity_id AS kw_id,
                   SUM(gs.cost_micros) AS total_cost_micros
            FROM gads_stats_daily gs
            JOIN keywords k ON k.id = gs.entity_id
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE gs.entity_type = 'keyword'
              AND ac.account_id = :aid
              AND gs.date >= :cutoff
              AND k.status = 'enabled'
            GROUP BY gs.entity_id
            HAVING SUM(gs.cost_micros) >= 5000000 AND SUM(gs.conversions) = 0
        """), {"aid": aid, "cutoff": cutoff}).mappings().all()

        if preview:
            count = len(rows)
            total_micros = sum(int(r["total_cost_micros"]) for r in rows)
            return jsonify({"paused": count, "saved_micros": total_micros})

        paused = 0
        saved_micros = 0
        executor = None
        try:
            from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor
            executor = GoogleAdsAutoExecutor(account_id=aid)
        except Exception:
            pass

        for row in rows:
            kw = AdsKeyword.query.get(row["kw_id"])
            if not kw:
                continue
            if executor:
                try:
                    executor.execute_pause_keyword(kw.id)
                except Exception:
                    pass
            kw.status = "paused"
            paused += 1
            saved_micros += int(row["total_cost_micros"])

        db.session.commit()
        return jsonify({"paused": paused, "saved_micros": saved_micros})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("bulk_pause_wasted error")
        return jsonify({"error": str(e)}), 500


@gads_bp.post("/bulk-tighten-broad")
@login_required
def bulk_tighten_broad():
    """
    Change all open broad_match optimizer recommendations to phrase match.
    Returns {"changed": N}
    """
    if not is_paid_account():
        return jsonify({"error": "Paid plan required"}), 403

    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    preview = request.args.get("preview") == "1"

    try:
        import json as _json
        recs = OptimizerRecommendation.query.filter_by(
            account_id=aid, status="open", category="broad_match"
        ).all()

        if preview:
            return jsonify({"changed": len(recs)})

        changed = 0
        executor = None
        try:
            from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor
            executor = GoogleAdsAutoExecutor(account_id=aid)
        except Exception:
            pass

        for rec in recs:
            try:
                suggested = _json.loads(rec.suggested_action_json) if isinstance(rec.suggested_action_json, str) else (rec.suggested_action_json or {})
                kw_id = suggested.get("keyword_id")
                if not kw_id:
                    continue
                kw = AdsKeyword.query.get(kw_id)
                if not kw:
                    continue
                if executor:
                    try:
                        executor.execute_change_match_type(int(kw_id), to="phrase")
                    except Exception:
                        pass
                kw.match_type = "phrase"
                rec.status = "applied"
                changed += 1
            except Exception:
                continue

        db.session.commit()
        return jsonify({"changed": changed})
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("bulk_tighten_broad error")
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
        from app.services.google_ads_sync import sync_structure, sync_account
        result["structure"] = sync_structure(aid)
    except Exception as exc:
        current_app.logger.exception("Google Ads structure sync failed for account %s", aid)
        result["errors"].append(f"Structure: {exc}")

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

    # Record sync timestamp so every tab can show data freshness
    try:
        from app.google.autonomous_routes import _save_setting
        from datetime import datetime as _dt
        _save_setting(aid, "gads_last_synced_at", _dt.utcnow().isoformat())
    except Exception:
        current_app.logger.warning("Could not record gads_last_synced_at for account %s", aid)

    status = 200 if not result["errors"] else 207
    return jsonify(result), status


# ---------------------------
# Search Terms tab
# ---------------------------

# ---- Generic intent signals (apply to every vertical) ----
#
# Classification order:
#   1. Generic service-intent  → relevant (hire-someone language)
#   2. Per-vertical service signal → relevant (vertical-specific verbs)
#   3. Generic product/DIY intent → irrelevant
#   4. Per-vertical buying pattern → irrelevant (catches vertical-specific
#      product nouns, brand names, dimensions, materials)
#   5. Default → relevant

_GENERIC_SERVICE_INTENT = [
    # "near me" alone is service intent; "for sale near me" handled by product layer
    r"\bnear me\b",
    r"\bin my area\b", r"\bin my city\b", r"\bin my town\b",
    r"\bcompan(?:y|ies)\b",
    r"\bcontractor[s]?\b",
    r"\bprofessional[s]?\b", r"\bpro[s]?\b(?!\w)",
    r"\bhire\b", r"\bhiring\b",
    r"\bemergency\b", r"\bsame.?day\b", r"\b24.?hour\b", r"\b24/7\b",
    # "my <noun>" implies they own one — "clean my pool", "fix my roof"
    r"\b(?:clean|fix|repair|service|treat|inspect|tune.?up)\s+(?:my|our)\b",
    # frequency words imply recurring service
    r"\bweekly\b", r"\bmonthly\b", r"\bbi.?weekly\b", r"\brecurring\b",
    r"\bquote\s+for\b", r"\bestimate\s+for\b",
    r"\bbook(?:ing)?\b", r"\bappointment[s]?\b", r"\bscheduling\b",
]

_GENERIC_PRODUCT_INTENT = [
    r"\bfor sale\b",
    r"\bon sale\b",
    r"\bamazon\b", r"\bhome depot\b", r"\blowes?\b", r"\bcostco\b", r"\bwalmart\b",
    r"\bebay\b", r"\bcraigslist\b", r"\bwayfair\b",
    r"\bdiy\b", r"\bdo it yourself\b",
    r"\bhow to\b",
    r"\bbest\b.{0,20}\b(?:brand|product|model|\d{4})\b",
    r"\b(?:vs|versus)\b",
    r"\breview[s]?\b",
    r"\b(?:model|sku|part)\s*#?\s*\w*\d", # part numbers / model #s
    r"\bkit[s]?\b",
    r"\bbuy\s+\w+",     # "buy chlorine", "buy pump", etc.
    r"\bpurchase\b",
    r"\border\s+online\b",
    r"\bshipping\b", r"\bdelivery\b",
    r"\bwholesale\b",
    r"\bused\b\s+\w+\s+(?:for sale|near me)?",  # "used pump for sale"
    r"\b\d+[x×]\d+\b",                       # dimensions like 12x24 (product spec)
    r"\b\d+\s*(?:foot|ft)\s+(?:wide|long|tall|deep)\b",
    r"\bbtu\b", r"\bseer\b",                 # spec numbers → shopping
]

# ---- Per-vertical layers (tiebreakers) ----

_SERVICE_SIGNALS = {
    "pool_cleaning": [
        r"\bcleaning\b", r"\bcleans\b",
        r"\bmaintenan", r"\bmaintain",
        r"\bservic",
        r"\brepair", r"\btreatment\b", r"\btreating\b",
        r"\bcare\b",
    ],
    "roofing": [
        r"\brepair\b", r"\breplace\b", r"\bleak[s]?\b",
        r"\binspect", r"\bservic", r"\bmaintenan",
        r"\bre.?roof", r"\breplacement\b",
    ],
    "hvac_ac": [
        r"\brepair\b", r"\bservic", r"\bmaintenan", r"\btune.?up\b",
        r"\brecharge\b", r"\brefrigerant\b", r"\bleak[s]?\b",
    ],
    "plumbing": [
        r"\brepair\b", r"\bservic", r"\bleak[s]?\b",
        r"\bclog(?:ged)?\b", r"\bbackup\b", r"\bunclog\b",
    ],
    "generic": [],
}

_POOL_PRODUCT_NOUNS = (
    r"chlorine|chemicals?|algaecide|vacuum|cleaner[s]?|robot|"
    r"pump[s]?|filter[s]?|brush(?:es)?|shock|cover[s]?|heater[s]?|"
    r"liner[s]?|skimmer[s]?|salt|tablets?|ph\b|alkalinity"
)

_BUYING_PATTERNS = {
    "pool_cleaning": [
        # pool/product + price/cost in either direction
        r"\bpool[s]?\b.{0,30}\b(cost[s]?|price[sd]?)\b",
        r"\b(cost[s]?|price[sd]?)\b.{0,30}\bpool[s]?\b",
        rf"\b({_POOL_PRODUCT_NOUNS})\b.{{0,30}}\b(cost[s]?|price[sd]?)\b",
        rf"\b(cost[s]?|price[sd]?)\b.{{0,30}}\b({_POOL_PRODUCT_NOUNS})\b",
        # vertical-specific product/build language
        r"\bfiberglass\b", r"\bviny[l]?\b", r"\bconcrete pool\b",
        r"\bbuild\b", r"\binstall(?:ation)?\b",
        r"\binground pool\b", r"\babove.?ground pool\b",
        r"\bcheap pool\b", r"\baffordable pool\b",
    ],
    "roofing": [
        r"\broof\s+(cost[s]?|price[sd]?)\b",
        r"\bmaterial[s]?\b", r"\bshingle[s]?\b", r"\btile[s]?\b",
        r"\bmetal roof\b", r"\basphalt\b",
        r"\bper square\b", r"\bsquare foot\b",
        r"\binstall(?:ation)?\b",
    ],
    "hvac_ac": [
        r"\bac\s+(cost[s]?|price[sd]?|unit[s]?)\b",
        r"\bhvac\s+(cost[s]?|price[sd]?|unit[s]?)\b",
        r"\btrane\b", r"\bcarrier\b", r"\blennox\b", r"\bgoodman\b", r"\brheem\b",
        r"\binstall(?:ation)?\b",
    ],
    "plumbing": [
        r"\bplumb(?:ing)?\s+(cost[s]?|price[sd]?)\b",
        r"\bparts?\b", r"\bfixture[s]?\b",
        r"\bfaucet[s]?\b", r"\btoilet[s]?\b", r"\bsink[s]?\b",
        r"\binstall(?:ation)?\b",
    ],
    "generic": [
        r"\bcheap\b", r"\baffordable\b",
        r"\bcost[s]?\b", r"\bprice[sd]?\b",
    ],
}


_IRRELEVANT_REASONS = {
    "diy": "People searching this want to do it themselves, not hire a professional",
    "product": "People searching this want to buy a product, not hire a service",
    "for_sale": "People searching this want to buy a product, not hire a service",
    "retailer": "This search leads to a retail store, not a service provider",
    "informational": "This is a research query, not a ready-to-buy search",
    "price_comparison": "This searcher is comparison-shopping, not ready to call",
    "buying_pattern": "This search is unlikely to convert to a paying customer",
}


def _classify_term_with_reason(term: str, service_type: str) -> tuple:
    """
    Returns (classification, reason) where classification is 'relevant' or
    'irrelevant' and reason is a plain-English string for irrelevant terms
    (None for relevant terms).
    """
    import re
    t = (term or "").lower()

    # 1. Generic service-intent (hire-me language)
    if any(re.search(p, t) for p in _GENERIC_SERVICE_INTENT):
        if not re.search(r"\bfor sale\b", t):
            return "relevant", None

    # 2. Generic product/DIY intent — unambiguous shopping language
    if any(re.search(p, t) for p in _GENERIC_PRODUCT_INTENT):
        if re.search(r"\bdiy\b|\bdo it yourself\b|\bhow to\b", t):
            reason = _IRRELEVANT_REASONS["diy"]
        elif re.search(r"\bfor sale\b|\bon sale\b", t):
            reason = _IRRELEVANT_REASONS["for_sale"]
        elif re.search(r"\bamazon\b|\bhome depot\b|\blowes?\b|\bcostco\b|\bwalmart\b|\bebay\b|\bcraigslist\b|\bwayfair\b", t):
            reason = _IRRELEVANT_REASONS["retailer"]
        elif re.search(r"\breview[s]?\b|\bvs\b|\bversus\b|\bcompare\b|\bbest\b", t):
            reason = _IRRELEVANT_REASONS["informational"]
        elif re.search(r"\bcost[s]?\b|\bprice[sd]?\b|\bcheap\b|\baffordable\b", t):
            reason = _IRRELEVANT_REASONS["price_comparison"]
        else:
            reason = _IRRELEVANT_REASONS["product"]
        return "irrelevant", reason

    # 3. Vertical-specific service verbs
    signals = _SERVICE_SIGNALS.get(service_type, [])
    if signals and any(re.search(p, t) for p in signals):
        return "relevant", None

    # 4. Vertical-specific buying patterns (product nouns + price, brand names, etc.)
    patterns = _BUYING_PATTERNS.get(service_type, _BUYING_PATTERNS["generic"])
    if any(re.search(p, t) for p in patterns):
        if re.search(r"\bcost[s]?\b|\bprice[sd]?\b|\bcheap\b|\baffordable\b", t):
            reason = _IRRELEVANT_REASONS["price_comparison"]
        else:
            reason = _IRRELEVANT_REASONS["buying_pattern"]
        return "irrelevant", reason

    return "relevant", None


def _classify_term(term: str, service_type: str) -> str:
    return _classify_term_with_reason(term, service_type)[0]


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

    service_type = "generic"
    try:
        from app.google.forecasting_routes import _infer_service_type
        service_type = _infer_service_type(aid)
    except Exception:
        pass

    for t in terms_data:
        t["relevance"], t["irrelevant_reason"] = _classify_term_with_reason(t["search_term"], service_type)
        conv = t.get("conversions")
        cost = t.get("cost_micros") or 0
        t["cpl"] = round(cost / 1_000_000 / conv, 2) if conv and conv > 0 else None

    wasted_spend_dollars = sum(
        (t["cost_micros"] or 0) / 1_000_000
        for t in terms_data if t["relevance"] == "irrelevant"
    )
    wasted_term_count = sum(1 for t in terms_data if t["relevance"] == "irrelevant")

    campaigns_list = [
        {"id": c.id, "name": c.name}
        for c in AdsCampaign.query.filter_by(account_id=aid).order_by(AdsCampaign.name).all()
    ]

    return render_template(
        "google/ads/search_terms.html",
        terms_data=terms_data,
        campaigns_list=campaigns_list,
        wasted_spend_dollars=wasted_spend_dollars,
        wasted_term_count=wasted_term_count,
        service_type=service_type,
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


@gads_bp.post("/block-irrelevant-search-terms")
@login_required
def block_irrelevant_search_terms():
    """
    Classify all unblocked search terms for this account and add the irrelevant
    ones as campaign-level EXACT negative keywords. Saves one AIAction row per
    blocked term and returns the count blocked.
    """
    if not is_paid_account():
        return jsonify({"error": "Paid plan required"}), 403

    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    from app.models_ads import SearchTerm

    service_type = "generic"
    try:
        from app.google.forecasting_routes import _infer_service_type
        service_type = _infer_service_type(aid)
    except Exception:
        pass

    try:
        rows = db.session.execute(text("""
            SELECT st.id, st.search_term, st.campaign_id
            FROM search_terms st
            LEFT JOIN ads_campaigns ac ON ac.id = st.campaign_id
            WHERE (ac.account_id = :aid OR st.campaign_id IS NULL)
              AND st.date >= (CURRENT_DATE - INTERVAL 30 DAY)
              AND st.added_as_negative = 0
        """), {"aid": aid}).mappings().all()
    except Exception as exc:
        current_app.logger.exception("block_irrelevant_search_terms: query failed")
        return jsonify({"error": str(exc)}), 500

    blocked = 0
    try:
        from datetime import datetime as _dt
        for row in rows:
            classification, _ = _classify_term_with_reason(row["search_term"], service_type)
            if classification != "irrelevant":
                continue

            st = SearchTerm.query.get(row["id"])
            if not st:
                continue

            neg = NegativeKeyword(
                scope="campaign",
                campaign_id=st.campaign_id,
                text=st.search_term,
                match_type="EXACT",
            )
            db.session.add(neg)
            st.added_as_negative = True

            action = AIAction(
                account_id=aid,
                action_type="search_term_blocked",
                title=f"Blocked irrelevant search term: {st.search_term}",
                description=f"Added '{st.search_term}' as campaign-level EXACT negative keyword",
                campaign_id=str(st.campaign_id) if st.campaign_id else None,
                after_value={"search_term": st.search_term, "match_type": "EXACT", "scope": "campaign"},
                status="executed",
                executed_at=_dt.utcnow(),
                executed_by="bulk_block",
                can_undo=True,
            )
            db.session.add(action)
            blocked += 1

        db.session.commit()
        return jsonify({"ok": True, "blocked": blocked})
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("block_irrelevant_search_terms error")
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


@gads_bp.post("/actions/<int:action_id>/undo")
@login_required
def action_undo(action_id: int):
    """
    Reverse an AI action in Google Ads and mark it as undone.
    Supports: keyword_paused, bid_adjusted, negative_keyword_added.
    """
    from app.models_ai_actions import AIAction
    from app.auth.utils import current_user_id

    aid = current_account_id()
    if not aid:
        return jsonify({"error": "Not authenticated"}), 401

    action = AIAction.query.filter_by(id=action_id, account_id=aid).first()
    if not action:
        return jsonify({"error": "Action not found"}), 404

    if not action.is_undoable:
        if action.status == "undone":
            return jsonify({"error": "Action already undone"}), 409
        if not action.can_undo:
            return jsonify({"error": "This action cannot be undone"}), 422
        return jsonify({"error": f"Action cannot be undone (status: {action.status})"}), 422

    try:
        from app.services.google_ads_auto_executor import GoogleAdsAutoExecutor
        executor = GoogleAdsAutoExecutor(account_id=aid)
        uid = current_user_id() if callable(current_user_id) else None
        success = executor.undo_action(action_id, user_id=uid)
        if not success:
            return jsonify({"error": "Undo failed — check server logs"}), 500
        return jsonify({"ok": True, "status": "undone"})
    except Exception as exc:
        current_app.logger.exception("action_undo error for action %s", action_id)
        db.session.rollback()
        return jsonify({"error": str(exc)}), 500


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


# ---------------------------------------------------------------------------
# Goals onboarding
# ---------------------------------------------------------------------------
@gads_bp.get("/goals")
@login_required
def goals_page():
    """Render the goal-setting wizard."""
    aid = current_account_id()
    goal = None
    try:
        goal = AdsAccountGoal.query.filter_by(account_id=aid).first()
    except Exception:
        pass
    return render_template("google/ads/goals.html", goal=goal)


@gads_bp.post("/goals")
@login_required
def goals_save():
    """Save or update account goals."""
    aid = current_account_id()
    if not aid:
        flash("Not authenticated.", "error")
        return redirect(url_for("gads_bp.goals_page"))

    try:
        target_leads = request.form.get("target_monthly_leads")
        target_cpa_raw = request.form.get("target_cpa")
        clv_raw = request.form.get("customer_lifetime_value")
        budget_raw = request.form.get("monthly_budget")
        business_type = request.form.get("business_type", "").strip() or None

        target_cpa_cents = int(float(target_cpa_raw) * 100) if target_cpa_raw else None
        clv_cents = int(float(clv_raw) * 100) if clv_raw else None
        budget_cents = int(float(budget_raw) * 100) if budget_raw else None

        goal = AdsAccountGoal.query.filter_by(account_id=aid).first()
        if goal is None:
            goal = AdsAccountGoal(account_id=aid)
            db.session.add(goal)

        if target_leads:
            goal.target_monthly_leads = int(target_leads)
        goal.target_cpa_cents = target_cpa_cents
        goal.customer_lifetime_value_cents = clv_cents
        goal.monthly_budget_cents = budget_cents
        goal.business_type = business_type
        goal.onboarding_completed = True

        db.session.commit()
        flash("Goals saved! We'll tune your recommendations to hit them.", "success")
    except Exception:
        current_app.logger.exception("goals_save error")
        db.session.rollback()
        flash("Something went wrong saving your goals. Please try again.", "error")

    return redirect(url_for("gads_bp.optimize", tab="cockpit"))


@gads_bp.get("/goals.json")
@login_required
def goals_json():
    """Return current goals as JSON."""
    aid = current_account_id()
    try:
        goal = AdsAccountGoal.query.filter_by(account_id=aid).first()
        if goal is None:
            return jsonify({})
        return jsonify({
            "target_monthly_leads": goal.target_monthly_leads,
            "target_cpa_cents": goal.target_cpa_cents,
            "target_cpa_dollars": round(goal.target_cpa_cents / 100, 2) if goal.target_cpa_cents else None,
            "customer_lifetime_value_cents": goal.customer_lifetime_value_cents,
            "monthly_budget_cents": goal.monthly_budget_cents,
            "business_type": goal.business_type,
            "onboarding_completed": goal.onboarding_completed,
        })
    except Exception:
        current_app.logger.exception("goals_json error")
        return jsonify({"error": "Failed to load goals"}), 500
