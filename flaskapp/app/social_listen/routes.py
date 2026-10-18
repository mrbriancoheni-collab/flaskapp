# app/social_listen/routes.py
"""
Blueprint for /admin/social-listen — social listening dashboard and
action routes (approve / edit / skip).
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime
from typing import Optional

from flask import (
    Blueprint, request, render_template, redirect, url_for,
    flash, g, current_app
)
from sqlalchemy import text

from app.auth.decorators import require_admin_cloaked as require_admin

logger = logging.getLogger(__name__)

social_listen_bp = Blueprint(
    "social_listen_bp",
    __name__,
    url_prefix="/admin/social-listen",
    template_folder="../templates",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db():
    from app import db
    return db


def _current_user_id() -> Optional[int]:
    user = getattr(g, "user", None)
    if user:
        return getattr(user, "id", None)
    return None


def _get_config(user_id: int) -> Optional[dict]:
    db = _db()
    row = db.session.execute(
        text("SELECT * FROM social_listen_config WHERE user_id = :uid"),
        {"uid": user_id},
    ).mappings().one_or_none()
    return dict(row) if row else None


def _ensure_config(user_id: int) -> dict:
    cfg = _get_config(user_id)
    if cfg:
        return cfg
    db = _db()
    db.session.execute(
        text("""
            INSERT IGNORE INTO social_listen_config
                (user_id, topics, sources, email_recipient, schedule, enabled)
            VALUES (:uid, :topics, :sources, '', 'daily', 1)
        """),
        {
            "uid": user_id,
            "topics": json.dumps(["demand generation", "B2B marketing"]),
            "sources": json.dumps(["google_news", "google_search", "reddit"]),
        },
    )
    db.session.commit()
    return _get_config(user_id)


def _opp_by_token(token: str) -> Optional[dict]:
    db = _db()
    row = db.session.execute(
        text("SELECT * FROM social_opportunities WHERE email_token = :tok"),
        {"tok": token},
    ).mappings().one_or_none()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@social_listen_bp.route("/", methods=["GET"])
@require_admin
def index():
    from app.social_listen.models import ensure_tables
    ensure_tables()
    db = _db()
    user_id = _current_user_id()
    cfg = _get_config(user_id) if user_id else None

    # Summary counts
    counts = {}
    if user_id:
        rows = db.session.execute(
            text("""
                SELECT status, COUNT(*) AS cnt
                FROM social_opportunities
                WHERE user_id = :uid
                GROUP BY status
            """),
            {"uid": user_id},
        ).mappings().all()
        counts = {r["status"]: r["cnt"] for r in rows}

    # Recent opportunities (all statuses)
    opps = []
    if user_id:
        opps = db.session.execute(
            text("""
                SELECT * FROM social_opportunities
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT 50
            """),
            {"uid": user_id},
        ).mappings().all()
        opps = [dict(o) for o in opps]

    return render_template(
        "social_listen_index.html",
        cfg=cfg,
        counts=counts,
        opps=opps,
    )


@social_listen_bp.route("/settings", methods=["GET", "POST"])
@require_admin
def settings():
    from app.social_listen.models import ensure_tables
    ensure_tables()
    db = _db()
    user_id = _current_user_id()
    cfg = _ensure_config(user_id)

    if request.method == "POST":
        raw_topics = request.form.get("topics", "")
        raw_sources = request.form.get("sources", "")
        email_recipient = request.form.get("email_recipient", "").strip()
        schedule = request.form.get("schedule", "daily")
        enabled = 1 if request.form.get("enabled") else 0

        topics = [t.strip() for t in raw_topics.split(",") if t.strip()]
        sources = [s.strip() for s in raw_sources.split(",") if s.strip()]

        db.session.execute(
            text("""
                UPDATE social_listen_config
                SET topics = :topics, sources = :sources,
                    email_recipient = :email, schedule = :sched, enabled = :en,
                    updated_at = NOW()
                WHERE user_id = :uid
            """),
            {
                "topics": json.dumps(topics),
                "sources": json.dumps(sources),
                "email": email_recipient,
                "sched": schedule,
                "en": enabled,
                "uid": user_id,
            },
        )
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("social_listen_bp.settings"))

    # Parse JSON for display
    try:
        cfg["topics_list"] = json.loads(cfg.get("topics") or "[]")
    except Exception:
        cfg["topics_list"] = []
    try:
        cfg["sources_list"] = json.loads(cfg.get("sources") or "[]")
    except Exception:
        cfg["sources_list"] = []

    return render_template("social_listen_settings.html", cfg=cfg)


@social_listen_bp.route("/run", methods=["GET"])
@require_admin
def run_now():
    """Manually trigger crawl → score → draft → store → email for the current user."""
    from app.social_listen.models import ensure_tables
    ensure_tables()

    db = _db()
    user_id = _current_user_id()
    cfg = _ensure_config(user_id)

    try:
        topics = json.loads(cfg.get("topics") or "[]")
        sources = json.loads(cfg.get("sources") or "[]")
        email_recipient = cfg.get("email_recipient") or ""
    except Exception:
        topics, sources, email_recipient = ["marketing"], ["google_news"], ""

    if not topics:
        topics = ["demand generation", "B2B marketing"]
    if not sources:
        sources = ["google_news", "google_search", "reddit"]

    try:
        from app.social_listen.crawler import crawl_opportunities
        from app.social_listen.scorer import score_and_filter
        from app.social_listen.drafter import draft_content
        from app.social_listen.emailer import generate_tokens, send_opportunity_digest

        raw = crawl_opportunities(topics, sources)
        scored = score_and_filter(raw)
        drafted = [draft_content(item) for item in scored]
        drafted = generate_tokens(drafted)

        stored = []
        for item in drafted:
            db.session.execute(
                text("""
                    INSERT INTO social_opportunities
                        (user_id, source, source_url, author, original_content, topic,
                         ai_score, ai_reason, draft_comment, draft_post,
                         status, email_token, created_at)
                    VALUES
                        (:uid, :source, :source_url, :author, :content, :topic,
                         :score, :reason, :comment, :post,
                         'new', :token, NOW())
                    ON DUPLICATE KEY UPDATE
                        status = 'new', updated_at = NOW()
                """),
                {
                    "uid": user_id,
                    "source": item.get("source", ""),
                    "source_url": (item.get("source_url") or "")[:1000],
                    "author": (item.get("author") or "")[:200],
                    "content": item.get("original_content") or "",
                    "topic": (item.get("topic") or "")[:200],
                    "score": item.get("ai_score", 5.0),
                    "reason": item.get("ai_reason") or "",
                    "comment": item.get("draft_comment") or "",
                    "post": item.get("draft_post") or "",
                    "token": item["email_token"],
                },
            )
            stored.append(item)
        db.session.commit()

        # Update status to 'emailed' and send
        if email_recipient and stored:
            for item in stored:
                db.session.execute(
                    text("UPDATE social_opportunities SET status='emailed' WHERE email_token=:tok"),
                    {"tok": item["email_token"]},
                )
            db.session.commit()
            base_url = request.host_url.rstrip("/")
            send_opportunity_digest(email_recipient, stored, base_url)
            flash(f"Crawled {len(stored)} opportunities and emailed {email_recipient}.", "success")
        else:
            flash(
                f"Crawled {len(stored)} opportunities. "
                f"No email sent (no recipient configured).",
                "info",
            )
    except Exception as exc:
        logger.exception("social listen run_now failed")
        flash(f"Run failed: {exc}", "danger")

    return redirect(url_for("social_listen_bp.index"))


@social_listen_bp.route("/approve/<token>", methods=["GET"])
@require_admin
def approve(token: str):
    opp = _opp_by_token(token)
    if not opp:
        flash("Opportunity not found.", "warning")
        return redirect(url_for("social_listen_bp.index"))

    approve_type = request.args.get("type", "comment")
    db = _db()
    db.session.execute(
        text("""
            UPDATE social_opportunities
            SET status = 'approved', updated_at = NOW()
            WHERE email_token = :tok
        """),
        {"tok": token},
    )
    db.session.commit()

    draft_text = (
        opp.get("draft_comment") if approve_type == "comment"
        else opp.get("draft_post")
    )
    flash("Approved! Copy the draft below to post.", "success")
    return render_template(
        "social_listen_confirm.html",
        opp=opp,
        draft_text=draft_text,
        approve_type=approve_type,
        action="approved",
    )


@social_listen_bp.route("/edit/<token>", methods=["GET", "POST"])
@require_admin
def edit(token: str):
    opp = _opp_by_token(token)
    if not opp:
        flash("Opportunity not found.", "warning")
        return redirect(url_for("social_listen_bp.index"))

    if request.method == "POST":
        draft_comment = request.form.get("draft_comment", opp.get("draft_comment") or "")
        draft_post = request.form.get("draft_post", opp.get("draft_post") or "")
        user_take = request.form.get("user_take", "")
        db = _db()
        db.session.execute(
            text("""
                UPDATE social_opportunities
                SET draft_comment = :comment, draft_post = :post,
                    user_take = :take, status = 'approved', updated_at = NOW()
                WHERE email_token = :tok
            """),
            {"comment": draft_comment, "post": draft_post, "take": user_take, "tok": token},
        )
        db.session.commit()
        flash("Draft saved and approved!", "success")
        return redirect(url_for("social_listen_bp.index"))

    return render_template("social_listen_edit.html", opp=opp)


@social_listen_bp.route("/skip/<token>", methods=["GET"])
@require_admin
def skip(token: str):
    opp = _opp_by_token(token)
    if not opp:
        flash("Opportunity not found.", "warning")
        return redirect(url_for("social_listen_bp.index"))

    db = _db()
    db.session.execute(
        text("""
            UPDATE social_opportunities
            SET status = 'skipped', updated_at = NOW()
            WHERE email_token = :tok
        """),
        {"tok": token},
    )
    db.session.commit()
    flash("Opportunity skipped.", "info")
    return render_template(
        "social_listen_confirm.html",
        opp=opp,
        draft_text=None,
        approve_type=None,
        action="skipped",
    )
