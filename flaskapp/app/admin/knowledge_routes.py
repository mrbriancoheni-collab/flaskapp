# app/admin/knowledge_routes.py
"""
Admin: Agent Knowledge Source Management

Admins approve/reject external knowledge sources that agents learn from.
All new sources start as pending (is_approved=False) and must be approved here
before the daily refresh will fetch them.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from app import db
from app.auth.utils import login_required
from app.models_knowledge import AgentKnowledgeSource, AgentKnowledgeCache, AGENT_TYPES

knowledge_bp = Blueprint("knowledge_bp", __name__, url_prefix="/admin/knowledge")


def _require_admin(f):
    """Simple admin guard — reuse the same pattern as agent_config_routes."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(g, "user", None) or not getattr(g.user, "is_admin", False):
            flash("Admin access required.", "error")
            return redirect(url_for("account_bp.dashboard"))
        return f(*args, **kwargs)
    return decorated


@knowledge_bp.route("/", endpoint="index")
@login_required
@_require_admin
def index():
    pending = AgentKnowledgeSource.pending_approval()
    approved = AgentKnowledgeSource.query.filter_by(is_approved=True, is_active=True).order_by(
        AgentKnowledgeSource.agent_type, AgentKnowledgeSource.title
    ).all()

    # Cache status per agent type
    cache_status = {}
    for agent_type in AGENT_TYPES:
        last = AgentKnowledgeCache.get_latest_refreshed_at(agent_type)
        count = AgentKnowledgeCache.query.filter_by(agent_type=agent_type).count()
        cache_status[agent_type] = {"last_refreshed": last, "entry_count": count}

    return render_template(
        "admin/knowledge_sources.html",
        pending=pending,
        approved=approved,
        agent_types=AGENT_TYPES,
        cache_status=cache_status,
    )


@knowledge_bp.route("/add", methods=["POST"], endpoint="add_source")
@login_required
@_require_admin
def add_source():
    agent_type = request.form.get("agent_type", "").strip()
    title = request.form.get("title", "").strip()
    url = request.form.get("url", "").strip()
    source_type = request.form.get("source_type", "webpage").strip()
    category = request.form.get("category", "best_practices").strip()
    refresh_frequency = request.form.get("refresh_frequency", "weekly").strip()

    if not all([agent_type, title, url]):
        flash("Agent type, title, and URL are required.", "error")
        return redirect(url_for("knowledge_bp.index"))

    if agent_type not in AGENT_TYPES:
        flash(f"Invalid agent type: {agent_type}", "error")
        return redirect(url_for("knowledge_bp.index"))

    if not url.startswith("https://"):
        flash("URL must start with https://", "error")
        return redirect(url_for("knowledge_bp.index"))

    existing = AgentKnowledgeSource.query.filter_by(url=url).first()
    if existing:
        flash("A source with that URL already exists.", "warning")
        return redirect(url_for("knowledge_bp.index"))

    src = AgentKnowledgeSource(
        agent_type=agent_type,
        title=title,
        url=url,
        source_type=source_type,
        category=category,
        refresh_frequency=refresh_frequency,
        is_approved=False,
    )
    db.session.add(src)
    db.session.commit()

    flash(f"Source '{title}' added and is pending approval.", "success")
    return redirect(url_for("knowledge_bp.index"))


@knowledge_bp.route("/<int:source_id>/approve", methods=["POST"], endpoint="approve_source")
@login_required
@_require_admin
def approve_source(source_id: int):
    src = AgentKnowledgeSource.query.get_or_404(source_id)
    src.is_approved = True
    src.approved_by_user_id = g.user.id
    db.session.commit()
    flash(f"Source '{src.title}' approved. It will be fetched on the next daily refresh.", "success")
    return redirect(url_for("knowledge_bp.index"))


@knowledge_bp.route("/<int:source_id>/reject", methods=["POST"], endpoint="reject_source")
@login_required
@_require_admin
def reject_source(source_id: int):
    src = AgentKnowledgeSource.query.get_or_404(source_id)
    src.is_active = False
    db.session.commit()
    flash(f"Source '{src.title}' rejected and deactivated.", "info")
    return redirect(url_for("knowledge_bp.index"))


@knowledge_bp.route("/<int:source_id>/refresh", methods=["POST"], endpoint="refresh_source")
@login_required
@_require_admin
def refresh_source(source_id: int):
    src = AgentKnowledgeSource.query.get_or_404(source_id)
    if not src.is_approved:
        flash("Source must be approved before refreshing.", "error")
        return redirect(url_for("knowledge_bp.index"))

    from app.services.agent_knowledge_service import refresh_knowledge_source
    ok = refresh_knowledge_source(src)
    if ok:
        flash(f"'{src.title}' refreshed successfully.", "success")
    else:
        flash(f"Refresh failed for '{src.title}'. Check the fetch error log.", "error")
    return redirect(url_for("knowledge_bp.index"))


@knowledge_bp.route("/refresh-all", methods=["POST"], endpoint="refresh_all")
@login_required
@_require_admin
def refresh_all():
    from app.services.agent_knowledge_service import refresh_all_approved_sources
    counts = refresh_all_approved_sources(force=True)
    flash(
        f"Knowledge refresh complete: {counts['success']} updated, "
        f"{counts['skipped']} skipped, {counts['failed']} failed.",
        "success",
    )
    return redirect(url_for("knowledge_bp.index"))


@knowledge_bp.route("/cache/<agent_type>", endpoint="view_cache")
@login_required
@_require_admin
def view_cache(agent_type: str):
    if agent_type not in AGENT_TYPES:
        flash("Unknown agent type.", "error")
        return redirect(url_for("knowledge_bp.index"))

    entries = (
        AgentKnowledgeCache.query
        .filter_by(agent_type=agent_type)
        .order_by(AgentKnowledgeCache.refreshed_at.desc())
        .all()
    )
    return render_template(
        "admin/knowledge_cache.html",
        agent_type=agent_type,
        entries=entries,
    )


@knowledge_bp.route("/seed-defaults", methods=["POST"], endpoint="seed_defaults")
@login_required
@_require_admin
def seed_defaults():
    from app.services.agent_knowledge_service import seed_default_sources
    added = seed_default_sources()
    flash(
        f"Seeded {added} default knowledge source(s). Review and approve them below.",
        "success" if added else "info",
    )
    return redirect(url_for("knowledge_bp.index"))
