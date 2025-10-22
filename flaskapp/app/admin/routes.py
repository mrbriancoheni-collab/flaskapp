# app/admin/routes.py
from __future__ import annotations
from datetime import datetime
from typing import Optional

from flask import (
    Blueprint, request, render_template, redirect, url_for, flash,
    session, g, current_app
)
from sqlalchemy import or_, desc

from app.extensions import db
from app.auth.session_utils import login_required
from app.auth.decorators import require_admin_cloaked as require_admin
from app.models import Account, User, CRMContact, CRM_STAGES

# Try to import Subscription if your project has it
try:
    from app.models import Subscription  # optional
except Exception:
    Subscription = None  # type: ignore

admin_bp = Blueprint("admin_bp", __name__, url_prefix="/admin", template_folder="templates")


def _audit(
    action: str,
    *,
    target_user_id: Optional[int] = None,
    target_account_id: Optional[int] = None,
    note: str = ""
):
    """Write a best-effort admin audit entry without crashing the request."""
    try:
        from app.models import AdminAuditLog  # optional
        entry = AdminAuditLog(
            admin_user_id=getattr(g, "real_admin_user_id", None) or (g.user.id if getattr(g, "user", None) else None),
            action=action,
            target_user_id=target_user_id,
            target_account_id=target_account_id,
            note=(note or "")[:1000],
            created_at=datetime.utcnow(),
            ip=request.headers.get("X-Forwarded-For", request.remote_addr),
            user_agent=request.headers.get("User-Agent", ""),
        )
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _recent_paid_accounts(limit: int = 8):
    """Return most-recent paid accounts via Subscription when present; else Account plan/plan_code/status."""
    paid_states = tuple(current_app.config.get("PAID_STRIPE_STATES", ("active", "trialing")))
    paid_plans = tuple(current_app.config.get("PAID_PLANS", ("pro", "team", "enterprise")))

    # Preferred: use Subscription if available
    if Subscription is not None and hasattr(Subscription, "status") and hasattr(Subscription, "account_id"):
        subs_q = (
            Subscription.query
            .filter(Subscription.status.in_(paid_states))
            .order_by(desc(getattr(Subscription, "updated_at", Subscription.id)))
        )
        subs = subs_q.limit(limit * 3).all()
        acct_ids = [getattr(s, "account_id", None) for s in subs if getattr(s, "account_id", None)]
        if acct_ids:
            return (
                Account.query.filter(Account.id.in_(acct_ids))
                .order_by(desc(Account.created_at))
                .limit(limit)
                .all()
            )

    # Fallback: rely on Account.* plan columns or status
    qry = Account.query
    if hasattr(Account, "plan"):
        qry = qry.filter(Account.plan.in_(paid_plans))
    elif hasattr(Account, "plan_code"):
        qry = qry.filter(Account.plan_code.in_(paid_plans))
    else:
        # last-resort heuristic
        if hasattr(Account, "status"):
            qry = qry.filter(Account.status == "active")

    return qry.order_by(desc(Account.created_at)).limit(limit).all()


def _primary_user_map(accounts):
    """Pick a likely primary user per account for display (owner/admin/first user)."""
    out = {}
    for a in accounts:
        try:
            users = User.query.filter_by(account_id=a.id).order_by(User.created_at.asc()).all()
            owner = next((u for u in users if getattr(u, "role", "") in ("owner", "admin")), None)
            out[a.id] = owner or (users[0] if users else None)
        except Exception:
            out[a.id] = None
    return out


# -------------------------
# Dashboard
# -------------------------
@admin_bp.get("/")
@login_required
@require_admin
def dashboard():
    accounts = Account.query.order_by(desc(Account.created_at)).limit(8).all()
    users = User.query.order_by(desc(User.created_at)).limit(8).all()

    subs_active = subs_canceled = None
    if Subscription is not None and hasattr(Subscription, "status"):
        subs_active = Subscription.query.filter(Subscription.status.in_(("active", "trialing"))).count()
        subs_canceled = Subscription.query.filter(Subscription.status == "canceled").count()

    paid_new = _recent_paid_accounts(limit=8)
    paid_new_primary_user = _primary_user_map(paid_new)

    return render_template(
        "admin/dashboard.html",
        accounts=accounts,
        users=users,
        subs_active=subs_active,
        subs_canceled=subs_canceled,
        paid_new=paid_new,
        paid_new_primary_user=paid_new_primary_user,
    )


# -------------------------
# Accounts
# -------------------------
@admin_bp.get("/accounts")
@login_required
@require_admin
def accounts():
    q = (request.args.get("q") or "").strip()
    qry = Account.query
    if q:
        cols = []
        for attr in ("name", "plan", "plan_code", "status"):
            if hasattr(Account, attr):
                cols.append(getattr(Account, attr).ilike(f"%{q}%"))
        if cols:
            qry = qry.filter(or_(*cols))

    page = max(int(request.args.get("page", 1)), 1)
    per = min(max(int(request.args.get("per", 25)), 1), 200)
    rows = qry.order_by(desc(Account.created_at)).paginate(page=page, per_page=per, error_out=False)
    return render_template("admin/accounts.html", rows=rows, q=q)


@admin_bp.get("/accounts/<int:account_id>")
@login_required
@require_admin
def account_detail(account_id: int):
    acct = Account.query.get_or_404(account_id)
    users = User.query.filter_by(account_id=acct.id).order_by(User.created_at.asc()).all()
    sub = None
    if Subscription is not None:
        sub = Subscription.query.filter_by(account_id=acct.id).order_by(
            desc(getattr(Subscription, "updated_at", Subscription.id)),
            desc(getattr(Subscription, "created_at", Subscription.id))
        ).first()
    return render_template("admin/account_detail.html", acct=acct, users=users, sub=sub)


# -------------------------
# Impersonation
# -------------------------
@admin_bp.post("/impersonate/<int:user_id>")
@login_required
@require_admin
def impersonate(user_id: int):
    user = User.query.get_or_404(user_id)
    if getattr(user, "role", "") == "admin":
        flash("Refusing to impersonate another admin.", "warning")
        return redirect(url_for("admin_bp.account_detail", account_id=user.account_id))
    session["impersonator_user_id"] = g.user.id
    session["impersonated_user_id"] = user.id
    session.modified = True
    _audit("impersonate_start", target_user_id=user.id, target_account_id=user.account_id)
    flash(f"You are now impersonating {user.email}.", "success")
    return redirect(url_for("account_bp.dashboard"))


@admin_bp.post("/stop-impersonation")
@login_required
def stop_impersonation():
    _audit("impersonate_stop", note=f"prev={session.get('impersonated_user_id')}")
    session.pop("impersonated_user_id", None)
    session.pop("impersonator_user_id", None)
    session.modified = True
    flash("Stopped impersonating.", "success")
    return redirect(url_for("admin_bp.dashboard"))


# -------------------------
# Audit Logs
# -------------------------
@admin_bp.get("/logs")
@login_required
@require_admin
def logs():
    try:
        from app.models import AdminAuditLog
    except Exception:
        flash("Audit log model missing.", "warning")
        return render_template("admin/logs.html", rows=None)

    page = max(int(request.args.get("page", 1)), 1)
    per = min(max(int(request.args.get("per", 50)), 1), 200)
    rows = AdminAuditLog.query.order_by(desc(AdminAuditLog.created_at)).paginate(page=page, per_page=per, error_out=False)
    return render_template("admin/logs.html", rows=rows)


# -------------------------
# Simple CRM
# -------------------------
@admin_bp.get("/crm")
@login_required
@require_admin
def crm_list():
    q = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "").strip()

    qry = CRMContact.query
    if q:
        like = f"%{q}%"
        qry = qry.filter(
            or_(
                CRMContact.business_name.ilike(like),
                CRMContact.contact_name.ilike(like),
                CRMContact.email.ilike(like),
                CRMContact.phone.ilike(like),
                CRMContact.domain.ilike(like),
                CRMContact.notes.ilike(like),
            )
        )
    if stage:
        qry = qry.filter(CRMContact.stage == stage)

    page = max(int(request.args.get("page", 1)), 1)
    per = min(max(int(request.args.get("per", 25)), 1), 200)
    rows = qry.order_by(desc(CRMContact.updated_at)).paginate(page=page, per_page=per, error_out=False)

    return render_template("admin/crm_list.html", rows=rows, q=q, stage=stage, stages=CRM_STAGES)


@admin_bp.get("/crm/new")
@login_required
@require_admin
def crm_new():
    return render_template("admin/crm_edit.html", item=None, stages=CRM_STAGES)


@admin_bp.post("/crm/new")
@login_required
@require_admin
def crm_create():
    form = request.form
    item = CRMContact(
        stage=form.get("stage") or "stranger",
        business_name=form.get("business_name") or "",
        contact_name=form.get("contact_name") or "",
        email=form.get("email") or "",
        phone=form.get("phone") or "",
        domain=form.get("domain") or "",
        address1=form.get("address1") or "",
        address2=form.get("address2") or "",
        city=form.get("city") or "",
        region=form.get("region") or "",
        postal_code=form.get("postal_code") or "",
        country=form.get("country") or "",
        source=form.get("source") or "",
        notes=form.get("notes") or "",
        owner_user_id=int(form.get("owner_user_id")) if form.get("owner_user_id") else None,
        account_id=int(form.get("account_id")) if form.get("account_id") else None,
    )
    db.session.add(item)
    db.session.commit()
    _audit("crm_create", note=f"id={item.id} {item.business_name}")
    flash("Contact created.", "success")
    return redirect(url_for("admin_bp.crm_detail", contact_id=item.id))


@admin_bp.get("/crm/<int:contact_id>")
@login_required
@require_admin
def crm_detail(contact_id: int):
    item = CRMContact.query.get_or_404(contact_id)
    return render_template("admin/crm_detail.html", item=item, stages=CRM_STAGES)


@admin_bp.get("/crm/<int:contact_id>/edit")
@login_required
@require_admin
def crm_edit(contact_id: int):
    item = CRMContact.query.get_or_404(contact_id)
    return render_template("admin/crm_edit.html", item=item, stages=CRM_STAGES)


@admin_bp.post("/crm/<int:contact_id>/edit")
@login_required
@require_admin
def crm_update(contact_id: int):
    item = CRMContact.query.get_or_404(contact_id)
    form = request.form

    item.stage = form.get("stage") or item.stage
    item.business_name = form.get("business_name") or item.business_name
    item.contact_name = form.get("contact_name") or item.contact_name
    item.email = form.get("email") or item.email
    item.phone = form.get("phone") or item.phone
    item.domain = form.get("domain") or item.domain
    item.address1 = form.get("address1") or item.address1
    item.address2 = form.get("address2") or item.address2
    item.city = form.get("city") or item.city
    item.region = form.get("region") or item.region
    item.postal_code = form.get("postal_code") or item.postal_code
    item.country = form.get("country") or item.country
    item.source = form.get("source") or item.source
    item.notes = form.get("notes") or item.notes
    item.owner_user_id = int(form.get("owner_user_id")) if form.get("owner_user_id") else item.owner_user_id
    item.account_id = int(form.get("account_id")) if form.get("account_id") else item.account_id

    db.session.commit()
    _audit("crm_update", note=f"id={item.id} {item.business_name}")
    flash("Contact updated.", "success")
    return redirect(url_for("admin_bp.crm_detail", contact_id=item.id))


# ============================================================================
# Google Ads AI Optimization - Admin Pages
# ============================================================================

@admin_bp.get("/google-ads/recommendations")
@login_required
@require_admin
def google_ads_recommendations():
    """View all AI recommendations (Google Ads, Analytics, Search Console) and their change log."""
    from app.models_ads import OptimizerRecommendation, OptimizerAction

    # Get filter parameters
    status_filter = request.args.get('status', 'all')
    source_type_filter = request.args.get('source_type', 'all')  # NEW: Filter by source
    account_id = request.args.get('account_id', type=int)
    category = request.args.get('category', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Build query
    query = OptimizerRecommendation.query

    if status_filter != 'all':
        query = query.filter(OptimizerRecommendation.status == status_filter)

    # NEW: Filter by source type
    if source_type_filter != 'all':
        query = query.filter(OptimizerRecommendation.source_type == source_type_filter)

    if account_id:
        query = query.filter(OptimizerRecommendation.account_id == account_id)

    if category != 'all':
        query = query.filter(OptimizerRecommendation.category == category)

    # Order by most recent first
    query = query.order_by(desc(OptimizerRecommendation.created_at))

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    recommendations = pagination.items

    # Get accounts for filter dropdown
    accounts_with_recs = db.session.query(
        OptimizerRecommendation.account_id,
        Account.name
    ).join(
        Account, OptimizerRecommendation.account_id == Account.id
    ).distinct().all()

    # Get actions for each recommendation
    rec_ids = [r.id for r in recommendations]
    actions = {}
    if rec_ids:
        all_actions = OptimizerAction.query.filter(
            OptimizerAction.recommendation_id.in_(rec_ids)
        ).all()
        for action in all_actions:
            if action.recommendation_id not in actions:
                actions[action.recommendation_id] = []
            actions[action.recommendation_id].append(action)

    # Get user names for actions
    user_ids = set()
    for action_list in actions.values():
        for action in action_list:
            if action.applied_by:
                user_ids.add(action.applied_by)

    users = {}
    if user_ids:
        user_records = User.query.filter(User.id.in_(user_ids)).all()
        users = {u.id: u for u in user_records}

    # Get account names
    account_ids = set(r.account_id for r in recommendations if r.account_id)
    account_names = {}
    if account_ids:
        account_records = Account.query.filter(Account.id.in_(account_ids)).all()
        account_names = {a.id: a.name or f"Account #{a.id}" for a in account_records}

    # Get category stats
    category_stats = db.session.query(
        OptimizerRecommendation.category,
        db.func.count(OptimizerRecommendation.id).label('count')
    ).filter(
        OptimizerRecommendation.status == 'open'
    ).group_by(OptimizerRecommendation.category).all()

    # Get status stats
    status_stats = db.session.query(
        OptimizerRecommendation.status,
        db.func.count(OptimizerRecommendation.id).label('count')
    ).group_by(OptimizerRecommendation.status).all()

    # NEW: Get source type stats
    source_type_stats = db.session.query(
        OptimizerRecommendation.source_type,
        db.func.count(OptimizerRecommendation.id).label('count')
    ).filter(
        OptimizerRecommendation.status == 'open'
    ).group_by(OptimizerRecommendation.source_type).all()

    return render_template(
        "admin/google_ads_recommendations.html",
        recommendations=recommendations,
        pagination=pagination,
        actions=actions,
        users=users,
        account_names=account_names,
        accounts_with_recs=accounts_with_recs,
        category_stats=dict(category_stats),
        status_stats=dict(status_stats),
        source_type_stats=dict(source_type_stats),  # NEW
        status_filter=status_filter,
        source_type_filter=source_type_filter,  # NEW
        account_id_filter=account_id,
        category_filter=category
    )


@admin_bp.get("/google-ads/settings")
@login_required
@require_admin
def google_ads_settings():
    """View and edit Google Ads AI optimization settings."""
    import os

    # Get current settings from environment/config
    settings = {
        'HIGH_SPEND_DAILY_THRESHOLD': os.getenv('HIGH_SPEND_DAILY_THRESHOLD', '1000'),
        'MEDIUM_SPEND_DAILY_THRESHOLD': os.getenv('MEDIUM_SPEND_DAILY_THRESHOLD', '500'),
        'OPENAI_MODEL': os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
        'OPENAI_API_KEY_SET': bool(os.getenv('OPENAI_API_KEY')),
    }

    # Get scheduler job status
    try:
        scheduler = current_app.scheduler
        jobs_info = []
        for job_id in ['generate_google_ads_insights_weekly', 'generate_google_ads_insights_daily']:
            job = scheduler.get_job(job_id)
            if job:
                jobs_info.append({
                    'id': job.id,
                    'name': job.name or job.id.replace('_', ' ').title(),
                    'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                    'trigger': str(job.trigger)
                })
    except:
        jobs_info = []

    # Get recent insights stats
    from app.models_ads import OptimizerRecommendation

    stats = {
        'total_recommendations': OptimizerRecommendation.query.count(),
        'open_recommendations': OptimizerRecommendation.query.filter_by(status='open').count(),
        'applied_recommendations': OptimizerRecommendation.query.filter_by(status='applied').count(),
        'dismissed_recommendations': OptimizerRecommendation.query.filter_by(status='dismissed').count(),
    }

    # Get accounts with Google Ads connected
    accounts_with_ads = Account.query.filter(
        Account.google_ads_connected == True
    ).count()

    return render_template(
        "admin/google_ads_settings.html",
        settings=settings,
        jobs_info=jobs_info,
        stats=stats,
        accounts_with_ads=accounts_with_ads
    )


@admin_bp.post("/google-ads/settings")
@login_required
@require_admin
def google_ads_settings_update():
    """Update Google Ads AI optimization settings."""
    import os

    # Note: These settings need to be updated in the actual code file
    # or via environment variables and app restart
    # This is a placeholder for the UI - actual implementation would need
    # to write to a config file or environment variable management system

    high_spend = request.form.get('high_spend_threshold', '1000')
    medium_spend = request.form.get('medium_spend_threshold', '500')

    # For now, just flash a message explaining what needs to be done
    flash(
        f"To apply these settings, update your environment variables:\n"
        f"HIGH_SPEND_DAILY_THRESHOLD={high_spend}\n"
        f"MEDIUM_SPEND_DAILY_THRESHOLD={medium_spend}\n"
        f"Then restart the application.",
        "info"
    )

    _audit("google_ads_settings_update", note=f"high={high_spend}, medium={medium_spend}")

    return redirect(url_for("admin_bp.google_ads_settings"))


@admin_bp.post("/google-ads/trigger-job/<job_id>")
@login_required
@require_admin
def google_ads_trigger_job(job_id: str):
    """Manually trigger a Google Ads insights job."""
    try:
        scheduler = current_app.scheduler
        job = scheduler.get_job(job_id)

        if job:
            # Trigger job to run immediately
            job.modify(next_run_time=datetime.now())
            flash(f"Job '{job_id}' triggered successfully. It will run shortly.", "success")
            _audit("google_ads_trigger_job", note=f"job_id={job_id}")
        else:
            flash(f"Job '{job_id}' not found.", "error")
    except Exception as e:
        flash(f"Failed to trigger job: {str(e)}", "error")

    return redirect(url_for("admin_bp.google_ads_settings"))


# ============================================================================
# AI Prompts Management
# ============================================================================

@admin_bp.get("/ai-prompts")
@login_required
@require_admin
def ai_prompts_list():
    """View and manage AI prompts for all services."""
    from app.models_ads import AIPrompt
    from app.services.ai_prompts_init import initialize_ai_prompts

    # Check if prompts exist, if not initialize
    prompt_count = AIPrompt.query.count()
    if prompt_count == 0:
        initialized = initialize_ai_prompts()
        flash(f"Initialized {initialized} default AI prompts.", "success")

    prompts = AIPrompt.query.order_by(AIPrompt.prompt_key).all()

    return render_template(
        "admin/ai_prompts.html",
        prompts=prompts
    )


@admin_bp.get("/ai-prompts/<int:prompt_id>")
@login_required
@require_admin
def ai_prompt_edit(prompt_id: int):
    """Edit a specific AI prompt."""
    from app.models_ads import AIPrompt

    prompt = AIPrompt.query.get_or_404(prompt_id)

    return render_template(
        "admin/ai_prompt_edit.html",
        prompt=prompt
    )


@admin_bp.post("/ai-prompts/<int:prompt_id>")
@login_required
@require_admin
def ai_prompt_update(prompt_id: int):
    """Update a specific AI prompt."""
    from app.models_ads import AIPrompt

    prompt = AIPrompt.query.get_or_404(prompt_id)

    # Update fields
    prompt.name = request.form.get('name', '').strip()
    prompt.description = request.form.get('description', '').strip()
    prompt.system_message = request.form.get('system_message', '').strip()
    prompt.prompt_template = request.form.get('prompt_template', '').strip()
    prompt.model = request.form.get('model', 'gpt-4o-mini').strip()

    try:
        prompt.temperature = float(request.form.get('temperature', 0.7))
    except ValueError:
        prompt.temperature = 0.7

    try:
        prompt.max_tokens = int(request.form.get('max_tokens', 2000))
    except ValueError:
        prompt.max_tokens = 2000

    prompt.is_active = request.form.get('is_active') == 'on'
    prompt.updated_by = current_user.id

    db.session.commit()

    flash(f"Updated prompt '{prompt.name}' successfully.", "success")
    _audit("ai_prompt_update", note=f"prompt_id={prompt_id}, key={prompt.prompt_key}")

    return redirect(url_for("admin_bp.ai_prompts_list"))


@admin_bp.post("/ai-prompts/init")
@login_required
@require_admin
def ai_prompts_initialize():
    """Initialize or reset AI prompts to defaults."""
    from app.services.ai_prompts_init import initialize_ai_prompts

    force = request.form.get('force') == 'on'
    count = initialize_ai_prompts(force=force)

    if force:
        flash(f"Reset {count} AI prompts to default values.", "success")
    else:
        flash(f"Initialized {count} missing AI prompts.", "success")

    _audit("ai_prompts_init", note=f"force={force}, count={count}")

    return redirect(url_for("admin_bp.ai_prompts_list"))
