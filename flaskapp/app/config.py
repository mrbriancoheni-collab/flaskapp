import os

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this")
    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Stripe keys
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    # Use the new env var names
    STRIPE_MONTHLY_PRICE_ID = os.environ.get("STRIPE_MONTHLY_PRICE_ID", "")
    STRIPE_YEARLY_PRICE_ID = os.environ.get("STRIPE_YEARLY_PRICE_ID", "")

    # Checkout redirect URLs
    STRIPE_SUCCESS_URL = os.environ.get("STRIPE_SUCCESS_URL", "/account/dashboard?payment=success")
    STRIPE_CANCEL_URL = os.environ.get("STRIPE_CANCEL_URL", "/account/dashboard?payment=cancelled")

    # Backward-compat fallback if you still had the old names set
    if not STRIPE_MONTHLY_PRICE_ID:
        STRIPE_MONTHLY_PRICE_ID = os.environ.get("STRIPE_PRICE_BASIC", "")
    if not STRIPE_YEARLY_PRICE_ID:
        STRIPE_YEARLY_PRICE_ID = os.environ.get("STRIPE_PRICE_PRO", "")

    GOOGLE_ADS_DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN") or None
    GOOGLE_ADS_LOGIN_CUSTOMER_ID = (os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or "").replace("-", "") or None
    GOOGLE_ADS_CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID","")
    GOOGLE_ADS_CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET","")
    GOOGLE_ADS_REDIRECT_URI = os.getenv("GOOGLE_ADS_REDIRECT_URI","http://localhost:8000/oauth/google-ads/callback")
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

    # Email settings
    EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "smtp")  # 'smtp' or 'sendgrid'
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "noreply@fieldsprout.com")
    EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "FieldSprout")

    # SMTP settings (if using SMTP provider)
    SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

    # SendGrid settings (if using SendGrid provider)
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

    # Sentry error tracking and monitoring
    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
    SENTRY_ENVIRONMENT = os.environ.get("SENTRY_ENVIRONMENT", os.environ.get("ENVIRONMENT", "production"))
    SENTRY_RELEASE = os.environ.get("SENTRY_RELEASE", os.environ.get("GIT_COMMIT", "unknown"))
    SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))  # 10% of requests
    SENTRY_PROFILES_SAMPLE_RATE = float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.1"))  # 10% profiling
    SENTRY_SAMPLE_RATE = float(os.environ.get("SENTRY_SAMPLE_RATE", "1.0"))  # 100% of errors

    # Optional
    BASE_URL = os.environ.get("BASE_URL", "")
