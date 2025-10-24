# app/account.py
from flask import Blueprint, render_template, request, redirect, url_for, session
from app.auth.utils import login_required, current_user
from app.models import db, Account, Subscription

account_bp = Blueprint('account_bp', __name__, template_folder='../templates')

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
