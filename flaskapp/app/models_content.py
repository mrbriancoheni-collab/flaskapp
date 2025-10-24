# app/models_content.py (append)

from datetime import datetime
from app import db

class POVProfile(db.Model):
    __tablename__ = "pov_profiles"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer)
    site_id = db.Column(db.Integer, db.ForeignKey("wp_sites.id"))
    scope = db.Column(db.Enum("global","site","service", name="pov_scope"), default="global", nullable=False)

    name = db.Column(db.String(191), nullable=False)
    slug = db.Column(db.String(191), nullable=False)

    industry = db.Column(db.String(191))
    service_key = db.Column(db.String(191))

    pov_text = db.Column(db.Text, nullable=False)
    brand_voice = db.Column(db.String(255))
    tone = db.Column(db.String(40))
    customer_needs = db.Column(db.Text)
    expertise_bullets = db.Column(db.Text)
    answers_json = db.Column(db.Text)
    source = db.Column(db.String(40))

    is_default = db.Column(db.Boolean, default=False, nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("account_id", "slug", name="uq_account_slug"),
    )

    def as_dict(self):
        return {
            "id": self.id,
            "scope": self.scope,
            "name": self.name,
            "slug": self.slug,
            "industry": self.industry,
            "service_key": self.service_key,
            "pov_text": self.pov_text,
            "brand_voice": self.brand_voice,
            "tone": self.tone,
            "customer_needs": self.customer_needs,
            "expertise_bullets": self.expertise_bullets,
            "is_default": self.is_default,
            "is_archived": self.is_archived,
        }

# app/models_content.py (append)

from datetime import datetime
from app import db

class POVAutosave(db.Model):
    __tablename__ = "pov_autosaves"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer)
    site_id = db.Column(db.Integer)
    scope = db.Column(db.Enum("global","site","service", name="pov_scope_as"), default="global", nullable=False)
    service_key = db.Column(db.String(191))
    draft_key = db.Column(db.String(191), nullable=False)
    data_json = db.Column(db.Text, nullable=False)
    is_submitted = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("account_id", "draft_key", name="uq_autosave"),
    )
