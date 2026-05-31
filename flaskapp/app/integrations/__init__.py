from flask import Blueprint

integrations_hub_bp = Blueprint("integrations_hub_bp", __name__, url_prefix="/account/integrations")

from app.integrations import routes  # noqa
