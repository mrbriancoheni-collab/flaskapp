# app/pages/__init__.py
from flask import Blueprint, render_template

pages_bp = Blueprint("pages", __name__)

@pages_bp.route("/about")
def about():
    return render_template("pages/about.html")

@pages_bp.route("/contact")
def contact():
    return render_template("pages/contact.html")

@pages_bp.route("/security")
def security():
    return render_template("pages/security.html")