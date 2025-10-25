# app/billing/init.py
from __future__ import annotations
from flask import Blueprint, render_template
from app.auth.session import login_required

billing_bp = Blueprint("billing", __name__, url_prefix="/billing")

@billing_bp.route("/choose")
@login_required
def choose_plan():
    # You can replace with live plan data pulled from Stripe
    plans = [
        {"id": "free", "name": "Free", "price": 0, "benefits": ["Basic listing sync"]},
        {"id": "monthly", "name": "Growth (Monthly)", "price": 99, "benefits": [
            "AI campaign suggestions", "Lead quality insights", "A/B creative tips"
        ]},
        {"id": "annual", "name": "Growth (Annual)", "price": 999, "benefits": [
            "Everything in Monthly", "2 months free"
        ]},
    ]
    return render_template("billing/choose_plan.html", plans=plans)
