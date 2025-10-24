# app/models_strategy.py
from datetime import datetime
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy.types import JSON as SAJSON
from app import db

JSONType = MySQLJSON().with_variant(SAJSON(), 'sqlite')

class MarketingStrategy(db.Model):
    __tablename__ = "marketing_strategies"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=True, index=True)

    # Basic business setup
    name = db.Column(db.String(255), nullable=False)  # internal name for the strategy
    business_name = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    industry = db.Column(db.String(255), nullable=True)
    locations = db.Column(JSONType, nullable=True)           # ["Austin, TX", "Remote US"]

    # POVs & targeting
    pov_ids = db.Column(JSONType, nullable=True)             # [1,2,3]
    target_audience = db.Column(JSONType, nullable=True)     # freeform notes + segments
    personas = db.Column(JSONType, nullable=True)            # optional deep personas

    # Inputs that produce the “doc”
    goals = db.Column(JSONType, nullable=True)               # list of SMART goals
    positioning = db.Column(db.Text, nullable=True)          # value prop & differentiation
    messaging = db.Column(JSONType, nullable=True)           # key messages by audience
    brand_voice = db.Column(db.Text, nullable=True)          # tone/voice/lexicon
    competitors = db.Column(JSONType, nullable=True)         # [{"name": "...", "url": "..."}]
    primary_keywords = db.Column(JSONType, nullable=True)    # ["best x", "y near me"]
    extra_keywords = db.Column(JSONType, nullable=True)

    channels = db.Column(JSONType, nullable=True)            # ["SEO","Email","Paid Search",...]
    content_plan = db.Column(JSONType, nullable=True)        # calendar-ish outline
    offers = db.Column(JSONType, nullable=True)              # promos/lead magnets
    constraints = db.Column(JSONType, nullable=True)         # legal/compliance/time/budget caps
    tools = db.Column(JSONType, nullable=True)               # GA4, GSC, ESP, CRM, CMS, WP, etc.
    budget_cents = db.Column(db.Integer, nullable=True)
    timeline = db.Column(JSONType, nullable=True)            # phases + dates
    kpis = db.Column(JSONType, nullable=True)                # metrics by channel

    # Generated (editable) output
    strategy_html = db.Column(db.Text, nullable=True)        # assembled doc

    # Meta
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
