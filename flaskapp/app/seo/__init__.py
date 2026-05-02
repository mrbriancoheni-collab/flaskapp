# app/seo/__init__.py
from __future__ import annotations

import logging
from datetime import datetime
from flask import Blueprint, render_template, request, flash, url_for, redirect, current_app, jsonify
from app.auth.utils import login_required, is_paid_account, current_account_id

logger = logging.getLogger(__name__)

seo_bp = Blueprint("seo_bp", __name__, template_folder="../../templates")


@seo_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    aid = current_account_id()
    gsc_connected = False
    site_url = None
    summary = {}
    top_queries = []
    latest_snapshot = None
    unread_alerts = 0
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
            data = _fetch_gsc_report(site_url, start.isoformat(), end.isoformat()) or {}
            summary = data.get("summary", {})
            top_queries = (data.get("top_queries") or [])[:5]
    except Exception as e:
        error = str(e)

    try:
        from app.seo.monitor import get_recent_snapshots, get_unread_alerts
        if site_url:
            snaps = get_recent_snapshots(site_url, limit=1)
            latest_snapshot = snaps[0] if snaps else None
        alerts = get_unread_alerts(account_id=aid, limit=50)
        unread_alerts = len([a for a in alerts if not a.is_read])
    except Exception:
        pass

    return render_template(
        "seo/index.html",
        gsc_connected=gsc_connected,
        site_url=site_url,
        summary=summary,
        top_queries=top_queries,
        latest_snapshot=latest_snapshot,
        unread_alerts=unread_alerts,
        error=error,
    )


@seo_bp.route("/rankings", methods=["GET"], endpoint="rankings")
@login_required
def rankings():
    """Pull top search queries with position history sparklines."""
    aid = current_account_id()
    rows = []
    gsc_connected = False
    site_url = None
    error = None
    history: dict = {}  # {query: [pos, pos, ...]} oldest→newest

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

            # Build position history from stored snapshots
            try:
                from app.seo.monitor import get_recent_snapshots
                snapshots = get_recent_snapshots(site_url, limit=14)
                snapshots_asc = list(reversed(snapshots))
                query_names = {r["query"] for r in rows}
                for snap in snapshots_asc:
                    gsc_snap = (snap.data or {}).get("gsc") or {}
                    for q in (gsc_snap.get("queries") or []):
                        qname = q.get("query", "")
                        if qname in query_names:
                            history.setdefault(qname, []).append(round(q.get("position", 0), 1))
            except Exception:
                pass

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
        history=history,
        error=error,
    )


@seo_bp.route("/monitor", methods=["GET"], endpoint="monitor")
@login_required
def monitor():
    """SEO health monitoring dashboard."""
    from app.auth.utils import current_account_id
    aid      = current_account_id()
    site_url = None
    snapshots = []
    alerts    = []
    unread_count = 0

    try:
        from app.google import _get_gsc_selected_site
        import os
        site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE")
    except Exception:
        pass

    # Also try WP site URL as fallback
    if not site_url:
        try:
            from app.models_wp import WPSite
            from sqlalchemy import text
            from app import db
            row = db.session.execute(
                text("SELECT base_url FROM wp_sites WHERE account_id=:aid LIMIT 1"),
                {"aid": aid},
            ).fetchone()
            if row:
                site_url = row[0]
        except Exception:
            pass

    if site_url:
        from app.seo.monitor import get_recent_snapshots, get_unread_alerts
        snapshots     = get_recent_snapshots(site_url, limit=14)
        alerts        = get_unread_alerts(account_id=aid, limit=30)
        unread_count  = len([a for a in alerts if not a.is_read])

    return render_template(
        "seo/monitor.html",
        site_url=site_url,
        snapshots=snapshots,
        alerts=alerts,
        unread_count=unread_count,
    )


@seo_bp.route("/monitor/run", methods=["POST"], endpoint="monitor_run")
@login_required
def monitor_run():
    """Manually trigger an immediate monitoring check."""
    from app.auth.utils import current_account_id
    aid      = current_account_id()
    site_url = request.form.get("site_url", "").strip()

    if not site_url:
        flash("No site URL to check.", "error")
        return redirect(url_for("seo_bp.monitor"))

    try:
        from app.seo.monitor import run_monitoring_check
        # Find site_id
        site_id = None
        try:
            from app.models_wp import WPSite
            s = WPSite.query.filter_by(account_id=aid).first()
            if s:
                site_id = s.id
        except Exception:
            pass

        result = run_monitoring_check(
            site_url=site_url, site_id=site_id,
            account_id=aid, force=True,
        )
        if result.get("ok"):
            n = result["alerts_created"]
            flash(
                f"Check complete — {n} new alert{'s' if n != 1 else ''} generated." if n
                else "Check complete — no new issues detected.",
                "success" if not n else "warning",
            )
        else:
            flash(result.get("error") or "Check failed.", "error")
    except Exception as exc:
        logger.exception("Manual monitor run failed")
        flash(f"Monitor run failed: {exc}", "error")

    return redirect(url_for("seo_bp.monitor"))


@seo_bp.route("/monitor/cron", methods=["GET"], endpoint="monitor_cron")
def monitor_cron():
    """
    Cron endpoint — call daily, e.g. 0 6 * * * curl /account/seo/monitor/cron?secret=X
    Requires the same CRON_SECRET used by the WP cron-runner.
    """
    from flask import current_app
    supplied = (request.args.get("secret") or request.args.get("key") or "").strip()
    expected = (current_app.config.get("CRON_SECRET") or "").strip()
    if not (supplied and expected and supplied == expected):
        return jsonify({"ok": False, "error": "forbidden"}), 403

    from app.seo.monitor import run_monitoring_check
    from app.models_wp import WPSite

    results = []
    try:
        sites = WPSite.query.all()
        for site in sites:
            r = run_monitoring_check(
                site_url   = site.base_url,
                site_id    = site.id,
                account_id = site.account_id,
            )
            results.append({"site": site.base_url, **r})
    except Exception as exc:
        logger.exception("SEO monitor cron failed")
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "ran_at": datetime.utcnow().isoformat() + "Z",
                    "results": results})


@seo_bp.route("/alerts/dismiss", methods=["POST"], endpoint="alerts_dismiss")
@login_required
def alerts_dismiss():
    """Mark one or all alerts as read."""
    from app.auth.utils import current_account_id
    from app import db
    from app.models_seo import SEOAlert

    aid        = current_account_id()
    alert_id   = request.form.get("alert_id")
    dismiss_all = request.form.get("dismiss_all")

    try:
        if dismiss_all:
            SEOAlert.query.filter_by(account_id=aid, is_read=False).update({"is_read": True})
        elif alert_id:
            a = SEOAlert.query.get(int(alert_id))
            if a and a.account_id == aid:
                a.is_read = True
        db.session.commit()
    except Exception as exc:
        logger.exception("Alert dismiss failed")
        flash(f"Could not dismiss: {exc}", "error")

    return redirect(url_for("seo_bp.monitor"))


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
