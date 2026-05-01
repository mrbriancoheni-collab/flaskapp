# app/wp/__init__.py
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from flask import (
    Blueprint, render_template, request, redirect as _redirect, url_for,
    flash, current_app, jsonify, g, session
)
from sqlalchemy import text, inspect
from sqlalchemy.exc import OperationalError

from app.models_wp import WPSite, WPJob, WPLog
from app.wp.wp_client import WPClient

from app import db
from app.auth.utils import login_required, is_paid_account

bp = Blueprint("my_ai_bp", __name__, url_prefix="/account/my-ai")
wp_bp = Blueprint("wp_bp", __name__)

# Optional analyzer (bs4/requests)
try:
    from app.agents.analyzer import analyze_url  # returns {h1,title,excerpt,draft_html}
except Exception:
    analyze_url = None

# Optional rate limiter (auto-fallback to no-op)
try:
    from app import limiter
except Exception:
    limiter = None

# ---------- helpers ----------

def _limit(spec: str):
    def _wrap(fn):
        if limiter:
            return limiter.limit(spec)(fn)
        return fn
    return _wrap

def see_other(endpoint: str, **values):
    """303 redirect so browser performs a fresh GET (prevents resubmits)."""
    return _redirect(url_for(endpoint, **values), code=303)

def _has_column(table: str, col: str) -> bool:
    try:
        q = text("""
            SELECT 1
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :t
              AND COLUMN_NAME = :c
            LIMIT 1
        """)
        return bool(db.session.execute(q, {"t": table, "c": col}).scalar())
    except Exception:
        try:
            insp = inspect(db.engine)
            cols = [c["name"] for c in insp.get_columns(table)]
            return col in cols
        except Exception:
            return False

def _account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    row = db.session.execute(
        text("SELECT account_id FROM users WHERE id=:id"),
        {"id": uid},
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None

def _wp_has_account_id() -> bool:
    key = "_wp_has_account_id"
    if hasattr(g, key):
        return getattr(g, key)
    exists = False
    try:
        row = db.session.execute(text("SHOW COLUMNS FROM wp_sites LIKE 'account_id'")).fetchone()
        exists = bool(row)
    except Exception:
        try:
            insp = inspect(db.engine)
            cols = [c["name"] for c in insp.get_columns("wp_sites")]
            exists = "account_id" in cols
        except Exception:
            exists = False
    setattr(g, key, exists)
    return exists

def _site_query_for_account(aid: Optional[int]):
    q = WPSite.query
    if _wp_has_account_id() and aid:
        q = q.filter_by(account_id=aid)
    return q

def _current_site() -> Optional[WPSite]:
    """First try DB (preferred). If missing, fall back to env vars so the UI still works."""
    try:
        aid = _account_id()
        site = _site_query_for_account(aid).first()
    except OperationalError:
        current_app.logger.warning("WPSite query failed (schema mismatch). Falling back to env settings only.")
        site = None

    if site:
        return site

    base = current_app.config.get("WP_BASE")
    user = current_app.config.get("WP_USER")
    pw = current_app.config.get("WP_APP_PW")
    if base and user and pw:
        s = WPSite(base_url=base, username=user, app_password=pw)
        s.id = 0  # ephemeral/in-memory indicator
        return s
    return None

def _secret_ok() -> bool:
    supplied = (request.args.get("secret") or request.args.get("key") or "").strip()
    expected = (current_app.config.get("CRON_SECRET") or "").strip()
    return bool(supplied and expected and supplied == expected)

def _openai_key() -> Optional[str]:
    return os.getenv("OPENAI_API_KEY") or (current_app.config or {}).get("OPENAI_API_KEY")

# ---------- queue processor ----------

def _ai_generate_post(brief: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produce {title, html, excerpt} from a brief. Uses analyzer (if URL given),
    otherwise tries OpenAI, and finally falls back to a heuristic stub.
    """
    prompt = (brief.get("prompt") or "").strip()
    source_url = (brief.get("source_url") or "").strip() or None
    tone = brief.get("tone") or ""
    word_count = (brief.get("word_count") or "").strip()
    outline = brief.get("outline") or ""
    primary_kw = brief.get("primary_keyword") or ""
    extra_kws = brief.get("extra_keywords") or []
    topics = brief.get("topics") or []
    pov_ids = brief.get("pov_ids") or []

    # 1) Analyzer if source URL provided
    if source_url and analyze_url:
        try:
            rep = analyze_url(source_url)
            title = rep.get("h1") or rep.get("title") or (topics[0] if topics else "New Post")
            html = rep.get("draft_html") or ""
            excerpt = rep.get("excerpt") or ""
            if html:
                return {"title": title, "html": html, "excerpt": excerpt}
        except Exception:
            current_app.logger.exception("Analyzer failed for %s", source_url)

    # 2) OpenAI
    key = _openai_key()
    if key:
        try:
            import json, requests
            sys = (
                "You are a senior content writer for a local services blog. "
                "Write helpful, original, practical content with clear structure (H2/H3), "
                "and a short meta-style excerpt. Return STRICT JSON: {title, html, excerpt}."
            )
            user = {
                "brief": {
                    "prompt": prompt,
                    "tone": tone,
                    "word_count": word_count,
                    "outline": outline,
                    "primary_keyword": primary_kw,
                    "extra_keywords": extra_kws,
                    "topics": topics,
                    "pov_ids": pov_ids,
                    "source_url": source_url,
                },
                "rules": [
                    "Prefer 800–1200 words unless word_count given.",
                    "Use short paragraphs and scannable subheads.",
                    "Add simple bullet lists where useful.",
                    "No commentary; JSON only.",
                ],
            }
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": (current_app.config or {}).get("OPENAI_MODEL", "gpt-4o-mini"),
                    "temperature": 0.5,
                    "messages": [{"role": "system", "content": sys},
                                 {"role": "user", "content": json.dumps(user)}],
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if r.status_code < 400:
                data = r.json()["choices"][0]["message"]["content"]
                obj = json.loads(data)
                return {
                    "title": (obj.get("title") or "New Post").strip(),
                    "html": obj.get("html") or "",
                    "excerpt": obj.get("excerpt") or "",
                }
            else:
                current_app.logger.error("OpenAI error %s: %s", r.status_code, r.text[:500])
        except Exception:
            current_app.logger.exception("OpenAI generation failed")

    # 3) Heuristic fallback
    title = topics[0] if topics else (primary_kw or "New Post")
    if prompt:
        title = title or "New Post"
    html = f"""<h2>{title}</h2>
<p>Looking for clear, practical guidance? This post covers {primary_kw or 'a key topic'} with simple steps you can use today.</p>
<h3>What you’ll learn</h3>
<ul>
<li>How to spot common issues</li>
<li>Quick fixes you can try</li>
<li>When to call a professional</li>
</ul>
<p>If you need help, contact our team for fast, friendly service.</p>"""
    excerpt = "Clear, practical tips you can use today—plus when to call a pro."
    return {"title": title, "html": html, "excerpt": excerpt}

def _process_queue(max_jobs: int = 5) -> dict:
    site = _current_site()
    if not site:
        return {"ok": False, "processed": 0, "error": "No WordPress settings"}

    processed = 0
    now = datetime.utcnow()

    due_jobs = (
        WPJob.query
        .filter(WPJob.status == "queued")
        .filter((WPJob.run_at == None) | (WPJob.run_at <= now))  # noqa: E711
        .order_by(WPJob.created_at.asc())
        .limit(max_jobs)
        .all()
    )

    for job in due_jobs:
        job.status = "running"
        job.last_error = None
        db.session.commit()

        try:
            c = WPClient(site.base_url, site.username, site.app_password)

            if job.kind == "publish":
                p = job.payload or {}
                res = c.create_or_update_post(
                    title=p.get("title", ""),
                    html=p.get("html", ""),
                    excerpt=p.get("excerpt"),
                    status=p.get("status") or "draft",
                    publish_dt=p.get("publish_dt"),
                    categories=p.get("categories"),
                    tags=p.get("tags"),
                    yoast_title=p.get("yoast_title"),
                    yoast_desc=p.get("yoast_desc"),
                    faq_jsonld=p.get("faq_jsonld"),
                    featured_media=p.get("featured_media"),
                )
                link = res.get("link")
                msg = f"Published post {res.get('id')} → {link}" if link else f"Published post {res.get('id')}"
                db.session.add(WPLog(site_id=site.id, job_id=job.id, level="info", message=msg))

            elif job.kind == "refresh":
                p = job.payload or {}
                post_id = int(p.get("post_id", 0))
                if not post_id:
                    raise ValueError("refresh job missing post_id")

                post = c.get_post(post_id)
                title = p.get("new_title") or post["title"]["rendered"]
                desc = p.get("new_desc")

                c.create_or_update_post(
                    post_id=post_id,
                    title=title,
                    html=post["content"]["rendered"],
                    status=p.get("status") or "publish",
                    yoast_title=title if desc else None,
                    yoast_desc=desc if desc else None,
                )
                db.session.add(WPLog(site_id=site.id, job_id=job.id, level="info", message=f"Refreshed post {post_id}"))

            elif job.kind == "ai_generate":
                brief = job.payload or {}
                draft = _ai_generate_post(brief)

                needs_approval = bool(brief.get("require_approval")) or bool(getattr(site, "autopilot_require_approval", False))
                status = "draft" if needs_approval else "publish"

                res = c.create_or_update_post(
                    title=draft.get("title") or "New Post",
                    html=draft.get("html") or "",
                    excerpt=draft.get("excerpt") or "",
                    status=status,
                    publish_dt=None,
                    yoast_title=draft.get("title"),
                    yoast_desc=draft.get("excerpt"),
                )
                link = res.get("link")
                msg = f"AI draft created {res.get('id')} → {link}" if link else f"AI draft created {res.get('id')}"
                db.session.add(WPLog(site_id=site.id, job_id=job.id, level="info", message=msg))

            else:
                db.session.add(WPLog(site_id=site.id, job_id=job.id, level="warning", message=f"Unknown job kind: {job.kind}"))

            job.status = "done"
            db.session.commit()
            processed += 1

        except Exception as e:
            current_app.logger.exception("WP job failed")
            job.status = "error"
            job.last_error = str(e)
            db.session.add(WPLog(site_id=site.id, job_id=job.id, level="error", message=str(e)))
            db.session.commit()

    return {"ok": True, "processed": processed}

# ---------- email approve ----------

def _send_approval_email(to_email: str, job: WPJob):
    """Send approval email using Mailgun via email_service."""
    from app.services.email_service import send_email

    approve_token = current_app.config.get("APPROVAL_TOKEN") or os.urandom(12).hex()
    approve_url = url_for("wp_bp.approve", job_id=job.id, token=approve_token, _external=True)

    p = job.payload or {}
    title = p.get("title", "Content approval")
    preview = (p.get("html") or "")[:500]

    text_body = f"""Please review and approve.

Title: {title}

Preview (first 500 chars):
{preview}

Approve: {approve_url}
"""

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #f8f9fa; padding: 20px; border-radius: 8px;">
            <h2 style="color: #333; margin-top: 0;">Content Approval Required</h2>
            <p><strong>Title:</strong> {title}</p>
            <p><strong>Preview:</strong></p>
            <div style="background: white; padding: 15px; border-left: 4px solid #7c3aed; margin: 10px 0;">
                {preview}
            </div>
            <div style="margin-top: 20px;">
                <a href="{approve_url}" style="display: inline-block; background: #7c3aed; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">
                    Approve Content
                </a>
            </div>
        </div>
    </body>
    </html>
    """

    success = send_email(
        to=to_email,
        subject=f"[Approve] {title}",
        html_body=html_body,
        text_body=text_body
    )

    if success:
        current_app.logger.info("Sent approval email for job %s to %s", job.id, to_email)
    else:
        current_app.logger.error("Failed to send approval email for job %s to %s", job.id, to_email)

# ---------- routes: navigation & setup ----------

@wp_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    return see_other("wp_bp.insights")

@wp_bp.route("/settings", methods=["GET", "POST"], endpoint="settings")
@login_required
def settings():
    aid = _account_id()
    try:
        site = _site_query_for_account(aid).first()
    except OperationalError:
        current_app.logger.warning("WPSite query failed in settings (schema mismatch).")
        site = None

    if request.method == "POST":
        is_autopilot_post = any(k in request.form for k in (
            "autopilot_enabled", "autopilot_daily_new",
            "autopilot_daily_refresh", "autopilot_require_approval"
        ))

        if is_autopilot_post:
            if not site:
                base = (request.form.get("base_url") or "").strip()
                user = (request.form.get("username") or "").strip()
                pw = (request.form.get("app_password") or "").strip()
                if not base or not user or not pw:
                    flash("Please save your WordPress connection first.", "error")
                    return see_other("wp_bp.settings")
                try:
                    if _wp_has_account_id():
                        site = WPSite(account_id=aid, base_url=base, username=user, app_password=pw)
                    else:
                        site = WPSite(base_url=base, username=user, app_password=pw)
                    db.session.add(site)
                    db.session.commit()
                except OperationalError:
                    current_app.logger.exception("Creating WPSite failed (schema mismatch).")
                    flash("Database schema is out of date for WordPress settings. Please run the migration that adds wp_sites.account_id.", "error")
                    return see_other("wp_bp.settings")

            site.autopilot_enabled = bool(request.form.get("autopilot_enabled"))
            try:
                site.autopilot_daily_new = max(0, int(request.form.get("autopilot_daily_new", 1)))
            except Exception:
                site.autopilot_daily_new = 1
            try:
                site.autopilot_daily_refresh = max(0, int(request.form.get("autopilot_daily_refresh", 1)))
            except Exception:
                site.autopilot_daily_refresh = 1
            site.autopilot_require_approval = bool(request.form.get("autopilot_require_approval"))

            db.session.commit()
            flash("Autopilot settings saved.", "success")
            return see_other("wp_bp.settings")

        base = (request.form.get("base_url") or "").strip()
        user = (request.form.get("username") or "").strip()
        pw = (request.form.get("app_password") or "").strip()

        if not base or not user or not pw:
            flash("Base URL, username, and App Password are required.", "error")
            return render_template("wp/settings.html", site=site)

        try:
            if not site:
                if _wp_has_account_id():
                    site = WPSite(account_id=aid, base_url=base, username=user, app_password=pw)
                else:
                    site = WPSite(base_url=base, username=user, app_password=pw)
                db.session.add(site)
            else:
                site.base_url = base
                site.username = user
                if pw != "********":
                    site.app_password = pw

            db.session.commit()
            flash("Saved WordPress settings.", "success")
        except OperationalError:
            current_app.logger.exception("Saving WPSite failed (schema mismatch).")
            flash("Database schema is out of date for WordPress settings. Please run the migration to add wp_sites.account_id (you can keep using env vars meanwhile).", "error")

        return see_other("wp_bp.settings")

    return render_template("wp/settings.html", site=site)

@wp_bp.route("/test", methods=["POST"], endpoint="test")
@login_required
def test():
    site = _current_site()
    if not site:
        flash("No WordPress settings found. Please configure first.", "error")
        return see_other("wp_bp.settings")

    results = {"api_index": None, "posts_endpoint": None, "auth": None}

    try:
        c = WPClient(site.base_url, site.username, site.app_password)

        # Step 1: Check if REST API is accessible at all
        try:
            import requests
            # Try both endpoints without auth first to see what's blocked
            for url in [f"{site.base_url}/wp-json/", f"{site.base_url}/index.php?rest_route=/"]:
                try:
                    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code == 200:
                        results["api_index"] = "ok"
                        break
                    elif r.status_code == 403:
                        results["api_index"] = f"403 blocked at {url}"
                except Exception:
                    continue
        except Exception as e:
            results["api_index"] = f"error: {e}"

        # Step 2: Check auth with existing method
        res = c.auth_check()
        if res.get("ok"):
            results["auth"] = f"ok (author #{res.get('author', '?')})"
        else:
            results["auth"] = res.get("error", "failed")

        # Step 3: Try to actually access posts endpoint (the real test)
        try:
            # Just try to list posts - this tests if posts API is accessible
            test_resp = c._req("GET", "/wp/v2/posts", params={"per_page": 1})
            results["posts_endpoint"] = "ok"
        except Exception as post_err:
            err_str = str(post_err)
            results["posts_endpoint"] = err_str[:200]

        # Summarize results
        if results["posts_endpoint"] == "ok":
            flash(f"Success! WordPress API is working. Auth: {results['auth']}", "success")
        elif "403" in str(results.get("posts_endpoint", "")):
            # Posts endpoint blocked - this is the real problem
            flash(
                "403 Forbidden on posts API. Your WordPress site is blocking REST API requests. "
                "Check: 1) Security plugins (Wordfence, Sucuri) - whitelist your server IP, "
                "2) Cloudflare - create a rule to allow /wp-json/* and index.php?rest_route=*, "
                "3) .htaccess or server config blocking Authorization header.",
                "error"
            )
        else:
            flash(f"Connection issue: {results.get('posts_endpoint', 'Unknown error')}", "error")

        current_app.logger.info("WP test results: %s", results)

    except Exception as e:
        current_app.logger.exception("WP test failed")
        flash(f"Could not connect: {e}", "error")

    return see_other("wp_bp.settings")


@wp_bp.route("/diagnose", methods=["GET"], endpoint="diagnose")
@login_required
def diagnose():
    """Detailed diagnostic endpoint returning JSON with all test results."""
    site = _current_site()
    if not site:
        return jsonify({"error": "No WordPress site configured"}), 400

    import requests as req_lib
    diag = {
        "site_url": site.base_url,
        "tests": {}
    }

    # Test 1: Raw connectivity (no auth)
    for label, url in [
        ("wp_json_noauth", f"{site.base_url}/wp-json/"),
        ("rest_route_noauth", f"{site.base_url}/index.php?rest_route=/"),
    ]:
        try:
            r = req_lib.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            diag["tests"][label] = {"status": r.status_code, "ok": r.status_code == 200}
        except Exception as e:
            diag["tests"][label] = {"error": str(e)}

    # Test 2: With auth
    try:
        c = WPClient(site.base_url, site.username, site.app_password)

        # Auth check
        auth_res = c.auth_check()
        diag["tests"]["auth_check"] = auth_res

        # Posts list
        try:
            c._req("GET", "/wp/v2/posts", params={"per_page": 1})
            diag["tests"]["posts_list"] = {"ok": True}
        except Exception as e:
            diag["tests"]["posts_list"] = {"ok": False, "error": str(e)[:500]}

        # Categories (often less protected)
        try:
            c._req("GET", "/wp/v2/categories", params={"per_page": 1})
            diag["tests"]["categories"] = {"ok": True}
        except Exception as e:
            diag["tests"]["categories"] = {"ok": False, "error": str(e)[:200]}

    except Exception as e:
        diag["tests"]["client_init"] = {"error": str(e)}

    # Recommendation
    posts_ok = diag["tests"].get("posts_list", {}).get("ok", False)
    if posts_ok:
        diag["recommendation"] = "All tests passed. Publishing should work."
    elif "403" in str(diag["tests"].get("posts_list", {})):
        diag["recommendation"] = (
            "Posts API returns 403. This is usually caused by: "
            "1) Security plugin blocking REST API (check Wordfence/Sucuri settings), "
            "2) Cloudflare/WAF blocking requests (add firewall rule to allow), "
            "3) Server stripping Authorization header (check .htaccess)."
        )
    else:
        diag["recommendation"] = "Connection issues detected. Check credentials and site URL."

    return jsonify(diag)

# ---------- content ops ----------

@wp_bp.route("/publisher", methods=["GET"], endpoint="publisher")
@login_required
def publisher():
    site = _current_site()
    jobs_ = WPJob.query.order_by(WPJob.created_at.desc()).limit(50).all()
    return render_template("wp/publisher.html", site=site, jobs=jobs_)

# GET legacy “compose” just points at /new
@wp_bp.route("/compose", methods=["GET"], endpoint="compose")
@login_required
def compose_get_legacy():
    return see_other("wp_bp.new_post")

# POST submit moved to unique path to avoid ANY endpoint collisions
@wp_bp.route("/compose/submit", methods=["POST"], endpoint="compose_submit")
@login_required
def compose_submit():
    """
    Handle new post submissions from new_post.html.
    Supports both 'manual' and 'ai' modes (AI is paid-gated).
    """
    site = _current_site()
    if not site:
        flash("Configure WordPress first.", "error")
        return see_other("wp_bp.settings")

    mode = (request.form.get("mode") or "manual").strip().lower()

    if mode == "manual":
        title = (request.form.get("title") or "").strip()
        content = (request.form.get("content") or "").strip()
        if not title or not content:
            flash("Title and content are required.", "error")
            return see_other("wp_bp.new_post")

        needs_approval = bool(getattr(site, "autopilot_require_approval", False))
        status = "draft" if needs_approval else "publish"

        payload = {
            "title": title,
            "html": content,
            "excerpt": "",
            "status": status,
            "publish_dt": None,
            "needs_approval": needs_approval,
        }

        job = WPJob(site_id=site.id, kind="publish", payload=payload)
        db.session.add(job)
        db.session.commit()
        flash("Post queued successfully.", "success")

    elif mode == "ai":
        if not is_paid_account():
            flash("AI drafting is available on paid plans. Upgrade to continue.", "warning")
            return see_other("wp_bp.new_post")

        pov_ids_raw = request.form.getlist("pov_ids[]") or request.form.getlist("pov_ids") or []
        try:
            pov_ids = [int(x) for x in pov_ids_raw if str(x).isdigit()]
        except Exception:
            pov_ids = []

        topics_base = []
        if request.form.get("topic"):
            topics_base.append(request.form.get("topic"))
        if request.form.get("topics_extra"):
            topics_base.extend((request.form.get("topics_extra") or "").split(","))

        brief = {
            "prompt": (request.form.get("prompt") or "").strip(),
            "source_url": (request.form.get("source_url") or "").strip() or None,
            "tone": (request.form.get("tone") or "").strip() or None,
            "word_count": (request.form.get("word_count") or "").strip() or None,
            "outline": (request.form.get("outline") or "").strip() or None,
            "include_images": bool(request.form.get("include_images")),
            "pov_ids": pov_ids,
            "primary_keyword": (request.form.get("primary_keyword") or "").strip() or None,
            "extra_keywords": [
                k.strip() for k in (request.form.get("extra_keywords") or "").split(",") if k.strip()
            ],
            "topics": [t.strip() for t in topics_base if t and t.strip()],
            "require_approval": bool(request.form.get("require_approval")),
        }

        job = WPJob(site_id=site.id, kind="ai_generate", payload=brief)
        db.session.add(job)
        db.session.commit()
        flash("AI draft request queued successfully.", "success")

    else:
        flash("Invalid compose mode.", "error")

    return see_other("wp_bp.publisher")

@wp_bp.route("/publisher/run-now", methods=["POST"], endpoint="run_now")
@login_required
def run_now():
    try:
        max_jobs = int(request.form.get("max", 5))
        max_jobs = max(1, min(max_jobs, 20))
    except Exception:
        max_jobs = 5

    result = _process_queue(max_jobs=max_jobs)
    if result.get("ok"):
        flash(f"Processed {result.get('processed', 0)} job(s).", "success")
    else:
        flash(result.get("error") or "Failed to process jobs.", "error")
    return see_other("wp_bp.publisher")

@wp_bp.route("/analyze", methods=["GET", "POST"], endpoint="analyze")
@login_required
def analyze():
    if request.method == "GET":
        return render_template("wp/analyze.html")

    if analyze_url is None:
        flash("Analyzer is not available on this instance.", "error")
        return see_other("wp_bp.publisher")

    url = (request.form.get("url") or "").strip()
    require_approval = bool(request.form.get("require_approval"))
    if not url:
        flash("URL required.", "error")
        return see_other("wp_bp.analyze")

    site = _current_site()
    if not site:
        flash("Configure WordPress first.", "error")
        return see_other("wp_bp.settings")

    try:
        rep = analyze_url(url)
        title = f"Improvement Plan: {rep.get('h1') or rep.get('title') or url}"
        payload = {
            "title": title,
            "html": rep.get("draft_html") or "",
            "excerpt": rep.get("excerpt") or "",
            "status": "draft" if (require_approval or site.autopilot_require_approval) else "publish",
            "needs_approval": True if (require_approval or site.autopilot_require_approval) else False,
            "analysis_url": url,
        }
        job = WPJob(site_id=site.id, kind="publish", payload=payload)
        db.session.add(job)
        db.session.commit()

        to = current_app.config.get("APPROVAL_EMAIL")
        if to and payload.get("needs_approval"):
            try:
                _send_approval_email(to, job)
            except Exception:
                current_app.logger.exception("Approval email failed")

        flash("Analysis queued.", "success")
    except Exception:
        current_app.logger.exception("Analyze queue failed")
        flash("Could not analyze the page.", "error")

    return see_other("wp_bp.publisher")

@wp_bp.route("/new", methods=["GET", "POST"], endpoint="new_post")
@login_required
def new_post():
    site = _current_site()
    if request.method == "GET":
        return render_template("wp/new_post.html", site=site)

    if not site:
        flash("Configure WordPress first.", "error")
        return see_other("wp_bp.settings")

    title = (request.form.get("title") or "").strip()
    html  = (request.form.get("html") or "").strip()
    excerpt = (request.form.get("excerpt") or "").strip()
    when = (request.form.get("publish_when") or "now").strip()  # now | future+<days>
    require_approval = bool(request.form.get("require_approval"))

    if not title or not html:
        flash("Title and content are required.", "error")
        return see_other("wp_bp.new_post")

    run_at = None
    status = "publish"
    publish_dt = None

    if when.startswith("future+"):
        try:
            days = int(when.split("+", 1)[1])
            run_at = datetime.utcnow() + timedelta(days=days)
            status = "future"
            publish_dt = (datetime.utcnow() + timedelta(days=days))
        except Exception:
            run_at = None

    needs_approval = require_approval or bool(getattr(site, "autopilot_require_approval", False))
    if needs_approval:
        status = "draft"
        publish_dt = None

    payload = {
        "title": title,
        "html": html,
        "excerpt": excerpt,
        "status": status,
        "publish_dt": publish_dt,
        "needs_approval": needs_approval,
    }

    job = WPJob(site_id=site.id, kind="publish", payload=payload, run_at=run_at)
    db.session.add(job)
    db.session.commit()

    to = current_app.config.get("APPROVAL_EMAIL")
    if to and needs_approval:
        try:
            _send_approval_email(to, job)
        except Exception:
            current_app.logger.exception("Approval email failed")

    flash("Post queued.", "success")
    return see_other("wp_bp.publisher")

@wp_bp.route("/edit/refresh", methods=["POST"], endpoint="queue_refresh")
@login_required
def queue_refresh():
    site = _current_site()
    post_id = (request.form.get("post_id") or "").strip()
    new_title = request.form.get("new_title") or ""
    new_desc  = request.form.get("new_desc") or ""
    status    = (request.form.get("status") or "publish").strip()

    if not site or not post_id:
        flash("Site settings and post_id are required.", "error")
        return see_other("wp_bp.publisher")

    payload = {"post_id": int(post_id), "new_title": new_title, "new_desc": new_desc, "status": status}
    job = WPJob(site_id=site.id, kind="refresh", payload=payload)
    db.session.add(job)
    db.session.commit()
    flash("Refresh queued.", "success")
    return see_other("wp_bp.publisher")

@wp_bp.route("/approve", methods=["POST"], endpoint="approve")
@login_required
def approve():
    token = request.form.get("token", "") or request.args.get("token", "")
    job_id = int(request.form.get("job_id", 0) or request.args.get("job_id", 0))
    if not job_id or token != (current_app.config.get("APPROVAL_TOKEN") or ""):
        flash("Invalid approval.", "error")
        return see_other("wp_bp.publisher")

    job = WPJob.query.get_or_404(job_id)
    p = job.payload or {}
    p.pop("needs_approval", None)
    p["status"] = p.get("status") if p.get("status") == "future" else "publish"
    job.payload = p
    db.session.commit()
    flash("Approved. It will publish on the next runner tick.", "success")
    return see_other("wp_bp.publisher")

# ---------- insights ----------

@wp_bp.route("/insights", methods=["GET"], endpoint="insights")
@login_required
def insights():
    jobs = (WPJob.query
            .order_by(WPJob.created_at.desc())
            .limit(50).all())

    ga = None
    gsc = None
    try:
        from app.models_analytics import GAStat, GSCStat
        ga = GAStat.latest()
        gsc = GSCStat.latest()
    except Exception:
        pass

    seo_alerts = []
    seo_unread = 0
    try:
        from app.seo.monitor import get_unread_alerts
        aid = _account_id()
        if aid:
            seo_alerts = get_unread_alerts(account_id=aid, limit=3)
            seo_unread = len([a for a in seo_alerts if not a.is_read])
    except Exception:
        pass

    return render_template("wp/insights.html", jobs=jobs, ga=ga, gsc=gsc,
                           seo_alerts=seo_alerts, seo_unread=seo_unread)

# ---------- cron (no login) ----------

@wp_bp.route("/cron-runner", methods=["GET"])
@wp_bp.route("/run", methods=["GET"])   # legacy
@_limit("6/minute")
def cron_runner():
    if not _secret_ok():
        current_app.logger.warning("wp cron-runner: bad or missing secret")
        return jsonify({"ok": False, "error": "forbidden"}), 403

    try:
        max_jobs = int(request.args.get("max", 5))
        max_jobs = max(1, min(max_jobs, 20))
    except Exception:
        max_jobs = 5

    ran_at = datetime.utcnow().isoformat() + "Z"
    current_app.logger.info("wp cron-runner: start at %s (max=%s)", ran_at, max_jobs)

    result = _process_queue(max_jobs=max_jobs)

    # Hook SEO monitor — runs at most once per 23 h per site (throttled inside)
    seo_monitor_results = []
    try:
        from app.seo.monitor import run_monitoring_check
        sites = WPSite.query.all()
        for site in sites:
            r = run_monitoring_check(
                site_url=site.base_url,
                site_id=site.id,
                account_id=site.account_id,
            )
            seo_monitor_results.append({"site": site.base_url, **r})
    except Exception as exc:
        current_app.logger.exception("SEO monitor hook failed in cron_runner")
        seo_monitor_results = [{"error": str(exc)}]

    return jsonify({"ran_at": ran_at, **result,
                    "seo_monitor": seo_monitor_results}), 200

# ---------- legacy / compatibility aliases ----------

@wp_bp.route("/schema-gen", methods=["GET", "POST"], endpoint="schema_gen")
@login_required
def schema_gen():
    site   = _current_site()
    result = None
    injected = None

    if request.method == "POST":
        action = (request.form.get("action") or "generate").strip()

        # ── shared form values ──────────────────────────────────────────────
        source_type = (request.form.get("source_type") or "url").strip()
        post_id_raw = (request.form.get("post_id") or "").strip()
        source_url  = (request.form.get("source_url") or "").strip()

        schema_kwargs = dict(
            include_article       = bool(request.form.get("include_article")),
            include_faq           = bool(request.form.get("include_faq")),
            include_howto         = bool(request.form.get("include_howto")),
            include_local_business= bool(request.form.get("include_local_business")),
            override_title        = (request.form.get("override_title") or "").strip(),
            override_author       = (request.form.get("override_author") or "").strip(),
            override_description  = (request.form.get("override_description") or "").strip(),
            override_image_url    = (request.form.get("override_image_url") or "").strip(),
            business_name         = (request.form.get("business_name") or "").strip(),
            business_phone        = (request.form.get("business_phone") or "").strip(),
            business_address      = (request.form.get("business_address") or "").strip(),
            business_type         = (request.form.get("business_type") or "LocalBusiness").strip(),
        )

        if action == "generate":
            try:
                from app.wp.schema_gen import generate_from_url, generate_from_wp_post
                if source_type == "post" and post_id_raw and site:
                    from app.wp.wp_client import WPClient
                    client = WPClient(site.base_url, site.username, site.app_password)
                    result = generate_from_wp_post(client, int(post_id_raw), **schema_kwargs)
                elif source_url:
                    result = generate_from_url(source_url, **schema_kwargs)
                else:
                    flash("Enter a Post ID or URL to generate schema.", "error")
                if result and result.get("error"):
                    flash(result["error"], "error")
                    result = None
            except Exception:
                current_app.logger.exception("Schema generation failed")
                flash("Schema generation failed — please try again.", "error")

        elif action == "inject":
            if not site:
                flash("Connect a WordPress site first.", "error")
            else:
                inject_post_id = int(request.form.get("inject_post_id") or 0)
                schemas_json   = request.form.get("schemas_json") or "[]"
                replace        = bool(request.form.get("replace_existing"))
                if not inject_post_id:
                    flash("Post ID required for injection.", "error")
                else:
                    try:
                        import json as _json
                        from app.wp.schema_gen import inject_schema_into_post
                        from app.wp.wp_client import WPClient
                        schemas = _json.loads(schemas_json)
                        if not isinstance(schemas, list):
                            schemas = [schemas]
                        client  = WPClient(site.base_url, site.username, site.app_password)
                        injected = inject_schema_into_post(client, inject_post_id,
                                                           schemas, replace_existing=replace)
                        if injected.get("ok"):
                            flash(f"Schema injected into post #{inject_post_id}.", "success")
                        else:
                            flash(injected.get("error") or "Injection failed.", "error")
                    except Exception:
                        current_app.logger.exception("Schema injection failed")
                        flash("Injection failed — please try again.", "error")

    return render_template("wp/schema_gen.html", site=site, result=result, injected=injected)


@wp_bp.route("/tech-seo", methods=["GET", "POST"], endpoint="tech_seo")
@login_required
def tech_seo():
    site = _current_site()
    result = None
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        if not url and site:
            url = site.base_url
        if not url:
            flash("Enter a URL or connect a WordPress site first.", "error")
            return render_template("wp/tech_seo.html", site=site, result=None)
        try:
            from app.wp.tech_seo import run_technical_audit
            psi_key = os.getenv("GOOGLE_PSI_API_KEY") or (current_app.config or {}).get("GOOGLE_PSI_API_KEY")
            result = run_technical_audit(url, psi_api_key=psi_key)
            if result.get("error"):
                flash(result["error"], "error")
                result = None
        except Exception:
            current_app.logger.exception("Technical SEO audit failed")
            flash("Audit failed — please try again.", "error")
    return render_template("wp/tech_seo.html", site=site, result=result)


@wp_bp.route("/seo-audit", methods=["GET", "POST"], endpoint="seo_audit")
@login_required
def seo_audit():
    result = None
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        keyword = (request.form.get("keyword") or "").strip()
        if not url:
            flash("URL is required.", "error")
            return see_other("wp_bp.seo_audit")
        try:
            from app.wp.seo_audit import audit_url
            result = audit_url(url, keyword)
            if result.get("error"):
                flash(result["error"], "error")
                result = None
        except Exception:
            current_app.logger.exception("SEO audit failed")
            flash("Audit failed — please try again.", "error")
    return render_template("wp/seo_audit.html", result=result)


@wp_bp.route("/analyze-page", methods=["GET"], endpoint="analyze_page")
@login_required
def analyze_page_alias():
    return see_other("wp_bp.analyze")

@wp_bp.route("/jobs", methods=["GET"], endpoint="jobs")
@login_required
def jobs_alias():
    return see_other("wp_bp.publisher")

@wp_bp.route("/jobs/new-post", methods=["POST"], endpoint="queue_post")
@login_required
def queue_post_alias():
    return new_post()

@wp_bp.route("/edit", methods=["GET"], endpoint="edit_lookup")
@login_required
def edit_lookup_stub():
    flash("Edit lookup coming soon. Use Publisher to see recent jobs.", "info")
    return see_other("wp_bp.publisher")

# allow WPLog(...).save() convenience
def _save(self):
    db.session.add(self)
    db.session.commit()
    return self
WPLog.save = _save
