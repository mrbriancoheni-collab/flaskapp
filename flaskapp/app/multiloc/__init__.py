from flask import Blueprint
multiloc_bp = Blueprint("multiloc_bp", __name__, url_prefix="/account/locations")
from app.multiloc import routes  # noqa
