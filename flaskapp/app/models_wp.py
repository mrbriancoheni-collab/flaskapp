# app/models_wp.py
from datetime import datetime
from app import db
from sqlalchemy.sql import func

class WPSite(db.Model):
    __tablename__ = "wp_sites"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, nullable=True)
    base_url = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(190), nullable=False)
    app_password = db.Column(db.String(255), nullable=False)
    default_category = db.Column(db.String(191))
    default_tag = db.Column(db.String(191))
    autopilot_enabled = db.Column(db.Boolean, default=False, nullable=False)
    autopilot_daily_new = db.Column(db.Integer, default=1, nullable=False)
    autopilot_daily_refresh = db.Column(db.Integer, default=1, nullable=False)
    autopilot_require_approval = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime)

class WPJob(db.Model):
    __tablename__ = "wp_jobs"
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("wp_sites.id"), nullable=False)
    kind = db.Column(db.String(32), nullable=False)  # 'publish' or 'refresh'
    payload = db.Column(db.JSON, nullable=False, default={})  # title/html/meta/etc OR post_id/changes
    run_at = db.Column(db.DateTime, nullable=True)  # when to run (null = ASAP)
    status = db.Column(db.String(32), nullable=False, default="queued")  # queued|running|done|error
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class WPLog(db.Model):
    __tablename__ = "wp_logs"
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("wp_sites.id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("wp_jobs.id"), nullable=True)
    level = db.Column(db.String(16), default="info", nullable=False)  # info|warn|error
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
