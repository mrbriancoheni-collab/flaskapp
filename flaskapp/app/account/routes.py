# app/account/routes.py
from __future__ import annotations
from flask import Blueprint, g, render_template
from app.auth.session import login_required

account_bp = Blueprint("account", __name__, url_prefix="/account")

@account_bp.route("/")
@login_required
def dashboard():
    user = g.user
    plan = user.account.plan if user and user.account else "free"
    return render_template("account/dashboard.html", plan=plan, user=user)
