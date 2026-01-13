# app/account.py
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
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
    account = current_user.account
    subscription = account.subscription
    # TODO: call Stripe to update subscription plan here
    subscription.plan = new_plan
    subscription.status = 'active'
    db.session.commit()
    return redirect(url_for('account_bp.account_profile'))

@account_bp.route('/account/cancel', methods=['POST'])
@login_required
def account_cancel():
    account = current_user.account
    subscription = account.subscription
    # TODO: call Stripe API to cancel subscription if needed
    subscription.status = 'canceled'
    account.status = 'canceled'
    db.session.commit()
    return redirect(url_for('account_bp.account_profile'))


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
