# app/cron_tasks.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, List, Tuple

from sqlalchemy import text

from app import db
from app.models.wp_job import WPJob


# =========================
# Core CRON entrypoints
# =========================

def run_minutely(app, db):
    """Lightweight work every minute."""
    app.logger.info("[CRON] minutely tick at %s", datetime.utcnow().isoformat())

    # Process exactly one queued WP job per minute (keeps load steady)
    try:
        processed = process_wp_jobs(app)
        if processed:
            app.logger.info("[CRON] processed 1 WP job")
    except Exception:
        app.logger.exception("[CRON] process_wp_jobs failed")


def run_hourly(app, db):
    """Periodic housekeeping. Keep this light; heavy jobs belong in run_daily."""
    app.logger.info("[CRON] hourly tick at %s", datetime.utcnow().isoformat())
    # TODO: queue blog drafts, refresh sitemaps, sync analytics, etc.


def run_daily(app, db):
    """
    Daily heavy tasks.
    - Generates Google Business Profile monthly insights (at most every ~27 days per account).
    """
    app.logger.info("[CRON] daily tick at %s", datetime.utcnow().isoformat())

    try:
        _run_daily_gmb_insights(app)
    except Exception:
        app.logger.exception("[CRON] GMB monthly insights run failed")

    # TODO: email digests, cleanups, churn pings, etc.


# =========================
# WordPress job runner
# =========================

def process_wp_jobs(app) -> bool:
    """
    Pick the oldest queued job and run it.
    Returns True if a job was processed, else False.
    """
    now = datetime.utcnow()

    job = (
        WPJob.query
        .filter(WPJob.status == "queued")
        .order_by(
            WPJob.scheduled_at.is_(None),
            WPJob.scheduled_at.asc(),
            WPJob.priority.desc(),
            WPJob.created_at.asc(),
        )
        .first()
    )
    if not job:
        return False

    try:
        job.status = "running"
        job.started_at = now
        db.session.commit()

        if job.action == "publish_manual":
            # TODO: replace with your real WP publish call
            title = (job.payload or {}).get("title") or "Untitled"
            content = (job.payload or {}).get("content") or ""
            # result = publish_to_wordpress(title, content, ...)
            job.result = {"preview_url": None, "wp_post_id": None, "title": title}
            job.status = "done"

        elif job.action == "generate_ai_post":
            # TODO: call your AI writer (OpenAI/Claude) and optionally publish/save draft
            brief = job.payload or {}
            # draft = generate_ai_article(brief)
            # optionally post to WP as draft
            job.result = {"draft_title": brief.get("primary_keyword") or "AI Draft", "wp_post_id": None}
            job.status = "done"

        else:
            job.error = f"Unknown action: {job.action}"
            job.status = "failed"

        job.completed_at = datetime.utcnow()
        db.session.commit()
        return True

    except Exception as e:
        app.logger.exception("WP job failed")
        job.status = "failed"
        job.error = str(e)
        job.retries = (job.retries or 0) + 1
        db.session.commit()
        return False


# =========================
# GMB Monthly Insights
# =========================

def _run_daily_gmb_insights(app) -> None:
    """
    Generate OpenAI-powered GBP insights for eligible accounts.
    - Skips if OPENAI_API_KEY is missing.
    - Only runs for accounts that have a refreshable GBP token.
    - Per-account interval: >= 27 days since the last insights.
    - Per-run cap: GMB_INSIGHTS_MAX_PER_RUN (default 25).
    """
    # Feature flag
    enabled = app.config.get("GMB_INSIGHTS_ENABLED", True)
    if not enabled:
        app.logger.info("[CRON] GMB insights disabled (GMB_INSIGHTS_ENABLED=False)")
        return

    # Must have OpenAI configured
    if not (app.config.get("OPENAI_API_KEY")):
        app.logger.info("[CRON] GMB insights skipped (no OPENAI_API_KEY)")
        return

    max_per_run = int(app.config.get("GMB_INSIGHTS_MAX_PER_RUN", 25))
    lookback_days = int(app.config.get("GMB_INSIGHTS_INTERVAL_DAYS", 27))
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)

    # Find accounts with GBP refresh tokens
    accounts = _accounts_with_gbp_tokens(max_candidates=200)
    if not accounts:
        app.logger.info("[CRON] No GBP-connected accounts to consider")
        return

    app.logger.info(
        "[CRON] Considering %d GBP-connected accounts for insights (interval >= %d days, cap=%d)",
        len(accounts), lookback_days, max_per_run
    )

    processed = 0
    for aid in accounts:
        if processed >= max_per_run:
            break
        try:
            last = _last_gmb_insights_time(aid)
            if last and last > cutoff:
                # Too recent; skip
                continue

            ok = _generate_gmb_insights_for_account(app, aid)
            if ok:
                processed += 1
        except Exception:
            app.logger.exception("[CRON] insights generation failed for account_id=%s", aid)

    app.logger.info("[CRON] GMB insights generated for %d account(s)", processed)


def _accounts_with_gbp_tokens(max_candidates: int = 200) -> List[int]:
    """
    Return a list of account_ids that have a GBP refresh token.
    """
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT account_id
                      FROM google_oauth_tokens
                     WHERE LOWER(product) IN ('gbp','gmb','mybusiness')
                       AND refresh_token IS NOT NULL
                     ORDER BY account_id ASC
                     LIMIT :lim
                    """
                ),
                {"lim": max_candidates},
            ).fetchall()
        return [int(r[0]) for r in rows]
    except Exception:
        # On error, return empty list; caller logs higher up
        return []


def _last_gmb_insights_time(aid: int) -> Optional[datetime]:
    """Return the most recent generated_at for this account (or None)."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT MAX(generated_at)
                      FROM gmb_insights
                     WHERE account_id = :aid
                    """
                ),
                {"aid": aid},
            ).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _generate_gmb_insights_for_account(app, aid: int) -> bool:
    """
    Pull GBP performance and create insights via OpenAI.
    Uses helper functions from app.gmb to avoid duplication.
    """
    try:
        # Lazy import to avoid circular imports at module import time
        from app.gmb import (
            _refresh_token as gmb_refresh_token,
            _gbp_list_first_location_name,
            _gbp_fetch_performance,
            _gbp_metrics_to_prompt,
            _openai_insights_from_metrics,
            _save_insights,
        )
    except Exception:
        app.logger.exception("[CRON] could not import GMB helpers")
        return False

    # 1) Refresh access token
    access_token = gmb_refresh_token(aid)
    if not access_token:
        app.logger.info("[CRON] skip account_id=%s (no access token)", aid)
        return False

    # 2) Find first location
    loc = _gbp_list_first_location_name(access_token)
    if not loc:
        app.logger.info("[CRON] skip account_id=%s (no GBP locations)", aid)
        return False

    # 3) Fetch 28-day performance
    metrics = _gbp_fetch_performance(access_token, loc, days=28)

    # 4) Build LLM prompt & get HTML insights
    summary = _gbp_metrics_to_prompt(metrics)
    html = _openai_insights_from_metrics(summary)

    # 5) Persist insights
    _save_insights(aid, html)
    app.logger.info("[CRON] insights saved for account_id=%s", aid)
    return True
