# app/campaigns/__init__.py
from __future__ import annotations
from flask import Blueprint, render_template, request, flash, redirect, url_for
from app.auth.utils import login_required, paid_required, is_paid_account

campaigns_bp = Blueprint("campaigns_bp", __name__, url_prefix="/account/campaigns")

# ---------- Non-AI: catalog page ----------
@campaigns_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    """
    Seasonal campaign catalog (not AI-gated).
    Users can browse and add a campaign to their repository.
    """
    catalog = [
        {"slug": "fall-furnace-tuneup", "title": "Fall Furnace Tune-Up", "desc": "Pre-winter HVAC tune-ups with limited-time pricing."},
        {"slug": "pre-holiday-drain", "title": "Pre-Holiday Drain Clear", "desc": "Prevent clogs before company arrives."},
        {"slug": "summer-water-heater", "title": "Summer Water Heater Check", "desc": "Flush & inspect special."},
    ]

    if request.method == "POST":
        # Non-AI add-to-repo action
        chosen = request.form.get("slug")
        if not chosen:
            flash("Choose a campaign.", "error")
        else:
            # TODO: persist selection to DB
            flash(f"Campaign '{chosen}' added to your repository (placeholder).", "success")
        return redirect(url_for("campaigns_bp.index"))

    # Pass whether AI is enabled for UI (disable AI buttons client-side)
    return render_template("campaigns/index.html", catalog=catalog, ai_enabled=is_paid_account())

# ---------- AI: suggestions/variant generator (PAID ONLY) ----------
@campaigns_bp.route("/ai/suggest", methods=["POST"])
@login_required
@paid_required
def ai_suggest():
    """
    AI action that generates copy/variants for a selected campaign.
    This route is gated by @paid_required, so only paid users can reach it.
    """
    slug = request.form.get("slug", "").strip()
    prompt_extra = request.form.get("notes", "").strip()

    if not slug:
        flash("Choose a campaign to generate ideas.", "error")
        return redirect(url_for("campaigns_bp.index"))

    # --- Call your AI here (stubbed response for now) ---
    # ideas = your_ai_call(slug=slug, notes=prompt_extra)
    ideas = [
        f"[AI] Hook for {slug}: “Keep winter comfy—book your tune-up this week.”",
        f"[AI] Offer line for {slug}: “$89 furnace tune-up—limited slots.”",
        f"[AI] CTA for {slug}: “Schedule in 60 seconds.”",
    ]

    # Reuse the index template to show results (or render a dedicated template)
    catalog = []  # not needed if you show a result section; omit if you prefer
    return render_template("campaigns/index.html", catalog=catalog, ai_enabled=True, ai_ideas=ideas, chosen_slug=slug)
