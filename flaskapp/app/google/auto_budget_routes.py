# app/google/auto_budget_routes.py
"""
Google Ads Auto-Budget Routes

The full auto-budget feature lives at /account/auto-budget (account blueprint).
This thin blueprint redirects the legacy Google-specific URL to that page so
that any existing links or bookmarks continue to work.
"""

from flask import Blueprint, redirect

auto_budget_bp = Blueprint(
    "google_auto_budget_bp", __name__, url_prefix="/account/google/ads/auto-budget"
)


@auto_budget_bp.route("/", methods=["GET"])
def index():
    return redirect("/account/auto-budget")
