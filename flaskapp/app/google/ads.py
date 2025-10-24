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
)

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
def optimize():
    """
    Renders the Google Ads Optimize UI (tabs driven by ?tab=).
    Template: templates/google/ads/optimize.html
    """
    tab = request.args.get("tab", "campaigns")
    return render_template("google/ads/optimize.html", tab=tab)


# ---------------------------
# JSON: Overview KPIs
# ---------------------------
@gads_bp.get("/overview")
def overview():
    """
    Account-level KPI snapshot from gads_stats_daily.
    Query params: ?days=30 (default 30)
    """
    days = int(request.args.get("days", 30))
    row = db.session.execute(
        text(
            """
            SELECT
              COALESCE(SUM(impressions),0) AS impressions,
              COALESCE(SUM(clicks),0) AS clicks,
              COALESCE(SUM(cost_micros),0) AS cost_micros,
              COALESCE(SUM(conversions),0) AS conversions,
              CASE WHEN COALESCE(SUM(clicks),0) > 0
                   THEN COALESCE(SUM(cost_micros),0)/1000000.0/COALESCE(SUM(clicks),0)
                   ELSE 0 END AS avg_cpc
            FROM gads_stats_daily
            WHERE date >= (CURRENT_DATE - INTERVAL :days DAY)
              AND entity_type = 'account'
            """
        ),
        {"days": days},
    ).mappings().first() or {}
    return jsonify(row)


# ---------------------------
# JSON: Optimizer
# ---------------------------
@gads_bp.get("/optimizer/data")
def optimizer_data():
    """
    Returns optimizer recommendations (ranked).
    """
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
def optimizer_apply():
    """
    Stores a change-set to apply (to be executed by a worker or immediate mutator).
    Expect: {"recommendation_id": <id>, "changes": [...]}
    """
    payload = request.get_json(force=True)
    rec_id = int(payload.get("recommendation_id", 0))
    action = OptimizerAction(
        recommendation_id=rec_id,
        change_set_json=str(payload),
        status="pending",
    )
    db.session.add(action)
    db.session.commit()
    return jsonify({"status": "queued", "action_id": action.id})


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
