# app/wp/__init__.py  (top of file)
from __future__ import annotations

from datetime import datetime, timedelta
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, current_app, jsonify
)
from app.auth.utils import login_required
from app import db

from app.models_wp import WPSite, WPJob, WPLog
from app.wp.wp_client import WPClient

pov_bp = Blueprint("pov_bp", __name__, url_prefix="/pov")


# ---------- helpers ----------
def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9\-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "pov"


def _account_id() -> int | None:
    from flask import session as _s
    acc = _s.get("account_id")
    if acc:
        return int(acc)
    uid = _s.get("user_id")
    if not uid:
        return None
    row = db.session.execute(
        text("SELECT account_id FROM users WHERE id=:id"),
        {"id": uid},
    ).fetchone()
    return int(row[0]) if row else None


def _user_id() -> int | None:
    from flask import session as _s
    uid = _s.get("user_id")
    return int(uid) if uid else None


def _current_site() -> WPSite | None:
    return WPSite.query.first()


def _clear_other_defaults(item: POVProfile) -> None:
    """Ensure only one default per scope (and site/service scoping where applicable)."""
    base = POVProfile.query.filter(
        POVProfile.account_id == item.account_id,
        POVProfile.id != item.id,
        POVProfile.scope == item.scope,
        POVProfile.is_archived.is_(False),
    )
    if item.scope in ("site", "service"):
        base = base.filter(POVProfile.site_id == item.site_id)
    if item.scope == "service":
        base = base.filter(POVProfile.service_key == item.service_key)
    changed = False
    for other in base.all():
        if other.is_default:
            other.is_default = False
            changed = True
    if changed:
        db.session.commit()


# ---------- pages ----------
@pov_bp.route("/", methods=["GET"])
@login_required
def index():
    aid = _account_id()
    if not aid:
        flash("Please log in.", "error")
        return redirect(url_for("auth_bp.login"))
    items = (
        POVProfile.query.filter_by(account_id=aid, is_archived=False)
        .order_by(POVProfile.updated_at.desc())
        .all()
    )
    return render_template("pov/index.html", items=items)


@pov_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    aid = _account_id()
    uid = _user_id()
    site = _current_site()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        scope = (request.form.get("scope") or "global").strip()
        service_key = (request.form.get("service_key") or "").strip().lower() or None
        industry = (request.form.get("industry") or "").strip().lower() or None
        pov_text = (request.form.get("pov_text") or "").strip()
        brand_voice = (request.form.get("brand_voice") or "").strip() or None
        tone = (request.form.get("tone") or "").strip() or None
        customer_needs = (request.form.get("customer_needs") or "").strip() or None
        expertise_bullets = (request.form.get("expertise_bullets") or "").strip() or None
        is_default = request.form.get("is_default") == "1"

        if not name or not pov_text:
            flash("Name and POV are required.", "error")
            return render_template("pov/edit.html", item=None, site=site)

        item = POVProfile(
            account_id=aid,
            user_id=uid,
            site_id=site.id if (scope in ("site", "service") and site) else None,
            scope=scope,
            name=name,
            slug=_slugify(name),
            service_key=service_key if scope == "service" else None,
            industry=industry,
            pov_text=pov_text,
            brand_voice=brand_voice,
            tone=tone,
            customer_needs=customer_needs,
            expertise_bullets=expertise_bullets,
            source="manual",
            is_default=bool(is_default),
        )
        db.session.add(item)
        db.session.commit()

        if item.is_default:
            _clear_other_defaults(item)

        flash("POV saved.", "success")
        return redirect(url_for("pov_bp.index"))

    return render_template("pov/edit.html", item=None, site=site)


@pov_bp.route("/<int:pov_id>/edit", methods=["GET", "POST"])
@login_required
def edit(pov_id: int):
    aid = _account_id()
    site = _current_site()
    item = POVProfile.query.filter_by(account_id=aid, id=pov_id).first_or_404()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        scope = (request.form.get("scope") or item.scope).strip()
        item.name = name or item.name
        item.slug = _slugify(item.name)
        item.scope = scope
        item.service_key = (request.form.get("service_key") or "").strip().lower() if scope == "service" else None
        item.industry = (request.form.get("industry") or "").strip().lower() or None
        item.pov_text = (request.form.get("pov_text") or "").strip() or item.pov_text
        item.brand_voice = (request.form.get("brand_voice") or "").strip() or None
        item.tone = (request.form.get("tone") or "").strip() or None
        item.customer_needs = (request.form.get("customer_needs") or "").strip() or None
        item.expertise_bullets = (request.form.get("expertise_bullets") or "").strip() or None

        make_default = request.form.get("is_default") == "1"
        item.is_default = bool(make_default)

        if scope in ("site", "service"):
            item.site_id = site.id if site else None

        db.session.commit()

        if item.is_default:
            _clear_other_defaults(item)

        flash("Updated.", "success")
        return redirect(url_for("pov_bp.index"))

    return render_template("pov/edit.html", item=item, site=site)


@pov_bp.route("/<int:pov_id>/archive", methods=["POST"])
@login_required
def archive(pov_id: int):
    aid = _account_id()
    item = POVProfile.query.filter_by(account_id=aid, id=pov_id).first_or_404()
    item.is_archived = True
    item.is_default = False
    db.session.commit()
    flash("Archived.", "success")
    return redirect(url_for("pov_bp.index"))


@pov_bp.route("/<int:pov_id>/default", methods=["POST"])
@login_required
def set_default(pov_id: int):
    aid = _account_id()
    item = POVProfile.query.filter_by(account_id=aid, id=pov_id, is_archived=False).first_or_404()
    item.is_default = True
    db.session.commit()
    _clear_other_defaults(item)
    flash("Set as default.", "success")
    return redirect(url_for("pov_bp.index"))


# ---------- Autosave API ----------
@pov_bp.route("/autosave/<draft_key>", methods=["GET"])
@login_required
def autosave_get(draft_key: str):
    aid = _account_id()
    if not aid:
        return jsonify({"ok": False, "error": "not_logged_in"}), 403
    item = (
        POVAutosave.query.filter_by(account_id=aid, draft_key=draft_key)
        .order_by(POVAutosave.updated_at.desc())
        .first()
    )
    if not item:
        return jsonify({"ok": True, "data": None})
    try:
        data = json.loads(item.data_json or "{}")
    except Exception:
        data = {}
    return jsonify({"ok": True, "data": data, "updated_at": item.updated_at.isoformat() + "Z"})


@pov_bp.route("/autosave", methods=["POST"])
@login_required
def autosave_set():
    aid = _account_id()
    if not aid:
        return jsonify({"ok": False, "error": "not_logged_in"}), 403

    try:
        body = request.get_json(force=True) or {}
        draft_key = (body.get("draft_key") or "").strip()
        scope = (body.get("scope") or "global").strip()
        service_key = (body.get("service_key") or "").strip().lower() or None
        fields = body.get("fields") or {}
        if not draft_key:
            return jsonify({"ok": False, "error": "draft_key_required"}), 400

        item = POVAutosave.query.filter_by(account_id=aid, draft_key=draft_key).first()
        if not item:
            item = POVAutosave(
                account_id=aid,
                user_id=_user_id(),
                site_id=(_current_site().id if _current_site() else None),
                scope=scope,
                service_key=service_key,
                draft_key=draft_key,
                data_json=json.dumps(fields),
            )
            db.session.add(item)
        else:
            item.scope = scope
            item.service_key = service_key
            item.data_json = json.dumps(fields)

        db.session.commit()
        return jsonify({"ok": True, "updated_at": item.updated_at.isoformat() + "Z"})
    except Exception as e:
        current_app.logger.exception("autosave_set failed")
        return jsonify({"ok": False, "error": str(e)}), 500
