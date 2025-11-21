import os, sys

# Ensure we import from this app root
APP_ROOT = os.path.dirname(__file__)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# Guard against legacy env that broke Python earlier
os.environ.pop("PYTHONHOME", None)
os.environ.pop("PYTHONPATH", None)

# Load environment variables from .env file
def load_env_file(env_path):
    """Load environment variables from .env file if it exists"""
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith('#'):
                    # Split on first = only
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        # Only set if not already in environment
                        if key and not os.environ.get(key):
                            os.environ[key] = value

# Load .env file from same directory as this file
env_file = os.path.join(APP_ROOT, '.env')
load_env_file(env_file)

os.environ.setdefault("GOOGLE_ADS_DEVELOPER_TOKEN", "BVH9TCTe66hciT3TrMrKxg")

# Stripe Configuration - Set these values manually on production
# os.environ.setdefault("STRIPE_SECRET_KEY", "")
# os.environ.setdefault("STRIPE_PUBLIC_KEY", "")
# os.environ.setdefault("STRIPE_MONTHLY_PRICE_ID", "")
# os.environ.setdefault("STRIPE_YEARLY_PRICE_ID", "")
# os.environ.setdefault("STRIPE_MONTHLY_LINK", "")
# os.environ.setdefault("STRIPE_YEARLY_LINK", "")

# Use the factory defined in app/__init__.py
from app import application  # create_app() already called in app/__init__.py
