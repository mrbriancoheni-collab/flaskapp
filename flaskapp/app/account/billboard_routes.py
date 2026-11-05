"""
Billboard Ads platform routes.

GET  /account/billboard                        — dashboard
GET  /account/billboard/locations              — browse screens
GET  /account/billboard/campaigns/new          — campaign builder wizard
POST /account/billboard/campaigns/new          — create campaign (JSON)
GET  /account/billboard/campaigns/<id>         — campaign detail
POST /account/billboard/campaigns/<id>/status  — update status (JSON)
POST /account/billboard/creative/generate      — AI copy (JSON)
POST /account/billboard/estimate               — cost estimate (JSON)
"""
from __future__ import annotations

import logging

from flask import jsonify, render_template, request

from app import db
from app.account import account_bp
from app.auth.utils import current_account_id, login_required
from app.services import billboard_service

log = logging.getLogger(__name__)


@account_bp.route("/billboard", methods=["GET"], endpoint="billboard_dashboard")
@login_required
def billboard_dashboard():
    aid = current_account_id()
    campaigns = billboard_service.get_campaigns(aid) if aid else []
    total_spend = sum(float(c.get("total_budget") or 0) for c in campaigns)
    active_count = sum(1 for c in campaigns if c.get("status") == "active")
    return render_template(
        "account/billboard/dashboard.html",
        campaigns=campaigns,
        total_campaigns=len(campaigns),
        active_campaigns=active_count,
        total_spend=total_spend,
    )


@account_bp.route("/billboard/locations", methods=["GET"], endpoint="billboard_locations")
@login_required
def billboard_locations():
    city = request.args.get("city", "").strip()
    state = request.args.get("state", "").strip()
    screen_type = request.args.get("screen_type", "").strip()
    try:
        max_cpp = float(request.args.get("max_cpp", 0)) or None
    except (ValueError, TypeError):
        max_cpp = None

    locations = billboard_service.get_locations(
        city=city or None,
        state=state or None,
        screen_type=screen_type or None,
        max_cpp=max_cpp,
    )
    cities = billboard_service.get_cities()

    filters = {
        "city": city,
        "state": state,
        "screen_type": screen_type,
        "max_cpp": max_cpp,
    }
    return render_template(
        "account/billboard/locations.html",
        locations=locations,
        cities=cities,
        filters=filters,
    )


@account_bp.route("/billboard/campaigns/new", methods=["GET"], endpoint="billboard_new_campaign")
@login_required
def billboard_new_campaign():
    cities = billboard_service.get_cities()
    # Try to pre-fill trade from account settings
    trade = ""
    try:
        aid = current_account_id()
        if aid:
            row = db.session.execute(
                db.text("SELECT value FROM account_settings WHERE account_id = :aid AND `key` = 'trade' LIMIT 1"),
                {"aid": aid},
            ).fetchone()
            if row:
                trade = dict(row._mapping).get("value", "") if hasattr(row, "_mapping") else ""
    except Exception:
        pass
    return render_template("account/billboard/new_campaign.html", cities=cities, trade=trade)


@account_bp.route("/billboard/campaigns/new", methods=["POST"], endpoint="billboard_create_campaign")
@login_required
def billboard_create_campaign():
    try:
        aid = current_account_id()
        if not aid:
            return jsonify({"ok": False, "error": "Not authenticated"}), 401

        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "").strip()[:200]
        objective = str(data.get("objective") or "awareness").strip().lower()
        start_date = str(data.get("start_date") or "").strip()
        end_date = str(data.get("end_date") or "").strip()
        location_ids = [int(i) for i in (data.get("location_ids") or []) if str(i).strip().isdigit()]
        creative_headline = str(data.get("creative_headline") or "").strip()[:100]
        creative_subtext = str(data.get("creative_subtext") or "").strip()[:200]
        creative_cta = str(data.get("creative_cta") or "").strip()[:60]
        creative_type = str(data.get("creative_type") or "ai_generated").strip()

        if not name:
            return jsonify({"ok": False, "error": "Campaign name is required."}), 400
        if not location_ids:
            return jsonify({"ok": False, "error": "Select at least one screen."}), 400
        if not start_date or not end_date:
            return jsonify({"ok": False, "error": "Start and end dates are required."}), 400
        if objective not in ("awareness", "traffic", "leads"):
            objective = "awareness"

        from datetime import datetime
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            ed = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid date format. Use YYYY-MM-DD."}), 400
        if ed <= sd:
            return jsonify({"ok": False, "error": "End date must be after start date."}), 400

        campaign_id = billboard_service.create_campaign(
            account_id=aid,
            name=name,
            objective=objective,
            start_date=start_date,
            end_date=end_date,
            location_ids=location_ids,
            creative_headline=creative_headline,
            creative_subtext=creative_subtext,
            creative_cta=creative_cta,
            creative_type=creative_type,
        )
        return jsonify({"ok": True, "campaign_id": campaign_id})

    except Exception as e:
        log.exception("billboard_create_campaign error: %s", e)
        return jsonify({"ok": False, "error": "Failed to create campaign. Please try again."}), 500


@account_bp.route("/billboard/campaigns/<int:campaign_id>", methods=["GET"], endpoint="billboard_campaign_detail")
@login_required
def billboard_campaign_detail(campaign_id: int):
    aid = current_account_id()
    if not aid:
        return "Unauthorized", 401
    campaign = billboard_service.get_campaign(campaign_id, aid)
    if not campaign:
        return "Campaign not found", 404
    return render_template("account/billboard/campaign_detail.html", campaign=campaign)


@account_bp.route("/billboard/campaigns/<int:campaign_id>/status", methods=["POST"], endpoint="billboard_update_status")
@login_required
def billboard_update_status(campaign_id: int):
    try:
        aid = current_account_id()
        if not aid:
            return jsonify({"ok": False, "error": "Not authenticated"}), 401
        data = request.get_json(silent=True) or {}
        status = str(data.get("status") or "").strip().lower()
        if status not in ("active", "paused", "cancelled", "completed"):
            return jsonify({"ok": False, "error": "Invalid status"}), 400
        ok = billboard_service.update_campaign_status(campaign_id, aid, status)
        if not ok:
            return jsonify({"ok": False, "error": "Campaign not found"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        log.exception("billboard_update_status error: %s", e)
        return jsonify({"ok": False, "error": "Update failed"}), 500


@account_bp.route("/billboard/creative/generate", methods=["POST"], endpoint="billboard_generate_creative")
@login_required
def billboard_generate_creative():
    try:
        data = request.get_json(silent=True) or {}
        trade = str(data.get("trade") or "").strip()[:60]
        location = str(data.get("location") or "").strip()[:80]
        usp1 = str(data.get("usp1") or "").strip()[:100]
        usp2 = str(data.get("usp2") or "").strip()[:100]
        tone = str(data.get("tone") or "professional").strip().lower()
        if tone not in ("professional", "urgent", "friendly"):
            tone = "professional"
        if not trade:
            return jsonify({"ok": False, "error": "Trade is required"}), 400
        copy = billboard_service.generate_ai_copy(
            trade=trade,
            location=location,
            usp_list=[usp1, usp2],
            tone=tone,
        )
        return jsonify({"ok": True, "copy": copy})
    except Exception as e:
        log.exception("billboard_generate_creative error: %s", e)
        return jsonify({"ok": False, "error": "Generation failed. Please try again."}), 500


@account_bp.route("/billboard/estimate", methods=["POST"], endpoint="billboard_estimate")
@login_required
def billboard_estimate():
    try:
        data = request.get_json(silent=True) or {}
        raw_ids = data.get("location_ids") or []
        location_ids = [int(i) for i in raw_ids if str(i).strip().isdigit()]
        try:
            days = max(1, int(data.get("days") or 30))
        except (ValueError, TypeError):
            days = 30
        estimate = billboard_service.estimate_campaign_cost(location_ids, days)
        return jsonify({"ok": True, "estimate": estimate})
    except Exception as e:
        log.exception("billboard_estimate error: %s", e)
        return jsonify({"ok": False, "error": "Estimate failed"}), 500
