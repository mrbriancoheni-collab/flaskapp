# app/seo/__init__.py
from __future__ import annotations

import logging
from flask import Blueprint, render_template, request, flash, url_for, redirect, current_app, jsonify
from app.auth.utils import login_required, is_paid_account, current_account_id

logger = logging.getLogger(__name__)

seo_bp = Blueprint("seo_bp", __name__, template_folder="../../templates")


@seo_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    return render_template("seo/index.html")


@seo_bp.route("/rankings", methods=["GET"], endpoint="rankings")
@login_required
def rankings():
    """Pull top search queries directly from the GSC integration."""
    aid = current_account_id()
    rows = []
    gsc_connected = False
    site_url = None
    error = None

    try:
        from app.google import _fetch_gsc_report, _get_gsc_selected_site, _is_connected
        import os
        from datetime import date, timedelta

        gsc_connected = _is_connected(aid, "gsc")
        site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE")

        if gsc_connected and site_url:
            end = date.today()
            start = end - timedelta(days=28)
            data = _fetch_gsc_report(site_url, start.isoformat(), end.isoformat())
            if data:
                for q in (data.get("top_queries") or [])[:50]:
                    rows.append({
                        "query":  q.get("query", ""),
                        "clicks": q.get("clicks", 0),
                        "impr":   q.get("impressions", 0),
                        "ctr":    f"{q.get('ctr', 0) * 100:.1f}%",
                        "pos":    round(q.get("position", 0), 1),
                    })
        elif not gsc_connected:
            error = "Connect Google Search Console to see real rankings."
    except Exception as e:
        logger.exception("SEO rankings fetch failed")
        error = f"Could not load rankings: {e}"

    return render_template(
        "seo/rankings.html",
        rows=rows,
        gsc_connected=gsc_connected,
        site_url=site_url,
        error=error,
    )


@seo_bp.route("/optimize", methods=["GET", "POST"], endpoint="optimize")
@login_required
def optimize():
    """SEO optimization suggestions via AI (paid users only)."""
    suggestions = None
    if request.method != "POST":
        return render_template("seo/optimize.html", suggestions=suggestions)

    if not is_paid_account():
        flash("AI SEO features are available on paid plans. Upgrade to continue.", "warning")
        return redirect(url_for("main_bp.pricing"))

    aid = current_account_id()
    try:
        from app.google import _fetch_gsc_report, _get_gsc_selected_site, _is_connected
        import os
        from datetime import date, timedelta

        site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE")
        gsc_data = {}
        if _is_connected(aid, "gsc") and site_url:
            end = date.today()
            start = end - timedelta(days=28)
            gsc_data = _fetch_gsc_report(site_url, start.isoformat(), end.isoformat()) or {}

        # Build context for the AI
        top_queries = gsc_data.get("top_queries", [])[:10]
        top_pages   = gsc_data.get("top_pages", [])[:10]
        summary     = gsc_data.get("summary", {})

        context_lines = [
            f"Site: {site_url or 'unknown'}",
            f"Last 28d: {summary.get('clicks',0)} clicks, "
            f"{summary.get('impressions',0)} impressions, "
            f"avg position {summary.get('avg_position',0):.1f}",
        ]
        if top_queries:
            context_lines.append("Top queries: " + ", ".join(
                f"{q['query']} ({q.get('clicks',0)} clicks, pos {q.get('position',0):.1f})"
                for q in top_queries
            ))
        if top_pages:
            context_lines.append("Top pages: " + ", ".join(
                p.get("page", "") for p in top_pages
            ))

        prompt = (
            "You are an expert SEO consultant for local service businesses (HVAC, plumbing, electrical).\n"
            "Based on this Google Search Console data, give 5 specific, actionable SEO recommendations "
            "with estimated impact. Format as JSON with keys: title, description, action, impact, difficulty.\n\n"
            + "\n".join(context_lines)
        )

        from app.ai_clients import get_ai_client
        client = get_ai_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        import json, re
        raw = response.content[0].text
        # Extract JSON array from response
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            suggestions = json.loads(match.group())
        else:
            suggestions = [{"title": "AI Response", "description": raw,
                            "action": "", "impact": "", "difficulty": ""}]
        flash("SEO recommendations generated.", "success")

    except Exception as e:
        logger.exception("SEO AI optimize failed")
        flash(f"Could not generate suggestions: {e}", "error")

    return render_template("seo/optimize.html", suggestions=suggestions)
