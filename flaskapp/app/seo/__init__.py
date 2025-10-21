# app/seo/__init__.py
from __future__ import annotations

import os
from flask import Blueprint, render_template, request, flash, url_for, redirect, current_app
from app.auth.utils import login_required, is_paid_account

seo_bp = Blueprint("seo_bp", __name__, template_folder="../../templates")

@seo_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    return render_template("seo/index.html")

@seo_bp.route("/rankings", methods=["GET"], endpoint="rankings")
@login_required
def rankings():
    # TODO: pull from GSC Search Analytics API; show sample table for now
    rows = [
        {"query": "water heater repair", "clicks": 42, "impr": 980, "ctr": "4.3%", "pos": 7.2},
        {"query": "plumber daly city", "clicks": 21, "impr": 300, "ctr": "7.0%", "pos": 4.9},
    ]
    return render_template("seo/rankings.html", rows=rows)

@seo_bp.route("/optimize", methods=["GET", "POST"], endpoint="optimize")
@login_required
def optimize():
    """
    SEO optimization ideas via AI (paid users only).
    GET shows the form; POST triggers AI if account is paid.
    """
    suggestions = None
    if request.method == "POST":
        if not is_paid_account():
            flash("AI SEO features are available on paid plans. Upgrade to continue.", "warning")
            return redirect(url_for("main_bp.pricing"))

        if not (os.getenv("OPENAI_API_KEY") or current_app.config.get("OPENAI_API_KEY")):
            flash("AI is not configured (missing OPENAI_API_KEY).", "error")
            return redirect(url_for("seo_bp.optimize"))

        # TODO: call OpenAI here, similar to other AI integrations
        suggestions = {
            "title": "Boost your HVAC rankings",
            "meta_desc": "Optimize for long-tail searches like 'emergency AC repair in Daly City'.",
            "content": "Consider writing a 500-word blog post targeting seasonal plumbing keywords."
        }
        flash("AI SEO suggestions generated.", "success")

    return render_template("seo/optimize.html", suggestions=suggestions)
