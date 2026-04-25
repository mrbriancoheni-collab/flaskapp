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
)
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
    # Check if user has paid plan
    if not is_paid_account():
        flash("Google Ads Optimizer is available on paid plans. Upgrade to access optimization tools.", "warning")
        return redirect(url_for("account_bp.pricing"))

    tab = request.args.get("tab", "campaigns")
    aid = current_account_id()

    connected = False
    try:
        from app.google import _is_connected
        connected = _is_connected(aid, "ads")
    except Exception:
        pass

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
                           COALESCE(SUM(gs.clicks),0) AS clicks_30d
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

    return render_template(
        "google/ads/optimize.html",
        tab=tab,
        connected=connected,
        keywords_data=keywords_data,
        negatives_data=negatives_data,
        campaigns_list=campaigns_list,
        adgroups_list=adgroups_list,
        campaigns_tab_data=campaigns_tab_data,
        adgroups_tab_data=adgroups_tab_data,
        ads_tab_data=ads_tab_data,
    )


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
    Stores change-sets to apply (to be executed by a worker or immediate mutator).
    Supports both single and bulk operations:
    - Single: {"recommendation_id": <id>, "changes": [...]}
    - Bulk: {"recommendation_ids": [<id1>, <id2>, ...], "bulk": true}
    """
    try:
        # Check if user has paid plan
        if not is_paid_account():
            return jsonify({"error": "Paid plan required"}), 403

        payload = request.get_json(force=True)

        # Handle bulk operations
        if payload.get("bulk") and "recommendation_ids" in payload:
            rec_ids = payload.get("recommendation_ids", [])
            action_ids = []

            for rec_id in rec_ids:
                try:
                    action = OptimizerAction(
                        recommendation_id=int(rec_id),
                        change_set_json=str({"recommendation_id": rec_id, "bulk": True}),
                        status="pending",
                    )
                    db.session.add(action)
                    db.session.flush()  # Get ID before commit
                    action_ids.append(action.id)
                except Exception as e:
                    current_app.logger.error(f"Failed to queue recommendation {rec_id}: {e}")
                    continue

            db.session.commit()
            return jsonify({"status": "queued", "action_ids": action_ids, "count": len(action_ids)})

        # Handle single operation (backward compatibility)
        rec_id = int(payload.get("recommendation_id", 0))
        action = OptimizerAction(
            recommendation_id=rec_id,
            change_set_json=str(payload),
            status="pending",
        )
        db.session.add(action)
        db.session.commit()
        return jsonify({"status": "queued", "action_id": action.id})

    except Exception as e:
        current_app.logger.exception("Error in optimizer_apply")
        db.session.rollback()
        return jsonify({"error": f"Failed to apply optimization: {str(e)}"}), 500


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
