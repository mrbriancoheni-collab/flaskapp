# app/team/__init__.py
from flask import Blueprint

team_bp = Blueprint("team", __name__, url_prefix="/team")

from app.team import routes
