from datetime import datetime
from app import db

class GoogleToken(db.Model):
    __tablename__ = "google_tokens"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True)
    access_token = db.Column(db.Text)
    refresh_token = db.Column(db.Text)
    expiry = db.Column(db.DateTime)
    scopes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GAStat(db.Model):
    __tablename__ = "ga_stats"
    id = db.Column(db.Integer, primary_key=True)
    users_28d = db.Column(db.Integer)
    sessions_28d = db.Column(db.Integer)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def latest():
        return GAStat.query.order_by(GAStat.fetched_at.desc()).first()

class GSCStat(db.Model):
    __tablename__ = "gsc_stats"
    id = db.Column(db.Integer, primary_key=True)
    clicks_28d = db.Column(db.Integer)
    impr_28d = db.Column(db.Integer)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def latest():
        return GSCStat.query.order_by(GSCStat.fetched_at.desc()).first()
