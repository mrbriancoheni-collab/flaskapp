# app/models_geo.py
from app import db
from sqlalchemy.dialects.mysql import JSON

class GeoPoint(db.Model):
    __tablename__ = "geo_points"
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, index=True, nullable=False)
    source = db.Column(db.String(64), index=True)           # 'glsa', 'yelp', 'csv', 'manual', etc.
    name = db.Column(db.String(255))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    address = db.Column(db.String(255))
    city = db.Column(db.String(128))
    state = db.Column(db.String(32))
    zip = db.Column(db.String(16), index=True)
    lat = db.Column(db.Float, index=True)
    lng = db.Column(db.Float, index=True)
    occurred_at = db.Column(db.DateTime)                     # when the lead/job happened
    raw = db.Column(JSON)                                    # original payload if any
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# Optional: for polygon rendering later
class ZipBoundary(db.Model):
    __tablename__ = "zip_boundaries"
    id = db.Column(db.Integer, primary_key=True)
    zip = db.Column(db.String(16), unique=True, index=True)
    centroid_lat = db.Column(db.Float)
    centroid_lng = db.Column(db.Float)
    polygon_geojson = db.Column(db.Text)  # store as text; parse to GeoJSON in UI
