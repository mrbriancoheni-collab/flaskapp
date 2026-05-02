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


@seo_bp.route("/snippets", methods=["GET"], endpoint="snippets")
@login_required
def snippets():
    """Featured Snippet Optimizer — find position 2-10 queries ripe for snippet capture."""
    aid = current_account_id()
    opportunities = []
    gsc_connected = False
    site_url = None
    error = None

    try:
        from app.google import _is_connected, _get_gsc_selected_site
        import os
        gsc_connected = _is_connected(aid, "gsc")
        site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE")
    except Exception as exc:
        error = str(exc)

    if gsc_connected and site_url:
        try:
            from app.seo.keyword_gaps import _gsc_fetch, _rows_to_dicts, _date_range
            end, start = _date_range(3, 28)
            rows = _gsc_fetch(aid, site_url, start, end,
                              ["query", "page"], row_limit=200)
            qp_data = _rows_to_dicts(rows, ["query", "page"])

            # Filter to position 2-10, meaningful impressions
            candidates = [
                r for r in qp_data
                if 1.5 < r.get("position", 99) <= 10
                and r.get("impressions", 0) >= 50
            ]
            candidates.sort(key=lambda x: x["impressions"], reverse=True)
            candidates = candidates[:30]

            for c in candidates:
                query = c.get("query", "")
                pos   = round(c.get("position", 0), 1)
                impr  = int(c.get("impressions", 0))
                clicks = int(c.get("clicks", 0))
                ctr   = round(c.get("ctr", 0) * 100, 1) if c.get("ctr") else 0

                q_lower = query.lower()
                if any(q_lower.startswith(w) for w in ("what is", "what are", "define", "meaning")):
                    snippet_type, tip = "definition", "Add a concise 40-50 word definition paragraph directly below the H2."
                elif any(q_lower.startswith(w) for w in ("how to", "how do", "steps to", "how can")):
                    snippet_type, tip = "steps", "Use a numbered <ol> list with imperative step headings (verb-first)."
                elif any(q_lower.startswith(w) for w in ("best", "top", "list of", "types of")):
                    snippet_type, tip = "list", "Add a <ul> or <ol> list near the top of the page with 5-8 concise items."
                elif any(w in q_lower for w in ("vs", "versus", "compare", "difference")):
                    snippet_type, tip = "table", "Add an HTML comparison table with a clear header row and 2-4 columns."
                elif any(w in q_lower for w in ("cost", "price", "how much")):
                    snippet_type, tip = "table", "Add a pricing table or cost breakdown near the top of the page."
                else:
                    snippet_type, tip = "paragraph", "Add a direct, concise answer (40-60 words) in the first paragraph after the H1."

                difficulty = "easy" if pos <= 3 else ("medium" if pos <= 6 else "hard")

                opportunities.append({
                    "query":        query,
                    "page":         c.get("page", ""),
                    "position":     pos,
                    "impressions":  impr,
                    "clicks":       clicks,
                    "ctr":          ctr,
                    "snippet_type": snippet_type,
                    "tip":          tip,
                    "difficulty":   difficulty,
                })
        except Exception as exc:
            logger.exception("Snippet optimizer failed")
            error = f"Could not load data: {exc}"
    elif not gsc_connected:
        error = "Connect Google Search Console to find snippet opportunities."

    return render_template(
        "seo/snippets.html",
        opportunities=opportunities,
        gsc_connected=gsc_connected,
        site_url=site_url,
        error=error,
    )


@seo_bp.route("/pagespeed", methods=["GET", "POST"], endpoint="pagespeed")
@login_required
def pagespeed():
    """Page Speed & Core Web Vitals dashboard via Google PageSpeed Insights API."""
    aid = current_account_id()
    result = None
    error = None
    url_checked = None

    site_url = None
    try:
        from app.google import _get_gsc_selected_site
        import os
        site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE")
    except Exception:
        pass
    if not site_url:
        try:
            from app.models_wp import WPSite
            s = WPSite.query.filter_by(account_id=aid).first()
            if s:
                site_url = s.base_url
        except Exception:
            pass

    url_to_check = (request.form.get("url") or site_url or "").strip().rstrip("/")

    if request.method == "POST" and url_to_check:
        url_checked = url_to_check
        try:
            import requests as _req
            api_key = current_app.config.get("GOOGLE_PAGESPEED_KEY", "")
            scores = {}
            for strategy in ("mobile", "desktop"):
                params: dict = {
                    "url": url_to_check,
                    "strategy": strategy,
                    "category": ["performance", "accessibility", "best-practices", "seo"],
                }
                if api_key:
                    params["key"] = api_key

                r = _req.get(
                    "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                    params=params,
                    timeout=30,
                )
                r.raise_for_status()
                data = r.json()

                cats   = data.get("lighthouseResult", {}).get("categories", {})
                audits = data.get("lighthouseResult", {}).get("audits", {})

                def _score(key):
                    v = cats.get(key, {}).get("score")
                    return round(v * 100) if v is not None else None

                def _metric(key):
                    a = audits.get(key, {})
                    return {"value": a.get("displayValue", "—"), "score": a.get("score")}

                opps = []
                for audit_id, audit in audits.items():
                    if audit.get("score") is not None and audit["score"] < 0.9:
                        if audit.get("details", {}).get("type") in ("opportunity", "table"):
                            opps.append({
                                "title":       audit.get("title", ""),
                                "description": audit.get("description", ""),
                                "savings":     audit.get("displayValue", ""),
                                "score":       audit.get("score"),
                            })
                opps.sort(key=lambda x: x["score"] or 1)
                opps = opps[:6]

                scores[strategy] = {
                    "performance":    _score("performance"),
                    "accessibility":  _score("accessibility"),
                    "best_practices": _score("best-practices"),
                    "seo":            _score("seo"),
                    "lcp":  _metric("largest-contentful-paint"),
                    "fid":  _metric("total-blocking-time"),
                    "cls":  _metric("cumulative-layout-shift"),
                    "ttfb": _metric("server-response-time"),
                    "si":   _metric("speed-index"),
                    "opportunities": opps,
                }

            result = {"mobile": scores.get("mobile"), "desktop": scores.get("desktop")}
            flash("PageSpeed analysis complete.", "success")

        except Exception as exc:
            logger.exception("PageSpeed API failed")
            error = f"PageSpeed check failed: {exc}"

    return render_template(
        "seo/pagespeed.html",
        result=result,
        site_url=site_url,
        url_checked=url_checked,
        error=error,
    )
