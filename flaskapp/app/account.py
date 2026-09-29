# app/account.py
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, flash
from app.auth.utils import login_required, current_user
from app.models import db, Account, Subscription

account_bp = Blueprint('account_bp', __name__, template_folder='../templates')

# Also create an API blueprint for AJAX endpoints
api_bp = Blueprint('api_bp', __name__, url_prefix='/api')

@account_bp.route('/account', methods=['GET'])
@login_required
def account_profile():
    account = current_user.account
    return render_template('account/profile.html', account=account, subscription=account.subscription)

@account_bp.route('/account/change-plan', methods=['POST'])
@login_required
def account_change_plan():
    new_plan = request.form.get('plan')
    new_price_id = request.form.get('price_id')
    account = current_user.account

    try:
        from app.models_billing import Subscription as BillingSubscription
        sub = BillingSubscription.query.filter_by(user_id=str(current_user.id)).first()
        if sub and sub.stripe_subscription_id and new_price_id:
            from app.services.stripe_service import upgrade_subscription
            upgrade_subscription(sub.stripe_subscription_id, new_price_id)
            flash("Plan updated successfully.", "success")
        else:
            flash("Could not locate your subscription to update.", "warning")
    except Exception as e:
        flash(f"Plan change failed: {e}", "danger")

    return redirect(url_for('account_bp.account_profile'))

@account_bp.route('/account/cancel', methods=['POST'])
@login_required
def account_cancel():
    account = current_user.account

    try:
        from app.models_billing import Subscription as BillingSubscription
        sub = BillingSubscription.query.filter_by(user_id=str(current_user.id)).first()
        if sub and sub.stripe_subscription_id:
            from app.services.stripe_service import cancel_subscription
            cancel_subscription(sub.stripe_subscription_id, immediate=False)
            flash("Your subscription will cancel at the end of the current billing period.", "info")
        else:
            # No Stripe subscription — just mark locally
            if account.subscription:
                account.subscription.status = 'canceled'
            account.status = 'canceled'
            db.session.commit()
            flash("Account cancelled.", "info")
    except Exception as e:
        flash(f"Cancellation failed: {e}", "danger")

    return redirect(url_for('account_bp.account_profile'))


# ---------------------------------------------------------------------------
# Manual job log — for accounts without a connected CRM
# ---------------------------------------------------------------------------

@account_bp.route('/account/jobs', methods=['GET'])
@login_required
def jobs_list():
    account = current_user.account
    # Show last 50 NPS surveys as a proxy for "logged jobs"
    try:
        from app.models_tooling import NpsSurvey
        recent = (
            NpsSurvey.query
            .filter_by(account_id=account.id)
            .order_by(NpsSurvey.created_at.desc())
            .limit(50)
            .all()
        )
    except Exception:
        recent = []
    return render_template('account/jobs.html', account=account, recent=recent)


@account_bp.route('/account/jobs/log', methods=['POST'])
@login_required
def log_job():
    """Log a completed job and fire review/NPS/referral automations."""
    account = current_user.account
    customer_name = request.form.get('customer_name', '').strip() or None
    phone = request.form.get('phone', '').strip() or None
    email = request.form.get('email', '').strip() or None
    job_type = request.form.get('job_type', '').strip() or None

    if not (phone or email):
        flash("Please provide at least a phone number or email.", "warning")
        return redirect(url_for('account_bp.jobs_list'))

    try:
        from app.services.review_request_service import on_crm_job_completed

        class _Job:
            customer_name = None
            customer_phone = None
            customer_email = None
            job_type = None

        job = _Job()
        job.customer_name = customer_name
        job.customer_phone = phone
        job.customer_email = email
        job.job_type = job_type

        on_crm_job_completed(account.id, job)
        flash(
            f"Job logged for {customer_name or email or phone}. "
            "Review request, NPS survey, and referral request queued.",
            "success",
        )
    except Exception as e:
        flash(f"Error logging job: {e}", "danger")

    return redirect(url_for('account_bp.jobs_list'))


# API endpoints for AJAX calls
@api_bp.route('/account/update-industry', methods=['POST'])
@login_required
def update_industry():
    """Update account industry field (used by onboarding) - DEPRECATED: industry field removed"""
    try:
        data = request.get_json() or {}
        industry = data.get('industry', '').strip()

        if not industry:
            return jsonify({"error": "Industry is required"}), 400

        # NOTE: Industry field has been removed from the database
        # This endpoint is kept for backward compatibility but doesn't save anything
        # The industry is now stored in BusinessProfile model instead

        return jsonify({"ok": True, "industry": industry, "note": "Industry field deprecated"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
