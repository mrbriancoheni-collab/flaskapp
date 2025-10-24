import os, sys

# Ensure we import from this app root
APP_ROOT = os.path.dirname(__file__)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# Guard against legacy env that broke Python earlier
os.environ.pop("PYTHONHOME", None)
os.environ.pop("PYTHONPATH", None)


os.environ.setdefault("GOOGLE_ADS_DEVELOPER_TOKEN", "BVH9TCTe66hciT3TrMrKxg")

# Use the factory defined in app/__init__.py
from app import application  # create_app() already called in app/__init__.py
