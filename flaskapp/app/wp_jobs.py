# app/models/wp_job.py
from datetime import datetime
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy import Index
from app import db

try:
    JSONType = MySQLJSON
except Exception:  # fallback if not using MySQL JSON dialect
    from sqlalchemy.types import Text as JSONType  # stores JSON as text

class WPJob(db.Model):
    __tablename__ = "wp_jobs"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=True)

    # What to do
    action = db.Column(db.String(50), nullable=False)  # e.g. 'publish_manual', 'generate_ai_post'
    # Where it is
    status = db.Column(
        db.String(20),
        nullable=False,
        default="queued",  # queued -> running -> done / failed
        index=True,
    )

    # Inputs / outputs
    payload = db.Column(JSONType, nullable=True)   # inputs (title/content for manual; brief for AI)
    result  = db.Column(JSONType, nullable=True)   # outputs (wp_post_id, preview_url, etc.)
    error   = db.Column(db.Text, nullable=True)    # last error, if any

    # Timing & control
    priority     = db.Column(db.SmallInteger, nullable=False, default=0, index=True)
    retries      = db.Column(db.SmallInteger, nullable=False, default=0)
    scheduled_at = db.Column(db.DateTime, nullable=True, index=True)
    started_at   = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

Index("ix_wp_jobs_status_created", WPJob.status, WPJob.created_at.desc())
Index("ix_wp_jobs_sched_prio", WPJob.scheduled_at, WPJob.priority.desc())
