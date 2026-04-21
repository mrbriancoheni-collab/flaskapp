# app/campaigns/__init__.py
from __future__ import annotations

import logging
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import current_user
from app.auth.utils import login_required, paid_required, is_paid_account
from app import db

logger = logging.getLogger(__name__)

campaigns_catalog_bp = Blueprint(
    "campaigns_catalog_bp", __name__, url_prefix="/account/campaigns"
)

CATALOG = [
    {"slug": "fall-furnace-tuneup",    "title": "Fall Furnace Tune-Up",      "desc": "Pre-winter HVAC tune-ups with limited-time pricing.", "season": "Fall"},
    {"slug": "pre-holiday-drain",       "title": "Pre-Holiday Drain Clear",   "desc": "Prevent clogs before company arrives.", "season": "Fall"},
    {"slug": "summer-water-heater",     "title": "Summer Water Heater Check", "desc": "Flush & inspect special.", "season": "Summer"},
    {"slug": "spring-ac-tuneup",        "title": "Spring A/C Tune-Up",        "desc": "Get ahead of summer heat with a pre-season checkup.", "season": "Spring"},
    {"slug": "winter-pipe-protection",  "title": "Winter Pipe Protection",    "desc": "Insulation and inspection before the freeze.", "season": "Winter"},
    {"slug": "emergency-hvac",          "title": "24/7 Emergency HVAC",       "desc": "Year-round emergency repair campaign for urgent calls.", "season": "Year-round"},
]

CATALOG_BY_SLUG = {c["slug"]: c for c in CATALOG}


@campaigns_catalog_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    from app.models import CampaignSelection

    if request.method == "POST":
        slug = request.form.get("slug")
        campaign = CATALOG_BY_SLUG.get(slug)
        if not campaign:
            flash("Invalid campaign selection.", "error")
            return redirect(url_for("campaigns_catalog_bp.index"))

        # Persist to DB (upsert by account+slug)
        existing = CampaignSelection.query.filter_by(
            account_id=current_user.account_id,
            slug=slug
        ).first()
        if not existing:
            sel = CampaignSelection(
                account_id=current_user.account_id,
                user_id=current_user.id,
                slug=slug,
                title=campaign["title"],
                status="saved",
            )
            db.session.add(sel)
            db.session.commit()
            flash(f"'{campaign['title']}' added to your campaign repository.", "success")
        else:
            flash(f"'{campaign['title']}' is already in your repository.", "info")
        return redirect(url_for("campaigns_catalog_bp.index"))

    # Load saved selections for this account
    saved = CampaignSelection.query.filter_by(
        account_id=current_user.account_id
    ).order_by(CampaignSelection.created_at.desc()).all()
    saved_slugs = {s.slug for s in saved}

    return render_template(
        "campaigns/index.html",
        catalog=CATALOG,
        saved=saved,
        saved_slugs=saved_slugs,
        ai_enabled=is_paid_account(),
    )


@campaigns_catalog_bp.route("/ai/suggest", methods=["POST"])
@login_required
@paid_required
def ai_suggest():
    """Generate AI copy variants for a selected campaign (paid only)."""
    slug = request.form.get("slug", "").strip()
    notes = request.form.get("notes", "").strip()

    campaign = CATALOG_BY_SLUG.get(slug)
    if not campaign:
        flash("Invalid campaign.", "error")
        return redirect(url_for("campaigns_catalog_bp.index"))

    ideas = []
    try:
        from app.ai_clients import get_ai_client
        client = get_ai_client()
        prompt = (
            f"You are a Google Ads copywriter for local home-service businesses.\n"
            f"Generate 3 ad copy variations for a seasonal campaign: {campaign['title']}.\n"
            f"Description: {campaign['desc']}\n"
            f"Extra context from the user: {notes or 'none'}\n\n"
            "For each variation provide:\n"
            "- hook: a punchy opening headline (max 30 chars)\n"
            "- offer: the offer line (max 30 chars)\n"
            "- cta: call-to-action (max 15 chars)\n\n"
            "Respond as a JSON array with keys: hook, offer, cta."
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        import json, re
        raw = response.content[0].text
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            variants = json.loads(match.group())
            for v in variants:
                ideas.append(
                    f"Hook: {v.get('hook','')} | Offer: {v.get('offer','')} | CTA: {v.get('cta','')}"
                )
        else:
            ideas = [raw]

        # Cache ideas on the selection record if it exists
        from app.models import CampaignSelection
        sel = CampaignSelection.query.filter_by(
            account_id=current_user.account_id, slug=slug
        ).first()
        if sel:
            sel.ai_ideas = ideas
            db.session.commit()

    except Exception as e:
        logger.exception("AI suggest failed")
        flash(f"AI generation failed: {e}", "error")

    saved = db.session.query(__import__('app.models', fromlist=['CampaignSelection']).CampaignSelection).filter_by(
        account_id=current_user.account_id
    ).order_by(__import__('app.models', fromlist=['CampaignSelection']).CampaignSelection.created_at.desc()).all()
    saved_slugs = {s.slug for s in saved}

    return render_template(
        "campaigns/index.html",
        catalog=CATALOG,
        saved=saved,
        saved_slugs=saved_slugs,
        ai_enabled=True,
        ai_ideas=ideas,
        chosen_slug=slug,
    )


@campaigns_catalog_bp.route("/<slug>/remove", methods=["POST"])
@login_required
def remove(slug):
    """Remove a campaign from the user's saved repository."""
    from app.models import CampaignSelection
    sel = CampaignSelection.query.filter_by(
        account_id=current_user.account_id, slug=slug
    ).first()
    if sel:
        db.session.delete(sel)
        db.session.commit()
        flash("Campaign removed from your repository.", "info")
    return redirect(url_for("campaigns_catalog_bp.index"))
