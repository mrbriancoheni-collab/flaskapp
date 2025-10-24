# app/maps/__init__.py
from __future__ import annotations

import csv, io, json
from typing import List, Dict, Any, Optional
from datetime import datetime

from flask import (
    Blueprint, render_template, request, jsonify, flash, session, current_app
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required

# Create the blueprint FIRST so decorators can attach to it.
maps_bp = Blueprint("maps_bp", __name__, template_folder="../../templates")

# ----------------------------- helpers --------------------------------------
def _account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    row = db.session.execute(
        text("SELECT account_id FROM users WHERE id=:id"),
        {"id": uid},
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


# Try to import model classes if you created them (recommended),
# but keep graceful fallbacks so the UI still works if they’re absent.
try:
    from app.models import GeoPoint, AccountZipcode  # type: ignore
except Exception:  # pragma: no cover
    GeoPoint = None     # type: ignore
    AccountZipcode = None  # type: ignore


# ----------------------------- routes ---------------------------------------
@maps_bp.route("/", methods=["GET"], endpoint="index")
@login_required
def index():
    return render_template("maps/index.html")


# Heatmap: view
@maps_bp.route("/heatmap", methods=["GET"], endpoint="heatmap")
@login_required
def heatmap():
    return render_template("maps/heatmap.html")


# Heatmap: points API (used by the front-end map)
@maps_bp.route("/api/heatmap-points", methods=["GET"], endpoint="heatmap_points")
@login_required
def heatmap_points():
    aid = _account_id() or 0
    points: List[Dict[str, Any]] = []

    if GeoPoint:
        # ORM path
        rows = (
            GeoPoint.query.filter_by(account_id=aid)
            .order_by(GeoPoint.id.desc())
            .limit(5000)
            .all()
        )
        for r in rows:
            if r.lat is None or r.lng is None:
                continue
            points.append({
                "lat": float(r.lat),
                "lng": float(r.lng),
                "value": int(r.weight or 1),
                "label": r.label or "",
                "ts": r.occurred_at.isoformat() if r.occurred_at else None,
            })
    else:
        # Fallback raw SQL (if you haven’t created the model yet)
        try:
            sql = text(
                "SELECT lat, lng, weight, label, occurred_at "
                "FROM geo_points WHERE account_id=:aid ORDER BY id DESC LIMIT 5000"
            )
            for lat, lng, weight, label, occurred_at in db.session.execute(sql, {"aid": aid}):
                if lat is None or lng is None:
                    continue
                points.append({
                    "lat": float(lat),
                    "lng": float(lng),
                    "value": int(weight or 1),
                    "label": label or "",
                    "ts": occurred_at.isoformat() if occurred_at else None,
                })
        except Exception:
            current_app.logger.exception("Heatmap raw SQL failed")

    return jsonify({"ok": True, "count": len(points), "points": points})


# Heatmap: data ingest (CSV or JSON)
@maps_bp.route("/heatmap/ingest", methods=["GET", "POST"], endpoint="heatmap_ingest")
@login_required
def heatmap_ingest():
    """
    POST a CSV or JSON file containing lat/lng (and optional weight,label,occurred_at).
    CSV headers expected (case-insensitive): lat,lng[,weight,label,occurred_at]
    JSON expected: list of {lat,lng,weight?,label?,occurred_at?}
    """
    if request.method == "GET":
        return render_template("maps/ingest.html")

    aid = _account_id() or 0
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Please choose a CSV or JSON file to upload.", "error")
        return render_template("maps/ingest.html")

    created = 0
    skipped = 0

    def _persist(lat: float, lng: float, weight: int = 1, label: str = "", occurred_at: Optional[datetime] = None):
        nonlocal created
        if GeoPoint:
            gp = GeoPoint(
                account_id=aid,
                lat=lat,
                lng=lng,
                weight=weight,
                label=label[:255] if label else None,
                occurred_at=occurred_at,
                raw=None,
            )
            db.session.add(gp)
        else:
            db.session.execute(
                text(
                    "INSERT INTO geo_points (account_id, lat, lng, weight, label, occurred_at, created_at, updated_at) "
                    "VALUES (:aid,:lat,:lng,:weight,:label,:occurred_at, NOW(), NOW())"
                ),
                {"aid": aid, "lat": lat, "lng": lng, "weight": weight, "label": label[:255] if label else None,
                 "occurred_at": occurred_at},
            )
        created += 1

    try:
        filename = f.filename.lower()
        if filename.endswith(".csv"):
            content = f.read().decode("utf-8", errors="ignore")
            rdr = csv.DictReader(io.StringIO(content))
            for row in rdr:
                try:
                    lat = float((row.get("lat") or row.get("Lat") or row.get("latitude") or "").strip())
                    lng = float((row.get("lng") or row.get("Lng") or row.get("longitude") or "").strip())
                except Exception:
                    skipped += 1
                    continue
                weight = int((row.get("weight") or row.get("Weight") or 1) or 1)
                label = (row.get("label") or row.get("Label") or "").strip()
                ts = (row.get("occurred_at") or row.get("Occurred_At") or "").strip()
                occurred_at = None
                if ts:
                    try:
                        occurred_at = datetime.fromisoformat(ts)
                    except Exception:
                        pass
                _persist(lat, lng, weight, label, occurred_at)

        elif filename.endswith(".json"):
            data = json.loads(f.read().decode("utf-8", errors="ignore"))
            if not isinstance(data, list):
                raise ValueError("JSON must be a list of points.")
            for item in data:
                try:
                    lat = float(item.get("lat"))
                    lng = float(item.get("lng"))
                except Exception:
                    skipped += 1
                    continue
                weight = int(item.get("weight") or 1)
                label = (item.get("label") or "")[:255]
                occurred_at = None
                ts = item.get("occurred_at")
                if ts:
                    try:
                        occurred_at = datetime.fromisoformat(ts)
                    except Exception:
                        pass
                _persist(lat, lng, weight, label, occurred_at)
        else:
            flash("Unsupported file type. Upload a .csv or .json", "error")
            return render_template("maps/ingest.html")

        db.session.commit()
        flash(f"Ingest complete: {created} added, {skipped} skipped.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Heatmap ingest failed")
        flash("Upload failed. Check file format and try again.", "error")

    return render_template("maps/ingest.html")


# Zipcode coverage: view
@maps_bp.route("/zipcodes", methods=["GET"], endpoint="zipcodes")
@login_required
def zipcodes():
    aid = _account_id() or 0
    zips: List[str] = []

    if AccountZipcode:
        zips = [z.zipcode for z in AccountZipcode.query.filter_by(account_id=aid).order_by(AccountZipcode.zipcode).all()]
    else:
        # Fallback if you haven't created the table/model yet
        try:
            rows = db.session.execute(
                text("SELECT zipcode FROM account_zipcodes WHERE account_id=:aid ORDER BY zipcode"),
                {"aid": aid},
            ).fetchall()
            zips = [r[0] for r in rows]
        except Exception:
            zips = []

    return render_template("maps/zipcodes.html", zipcodes=zips)


# Zipcode coverage: save/update list (textarea with comma/space/line separated zips)
@maps_bp.route("/zipcodes", methods=["POST"], endpoint="zipcodes_save")
@login_required
def zipcodes_save():
    aid = _account_id() or 0
    raw = (request.form.get("zipcodes") or "").strip()

    # Normalize into 5-digit strings
    parts = [p.strip() for p in raw.replace(",", " ").split() if p.strip()]
    zips = []
    for p in parts:
        d = "".join(ch for ch in p if ch.isdigit())
        if len(d) == 5:
            zips.append(d)

    try:
        if AccountZipcode:
            # wipe-and-replace for simplicity
            AccountZipcode.query.filter_by(account_id=aid).delete()
            db.session.bulk_save_objects([AccountZipcode(account_id=aid, zipcode=z) for z in sorted(set(zips))])
        else:
            db.session.execute(text("DELETE FROM account_zipcodes WHERE account_id=:aid"), {"aid": aid})
            for z in sorted(set(zips)):
                db.session.execute(
                    text(
                        "INSERT INTO account_zipcodes (account_id, zipcode, created_at, updated_at) "
                        "VALUES (:aid,:z, NOW(), NOW())"
                    ),
                    {"aid": aid, "z": z},
                )
        db.session.commit()
        flash(f"Saved {len(set(zips))} zipcode(s).", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Saving zipcodes failed")
        flash("Could not save zipcodes.", "error")

    return zipcodes()  # re-render


# Zipcode map: renders polygons/markers client-side from saved list
@maps_bp.route("/zipcodes/map", methods=["GET"], endpoint="zipcodes_map")
@login_required
def zipcodes_map():
    return render_template("maps/zipcode_map.html")
