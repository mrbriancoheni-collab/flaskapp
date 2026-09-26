from __future__ import annotations
import json
from datetime import datetime
from app import db


class GA4AuditReport(db.Model):
    __tablename__ = "ga4_audit_reports"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=True, index=True)
    property_id = db.Column(db.String(64), nullable=False)
    property_name = db.Column(db.String(255), nullable=True)
    overall_score = db.Column(db.Float, nullable=True)
    overall_grade = db.Column(db.String(5), nullable=True)
    audit_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def get_data(self):
        return json.loads(self.audit_json) if self.audit_json else {}
