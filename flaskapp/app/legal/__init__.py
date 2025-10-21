# app/legal/__init__.py
from flask import Blueprint, render_template

legal_bp = Blueprint("legal_bp", __name__, template_folder="../../")

@legal_bp.route("/privacy")
def privacy():
    return render_template("privacy_policy.html")

@legal_bp.route("/terms")
def terms():
    return render_template("terms_of_service.html")
