# app/models_google.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict, Any

from flask import current_app
from sqlalchemy.dialects.mysql import LONGTEXT
from app import db


class GoogleOAuthToken(db.Model):
    __tablename__ = "google_oauth_tokens"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    # product: 'ga' (Analytics) or 'gsc' (Search Console)
    product = db.Column(db.String(10), nullable=False)

    # raw serialized credentials json (access_token, refresh_token, etc.)
    credentials_json = db.Column(LONGTEXT, nullable=False)

    # optional selections
    ga_property_id = db.Column(db.String(64), nullable=True)     # e.g. properties/123456789
    ga_property_name = db.Column(db.String(255), nullable=True)
    gsc_site = db.Column(db.String(255), nullable=True)          # e.g. https://example.com/

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @staticmethod
    def get_for(account_id: Optional[int], product: str) -> Optional["GoogleOAuthToken"]:
        q = GoogleOAuthToken.query.filter_by(product=product)
        if account_id is not None:
            q = q.filter((GoogleOAuthToken.account_id == account_id) | (GoogleOAuthToken.account_id.is_(None)))
        return q.order_by(GoogleOAuthToken.updated_at.desc()).first()

    def set_credentials(self, creds_json: Dict[str, Any]):
        import json
        self.credentials_json = json.dumps(creds_json)

    def get_credentials(self) -> Optional[dict]:
        import json
        try:
            return json.loads(self.credentials_json or "{}")
        except Exception:
            return None


def ensure_google_tables():
    """Call this once after deploy if you’re not running Alembic migrations."""
    with db.engine.begin() as conn:
        conn.execute(db.text("""
        CREATE TABLE IF NOT EXISTS google_oauth_tokens (
          id INT AUTO_INCREMENT PRIMARY KEY,
          account_id INT NULL,
          product VARCHAR(10) NOT NULL,
          credentials_json LONGTEXT NOT NULL,
          ga_property_id VARCHAR(64) NULL,
          ga_property_name VARCHAR(255) NULL,
          gsc_site VARCHAR(255) NULL,
          created_at DATETIME NOT NULL,
          updated_at DATETIME NOT NULL,
          INDEX idx_google_token_account (account_id),
          INDEX idx_google_token_product (product)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """))
