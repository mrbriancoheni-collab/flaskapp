import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this")
    # Only override SQLALCHEMY_DATABASE_URI if explicitly set in environment;
    # otherwise let the default from create_app() remain.
    _db_uri = os.environ.get("SQLALCHEMY_DATABASE_URI")
    if _db_uri:
        SQLALCHEMY_DATABASE_URI = _db_uri
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Stripe keys
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY") or os.environ.get("STRIPE_PUBLIC_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    # Price IDs for checkout sessions
    STRIPE_MONTHLY_PRICE_ID = os.environ.get("STRIPE_MONTHLY_PRICE_ID", "")
    STRIPE_YEARLY_PRICE_ID = os.environ.get("STRIPE_YEARLY_PRICE_ID", "")

    # Payment Links (alternative to checkout sessions)
    STRIPE_MONTHLY_LINK = os.environ.get("STRIPE_MONTHLY_LINK", "")
    STRIPE_YEARLY_LINK = os.environ.get("STRIPE_YEARLY_LINK", "")

    # Backward-compat fallback if you still had the old names set
    if not STRIPE_MONTHLY_PRICE_ID:
        STRIPE_MONTHLY_PRICE_ID = os.environ.get("STRIPE_PRICE_BASIC", "")
    if not STRIPE_YEARLY_PRICE_ID:
        STRIPE_YEARLY_PRICE_ID = os.environ.get("STRIPE_PRICE_PRO", "")

    # Google Ads API configuration (for existing integrations)
    GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or None
    GOOGLE_ADS_LOGIN_CUSTOMER_ID = (os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "").replace("-", "") or None
    GOOGLE_ADS_CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID","")
    GOOGLE_ADS_CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET","")

    # Default redirect URI for Ads Grader (separate from main Google OAuth)
    # Main Google OAuth uses GOOGLE_REDIRECT_URI for /account/google/callback
    # Ads Grader uses GOOGLE_ADS_REDIRECT_URI for /ads-grader/connect/callback
    GOOGLE_ADS_REDIRECT_URI = os.getenv("GOOGLE_ADS_REDIRECT_URI") or "https://fieldsprout.io/ads-grader/connect/callback"
    APP_FERNET_KEY = os.getenv("APP_FERNET_KEY","")  # set in prod
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY","")
    
    GMB_INSIGHTS_MAX_PER_RUN = 25      # how many accounts per daily run
    GMB_INSIGHTS_INTERVAL_DAYS = 27    # minimum days between insights per account

    GOOGLE_OAUTH_SCOPES = tuple(
        s.strip() for s in os.getenv(
            "GOOGLE_OAUTH_SCOPES",
            "https://www.googleapis.com/auth/webmasters.readonly"
        ).split(",")
    )

    # Password policy (3c)
    PASSWORD_MIN_LENGTH = 12
    PASSWORD_REQUIRE_UPPER = True
    PASSWORD_REQUIRE_LOWER = True
    PASSWORD_REQUIRE_DIGIT = True
    PASSWORD_REQUIRE_SPECIAL = True
    PASSWORD_USE_ZXCVBN = False  # set True if you install zxcvbn

    # Email provider configuration
    EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "brevo")  # Use Brevo as default provider
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
    BREVO_FROM_EMAIL = os.environ.get("BREVO_FROM_EMAIL", "noreply@fieldsprout.io")
    BREVO_FROM_NAME = os.environ.get("BREVO_FROM_NAME", "FieldSprout")
    # Physical mailing address shown in CAN-SPAM footer — required by law and Brevo
    BREVO_COMPANY_ADDRESS = os.environ.get("BREVO_COMPANY_ADDRESS", "FieldSprout Inc., 1234 Main St, Suite 100, Austin, TX 78701")

    # Lead automation enabled by default
    LEAD_AUTOMATION_ENABLED = os.environ.get("LEAD_AUTOMATION_ENABLED", "True").lower() == "true"

    # Optional
    BASE_URL = os.environ.get("BASE_URL", "")
