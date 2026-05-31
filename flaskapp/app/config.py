import os
import re

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this")
    # Only override SQLALCHEMY_DATABASE_URI if explicitly set in environment;
    # otherwise let the default from create_app() remain.
    _db_uri = os.environ.get("SQLALCHEMY_DATABASE_URI")
    if _db_uri:
        # Strip charset from the URL — some pymysql versions don't recognise
        # 'utf8mb4' or even 'utf8' via charset_by_name(). Pass it via
        # SQLALCHEMY_ENGINE_OPTIONS connect_args instead (see below).
        _db_uri = re.sub(r'[?&]charset=[^&]*', '', _db_uri).rstrip('?&')
        SQLALCHEMY_DATABASE_URI = _db_uri
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"charset": "utf8mb4"},
        "pool_pre_ping": True,
    }

    # Stripe keys
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY") or os.environ.get("STRIPE_PUBLIC_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    # ── Tier: Growth ($99/mo · $79/mo annual) ───────────────────────────────
    STRIPE_GROWTH_MONTHLY_PRICE_ID = os.environ.get("STRIPE_GROWTH_MONTHLY_PRICE_ID", "")
    STRIPE_GROWTH_YEARLY_PRICE_ID  = os.environ.get("STRIPE_GROWTH_YEARLY_PRICE_ID", "")
    STRIPE_GROWTH_MONTHLY_LINK     = os.environ.get("STRIPE_GROWTH_MONTHLY_LINK", "")
    STRIPE_GROWTH_YEARLY_LINK      = os.environ.get("STRIPE_GROWTH_YEARLY_LINK", "")

    # ── Tier: Pro ($249/mo · $199/mo annual) ────────────────────────────────
    STRIPE_PRO_MONTHLY_PRICE_ID = os.environ.get("STRIPE_PRO_MONTHLY_PRICE_ID", "")
    STRIPE_PRO_YEARLY_PRICE_ID  = os.environ.get("STRIPE_PRO_YEARLY_PRICE_ID", "")
    STRIPE_PRO_MONTHLY_LINK     = os.environ.get("STRIPE_PRO_MONTHLY_LINK", "")
    STRIPE_PRO_YEARLY_LINK      = os.environ.get("STRIPE_PRO_YEARLY_LINK", "")

    # ── Tier: Managed ($997/mo) ──────────────────────────────────────────────
    STRIPE_MANAGED_MONTHLY_PRICE_ID = os.environ.get("STRIPE_MANAGED_MONTHLY_PRICE_ID", "")
    STRIPE_MANAGED_MONTHLY_LINK     = os.environ.get("STRIPE_MANAGED_MONTHLY_LINK", "")

    # ── Legacy price IDs (existing customers — do not remove) ───────────────
    # Old single-tier setup: monthly=$250, annual=$2,400/yr
    STRIPE_MONTHLY_PRICE_ID = (
        os.environ.get("STRIPE_MONTHLY_PRICE_ID")
        or os.environ.get("STRIPE_PRICE_BASIC", "")
    )
    STRIPE_YEARLY_PRICE_ID = (
        os.environ.get("STRIPE_YEARLY_PRICE_ID")
        or os.environ.get("STRIPE_PRICE_PRO", "")
    )
    STRIPE_MONTHLY_LINK = os.environ.get("STRIPE_MONTHLY_LINK", "")
    STRIPE_YEARLY_LINK  = os.environ.get("STRIPE_YEARLY_LINK", "")

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

    # Plan tier names recognised as paid (used by is_paid_account and plan_required)
    PAID_PLANS = ('growth', 'pro', 'managed', 'active', 'trialing', 'basic', 'premium')

    # Optional
    BASE_URL = os.environ.get("BASE_URL", "")
