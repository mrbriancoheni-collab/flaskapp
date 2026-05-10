# app/wp/__init__.py
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from flask import (
    Blueprint, render_template, request, redirect as _redirect, url_for,
    flash, current_app, jsonify, g, session, abort
)
from sqlalchemy import text, inspect
from sqlalchemy.exc import OperationalError

from app.models_wp import WPSite, WPJob, WPLog
from app.wp.wp_client import WPClient

from app import db
from app.auth.utils import login_required, is_paid_account

logger = logging.getLogger(__name__)

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
    if aid:
        q = q.filter_by(account_id=aid)
    return q

def _current_site() -> Optional[WPSite]:
    """Return the WPSite for the current account. Ensures account_id column exists first."""
    # Ensure the account_id column is present (safe no-op if already there)
    try:
        WPSite.ensure_columns()
    except Exception:
        pass

    aid = _account_id()
    site = None
    try:
        if aid:
            site = WPSite.query.filter_by(account_id=aid).first()
            if not site:
                # First access after migration: claim any unowned site for this account
                unowned = WPSite.query.filter(
                    (WPSite.account_id == None) | (WPSite.account_id == 0)  # noqa: E711
                ).first()
                if unowned:
                    unowned.account_id = aid
                    db.session.commit()
                    site = unowned
        else:
            site = WPSite.query.first()
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
    Produce {title, html, excerpt} from a brief.
    Priority: 1) URL analyzer  2) Claude  3) OpenAI  4) heuristic stub
    """
    import json as _json
    prompt = (brief.get("prompt") or "").strip()
    source_url = (brief.get("source_url") or "").strip() or None
    tone = brief.get("tone") or "helpful and practical"
    word_count = (brief.get("word_count") or "900").strip()
    outline = brief.get("outline") or ""
    primary_kw = brief.get("primary_keyword") or ""
    extra_kws = brief.get("extra_keywords") or []
    topics = brief.get("topics") or []
    cluster_name = brief.get("cluster_name") or ""
    supporting_context = brief.get("supporting_context") or ""

    # 1) Analyzer — scrape and rewrite from a source URL
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

    # Build the shared content brief string used by Claude and OpenAI
    kw_line = f"Primary keyword: {primary_kw}" if primary_kw else ""
    extra_line = f"Secondary keywords: {', '.join(extra_kws)}" if extra_kws else ""
    cluster_line = f"Topic cluster: {cluster_name}" if cluster_name else ""
    context_line = f"Additional context: {supporting_context}" if supporting_context else ""
    outline_line = f"Suggested outline:\n{outline}" if outline else ""
    brief_block = "\n".join(filter(None, [kw_line, extra_line, cluster_line, context_line, outline_line, prompt]))

    # 2) Claude (primary AI writer)
    try:
        from app.ai_clients import get_ai_client
        client = get_ai_client()
        claude_prompt = f"""You are a senior SEO content writer. Write a complete, publish-ready blog post.

Content brief:
{brief_block}

Requirements:
- Tone: {tone}
- Target length: {word_count} words
- Use H2 and H3 headings for structure
- Include short paragraphs and bullet lists where appropriate
- Naturally incorporate the primary keyword in the title, first paragraph, and 2-3 subheadings
- End with a clear call-to-action paragraph

Return ONLY valid JSON with these exact keys:
{{"title": "...", "html": "...", "excerpt": "..."}}

The html value must be full HTML article content (no <html>/<body> wrapper).
The excerpt must be 145-155 characters optimised as a meta description."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4000,
            messages=[{"role": "user", "content": claude_prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        import re as _re
        raw = _re.sub(r'^```(?:json)?\s*', '', raw, flags=_re.MULTILINE)
        raw = _re.sub(r'\s*```$', '', raw, flags=_re.MULTILINE)
        obj = _json.loads(raw)
        if obj.get("title") and obj.get("html"):
            result = {
                "title": obj["title"].strip(),
                "html": obj["html"],
                "excerpt": (obj.get("excerpt") or "")[:160],
            }
            # Try to find a featured image via Unsplash (best-effort)
            unsplash_key = os.getenv("UNSPLASH_ACCESS_KEY")
            if unsplash_key and (primary_kw or obj["title"]):
                try:
                    import requests as _req
                    query = primary_kw or obj["title"]
                    r = _req.get(
                        "https://api.unsplash.com/search/photos",
                        params={"query": query, "per_page": 1, "orientation": "landscape"},
                        headers={"Authorization": f"Client-ID {unsplash_key}"},
                        timeout=5,
                    )
                    if r.status_code == 200:
                        items = r.json().get("results") or []
                        if items:
                            result["featured_image_url"] = items[0]["urls"]["regular"]
                            result["featured_image_alt"] = items[0].get("alt_description") or query
                except Exception:
                    pass
            return result
    except Exception:
        current_app.logger.exception("Claude post generation failed")

    # 3) OpenAI fallback
    key = _openai_key()
    if key:
        try:
            import requests
            sys_msg = (
                "You are a senior content writer for a local services blog. "
                "Write helpful, original, practical content with clear structure (H2/H3), "
                "and a short meta-style excerpt. Return STRICT JSON: {title, html, excerpt}."
            )
            user_msg = _json.dumps({
                "brief": brief_block,
                "rules": [
                    f"Target {word_count} words.",
                    "Use short paragraphs and scannable subheads.",
                    "Add simple bullet lists where useful.",
                    "No commentary; JSON only.",
                ],
            })
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": (current_app.config or {}).get("OPENAI_MODEL", "gpt-4o-mini"),
                    "temperature": 0.5,
                    "messages": [{"role": "system", "content": sys_msg},
                                 {"role": "user", "content": user_msg}],
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            if r.status_code < 400:
                obj = _json.loads(r.json()["choices"][0]["message"]["content"])
                return {
                    "title": (obj.get("title") or "New Post").strip(),
                    "html": obj.get("html") or "",
                    "excerpt": obj.get("excerpt") or "",
                }
            else:
                current_app.logger.error("OpenAI error %s: %s", r.status_code, r.text[:500])
        except Exception:
            current_app.logger.exception("OpenAI generation failed")

    # 4) Heuristic fallback
    title = topics[0] if topics else (primary_kw or "New Post")
    html = f"""<h2>{title}</h2>
<p>Looking for clear, practical guidance? This post covers {primary_kw or 'a key topic'} with simple steps you can use today.</p>
<h3>What you'll learn</h3>
<ul>
<li>How to spot common issues</li>
<li>Quick fixes you can try</li>
<li>When to call a professional</li>
</ul>
<p>If you need help, contact our team for fast, friendly service.</p>"""
    excerpt = "Clear, practical tips you can use today—plus when to call a pro."
    return {"title": title, "html": html, "excerpt": excerpt}

def _process_queue(max_jobs: int = 5, site: Optional[WPSite] = None) -> dict:
    if site is None:
        site = _current_site()
    if not site:
        return {"ok": False, "processed": 0, "error": "No WordPress settings"}

    processed = 0
    now = datetime.utcnow()

    due_jobs = (
        WPJob.query
        .filter(WPJob.site_id == site.id,
                WPJob.status == "queued")
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

                # Auto-generate social copy after a live publish (best-effort)
                if res.get("id") and link and p.get("status", "draft") == "publish":
                    try:
                        from app.ai_clients import get_ai_client
                        _sc = get_ai_client()
                        _title = p.get("title") or ""
                        _social_resp = _sc.messages.create(
                            model="claude-haiku-4-5-20251001",
                            max_tokens=300,
                            messages=[{"role": "user", "content":
                                f"Write a short social media post (2-3 sentences, no hashtags) "
                                f"promoting this blog post: '{_title}'. URL: {link}. "
                                f"Make it engaging and conversational. Plain text only."}],
                        )
                        _social_copy = _sc and _social_resp.content[0].text.strip()
                        if _social_copy:
                            db.session.add(WPLog(site_id=site.id, job_id=job.id, level="info",
                                                 message=f"[SOCIAL] {_social_copy}"))
                    except Exception:
                        pass

                # Auto-inject Article schema on publish (best-effort, never blocks the job)
                wp_post_id = res.get("id")
                if wp_post_id and p.get("status", "draft") == "publish":
                    try:
                        from app.wp.schema_gen import generate_from_wp_post, inject_schema_into_post
                        schema_result = generate_from_wp_post(c, wp_post_id, include_article=True, include_faq=True)
                        if schema_result and schema_result.get("schemas"):
                            inject_schema_into_post(c, wp_post_id, schema_result["schemas"], replace_existing=True)
                            db.session.add(WPLog(site_id=site.id, job_id=job.id, level="info",
                                                 message=f"Auto-injected schema into post {wp_post_id}"))
                    except Exception:
                        pass  # schema injection is non-critical

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

                # Upload featured image to WP media library before creating the post
                featured_media_id = None
                feat_url = draft.get("featured_image_url")
                feat_alt = draft.get("featured_image_alt") or (draft.get("title") or "")
                if feat_url:
                    try:
                        import re as _re
                        slug = _re.sub(r"[^a-z0-9]+", "-", (brief.get("primary_keyword") or "featured").lower()).strip("-")
                        featured_media_id = c.upload_image_from_url(feat_url, filename=f"{slug}.jpg", alt_text=feat_alt)
                        db.session.add(WPLog(site_id=site.id, job_id=job.id, level="info",
                                             message=f"Uploaded featured image (media #{featured_media_id})"))
                    except Exception:
                        current_app.logger.exception("Featured image upload failed for ai_generate job %d", job.id)

                res = c.create_or_update_post(
                    title=draft.get("title") or "New Post",
                    html=draft.get("html") or "",
                    excerpt=draft.get("excerpt") or "",
                    status=status,
                    publish_dt=None,
                    yoast_title=draft.get("title"),
                    yoast_desc=draft.get("excerpt"),
                    featured_media=featured_media_id,
                )
                link = res.get("link")
                msg = f"AI draft created {res.get('id')} → {link}" if link else f"AI draft created {res.get('id')}"
                db.session.add(WPLog(site_id=site.id, job_id=job.id, level="info", message=msg))

            elif job.kind == "seo_fix":
                p = job.payload or {}
                post_id = int(p.get("post_id", 0))
                if not post_id:
                    raise ValueError("seo_fix job missing post_id")

                # Fetch current post to preserve content
                existing = c.get_post(post_id)
                current_content = existing.get("content", {}).get("rendered", "")

                # Inject/replace schema block at end of content
                schema_html = p.get("schema_html", "")
                if schema_html:
                    import re as _re
                    # Strip any existing JSON-LD blocks to avoid duplication
                    current_content = _re.sub(
                        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>.*?</script>',
                        "", current_content, flags=_re.DOTALL | _re.IGNORECASE,
                    ).rstrip()
                    current_content = current_content + "\n" + schema_html

                fixes_applied = []
                kwargs: Dict[str, Any] = dict(
                    post_id=post_id,
                    title=existing.get("title", {}).get("rendered", ""),
                    html=current_content,
                    status=existing.get("status", "publish"),
                )
                if p.get("yoast_title"):
                    kwargs["yoast_title"] = p["yoast_title"]
                    fixes_applied.append("Yoast title")
                if p.get("yoast_desc"):
                    kwargs["yoast_desc"] = p["yoast_desc"]
                    fixes_applied.append("Yoast meta description")
                if p.get("excerpt"):
                    kwargs["excerpt"] = p["excerpt"]
                    fixes_applied.append("Excerpt")
                if schema_html:
                    fixes_applied.append("JSON-LD schema")

                c.create_or_update_post(**kwargs)
                msg = (
                    f"SEO auto-fix applied to post {post_id} "
                    f"[{', '.join(fixes_applied) or 'no changes'}] "
                    f"(SEO {p.get('seo_score','?')}, AEO {p.get('aeo_score','?')})"
                )
                db.session.add(WPLog(site_id=site.id, job_id=job.id, level="info", message=msg))

            elif job.kind == "edit":
                p = job.payload or {}
                post_id = int(p.get("post_id", 0))
                if not post_id:
                    raise ValueError("edit job missing post_id")
                res = c.create_or_update_post(
                    post_id=post_id,
                    title=p.get("title", ""),
                    html=p.get("html", ""),
                    excerpt=p.get("excerpt") or None,
                    status=p.get("status") or "publish",
                    yoast_title=p.get("title") or None,
                    yoast_desc=p.get("yoast_desc") or None,
                )
                link = res.get("link")
                msg = f"Edited post {post_id} → {link}" if link else f"Edited post {post_id}"
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

# ---------- SEO auto-fix helpers ----------

def _build_seo_fix_payload(site, url: str, keyword: str = "",
                            source: str = "autopilot") -> Optional[Dict[str, Any]]:
    """
    Audit a URL, generate schema, and return an seo_fix job payload.
    Returns None if the post can't be found on the WP site or no fixes needed.
    """
    try:
        from app.wp.seo_audit import audit_url
        audit = audit_url(url, target_keyword=keyword)
        if audit.get("error"):
            return None

        seo_score = audit.get("seo_score", 100)
        aeo_score = audit.get("aeo_score", 100)

        # Only fix pages that need it
        if seo_score >= 80 and aeo_score >= 70 and source == "autopilot":
            return None

        c = WPClient(site.base_url, site.username, site.app_password)
        post = c.find_post_by_url(url)

        # For the homepage, try the WP settings front-page ID directly
        if not post:
            try:
                base = site.base_url.rstrip("/")
                url_stripped = url.rstrip("/")
                if url_stripped in (base, base + "/"):
                    settings = c._req("GET", "/wp/v2/settings").json()
                    page_id = settings.get("page_on_front")
                    if page_id:
                        resp = c._req("GET", f"/wp/v2/pages/{page_id}").json()
                        if resp.get("id"):
                            post = resp
            except Exception:
                pass

        if not post:
            return None
        post_id = int(post["id"])

        # Generate schema
        schema_html = ""
        schema_result = None
        try:
            from app.wp.schema_gen import generate_from_url
            schema_result = generate_from_url(
                url,
                include_article=True,
                include_faq=True,
                include_howto=True,
            )
            if schema_result and schema_result.get("schema_json"):
                import json as _json
                schema_html = (
                    '<script type="application/ld+json">\n'
                    + _json.dumps(schema_result["schema_json"], indent=2)
                    + "\n</script>"
                )
        except Exception:
            pass

        # Build Yoast meta from audit findings
        yoast_desc = ""
        for chk in audit.get("seo_checks", []):
            if "meta description" in chk.get("label", "").lower() and chk.get("status") != "pass":
                # Use first 155 chars of page description if available
                yoast_desc = (schema_result or {}).get("description", "")[:155] if schema_result else ""
                break

        # For manual source always queue so the user gets feedback;
        # for autopilot skip if there's genuinely nothing to apply.
        if source != "manual" and not schema_html and not yoast_desc:
            return None

        return {
            "post_id":   post_id,
            "post_url":  url,
            "schema_html": schema_html,
            "yoast_desc":  yoast_desc,
            "seo_score":   seo_score,
            "aeo_score":   aeo_score,
            "source":      source,
        }
    except Exception:
        current_app.logger.exception("_build_seo_fix_payload failed for %s", url)
        return None


def _auto_audit_and_fix(site, account_id: int) -> Dict[str, Any]:
    """
    Fetch top GSC pages, audit the lowest-scoring ones, and queue seo_fix jobs.
    Throttled: skips any URL already fixed within the last 7 days.
    """
    import os
    from datetime import date, timedelta as td

    results: List[Dict] = []
    try:
        from app.google import _fetch_gsc_report, _get_gsc_selected_site, _is_connected
        if not _is_connected(account_id, "gsc"):
            return {"ok": True, "skipped": "GSC not connected", "fixed": 0}

        site_url = _get_gsc_selected_site(account_id) or os.getenv("GSC_SITE")
        if not site_url:
            return {"ok": True, "skipped": "No GSC site URL", "fixed": 0}

        end = date.today()
        start = end - td(days=28)
        data = _fetch_gsc_report(site_url, start.isoformat(), end.isoformat()) or {}
        top_pages = (data.get("top_pages") or [])[:10]

        # Collect recently-fixed URLs (last 7 days) to avoid re-fixing
        cutoff = datetime.utcnow() - td(days=7)
        recent_jobs = WPJob.query.filter(
            WPJob.kind == "seo_fix",
            WPJob.created_at >= cutoff,
        ).all()
        recent_urls = {j.payload.get("post_url") for j in recent_jobs if j.payload}

        fixed = 0
        for page in top_pages:
            page_url = page.get("page", "")
            if not page_url or page_url in recent_urls:
                continue
            # Only process pages on this WP site
            if site.base_url.rstrip("/") not in page_url:
                continue

            payload = _build_seo_fix_payload(site, page_url, source="autopilot")
            if payload:
                job = WPJob(site_id=site.id, kind="seo_fix", payload=payload)
                db.session.add(job)
                fixed += 1
                results.append({"url": page_url, "queued": True,
                                 "seo": payload["seo_score"], "aeo": payload["aeo_score"]})

        if fixed:
            db.session.commit()

        return {"ok": True, "fixed": fixed, "pages_checked": len(top_pages), "results": results}

    except Exception as exc:
        current_app.logger.exception("_auto_audit_and_fix failed")
        return {"ok": False, "error": str(exc)}


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
                if aid and not site.account_id:
                    site.account_id = aid

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
        auth_ok = str(results.get("auth", "")).startswith("ok")
        posts_ok = results["posts_endpoint"] == "ok"

        if posts_ok and auth_ok:
            flash(f"WordPress connected and authenticated. {results['auth']}", "success")
        elif posts_ok and not auth_ok:
            flash(
                "WordPress REST API is reachable but authentication failed. "
                "Your Application Password credentials are not working (401 rest_not_logged_in). "
                "Fix: 1) In WP Admin → Users → Profile, delete and regenerate the Application Password. "
                "2) If behind Cloudflare, add a WAF rule to pass the Authorization header for /wp-json/*. "
                f"Auth error: {results['auth']}",
                "error"
            )
        elif "403" in str(results.get("posts_endpoint", "")):
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
    jobs_ = (WPJob.query
             .filter_by(site_id=site.id)
             .order_by(WPJob.created_at.desc()).limit(50).all()) if site else []

    # Build a map of job_id → social copy from WPLog [SOCIAL] entries
    social_copy = {}
    if site and jobs_:
        job_ids = [j.id for j in jobs_]
        logs = WPLog.query.filter(
            WPLog.site_id == site.id,
            WPLog.job_id.in_(job_ids),
            WPLog.message.like("[SOCIAL]%"),
        ).all()
        for log in logs:
            social_copy[log.job_id] = log.message[len("[SOCIAL]"):].strip()

    return render_template("wp/publisher.html", site=site, jobs=jobs_, social_copy=social_copy)

# GET legacy "compose" just points at /new
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

# ---------- approval inbox ----------

@wp_bp.route("/approvals", methods=["GET"], endpoint="approvals")
@login_required
def approvals():
    """In-app approval queue for AI-generated and human-drafted posts awaiting review."""
    site = _current_site()
    if not site:
        return render_template("wp/approvals.html", pending=[])
    pending_jobs = (WPJob.query
                    .filter_by(site_id=site.id, status="queued")
                    .order_by(WPJob.created_at.desc())
                    .limit(200).all())
    # Filter in Python — JSON field querying is dialect-dependent
    pending = [j for j in pending_jobs if (j.payload or {}).get("needs_approval")]
    return render_template("wp/approvals.html", pending=pending)


@wp_bp.route("/approvals/<int:job_id>/approve", methods=["POST"], endpoint="approval_approve")
@login_required
def approval_approve(job_id: int):
    site = _current_site()
    job = WPJob.query.get_or_404(job_id)
    if not site or job.site_id != site.id:
        abort(403)
    p = dict(job.payload or {})
    p["needs_approval"] = False
    p["status"] = "future" if p.get("status") == "future" else "publish"
    job.payload = p
    db.session.commit()
    flash(f"Job #{job_id} approved — will publish on next cron tick.", "success")
    return see_other("wp_bp.approvals")


@wp_bp.route("/approvals/<int:job_id>/reject", methods=["POST"], endpoint="approval_reject")
@login_required
def approval_reject(job_id: int):
    site = _current_site()
    job = WPJob.query.get_or_404(job_id)
    if not site or job.site_id != site.id:
        abort(403)
    job.status = "error"
    job.last_error = "Rejected in approval inbox"
    db.session.commit()
    flash(f"Job #{job_id} rejected and removed from queue.", "info")
    return see_other("wp_bp.approvals")


@wp_bp.route("/approvals/bulk", methods=["POST"], endpoint="approval_bulk")
@login_required
def approval_bulk():
    site = _current_site()
    if not site:
        abort(403)
    action = request.form.get("bulk_action")  # "approve" or "reject"
    job_ids = request.form.getlist("job_ids")
    if not job_ids or action not in ("approve", "reject"):
        flash("No jobs selected.", "warning")
        return see_other("wp_bp.approvals")

    count = 0
    for jid in job_ids:
        try:
            job = WPJob.query.get(int(jid))
            if not job or job.site_id != site.id:
                continue
            if action == "approve":
                p = dict(job.payload or {})
                p["needs_approval"] = False
                p["status"] = "future" if p.get("status") == "future" else "publish"
                job.payload = p
            else:
                job.status = "error"
                job.last_error = "Bulk rejected"
            count += 1
        except Exception:
            pass
    db.session.commit()
    flash(f"{'Approved' if action == 'approve' else 'Rejected'} {count} post(s).", "success")
    return see_other("wp_bp.approvals")


@wp_bp.route("/content-queue", methods=["GET", "POST"], endpoint="content_queue_review")
@login_required
def content_queue_review():
    """Review pending topic cluster recommendations and selectively queue posts."""
    site = _current_site()
    aid = _account_id()
    recommendations = []
    last_updated = None
    queued_keywords = set()

    if aid:
        try:
            from app.models_seo import SEOScanResult
            rec_row = SEOScanResult.latest(aid, "content_recommendations")
            if rec_row and rec_row.data:
                recommendations = rec_row.data.get("recommendations") or []
                last_updated = rec_row.created_at
        except Exception:
            pass

    if site:
        existing = WPJob.query.filter(
            WPJob.site_id == site.id,
            WPJob.status.in_(["queued", "running", "done"]),
            WPJob.kind == "ai_generate",
        ).all()
        queued_keywords = {(j.payload or {}).get("primary_keyword", "").lower().strip() for j in existing}

    if request.method == "POST" and site:
        selected = request.form.getlist("topics")
        cluster_map = {}
        for rec in recommendations:
            cluster_map[rec.get("cluster_name", "")] = rec
        queued = 0
        for topic_str in selected:
            # topic_str = "cluster_name|||topic_title|||is_pillar"
            parts = topic_str.split("|||")
            if len(parts) < 2:
                continue
            cluster_name, kw = parts[0], parts[1]
            is_pillar = parts[2] == "1" if len(parts) > 2 else False
            if kw.lower() in queued_keywords:
                continue
            rec = cluster_map.get(cluster_name, {})
            all_topics = []
            if rec.get("pillar_topic"):
                all_topics.append(rec["pillar_topic"])
            all_topics += [t if isinstance(t, str) else t.get("title", "") for t in (rec.get("supporting_topics") or [])]
            payload = {
                "primary_keyword": kw,
                "cluster_name": cluster_name,
                "is_pillar": is_pillar,
                "supporting_context": (
                    f"Part of the '{cluster_name}' topic cluster. "
                    f"Related topics: {', '.join(t for t in all_topics if t != kw)}"
                ),
                "word_count": "1200" if is_pillar else "800",
                "status": "draft" if getattr(site, "autopilot_require_approval", True) else "publish",
                "needs_approval": bool(getattr(site, "autopilot_require_approval", True)),
                "require_approval": bool(getattr(site, "autopilot_require_approval", True)),
                "source": "manual_queue",
            }
            job = WPJob(site_id=site.id, kind="ai_generate", payload=payload)
            db.session.add(job)
            queued_keywords.add(kw.lower())
            queued += 1
        db.session.commit()
        if queued:
            flash(f"Queued {queued} post(s) for generation.", "success")
        return see_other("wp_bp.content_queue_review")

    return render_template(
        "wp/content_queue_review.html",
        site=site,
        recommendations=recommendations,
        last_updated=last_updated,
        queued_keywords=queued_keywords,
    )


# ---------- schedule view ----------

@wp_bp.route("/schedule", methods=["GET"], endpoint="schedule")
@login_required
def schedule():
    """Timeline view of scheduled and recently published posts."""
    now = datetime.utcnow()
    site = _current_site()
    site_id = site.id if site else None

    scheduled = (WPJob.query
                 .filter(WPJob.site_id == site_id,
                         WPJob.status == "queued",
                         WPJob.run_at != None)  # noqa: E711
                 .order_by(WPJob.run_at.asc())
                 .all()) if site_id else []

    # Queued without run_at (publish ASAP)
    asap = (WPJob.query
            .filter(WPJob.site_id == site_id,
                    WPJob.status == "queued",
                    WPJob.run_at == None)  # noqa: E711
            .filter(WPJob.kind.in_(["publish", "ai_generate"]))
            .order_by(WPJob.created_at.asc())
            .limit(20).all()) if site_id else []

    # Pending approval — these are scheduled but blocked
    pending_approval = [j for j in asap if (j.payload or {}).get("needs_approval")]
    asap_ready = [j for j in asap if not (j.payload or {}).get("needs_approval")]

    recently_published = (WPJob.query
                          .filter(WPJob.site_id == site_id,
                                  WPJob.status == "done",
                                  WPJob.kind.in_(["publish", "ai_generate"]))
                          .order_by(WPJob.updated_at.desc())
                          .limit(10).all()) if site_id else []

    return render_template(
        "wp/schedule.html",
        scheduled=scheduled,
        asap_ready=asap_ready,
        pending_approval=pending_approval,
        recently_published=recently_published,
        now=now,
    )


# ---------- insights ----------

@wp_bp.route("/insights", methods=["GET"], endpoint="insights")
@login_required
def insights():
    site = _current_site()
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=90)
    jobs = (WPJob.query
            .filter(
                WPJob.site_id == site.id,
                (WPJob.status != "error") | (WPJob.created_at >= cutoff),
            )
            .order_by(WPJob.created_at.desc())
            .limit(50).all()) if site else []

    # Fetch live published posts from the connected WP site
    live_posts = []
    if site and site.id:
        try:
            c = WPClient(site.base_url, site.username, site.app_password)
            raw = c.list_posts(per_page=10, status="publish")
            live_posts = [
                {
                    "id": p.get("id"),
                    "title": (p.get("title") or {}).get("rendered") or f"Post {p.get('id')}",
                    "link": p.get("link", ""),
                    "date": p.get("date", "")[:10],
                    "modified": p.get("modified", "")[:10],
                }
                for p in (raw or []) if p.get("link")
            ]
        except Exception:
            pass

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
    aid = None
    try:
        from app.seo.monitor import get_unread_alerts
        aid = _account_id()
        if aid:
            seo_alerts = get_unread_alerts(account_id=aid, limit=3)
            seo_unread = len([a for a in seo_alerts if not a.is_read])
    except Exception:
        pass

    autopilot_stats = {}
    if site:
        from datetime import timedelta
        week_ago = datetime.utcnow() - timedelta(days=7)
        queued_count = WPJob.query.filter(
            WPJob.site_id == site.id, WPJob.status == "queued",
            WPJob.kind.in_(["publish", "ai_generate"])
        ).count()
        done_this_week = WPJob.query.filter(
            WPJob.site_id == site.id, WPJob.status == "done",
            WPJob.kind.in_(["publish", "ai_generate"]),
            WPJob.updated_at >= week_ago
        ).count()
        pending_jobs = WPJob.query.filter(
            WPJob.site_id == site.id, WPJob.status == "queued"
        ).all()
        pending_approval_count = sum(1 for j in pending_jobs if (j.payload or {}).get("needs_approval"))
        autopilot_stats = {
            "enabled": bool(getattr(site, "autopilot_enabled", False)),
            "daily_new": getattr(site, "autopilot_daily_new", 1),
            "require_approval": bool(getattr(site, "autopilot_require_approval", True)),
            "queued_count": queued_count,
            "done_this_week": done_this_week,
            "pending_approval_count": pending_approval_count,
        }

    post_gsc = {}
    if live_posts and aid:
        try:
            from app.seo.keyword_gaps import _gsc_fetch, _rows_to_dicts, _date_range
            from app.google import _is_connected, _get_gsc_selected_site
            if _is_connected(aid, "gsc"):
                gsc_site_url = _get_gsc_selected_site(aid)
                if gsc_site_url:
                    start, end = _date_range(28)
                    rows = _gsc_fetch(aid, gsc_site_url, start, end, dimensions=["page"], row_limit=500)
                    for row in (rows or []):
                        url = (row.get("keys") or [""])[0]
                        for lp in live_posts:
                            if lp["link"] and (lp["link"].rstrip("/") == url.rstrip("/") or url in lp["link"]):
                                post_gsc[lp["link"]] = {
                                    "clicks": row.get("clicks", 0),
                                    "impressions": row.get("impressions", 0),
                                    "position": round(row.get("position", 0), 1),
                                    "ctr": round(row.get("ctr", 0) * 100, 1),
                                }
        except Exception:
            pass

    return render_template("wp/insights.html", jobs=jobs, ga=ga, gsc=gsc,
                           seo_alerts=seo_alerts, seo_unread=seo_unread,
                           site=site, live_posts=live_posts,
                           autopilot_stats=autopilot_stats, post_gsc=post_gsc,
                           aid=aid)

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

    all_sites = WPSite.query.all()
    total_processed = 0
    queue_errors = []
    for _site in all_sites:
        r = _process_queue(max_jobs=max_jobs, site=_site)
        total_processed += r.get("processed", 0)
        if r.get("error"):
            queue_errors.append(r["error"])
    result = {"ok": True, "processed": total_processed, "errors": queue_errors}

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

    # Hook SEO auto-fix — audits top GSC pages and queues seo_fix jobs (7-day throttle per URL)
    seo_fix_results = []
    try:
        sites = WPSite.query.all()
        for site in sites:
            if site.account_id:
                r = _auto_audit_and_fix(site, site.account_id)
                seo_fix_results.append({"site": site.base_url, **r})
    except Exception as exc:
        current_app.logger.exception("SEO auto-fix hook failed in cron_runner")
        seo_fix_results = [{"error": str(exc)}]

    return jsonify({"ran_at": ran_at, **result,
                    "seo_monitor": seo_monitor_results,
                    "seo_auto_fix": seo_fix_results}), 200

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
    site = _current_site()
    result = None

    # Fetch published posts AND pages for the dropdown (best-effort)
    wp_posts = []
    if site:
        try:
            c = WPClient(site.base_url, site.username, site.app_password)

            def _to_item(p, kind):
                title = (p.get("title") or {}).get("rendered") or f"{kind.title()} {p.get('id')}"
                return {"id": p.get("id"), "title": title, "link": p.get("link", ""), "kind": kind}

            posts = [_to_item(p, "post") for p in (c.list_posts(per_page=100, status="publish") or []) if p.get("link")]
            pages = [_to_item(p, "page") for p in (c.list_pages(per_page=100) or []) if p.get("link")]
            # Group: pages first (usually higher SEO value), then posts
            wp_posts = pages + posts
        except Exception:
            current_app.logger.debug("seo_audit: could not fetch WP posts/pages for dropdown")

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
    return render_template("wp/seo_audit.html", result=result, site=site, wp_posts=wp_posts)


@wp_bp.route("/seo-audit/ai-review", methods=["GET", "POST"], endpoint="seo_audit_review")
@login_required
def seo_audit_review():
    """
    AI-powered SEO audit quality gate.
    Runs the standard audit then passes every finding through Claude to:
    - Validate it's a genuine issue (not a false positive)
    - Add evidence and confidence score
    - Generate a developer-ready ticket with exact fix instructions
    Paid users only.
    """
    if not is_paid_account():
        flash("AI Audit Review is available on paid plans.", "warning")
        return redirect(url_for("main_bp.pricing"))

    result = None
    url_checked = None

    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        keyword = (request.form.get("keyword") or "").strip()
        if not url:
            flash("URL is required.", "error")
            return render_template("wp/seo_audit_review.html", result=None, site=_current_site())

        url_checked = url
        try:
            from app.wp.seo_audit import audit_url
            raw = audit_url(url, keyword)
            if raw.get("error"):
                flash(raw["error"], "error")
                return render_template("wp/seo_audit_review.html", result=None, site=_current_site())

            issues = raw.get("issues") or []
            if not issues:
                flash("No issues found — nothing to review.", "info")
                return render_template("wp/seo_audit_review.html", result=raw, site=_current_site(),
                                       url_checked=url_checked)

            # Build prompt for AI reviewer
            issue_lines = []
            for i, iss in enumerate(issues[:20], 1):
                issue_lines.append(
                    f"{i}. [{iss.get('severity','?').upper()}] {iss.get('issue','')}: {iss.get('detail','')}"
                )

            prompt = f"""You are a senior SEO engineer reviewing automated audit findings for: {url}
{"Target keyword: " + keyword if keyword else ""}

Audit findings to validate:
{chr(10).join(issue_lines)}

For each finding, apply the "Google engineer test": would a Google engineer confirm this is a genuine, correctly-diagnosed SEO problem?

Return a JSON array with one object per finding (same order), each with:
- finding_number: int (1-based)
- valid: true | false
- confidence: "high" | "medium" | "low"
- false_positive_reason: string or null (why it might not be a real issue)
- evidence: string (what to look for to confirm the issue)
- priority: "critical" | "high" | "medium" | "low"
- dev_ticket: string (exact developer-ready instruction: what file/element to change, what to change it to)
- estimated_impact: string (brief description of ranking/UX benefit if fixed)"""

            from app.ai_clients import get_ai_client
            import json as _json, re as _re
            client = get_ai_client()
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_text = response.content[0].text
            match = _re.search(r'\[.*\]', raw_text, _re.DOTALL)
            reviews = _json.loads(match.group()) if match else []

            # Merge reviews back onto issues
            review_map = {r.get("finding_number"): r for r in reviews}
            reviewed_issues = []
            for i, iss in enumerate(issues[:20], 1):
                review = review_map.get(i, {})
                reviewed_issues.append({**iss, "review": review})

            result = {
                **raw,
                "reviewed_issues": reviewed_issues,
                "valid_count":   sum(1 for r in reviews if r.get("valid")),
                "invalid_count": sum(1 for r in reviews if not r.get("valid")),
                "critical_count": sum(1 for r in reviews if r.get("priority") == "critical" and r.get("valid")),
            }
            flash(f"AI review complete — {result['valid_count']} confirmed issues, "
                  f"{result['invalid_count']} possible false positives.", "success")

        except Exception as exc:
            current_app.logger.exception("SEO AI audit review failed")
            flash(f"Review failed: {exc}", "error")

    return render_template(
        "wp/seo_audit_review.html",
        result=result,
        site=_current_site(),
        url_checked=url_checked,
    )


@wp_bp.route("/internal-links", methods=["GET", "POST"], endpoint="internal_links")
@login_required
def internal_links():
    """Find and insert internal link opportunities for a WordPress post."""
    import html as _html_mod
    site = _current_site()
    posts: List[Dict] = []
    suggestions: List[Dict] = []
    source_post: Optional[Dict] = None
    error = None

    if site:
        try:
            c = WPClient(site.base_url, site.username, site.app_password)
            posts = c.list_posts(per_page=100, status="publish")
        except Exception as exc:
            error = str(exc)

    if request.method == "POST":
        action  = (request.form.get("action") or "suggest").strip()
        post_id = int(request.form.get("post_id") or 0)

        if not site:
            flash("Connect a WordPress site first.", "error")
            return see_other("wp_bp.settings")
        if not post_id:
            flash("Select a post.", "error")
            return render_template("wp/internal_links.html",
                                   site=site, posts=posts, suggestions=[], source_post=None, error=error)
        try:
            c = WPClient(site.base_url, site.username, site.app_password)
            source_post = c.get_post(post_id)
            source_html  = source_post.get("content", {}).get("rendered", "")
            source_title = _html_mod.unescape(source_post.get("title", {}).get("rendered", "") or "")

            from app.wp.internal_links import find_link_opportunities, insert_links
            suggestions = find_link_opportunities(post_id, source_html, source_title, posts)

            if action == "apply" and suggestions:
                selected_indices = [int(i) for i in request.form.getlist("link_idx") if i.isdigit()]
                chosen = [suggestions[i] for i in selected_indices if i < len(suggestions)]

                if not chosen:
                    flash("Select at least one link to insert.", "warning")
                else:
                    new_html, count = insert_links(source_html, chosen)
                    if count:
                        payload = {
                            "post_id":        post_id,
                            "title":          source_title,
                            "html":           new_html,
                            "status":         source_post.get("status", "publish"),
                            "source":         "internal_links",
                            "links_inserted": count,
                        }
                        job = WPJob(site_id=site.id, kind="edit", payload=payload)
                        db.session.add(job)
                        db.session.commit()
                        flash(f"Queued {count} internal link{'s' if count != 1 else ''} "
                              f"for post #{post_id} (Job #{job.id}).", "success")
                        return see_other("wp_bp.edits")
                    else:
                        flash("Anchor text not found verbatim in post content. "
                              "Try editing the anchor text manually.", "warning")
        except Exception as exc:
            current_app.logger.exception("Internal links failed")
            error = str(exc)

    return render_template("wp/internal_links.html",
                           site=site, posts=posts, suggestions=suggestions,
                           source_post=source_post, error=error)


@wp_bp.route("/content-brief", methods=["GET", "POST"], endpoint="content_brief")
@login_required
def content_brief():
    """Generate a comprehensive content brief from a keyword + GSC data."""
    if not is_paid_account():
        flash("Content briefs are available on paid plans.", "warning")
        return redirect(url_for("main_bp.pricing"))

    brief = None
    keyword = ""
    error = None

    if request.method == "POST":
        keyword = (request.form.get("keyword") or "").strip()
        if not keyword:
            flash("Keyword is required.", "error")
            return render_template("wp/content_brief.html", brief=None, keyword="", error=None)

        try:
            aid = _account_id()
            gsc_data: Dict[str, Any] = {}
            related_queries: List[str] = []

            # Pull GSC data for this keyword
            try:
                from app.google import _is_connected, _get_gsc_selected_site
                from app.seo.keyword_gaps import _gsc_fetch, _rows_to_dicts, _date_range
                if aid and _is_connected(aid, "gsc"):
                    site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE", "")
                    if site_url:
                        end, start = _date_range(3, 30)
                        rows = _gsc_fetch(aid, site_url, start, end, ["query"], row_limit=200)
                        all_q = _rows_to_dicts(rows, ["query"])
                        for q in all_q:
                            if keyword.lower() in q.get("query", "").lower():
                                gsc_data = q
                            elif any(w in q.get("query", "").lower()
                                     for w in keyword.lower().split()):
                                related_queries.append(q.get("query", ""))
                        related_queries = related_queries[:10]
            except Exception:
                pass

            pos_text = (f"currently ranking at position {round(gsc_data.get('position', 0), 1)}, "
                        f"{int(gsc_data.get('impressions', 0))} impressions/month, "
                        f"{int(gsc_data.get('clicks', 0))} clicks/month"
                        if gsc_data else "no current ranking data")

            prompt = f"""You are an expert SEO content strategist for local service businesses (HVAC, plumbing, electrical, roofing, landscaping).

Target keyword: "{keyword}"
GSC data: {pos_text}
Related queries from GSC: {', '.join(related_queries) if related_queries else 'none available'}

Generate a comprehensive content brief as a JSON object with exactly these keys:
- recommended_title: SEO-optimized title (55-60 chars)
- meta_description: compelling meta description (145-155 chars)
- word_count_target: recommended word count as integer
- h1: the exact H1 heading
- outline: array of strings like ["H2: Section Name", "H3: Sub-section", ...]
- semantic_terms: array of 12-15 semantically related terms to include naturally
- questions_to_answer: array of 6-8 questions this post must answer
- schema_types: array of schema markup types to include
- tone: recommended tone (one of: informational, commercial, local, how-to)
- cta: recommended call-to-action text
- positioning: 2-sentence description of the content angle and why it will rank
- estimated_difficulty: easy | medium | hard"""

            from app.ai_clients import get_ai_client
            import json as _json, re as _re
            client = get_ai_client()
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
            match = _re.search(r'\{.*\}', raw, _re.DOTALL)
            if match:
                brief = _json.loads(match.group())
                brief["keyword"] = keyword
                brief["gsc_data"] = gsc_data

                # Enrich with AI-generated competitor content guidance
                try:
                    from app.ai_clients import get_ai_client
                    _client = get_ai_client()
                    _enrich_prompt = (
                        f"You are an SEO content strategist. For the keyword '{keyword}', "
                        f"describe what content the top-ranking pages typically include "
                        f"(headings, subtopics, word count, content format, key entities to mention). "
                        f"Return a JSON object with: "
                        f"typical_word_count (int), "
                        f"recommended_headings (list of 5-8 H2 titles), "
                        f"key_entities (list of 5-10 important terms to mention), "
                        f"content_format (e.g. 'how-to guide', 'listicle', 'comparison'), "
                        f"unique_angle (1-sentence suggestion for differentiation). "
                        f"JSON only."
                    )
                    _resp = _client.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=600,
                        messages=[{"role": "user", "content": _enrich_prompt}],
                    )
                    import re as _re2, json as _json2
                    _raw = _resp.content[0].text.strip()
                    _raw = _re2.sub(r'^```(?:json)?\s*', '', _raw, flags=_re2.MULTILINE)
                    _raw = _re2.sub(r'\s*```$', '', _raw, flags=_re2.MULTILINE)
                    _enrichment = _json2.loads(_raw)
                    if brief and isinstance(brief, dict):
                        brief["serp_enrichment"] = _enrichment
                except Exception:
                    pass
            else:
                error = "Could not parse AI response. Please try again."

        except Exception as exc:
            current_app.logger.exception("Content brief generation failed")
            error = f"Brief generation failed: {exc}"

    return render_template("wp/content_brief.html", brief=brief, keyword=keyword, error=error)


@wp_bp.route("/seo-audit/apply-fixes", methods=["POST"], endpoint="seo_apply_fixes")
@login_required
def seo_apply_fixes():
    """
    Run SEO/AEO audit on a URL, generate schema, and queue an seo_fix job
    to apply implementable fixes directly to the WordPress post.
    """
    site = _current_site()
    if not site:
        flash("Connect a WordPress site first.", "error")
        return see_other("wp_bp.seo_audit")

    url     = (request.form.get("url")     or "").strip()
    keyword = (request.form.get("keyword") or "").strip()

    if not url:
        flash("URL is required.", "error")
        return see_other("wp_bp.seo_audit")

    payload = _build_seo_fix_payload(site, url, keyword=keyword, source="manual")

    if payload is None:
        # Could not find post or no fixes to apply — re-run audit to show user
        flash("Could not match that URL to a WordPress post, or no fixable issues found. "
              "Make sure the URL belongs to your connected WP site.", "warning")
        return see_other("wp_bp.seo_audit")

    job = WPJob(site_id=site.id, kind="seo_fix", payload=payload)
    db.session.add(job)
    db.session.commit()

    fixes = []
    if payload.get("schema_html"):  fixes.append("JSON-LD schema")
    if payload.get("yoast_desc"):   fixes.append("Yoast meta description")

    flash(
        f"SEO fix queued for post #{payload['post_id']} "
        f"(Job #{job.id}) — will apply: {', '.join(fixes) or 'available fixes'}.",
        "success",
    )
    return see_other("wp_bp.edits")


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
def edit_lookup():
    """Browse / search WordPress posts to select one for editing."""
    site = _current_site()
    posts = []
    search = request.args.get("search", "").strip()
    error = None
    if site:
        try:
            c = WPClient(site.base_url, site.username, site.app_password)
            posts = c.list_posts(per_page=20, search=search, status="any")
        except Exception as exc:
            error = str(exc)
    return render_template("wp/edit_lookup.html",
                           site=site, posts=posts, search=search, error=error)


@wp_bp.route("/edit/<int:post_id>", methods=["GET"], endpoint="edit_post")
@login_required
def edit_post(post_id: int):
    """Load a live WP post into the editor."""
    site = _current_site()
    if not site:
        flash("Configure WordPress first.", "error")
        return see_other("wp_bp.settings")
    try:
        c = WPClient(site.base_url, site.username, site.app_password)
        post = c.get_post(post_id)
    except Exception as exc:
        flash(f"Could not load post #{post_id}: {exc}", "error")
        return see_other("wp_bp.edit_lookup")

    import html as _html
    raw_title   = post.get("title",   {}).get("rendered", "")
    raw_content = post.get("content", {}).get("rendered", "")
    raw_excerpt = post.get("excerpt", {}).get("rendered", "")
    # Strip outer <p> wrapping excerpt WP sometimes adds
    import re as _re
    raw_excerpt = _re.sub(r"^\s*<p>(.*?)</p>\s*$", r"\1", raw_excerpt, flags=_re.DOTALL).strip()

    return render_template(
        "wp/edit_post.html",
        post_id=post_id,
        title=_html.unescape(raw_title),
        html=raw_content,
        excerpt=raw_excerpt,
        status=post.get("status", "publish"),
        post_link=post.get("link", ""),
    )


@wp_bp.route("/edit/<int:post_id>/submit", methods=["POST"], endpoint="edit_post_submit")
@login_required
def edit_post_submit(post_id: int):
    """Queue an edit job for an existing WP post."""
    site = _current_site()
    if not site:
        flash("Configure WordPress first.", "error")
        return see_other("wp_bp.settings")

    title      = (request.form.get("title")      or "").strip()
    html_body  = (request.form.get("html")        or "").strip()
    excerpt    = (request.form.get("excerpt")     or "").strip()
    yoast_desc = (request.form.get("yoast_desc")  or "").strip()
    status     = (request.form.get("status")      or "publish").strip()
    needs_approval = bool(request.form.get("needs_approval"))

    if not title:
        flash("Title is required.", "error")
        return see_other("wp_bp.edit_post", post_id=post_id)

    if needs_approval:
        status = "draft"

    try:
        existing_post = WPClient(site.base_url, site.username, site.app_password).get_post(post_id)
    except Exception:
        existing_post = {}

    payload = {
        "post_id":        post_id,
        "title":          title,
        "html":           html_body,
        "excerpt":        excerpt,
        "yoast_desc":     yoast_desc,
        "status":         status,
        "needs_approval": needs_approval,
        "before_title":   (existing_post.get("title") or {}).get("rendered", ""),
        "before_excerpt": (existing_post.get("excerpt") or {}).get("rendered", ""),
    }
    job = WPJob(site_id=site.id, kind="edit", payload=payload)
    db.session.add(job)
    db.session.commit()
    flash(f"Edit queued for post #{post_id} (Job #{job.id}).", "success")
    return see_other("wp_bp.edits")


@wp_bp.route("/edits", methods=["GET"], endpoint="edits")
@login_required
def edits():
    """Dashboard of all pending / completed edit and refresh jobs."""
    site = _current_site()
    status_filter = request.args.get("status", "").strip()
    EDIT_KINDS = ["edit", "refresh", "seo_fix"]

    if not site:
        return render_template("wp/edits.html",
                               jobs=[], counts={s: 0 for s in ("queued", "running", "done", "error")},
                               status_filter=status_filter)

    q = WPJob.query.filter(WPJob.site_id == site.id, WPJob.kind.in_(EDIT_KINDS))
    if status_filter:
        q = q.filter_by(status=status_filter)
    jobs = q.order_by(WPJob.created_at.desc()).limit(200).all()

    counts: Dict[str, int] = {}
    for s in ("queued", "running", "done", "error"):
        counts[s] = WPJob.query.filter(
            WPJob.site_id == site.id,
            WPJob.kind.in_(EDIT_KINDS),
            WPJob.status == s,
        ).count()

    return render_template("wp/edits.html",
                           jobs=jobs, counts=counts, status_filter=status_filter)

@wp_bp.route("/freshness", methods=["GET"], endpoint="freshness")
@login_required
def freshness():
    """Content Freshness Dashboard — ranks posts by staleness + traffic decay."""
    aid = _account_id()
    site = _current_site()
    posts = []
    error = None

    if site:
        try:
            from app.wp.wp_client import WPClient
            c = WPClient(site.base_url, site.username, site.app_password)
            raw = c.list_posts(per_page=50, status="publish")

            # Build a map of declining pages from GSC if available
            declining_map: dict = {}
            try:
                from app.google import _is_connected, _get_gsc_selected_site
                from app.seo.keyword_gaps import run_keyword_gap_analysis
                import os
                if aid and _is_connected(aid, "gsc"):
                    gsc_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE", "")
                    if gsc_url:
                        gap = run_keyword_gap_analysis(aid, gsc_url)
                        for dp in (gap.get("declining_pages") or []):
                            pg = dp.get("page", "").rstrip("/")
                            declining_map[pg] = dp.get("change_pct", 0)
            except Exception:
                pass

            from datetime import datetime, timezone
            import re as _re
            now = datetime.now(timezone.utc)

            for p in raw:
                modified_str = p.get("modified_gmt") or p.get("modified", "")
                try:
                    modified = datetime.fromisoformat(
                        modified_str.replace("Z", "+00:00") if modified_str else ""
                    )
                    if modified.tzinfo is None:
                        modified = modified.replace(tzinfo=timezone.utc)
                    days_old = (now - modified).days
                except Exception:
                    days_old = 0

                post_url = (p.get("link") or "").rstrip("/")
                traffic_change = declining_map.get(post_url)

                # Staleness score: 0-100 (higher = staler)
                age_score = min(days_old / 365 * 50, 50)
                decay_score = min(abs(traffic_change) / 2, 50) if traffic_change and traffic_change < 0 else 0
                staleness = round(age_score + decay_score)

                posts.append({
                    "id":             p.get("id"),
                    "title":          _re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", "")),
                    "url":            post_url,
                    "days_old":       days_old,
                    "modified":       modified_str[:10] if modified_str else "—",
                    "traffic_change": round(traffic_change, 1) if traffic_change is not None else None,
                    "staleness":      staleness,
                })

            posts.sort(key=lambda x: x["staleness"], reverse=True)
        except Exception as exc:
            logger.exception("Freshness dashboard failed")
            error = f"Could not load posts: {exc}"

    return render_template(
        "wp/freshness.html",
        site=site,
        posts=posts,
        error=error,
    )


@wp_bp.route("/freshness/ai-plan", methods=["POST"], endpoint="freshness_ai_plan")
@login_required
def freshness_ai_plan():
    """Generate an AI-powered content refresh plan for stale posts."""
    import json as _json
    import re as _re
    try:
        data = request.get_json(force=True) or {}
        posts = data.get("posts", [])

        # Sort by staleness descending and take top 10
        top_posts = sorted(posts, key=lambda p: p.get("staleness", 0), reverse=True)[:10]

        post_lines = "\n".join(
            f"{i+1}. \"{p.get('title','')}\" — URL: {p.get('url','')} | "
            f"Days old: {p.get('days_old',0)} | Staleness score: {p.get('staleness',0)} | "
            f"Traffic change: {p.get('traffic_change') if p.get('traffic_change') is not None else 'N/A'}%"
            for i, p in enumerate(top_posts)
        )

        prompt = f"""You are a content strategist helping prioritise a content refresh plan for a WordPress site.

Here are the top stale posts ranked by staleness score (higher = more urgent):

{post_lines}

Return a JSON array of recommendation objects — one per post above — with EXACTLY this structure:
[
  {{
    "title": "post title",
    "url": "post url",
    "priority": <integer 1-10, 10 = most urgent>,
    "action": "<one of: refresh | rewrite | consolidate | redirect>",
    "reason": "<1-2 sentence explanation of why this action is recommended>",
    "specific_changes": ["bullet 1", "bullet 2", "bullet 3"]
  }},
  ...
]

Rules:
- priority should reflect how urgently the post needs attention (consider staleness + traffic decay together)
- action meanings: refresh=update stats/links/copy; rewrite=full new content; consolidate=merge with another post; redirect=remove and redirect traffic
- specific_changes must contain 2-3 concrete, actionable bullet points
- Return ONLY the JSON array, no prose before or after."""

        from app.ai_clients import get_ai_client
        client = get_ai_client()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        match = _re.search(r'\[.*\]', raw, _re.DOTALL)
        if not match:
            return jsonify({"error": "Could not parse AI response. Please try again."})
        recommendations = _json.loads(match.group())
        return jsonify({"recommendations": recommendations})

    except Exception as exc:
        logger.exception("AI freshness plan failed")
        return jsonify({"error": f"AI plan generation failed: {exc}"})


@wp_bp.route("/broken-links", methods=["GET", "POST"], endpoint="broken_links")
@login_required
def broken_links():
    """Scan published posts for broken links."""
    site = _current_site()
    report = None
    error = None
    scanning = False

    if request.method == "POST" and site:
        scanning = True
        try:
            from app.wp.wp_client import WPClient
            from app.wp.broken_links import scan_broken_links
            c = WPClient(site.base_url, site.username, site.app_password)
            raw = c.list_posts(per_page=30, status="publish")
            report = scan_broken_links(raw, site.base_url)
            if report and site:
                try:
                    from app.models_seo import SEOScanResult
                    SEOScanResult.save_result(
                        account_id=_account_id(), site_id=site.id,
                        scan_type="broken_links",
                        issue_count=report.get("broken_count", 0),
                        item_count=report.get("total_links_checked"),
                        data={
                            "broken_count": report.get("broken_count"),
                            "total_links_checked": report.get("total_links_checked"),
                            "broken": report.get("broken", [])[:30],
                        },
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.exception("Broken link scan failed")
            error = f"Scan failed: {exc}"

    return render_template(
        "wp/broken_links.html",
        site=site,
        report=report,
        error=error,
        scanning=scanning,
    )


@wp_bp.route("/bulk-meta", methods=["GET", "POST"], endpoint="bulk_meta")
@login_required
def bulk_meta():
    """Bulk meta editor — update titles and meta descriptions across multiple posts."""
    site = _current_site()
    posts = []
    error = None
    saved_count = 0

    if site:
        try:
            from app.wp.wp_client import WPClient
            import re as _re
            c = WPClient(site.base_url, site.username, site.app_password)

            if request.method == "POST":
                action = request.form.get("action", "save")

                if action == "ai_generate":
                    # Generate AI title + meta for selected posts
                    selected_ids = request.form.getlist("selected_ids")
                    if not selected_ids:
                        flash("Select at least one post to generate meta for.", "warning")
                        return redirect(url_for("wp_bp.bulk_meta"))

                    raw = c.list_posts(per_page=100, status="publish")
                    sel_set = set(int(i) for i in selected_ids)
                    to_generate = [p for p in raw if p.get("id") in sel_set]

                    from app.ai_clients import get_ai_client
                    import json as _json, re as _re2
                    ai_client = get_ai_client()

                    generated = {}
                    for p in to_generate[:10]:
                        pid = p.get("id")
                        title_raw = _re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", ""))
                        snippet = _re.sub(r"<[^>]+>", " ", p.get("excerpt", {}).get("rendered", "") or "")[:300]
                        prompt = (
                            f"Write an SEO-optimised title tag (50-60 chars) and meta description (145-155 chars) "
                            f"for this blog post.\n\nCurrent title: {title_raw}\nContent excerpt: {snippet}\n\n"
                            f"Return JSON with keys: title, meta_description"
                        )
                        try:
                            resp = ai_client.messages.create(
                                model="claude-haiku-4-5-20251001",
                                max_tokens=300,
                                messages=[{"role": "user", "content": prompt}],
                            )
                            m = _re2.search(r'\{.*\}', resp.content[0].text, _re2.DOTALL)
                            if m:
                                data = _json.loads(m.group())
                                generated[pid] = data
                        except Exception:
                            pass

                    # Store generated values in session for pre-fill
                    from flask import session as flask_session
                    flask_session["bulk_meta_generated"] = generated
                    flash(f"Generated meta for {len(generated)} post(s). Review and save below.", "success")
                    return redirect(url_for("wp_bp.bulk_meta"))

                elif action == "save":
                    # Save changed titles and excerpts
                    post_ids = request.form.getlist("post_id")
                    for pid_str in post_ids:
                        try:
                            pid = int(pid_str)
                            new_title = request.form.get(f"title_{pid}", "").strip()
                            new_meta  = request.form.get(f"meta_{pid}", "").strip()
                            if not new_title:
                                continue
                            payload = {"title": new_title}
                            if new_meta:
                                payload["excerpt"] = new_meta
                                payload["meta"] = {"_yoast_wpseo_metadesc": new_meta}
                            c._req("POST", f"/wp/v2/posts/{pid}", json_body=payload)
                            saved_count += 1
                        except Exception:
                            pass
                    flash(f"Saved {saved_count} post(s).", "success" if saved_count else "warning")

            # Load posts for display
            raw = c.list_posts(per_page=50, status="publish")
            from flask import session as flask_session
            generated = flask_session.pop("bulk_meta_generated", {})

            for p in raw:
                pid = p.get("id")
                title = _re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", ""))
                excerpt = _re.sub(r"<[^>]+>", " ", p.get("excerpt", {}).get("rendered", "") or "").strip()
                gen = generated.get(pid) or generated.get(str(pid)) or {}
                posts.append({
                    "id":      pid,
                    "title":   gen.get("title") or title,
                    "meta":    gen.get("meta_description") or excerpt[:160],
                    "url":     p.get("link", ""),
                    "ai_generated": bool(gen),
                })

        except Exception as exc:
            logger.exception("Bulk meta editor failed")
            error = f"Could not load posts: {exc}"

    return render_template(
        "wp/bulk_meta.html",
        site=site,
        posts=posts,
        error=error,
    )


@wp_bp.route("/image-seo", methods=["GET", "POST"], endpoint="image_seo")
@login_required
def image_seo():
    """Image SEO optimizer — audit alt texts across all posts, AI-generate missing ones."""
    site = _current_site()
    posts_data = []
    error = None
    saved_count = 0

    if site:
        try:
            from app.wp.wp_client import WPClient
            import re as _re
            c = WPClient(site.base_url, site.username, site.app_password)

            if request.method == "POST":
                action = request.form.get("action", "")
                if action == "save_alts":
                    # Apply edited alt texts back to post content
                    post_ids = request.form.getlist("post_id")
                    for pid_str in post_ids:
                        try:
                            pid = int(pid_str)
                            post = c.get_post(pid)
                            content = post.get("content", {}).get("raw") or \
                                      post.get("content", {}).get("rendered", "")
                            # Find all img src → new alt mapping
                            changed = False
                            for key, val in request.form.items():
                                if key.startswith(f"alt_{pid}_"):
                                    img_idx = key[len(f"alt_{pid}_"):]
                                    src_key = f"src_{pid}_{img_idx}"
                                    src = request.form.get(src_key, "")
                                    if src and val:
                                        # Replace alt="" or add alt to matching img
                                        pattern = (r'(<img[^>]*src=["\']' +
                                                   _re.escape(src) +
                                                   r'["\'][^>]*)(alt=["\'][^"\']*["\'])?([^>]*>)')
                                        new_tag = rf'\1 alt="{val}"\3'
                                        new_content, n = _re.subn(
                                            pattern, new_tag, content,
                                            flags=_re.IGNORECASE | _re.DOTALL,
                                        )
                                        if n:
                                            content = new_content
                                            changed = True
                            if changed:
                                c._req("POST", f"/wp/v2/posts/{pid}",
                                       json_body={"content": content})
                                saved_count += 1
                        except Exception:
                            pass
                    flash(f"Saved alt texts for {saved_count} post(s).", "success")

                elif action == "ai_generate":
                    # AI-generate alt texts for selected images
                    if not is_paid_account():
                        flash("AI alt text generation is available on paid plans.", "warning")
                        return redirect(url_for("wp_bp.image_seo"))

                    selected = request.form.getlist("selected_img")
                    if selected:
                        from app.ai_clients import get_ai_client
                        ai_client = get_ai_client()
                        import json as _json, re as _re2

                        generated: dict = {}
                        for img_key in selected[:20]:
                            src = request.form.get(f"src_val_{img_key}", img_key)
                            filename = src.split("/")[-1].split("?")[0]
                            post_title = request.form.get(f"post_title_{img_key}", "")
                            context = f'in a blog post titled "{post_title}"' if post_title else "on a website"
                            prompt = (
                                f"Write a concise, descriptive SEO alt text (max 120 characters) "
                                f"for an image {context}. "
                                f"Image filename: {filename}. "
                                f"Alt text should describe what's in the image and be relevant to the page topic. "
                                f"Return only the alt text with no quotes, punctuation at end, or explanation."
                            )
                            try:
                                resp = ai_client.messages.create(
                                    model="claude-haiku-4-5-20251001",
                                    max_tokens=60,
                                    messages=[{"role": "user", "content": prompt}],
                                )
                                generated[img_key] = resp.content[0].text.strip().strip('"\'')
                            except Exception:
                                pass
                        from flask import session as fs
                        fs["img_seo_generated"] = generated
                        flash(f"Generated {len(generated)} alt text(s). Review and save.", "success")
                        return redirect(url_for("wp_bp.image_seo"))

            # Load posts and extract image data
            from flask import session as fs
            generated = fs.pop("img_seo_generated", {})

            raw = c.list_posts(per_page=30, status="publish")
            IMG_RE = _re.compile(
                r'<img([^>]*?)(?:src=["\']([^"\']+)["\'])([^>]*?)(?:alt=["\']([^"\']*)["\'])?([^>]*?)>',
                _re.IGNORECASE | _re.DOTALL,
            )
            for p in raw:
                pid = p.get("id")
                title = _re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", ""))
                content = p.get("content", {}).get("rendered", "") or ""
                images = []
                for idx, m in enumerate(_re.finditer(
                    r'<img[^>]*src=["\']([^"\']+)["\'][^>]*>',
                    content, _re.IGNORECASE,
                )):
                    full_tag = m.group(0)
                    src = m.group(1)
                    alt_m = _re.search(r'alt=["\']([^"\']*)["\']', full_tag, _re.IGNORECASE)
                    alt = alt_m.group(1) if alt_m else None
                    img_key = f"{pid}_{idx}"
                    filename = src.split("/")[-1].split("?")[0]
                    is_decorative = bool(_re.match(r'(icon|logo|bg|background|divider)', filename, _re.I))
                    suggested = generated.get(img_key, "")
                    images.append({
                        "idx":      idx,
                        "src":      src,
                        "filename": filename,
                        "alt":      alt,
                        "missing":  alt is None or alt.strip() == "",
                        "generic":  alt and bool(_re.match(r'(image|img|photo|picture|\d+)', alt.strip(), _re.I)),
                        "key":      img_key,
                        "suggested": suggested,
                        "decorative": is_decorative,
                    })

                if images:
                    missing = sum(1 for i in images if i["missing"] and not i["decorative"])
                    posts_data.append({
                        "id": pid, "title": title,
                        "url": p.get("link", ""),
                        "images": images,
                        "missing_count": missing,
                        "total": len(images),
                    })

            posts_data.sort(key=lambda x: x["missing_count"], reverse=True)

        except Exception as exc:
            logger.exception("Image SEO failed")
            error = f"Could not load posts: {exc}"

    return render_template(
        "wp/image_seo.html",
        site=site,
        posts_data=posts_data,
        error=error,
    )


@wp_bp.route("/content-quality", methods=["GET"], endpoint="content_quality")
@login_required
def content_quality():
    """Thin & duplicate content detector — word counts, duplicate metas, near-duplicate titles."""
    site = _current_site()
    issues = []
    stats = {}
    error = None

    if site:
        try:
            from app.wp.wp_client import WPClient
            import re as _re
            from collections import defaultdict
            c = WPClient(site.base_url, site.username, site.app_password)
            raw = c.list_posts(per_page=100, status="publish")

            titles = []
            metas = defaultdict(list)
            thin_threshold = 300

            total = len(raw)
            thin_count = 0
            no_meta_count = 0

            for p in raw:
                pid = p.get("id")
                title = _re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", ""))
                content_html = p.get("content", {}).get("rendered", "") or ""
                content_text = _re.sub(r"<[^>]+>", " ", content_html)
                word_count = len(content_text.split())
                excerpt = _re.sub(r"<[^>]+>", " ", p.get("excerpt", {}).get("rendered", "") or "").strip()
                url = p.get("link", "")

                titles.append({"id": pid, "title": title, "url": url, "words": word_count})

                # Track duplicate metas
                meta_key = excerpt[:100].lower().strip()
                if meta_key:
                    metas[meta_key].append({"id": pid, "title": title, "url": url})
                else:
                    no_meta_count += 1
                    issues.append({
                        "type": "no_meta",
                        "severity": "warn",
                        "post_id": pid,
                        "title": title,
                        "url": url,
                        "detail": "No meta description / excerpt set.",
                        "fix": "Add a 145-155 character meta description.",
                    })

                if word_count < thin_threshold:
                    thin_count += 1
                    issues.append({
                        "type": "thin",
                        "severity": "fail" if word_count < 150 else "warn",
                        "post_id": pid,
                        "title": title,
                        "url": url,
                        "detail": f"Only {word_count} words — below the {thin_threshold}-word minimum.",
                        "fix": "Expand the content to at least 500 words for better ranking potential.",
                        "words": word_count,
                    })

            # Duplicate meta descriptions
            for meta_key, posts in metas.items():
                if len(posts) > 1:
                    for post in posts:
                        issues.append({
                            "type": "dup_meta",
                            "severity": "warn",
                            "post_id": post["id"],
                            "title": post["title"],
                            "url": post["url"],
                            "detail": f"Same meta description shared by {len(posts)} posts.",
                            "fix": "Write a unique meta description for each post.",
                            "duplicates": [p["title"] for p in posts if p["id"] != post["id"]][:3],
                        })

            # Near-duplicate titles (Jaccard similarity on word tokens)
            def _tokens(t):
                return set(_re.findall(r"[a-z]{3,}", t.lower()))

            for i, a in enumerate(titles):
                for b in titles[i + 1:]:
                    ta, tb = _tokens(a["title"]), _tokens(b["title"])
                    if not ta or not tb:
                        continue
                    jaccard = len(ta & tb) / len(ta | tb)
                    if jaccard >= 0.7:
                        issues.append({
                            "type": "dup_title",
                            "severity": "warn",
                            "post_id": a["id"],
                            "title": a["title"],
                            "url": a["url"],
                            "detail": f"Title is very similar to: \"{b['title']}\" (similarity {round(jaccard*100)}%).",
                            "fix": "Differentiate titles to avoid keyword cannibalization.",
                        })

            stats = {
                "total": total,
                "thin": thin_count,
                "no_meta": no_meta_count,
                "issues": len(issues),
            }

            # Sort: fail first, then warn; within severity by type
            severity_order = {"fail": 0, "warn": 1}
            issues.sort(key=lambda x: severity_order.get(x["severity"], 2))

            if site and issues is not None:
                try:
                    from app.models_seo import SEOScanResult
                    SEOScanResult.save_result(
                        account_id=_account_id(), site_id=site.id,
                        scan_type="content_quality",
                        issue_count=len(issues),
                        item_count=total,
                        data={
                            "stats": stats,
                            "issue_count": len(issues),
                            "total": total,
                            "issues_summary": [
                                {"type": i["type"], "severity": i["severity"],
                                 "url": i.get("url"), "title": i.get("title")}
                                for i in issues[:50]
                            ],
                        },
                    )
                except Exception:
                    pass

        except Exception as exc:
            logger.exception("Content quality check failed")
            error = f"Could not analyse posts: {exc}"

    return render_template(
        "wp/content_quality.html",
        site=site,
        issues=issues,
        stats=stats,
        error=error,
    )


@wp_bp.route("/geo-pages", methods=["GET", "POST"], endpoint="geo_pages")
@login_required
def geo_pages():
    """Geo Landing Page Generator — queue unique location pages per city × service."""
    if not is_paid_account():
        flash("Geo page generation is available on paid plans.", "warning")
        return redirect(url_for("main_bp.pricing"))

    site = _current_site()
    queued_results = None
    error = None

    if request.method == "POST" and site:
        service       = (request.form.get("service") or "").strip()
        cities_raw    = (request.form.get("cities") or "").strip()
        business_name = (request.form.get("business_name") or "").strip()
        phone         = (request.form.get("phone") or "").strip()
        extra_context = (request.form.get("extra_context") or "").strip()

        if not service or not cities_raw:
            flash("Service and at least one city are required.", "error")
        else:
            # Parse "City, ST" lines
            cities: List[Dict] = []
            for line in cities_raw.splitlines():
                line = line.strip().strip(",")
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                cities.append({"city": parts[0], "state": parts[1] if len(parts) > 1 else ""})

            if not cities:
                flash("No valid cities parsed. Use one city per line (e.g. Austin, TX).", "error")
            else:
                try:
                    from app.wp.geo_pages import generate_geo_pages
                    from app import db
                    queued_results = generate_geo_pages(
                        service=service,
                        cities=cities,
                        business_name=business_name,
                        phone=phone,
                        extra_context=extra_context,
                        site_id=site.id,
                        db_session=db.session,
                    )
                    n = len(queued_results["queued"])
                    s = len(queued_results["skipped"])
                    msg = f"Queued {n} geo page{'s' if n != 1 else ''} for generation."
                    if s:
                        msg += f" {s} skipped (already exist)."
                    flash(msg, "success" if n else "warning")
                except Exception as exc:
                    logger.exception("Geo page generation failed")
                    error = f"Generation failed: {exc}"
                    flash(error, "error")

    # Pre-fill business name from WP site
    prefill_name = ""
    prefill_phone = ""
    if site:
        try:
            from app.wp.wp_client import WPClient
            c = WPClient(site.base_url, site.username, site.app_password)
            info = c._req("GET", "/wp/v2/settings").json()
            prefill_name = info.get("title", "")
        except Exception:
            pass

    return render_template(
        "wp/geo_pages.html",
        site=site,
        queued_results=queued_results,
        prefill_name=prefill_name,
        error=error,
    )


@wp_bp.route("/redirects", methods=["GET", "POST"], endpoint="redirects")
@login_required
def redirects():
    """Redirect chain detector — find chains and 404s across all posts/pages."""
    site = _current_site()
    report = None
    error = None

    if request.method == "POST" and site:
        try:
            from app.wp.wp_client import WPClient
            from app.wp.redirect_checker import check_redirects
            c = WPClient(site.base_url, site.username, site.app_password)
            posts = c.list_posts(per_page=60, status="publish")
            # Also check pages
            try:
                pages_r = c._req("GET", "/wp/v2/pages",
                                  params={"per_page": 20, "status": "publish"})
                posts += (pages_r.json() if isinstance(pages_r.json(), list) else [])
            except Exception:
                pass
            report = check_redirects(posts)
            if report and site:
                try:
                    from app.models_seo import SEOScanResult
                    SEOScanResult.save_result(
                        account_id=_account_id(), site_id=site.id,
                        scan_type="redirects",
                        issue_count=(report.get("chains_count", 0) + report.get("broken_count", 0)),
                        item_count=report.get("total"),
                        data={
                            "total": report.get("total"),
                            "chains_count": report.get("chains_count"),
                            "broken_count": report.get("broken_count"),
                            "chains": report.get("chains", [])[:20],
                            "broken": report.get("broken", [])[:20],
                        },
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.exception("Redirect check failed")
            error = f"Check failed: {exc}"

    return render_template(
        "wp/redirects.html",
        site=site,
        report=report,
        error=error,
    )


@wp_bp.route("/seo-foundation", methods=["GET", "POST"], endpoint="seo_foundation")
@login_required
def seo_foundation():
    """WordPress SEO foundation checker — sitemap, robots.txt, indexing, Yoast, canonicals."""
    site = _current_site()
    checks = []
    score = None
    error = None
    site_url_checked = None

    if (request.method == "POST" or request.args.get("run")) and site:
        import requests as _req
        base = site.base_url.rstrip("/")
        site_url_checked = base

        def _chk(label: str, status: str, detail: str, fix: str = "") -> Dict:
            return {"label": label, "status": status, "detail": detail, "fix": fix}

        # 1. HTTPS
        checks.append(_chk(
            "HTTPS / SSL",
            "pass" if base.startswith("https://") else "fail",
            "Site uses HTTPS." if base.startswith("https://") else "Site is not HTTPS.",
            "" if base.startswith("https://") else "Install an SSL certificate — required by Google since 2014.",
        ))

        # 2. Robots.txt
        try:
            from app.wp.wp_client import WPClient
            c = WPClient(site.base_url, site.username, site.app_password)
            r = _req.get(f"{base}/robots.txt", timeout=8,
                         headers={"User-Agent": "FieldSprout/1.0"})
            robots = r.text if r.status_code == 200 else ""
            blocks_all = bool(re.search(r"Disallow:\s*/\s*$", robots, re.MULTILINE))
            blocks_wp  = bool(re.search(r"Disallow:\s*/wp-admin", robots, re.MULTILINE))
            checks.append(_chk(
                "Robots.txt",
                "fail" if blocks_all else "pass",
                f"robots.txt returned {r.status_code}." + (" ⚠ Disallow: / found — blocking ALL crawlers!" if blocks_all else ""),
                "" if not blocks_all else "Remove 'Disallow: /' from robots.txt immediately.",
            ))
        except Exception as e:
            checks.append(_chk("Robots.txt", "warn", f"Could not fetch robots.txt: {e}", "Check your server config."))
            c = None

        # 3. XML Sitemap
        sitemap_found = False
        for path in ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"):
            try:
                r = _req.get(f"{base}{path}", timeout=8,
                             headers={"User-Agent": "FieldSprout/1.0"})
                if r.status_code == 200 and "<urlset" in r.text or "<sitemapindex" in r.text:
                    sitemap_found = True
                    break
            except Exception:
                pass
        checks.append(_chk(
            "XML Sitemap",
            "pass" if sitemap_found else "fail",
            "XML sitemap found and accessible." if sitemap_found else "No XML sitemap found at /sitemap.xml or /wp-sitemap.xml.",
            "" if sitemap_found else "Enable the Yoast SEO sitemap or the built-in WordPress sitemap (Settings → Reading).",
        ))

        # 4. WordPress search engine visibility (reading settings)
        try:
            if c:
                settings = c._req("GET", "/wp/v2/settings").json()
                # WordPress "blog_public" = 0 means "discourage search engines"
                # The REST API doesn't expose this directly, but we can check the homepage
                r2 = _req.get(base, timeout=8, headers={"User-Agent": "Googlebot"})
                has_noindex = "noindex" in r2.text.lower() and "robots" in r2.text.lower()
                checks.append(_chk(
                    "Search Engine Indexing",
                    "fail" if has_noindex else "pass",
                    "Homepage is blocking search engines (noindex detected)!" if has_noindex
                    else "Homepage is indexable.",
                    "" if not has_noindex else
                    "Go to Settings → Reading → uncheck 'Discourage search engines'.",
                ))
        except Exception:
            checks.append(_chk("Search Engine Indexing", "warn", "Could not verify indexing status.", "Check Settings → Reading in WordPress admin."))

        # 5. Yoast / RankMath / SEOPress active
        seo_plugin = None
        try:
            if c:
                # Check for Yoast meta tags on homepage
                r3 = _req.get(base, timeout=8, headers={"User-Agent": "FieldSprout/1.0"})
                if "yoast" in r3.text.lower() or "wpseo" in r3.text.lower():
                    seo_plugin = "Yoast SEO"
                elif "rank-math" in r3.text.lower() or "rankmath" in r3.text.lower():
                    seo_plugin = "Rank Math"
                elif "seopress" in r3.text.lower():
                    seo_plugin = "SEOPress"
                elif "all-in-one-seo" in r3.text.lower() or "aioseo" in r3.text.lower():
                    seo_plugin = "All in One SEO"
        except Exception:
            pass
        checks.append(_chk(
            "SEO Plugin Active",
            "pass" if seo_plugin else "warn",
            f"{seo_plugin} detected." if seo_plugin else "No common SEO plugin detected (Yoast, Rank Math, SEOPress, AIOSEO).",
            "" if seo_plugin else "Install and configure Yoast SEO or Rank Math for title/meta control.",
        ))

        # 6. Canonical tags on homepage
        try:
            r4 = _req.get(base, timeout=8, headers={"User-Agent": "FieldSprout/1.0"})
            has_canonical = bool(re.search(r'<link[^>]+rel=["\']canonical["\']', r4.text, re.IGNORECASE))
            checks.append(_chk(
                "Canonical Tags",
                "pass" if has_canonical else "warn",
                "Canonical tag found on homepage." if has_canonical else "No canonical tag on homepage.",
                "" if has_canonical else "Configure your SEO plugin to output canonical tags on every page.",
            ))

            # 7. Open Graph tags
            has_og = bool(re.search(r'<meta[^>]+property=["\']og:', r4.text, re.IGNORECASE))
            checks.append(_chk(
                "Open Graph / Social Meta Tags",
                "pass" if has_og else "warn",
                "Open Graph tags found." if has_og else "No Open Graph meta tags on homepage.",
                "" if has_og else "Enable social meta tags in your SEO plugin (improves social sharing previews).",
            ))

            # 8. Title tag present and non-empty
            title_m = re.search(r"<title[^>]*>(.*?)</title>", r4.text, re.IGNORECASE | re.DOTALL)
            title_text = re.sub(r"<[^>]+>", "", title_m.group(1)).strip() if title_m else ""
            title_ok = bool(title_text and len(title_text) >= 20)
            checks.append(_chk(
                "Homepage Title Tag",
                "pass" if title_ok else ("warn" if title_text else "fail"),
                f"Title: \"{title_text[:70]}\"" if title_text else "No title tag found.",
                "" if title_ok else "Set a descriptive 50-60 character title tag on your homepage.",
            ))

            # 9. Meta description
            meta_m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
                                r4.text, re.IGNORECASE)
            meta_desc = meta_m.group(1).strip() if meta_m else ""
            meta_ok = bool(meta_desc and 70 <= len(meta_desc) <= 160)
            checks.append(_chk(
                "Homepage Meta Description",
                "pass" if meta_ok else ("warn" if meta_desc else "fail"),
                f"Meta desc ({len(meta_desc)} chars): \"{meta_desc[:100]}\"" if meta_desc else "No meta description found.",
                "" if meta_ok else (
                    "Meta description is too short or too long — aim for 145-155 chars." if meta_desc
                    else "Add a 145-155 char meta description to your homepage."
                ),
            ))

        except Exception as e:
            checks.append(_chk("Homepage Checks", "warn", f"Could not fetch homepage: {e}", "Ensure the site is publicly accessible."))

        # 10. Structured data on homepage
        try:
            has_schema = bool(re.search(r'application/ld\+json', r4.text if 'r4' in dir() else "", re.IGNORECASE))
            checks.append(_chk(
                "Structured Data (Schema)",
                "pass" if has_schema else "warn",
                "JSON-LD schema found on homepage." if has_schema else "No JSON-LD schema on homepage.",
                "" if has_schema else "Add LocalBusiness or Organization schema. Use the Schema Generator tool.",
            ))
        except Exception:
            pass

        weights = {"pass": 2, "warn": 1, "fail": 0}
        score = round(sum(weights[c["status"]] for c in checks) / (len(checks) * 2) * 100) if checks else 0

        if checks and site:
            try:
                from app.models_seo import SEOScanResult
                SEOScanResult.save_result(
                    account_id=_account_id(), site_id=site.id,
                    scan_type="seo_foundation", url=site_url_checked,
                    score=score,
                    pass_count=sum(1 for c in checks if c["status"] == "pass"),
                    warn_count=sum(1 for c in checks if c["status"] == "warn"),
                    fail_count=sum(1 for c in checks if c["status"] == "fail"),
                    data={"checks": checks, "score": score},
                )
            except Exception:
                pass

    return render_template(
        "wp/seo_foundation.html",
        site=site,
        checks=checks,
        score=score,
        site_url_checked=site_url_checked,
        error=error,
    )


@wp_bp.route("/index-coverage", methods=["GET"], endpoint="index_coverage")
@login_required
def index_coverage():
    """Index Coverage Monitor — find published pages with zero GSC presence."""
    site = _current_site()
    result = None
    error = None
    gsc_connected = False

    aid = _account_id()
    site_url = None

    try:
        from app.google import _is_connected, _get_gsc_selected_site
        import os
        gsc_connected = _is_connected(aid, "gsc")
        site_url = _get_gsc_selected_site(aid) or os.getenv("GSC_SITE")
    except Exception as exc:
        error = str(exc)

    if site and gsc_connected and site_url:
        try:
            from app.wp.wp_client import WPClient
            from app.wp.index_coverage import check_index_coverage
            c = WPClient(site.base_url, site.username, site.app_password)
            posts = c.list_posts(per_page=100, status="publish")
            pages = []
            try:
                pages = c.get(f"{site.base_url.rstrip('/')}/wp-json/wp/v2/pages",
                              params={"per_page": 100, "status": "publish"}) or []
            except Exception:
                pass
            all_content = posts + pages
            result = check_index_coverage(all_content, aid, site_url)
            if result:
                try:
                    from app.models_seo import SEOScanResult
                    SEOScanResult.save_result(
                        account_id=aid, site_id=site.id,
                        scan_type="index_coverage",
                        issue_count=result.get("unindexed_count"),
                        item_count=result.get("total"),
                        score=result.get("pct_indexed"),
                        data={
                            "indexed_count": result.get("indexed_count"),
                            "unindexed_count": result.get("unindexed_count"),
                            "total": result.get("total"),
                            "pct_indexed": result.get("pct_indexed"),
                            "unindexed_urls": [p["url"] for p in result.get("unindexed", [])],
                        },
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.exception("Index coverage check failed")
            error = f"Check failed: {exc}"
    elif not site:
        pass  # template handles no-site state
    elif not gsc_connected:
        error = "Connect Google Search Console to check index coverage."
    elif not site_url:
        error = "Select a GSC property in your Google settings."

    return render_template(
        "wp/index_coverage.html",
        site=site,
        result=result,
        gsc_connected=gsc_connected,
        site_url=site_url,
        error=error,
    )


@wp_bp.route("/orphan-pages", methods=["GET"], endpoint="orphan_pages")
@login_required
def orphan_pages():
    """Orphan Page Detector — find published pages with no internal links pointing to them."""
    site = _current_site()
    result = None
    error = None

    if site:
        try:
            from app.wp.wp_client import WPClient
            from app.wp.orphan_pages import detect_orphans
            c = WPClient(site.base_url, site.username, site.app_password)
            posts = c.list_posts(per_page=100, status="publish")
            pages = []
            try:
                pages = c.get(f"{site.base_url.rstrip('/')}/wp-json/wp/v2/pages",
                              params={"per_page": 100, "status": "publish"}) or []
            except Exception:
                pass
            all_content = posts + pages
            result = detect_orphans(all_content, site.base_url)
            if result:
                try:
                    from app.models_seo import SEOScanResult
                    SEOScanResult.save_result(
                        account_id=_account_id(), site_id=site.id,
                        scan_type="orphan_pages",
                        issue_count=result.get("orphan_count"),
                        item_count=result.get("total"),
                        data={
                            "orphan_count": result.get("orphan_count"),
                            "linked_count": result.get("linked_count"),
                            "total": result.get("total"),
                            "pct_orphaned": result.get("pct_orphaned"),
                            "orphan_urls": [p["url"] for p in result.get("orphans", [])],
                        },
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.exception("Orphan page detection failed")
            error = f"Detection failed: {exc}"

    return render_template(
        "wp/orphan_pages.html",
        site=site,
        result=result,
        error=error,
    )


@wp_bp.route("/seo-health", methods=["GET"], endpoint="seo_health")
@login_required
def seo_health():
    """Consolidated SEO Health dashboard — last scan results for all diagnostic tools."""
    site = _current_site()
    aid = _account_id()

    # Load last scan result for each tool that persists results to SEOScanResult
    scans = {}
    if aid:
        try:
            from app.models_seo import SEOScanResult
            for scan_type in ["seo_foundation", "content_quality", "broken_links",
                               "redirects", "index_coverage", "orphan_pages",
                               "tech_seo", "aeo_audit", "image_seo", "freshness"]:
                row = SEOScanResult.latest(aid, scan_type, site_id=site.id if site else None)
                if row:
                    scans[scan_type] = row
        except Exception:
            pass

    return render_template(
        "wp/seo_health.html",
        site=site,
        scans=scans,
        now=datetime.utcnow(),
    )


# allow WPLog(...).save() convenience
def _save(self):
    db.session.add(self)
    db.session.commit()
    return self
WPLog.save = _save
