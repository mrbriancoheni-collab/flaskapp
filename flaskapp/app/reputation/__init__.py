# app/reputation/__init__.py
"""
Reputation Dashboard — unified view of reviews across Google (GMB) and Yelp,
with AI-powered response drafts.

Routes:
  GET  /account/reputation              — dashboard
  POST /account/reputation/draft        — generate AI response draft (AJAX)
  POST /account/reputation/respond      — submit a response via GMB/Yelp API
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint, jsonify, redirect, render_template, request, session, url_for,
)
from sqlalchemy import text

from app import db

log = logging.getLogger(__name__)

reputation_bp = Blueprint("reputation_bp", __name__)

# ── Auth helpers ───────────────────────────────────────────────────────────────

def _current_account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        row = db.session.execute(
            text("SELECT account_id FROM users WHERE id=:id"), {"id": uid}
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def _login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if not _current_account_id():
            return redirect(url_for("auth_bp.login", next=request.path))
        return f(*a, **kw)
    return wrapper


# ── Review aggregation ─────────────────────────────────────────────────────────

SAMPLE_REVIEWS: List[Dict[str, Any]] = [
    {
        "id": "gmb_1", "source": "google", "source_label": "Google",
        "source_icon": "fa-google", "source_color": "blue",
        "author": "Sarah M.", "rating": 5,
        "text": "Absolutely amazing service! They fixed our AC in 2 hours and the technician was super professional.",
        "date": datetime.utcnow() - timedelta(days=2),
        "responded": False, "response": None,
    },
    {
        "id": "gmb_2", "source": "google", "source_label": "Google",
        "source_icon": "fa-google", "source_color": "blue",
        "author": "Tom R.", "rating": 4,
        "text": "Good job overall. Arrived on time and did what they said they would. Pricing was fair.",
        "date": datetime.utcnow() - timedelta(days=5),
        "responded": True,
        "response": "Thanks Tom! Really appreciate you taking the time.",
    },
    {
        "id": "gmb_3", "source": "google", "source_label": "Google",
        "source_icon": "fa-google", "source_color": "blue",
        "author": "Anonymous", "rating": 3,
        "text": "The work was fine but they were 45 minutes late without calling ahead.",
        "date": datetime.utcnow() - timedelta(days=8),
        "responded": False, "response": None,
    },
    {
        "id": "yelp_1", "source": "yelp", "source_label": "Yelp",
        "source_icon": "fa-yelp", "source_color": "red",
        "author": "Jessica L.", "rating": 5,
        "text": "Best HVAC company in the area! Have used them twice now and they never disappoint.",
        "date": datetime.utcnow() - timedelta(days=3),
        "responded": False, "response": None,
    },
    {
        "id": "yelp_2", "source": "yelp", "source_label": "Yelp",
        "source_icon": "fa-yelp", "source_color": "red",
        "author": "Marcus B.", "rating": 2,
        "text": "Charged me for parts I didn't need. Will not be using again.",
        "date": datetime.utcnow() - timedelta(days=12),
        "responded": False, "response": None,
    },
]


def _fetch_gmb_reviews(account_id: int) -> List[Dict[str, Any]]:
    """Fetch GMB reviews from DB or return empty list if not connected."""
    try:
        from app.services.gmb_insights import get_recent_reviews
        raw = get_recent_reviews(account_id) or []
        out = []
        for r in raw:
            out.append({
                "id": f"gmb_{r.get('reviewId', r.get('id', ''))}",
                "source": "google",
                "source_label": "Google",
                "source_icon": "fa-google",
                "source_color": "blue",
                "author": r.get("reviewer", {}).get("displayName", "Anonymous"),
                "rating": {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}.get(
                    r.get("starRating", ""), 0
                ),
                "text": r.get("comment", ""),
                "date": datetime.fromisoformat(r["createTime"][:19]) if r.get("createTime") else datetime.utcnow(),
                "responded": bool(r.get("reviewReply")),
                "response": (r.get("reviewReply") or {}).get("comment"),
            })
        return out
    except Exception:
        return []


def _fetch_yelp_reviews(account_id: int) -> List[Dict[str, Any]]:
    """Fetch Yelp reviews."""
    try:
        from app.services.yelp_insights import get_recent_reviews as yelp_reviews
        raw = yelp_reviews(account_id) or []
        out = []
        for r in raw:
            out.append({
                "id": f"yelp_{r.get('id', '')}",
                "source": "yelp",
                "source_label": "Yelp",
                "source_icon": "fa-yelp",
                "source_color": "red",
                "author": r.get("user", {}).get("name", "Anonymous"),
                "rating": r.get("rating", 0),
                "text": r.get("text", ""),
                "date": datetime.fromisoformat(r["time_created"][:19]) if r.get("time_created") else datetime.utcnow(),
                "responded": False,
                "response": None,
            })
        return out
    except Exception:
        return []


def _aggregate_reviews(account_id: int, use_sample: bool = False) -> List[Dict[str, Any]]:
    if use_sample:
        reviews = list(SAMPLE_REVIEWS)
    else:
        reviews = _fetch_gmb_reviews(account_id) + _fetch_yelp_reviews(account_id)
        if not reviews:
            reviews = list(SAMPLE_REVIEWS)

    reviews.sort(key=lambda r: r.get("date") or datetime.min, reverse=True)
    return reviews


def _compute_stats(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not reviews:
        return {"avg_rating": 0, "total": 0, "unanswered": 0, "by_rating": {}}
    total = len(reviews)
    avg = sum(r["rating"] for r in reviews) / total
    unanswered = sum(1 for r in reviews if not r["responded"])
    by_source = {}
    for r in reviews:
        src = r["source"]
        if src not in by_source:
            by_source[src] = {"count": 0, "total_rating": 0, "label": r["source_label"]}
        by_source[src]["count"] += 1
        by_source[src]["total_rating"] += r["rating"]
    for s in by_source.values():
        s["avg"] = round(s["total_rating"] / s["count"], 1) if s["count"] else 0
    return {
        "avg_rating": round(avg, 1),
        "total": total,
        "unanswered": unanswered,
        "by_source": by_source,
    }


# ── AI response draft ──────────────────────────────────────────────────────────

def _generate_response_draft(review_text: str, rating: int, business_name: str = "us") -> str:
    """Generate an AI review response draft via OpenAI/Claude."""
    try:
        from app.ai_clients import get_completion
        tone = "warm and grateful" if rating >= 4 else "empathetic and solution-focused"
        prompt = (
            f"You are a professional responding to a {rating}-star review for a local home services business. "
            f"Write a concise, {tone} response (2-3 sentences max). "
            f"Do NOT be sycophantic. Address the specific feedback. "
            f"Sign off with 'The {business_name} Team'.\n\n"
            f"Review: {review_text}"
        )
        return get_completion(prompt, max_tokens=200)
    except Exception:
        # Fallback templates
        if rating >= 4:
            return (
                f"Thank you so much for the kind words! We're thrilled you had a great experience "
                f"and look forward to helping you again in the future. "
                f"— The {business_name} Team"
            )
        return (
            f"We appreciate your honest feedback and are sorry to hear your experience fell short of expectations. "
            f"We'd love the chance to make this right — please reach out to us directly. "
            f"— The {business_name} Team"
        )


# ── Routes ─────────────────────────────────────────────────────────────────────

@reputation_bp.route("/account/reputation")
@_login_required
def dashboard():
    account_id = _current_account_id()
    source_filter = request.args.get("source", "all")
    rating_filter = request.args.get("rating", "all")
    show_unanswered = request.args.get("unanswered") == "1"

    reviews = _aggregate_reviews(account_id)
    is_sample = len(_fetch_gmb_reviews(account_id)) == 0 and len(_fetch_yelp_reviews(account_id)) == 0

    if source_filter != "all":
        reviews = [r for r in reviews if r["source"] == source_filter]
    if rating_filter != "all":
        reviews = [r for r in reviews if str(r["rating"]) == rating_filter]
    if show_unanswered:
        reviews = [r for r in reviews if not r["responded"]]

    stats = _compute_stats(reviews)

    return render_template(
        "reputation/index.html",
        reviews=reviews,
        stats=stats,
        source_filter=source_filter,
        rating_filter=rating_filter,
        show_unanswered=show_unanswered,
        is_sample=is_sample,
    )


@reputation_bp.route("/account/reputation/draft", methods=["POST"])
@_login_required
def draft_response():
    """Generate an AI response draft for a review (AJAX)."""
    data = request.get_json(silent=True) or {}
    review_text = data.get("text", "")
    rating = int(data.get("rating", 5))
    draft = _generate_response_draft(review_text, rating)
    return jsonify({"draft": draft})
