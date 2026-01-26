import os, sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Ensure we import from this app root
APP_ROOT = os.path.dirname(__file__)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

# Guard against legacy env that broke Python earlier
os.environ.pop("PYTHONHOME", None)
os.environ.pop("PYTHONPATH", None)

# Setup early logging BEFORE importing the app
LOG_FILE = os.path.join(APP_ROOT, 'stderr.log')

# Write directly to file first to confirm we can write
try:
    with open(LOG_FILE, 'a') as f:
        f.write(f"\n=== PASSENGER STARTUP {datetime.now()} ===\n")
        f.write(f"APP_ROOT: {APP_ROOT}\n")
        f.write(f"Python: {sys.version}\n")
        f.flush()
except Exception as e:
    pass  # Can't write, will try alternate location

try:
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))

    # Configure root logger
    logging.basicConfig(level=logging.DEBUG, handlers=[file_handler])
    logging.info(f"Logging initialized to: {LOG_FILE}")
except Exception as e:
    with open(LOG_FILE, 'a') as f:
        f.write(f"Failed to setup logging: {e}\n")

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

# Stripe Configuration
# Direct payment links (public URLs, safe to commit)
os.environ.setdefault("STRIPE_MONTHLY_LINK", "https://buy.stripe.com/cNifZagasf3v9Rx4f10ZW02")
os.environ.setdefault("STRIPE_YEARLY_LINK", "https://buy.stripe.com/4gM8wI1fy6wZgfVcLx0ZW01")

# Price IDs and secret keys should be set in .env file or hosting environment variables
# os.environ.setdefault("STRIPE_SECRET_KEY", "")
# os.environ.setdefault("STRIPE_PUBLIC_KEY", "")
# os.environ.setdefault("STRIPE_MONTHLY_PRICE_ID", "")
# os.environ.setdefault("STRIPE_YEARLY_PRICE_ID", "")

# Use the factory defined in app/__init__.py
from app import application  # create_app() already called in app/__init__.py
