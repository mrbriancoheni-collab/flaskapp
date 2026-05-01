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


@seo_bp.route("/gaps", methods=["GET"], endpoint="gaps")
@login_required
def gaps():
    """Keyword gap & content opportunity dashboard."""
    aid = current_account_id()
    result = None
    gsc_connected = False
    site_url = None
    error = None

    try:
        from app.google import _is_connected, _get_gsc_selected_site
        import os
        gsc_connected = _is_connected(aid, "gsc")
        site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE")
    except Exception as exc:
        logger.exception("GSC status check failed")
        error = str(exc)

    if gsc_connected and site_url:
        try:
            from app.seo.keyword_gaps import run_keyword_gap_analysis
            result = run_keyword_gap_analysis(aid, site_url)
            if result.get("error"):
                error = result["error"]
                result = None
        except Exception as exc:
            logger.exception("Keyword gap analysis failed")
            error = f"Analysis failed: {exc}"

    return render_template(
        "seo/gaps.html",
        result=result,
        gsc_connected=gsc_connected,
        site_url=site_url,
        error=error,
    )


@seo_bp.route("/gaps/queue", methods=["POST"], endpoint="gaps_queue")
@login_required
def gaps_queue():
    """
    Queue a WPJob (ai_generate or refresh) from a keyword gap opportunity.
    Redirects back to the gaps page with a flash message.
    """
    action   = (request.form.get("action") or "new_post").strip()
    keyword  = (request.form.get("keyword") or "").strip()
    post_url = (request.form.get("post_url") or "").strip()

    if not keyword:
        flash("Keyword is required.", "error")
        return redirect(url_for("seo_bp.gaps"))

    try:
        from app.models_wp import WPSite, WPJob
        from app import db
        from sqlalchemy import text

        # Find the connected WP site for this account
        aid = current_account_id()
        site = None
        try:
            row = db.session.execute(
                text("SELECT id FROM wp_sites WHERE account_id = :aid LIMIT 1"),
                {"aid": aid},
            ).fetchone()
            if row:
                site = WPSite.query.get(row[0])
        except Exception:
            site = WPSite.query.first()

        if not site:
            flash("Connect a WordPress site first to queue content.", "error")
            return redirect(url_for("seo_bp.gaps"))

        if action == "refresh" and post_url:
            # Queue a refresh job pointing at the specific URL
            payload = {
                "source_url":      post_url,
                "primary_keyword": keyword,
                "action":          "refresh",
            }
            job = WPJob(site_id=site.id, kind="ai_generate", payload=payload)
        else:
            # Queue a new AI post for the keyword
            payload = {
                "primary_keyword": keyword,
                "prompt": (
                    f"Write a comprehensive, helpful blog post targeting the keyword "
                    f"'{keyword}'. Include an FAQ section and step-by-step guidance where "
                    f"relevant. Optimise for featured snippets."
                ),
                "word_count": "1000",
                "topics": [keyword],
            }
            job = WPJob(site_id=site.id, kind="ai_generate", payload=payload)

        db.session.add(job)
        db.session.commit()

        action_label = "refresh" if action == "refresh" else "new post"
        flash(f"Queued {action_label} for '{keyword}' (Job #{job.id}).", "success")

    except Exception as exc:
        logger.exception("Gap queue job creation failed")
        flash(f"Could not queue job: {exc}", "error")

    return redirect(url_for("seo_bp.gaps"))


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
