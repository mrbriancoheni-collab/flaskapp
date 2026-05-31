from uuid import uuid4

from flask import render_template, redirect, url_for, flash, request

from app.multiloc import multiloc_bp
from app.auth.utils import login_required, current_account_id


@multiloc_bp.route("/", methods=["GET"])
@login_required
def dashboard():
    from app.models_multiloc import LocationGroup, LocationGroupMember, KeywordOverlap
    from app.models import GoogleAdsAuth

    aid = current_account_id()

    member_row = LocationGroupMember.query.filter_by(account_id=aid).first()
    if not member_row:
        return redirect(url_for("multiloc_bp.setup"))

    group = LocationGroup.query.get(member_row.group_id)
    members = LocationGroupMember.query.filter_by(group_id=group.id).all()

    # Check Google Ads connection for each member
    member_data = []
    for m in members:
        connected = GoogleAdsAuth.query.filter_by(account_id=m.account_id).first() is not None
        member_data.append({
            "member": m,
            "connected": connected,
        })

    overlap_count = KeywordOverlap.query.filter_by(group_id=group.id).count()

    return render_template(
        "multiloc/dashboard.html",
        group=group,
        member_data=member_data,
        overlap_count=overlap_count,
        current_aid=aid,
    )


@multiloc_bp.route("/setup", methods=["GET"])
@login_required
def setup():
    from app.models_multiloc import LocationGroupMember

    aid = current_account_id()
    existing = LocationGroupMember.query.filter_by(account_id=aid).first()
    if existing:
        return redirect(url_for("multiloc_bp.dashboard"))

    return render_template("multiloc/setup.html")


@multiloc_bp.route("/setup", methods=["POST"])
@login_required
def setup_post():
    from app.models_multiloc import LocationGroup, LocationGroupMember
    from app import db

    aid = current_account_id()

    name = request.form.get("name", "").strip() or "My Group"
    label = request.form.get("label", "").strip() or "Main Office"

    group = LocationGroup(
        name=name,
        primary_account_id=aid,
        join_token=uuid4().hex,
    )
    db.session.add(group)
    db.session.flush()  # get group.id

    member = LocationGroupMember(
        group_id=group.id,
        account_id=aid,
        location_label=label,
    )
    db.session.add(member)
    db.session.commit()

    flash("Group created", "success")
    return redirect(url_for("multiloc_bp.dashboard"))


@multiloc_bp.route("/join/<token>", methods=["GET"])
@login_required
def join(token):
    from app.models_multiloc import LocationGroup, LocationGroupMember
    from app import db

    aid = current_account_id()

    group = LocationGroup.query.filter_by(join_token=token).first()
    if not group:
        flash("Invalid join link.", "error")
        return redirect(url_for("multiloc_bp.setup"))

    existing = LocationGroupMember.query.filter_by(
        group_id=group.id, account_id=aid
    ).first()
    if existing:
        flash("Already a member", "info")
        return redirect(url_for("multiloc_bp.dashboard"))

    member = LocationGroupMember(
        group_id=group.id,
        account_id=aid,
        location_label="Location",
    )
    db.session.add(member)
    db.session.commit()

    flash("Joined group", "success")
    return redirect(url_for("multiloc_bp.dashboard"))


@multiloc_bp.route("/overlap", methods=["GET"])
@login_required
def overlap():
    from app.models_multiloc import LocationGroup, LocationGroupMember, KeywordOverlap

    aid = current_account_id()

    member_row = LocationGroupMember.query.filter_by(account_id=aid).first()
    if not member_row:
        return redirect(url_for("multiloc_bp.setup"))

    group = LocationGroup.query.get(member_row.group_id)

    # Build a label lookup for members
    members = LocationGroupMember.query.filter_by(group_id=group.id).all()
    label_map = {m.account_id: m.location_label for m in members}

    raw_overlaps = (
        KeywordOverlap.query
        .filter_by(group_id=group.id)
        .order_by(KeywordOverlap.detected_at.desc())
        .limit(500)
        .all()
    )

    # Group by (keyword_text, match_type)
    from collections import defaultdict
    grouped = defaultdict(list)
    for row in raw_overlaps:
        key = (row.keyword_text, row.match_type)
        grouped[key].append(row)

    # Build a sorted list for the template
    overlap_groups = []
    for (keyword_text, match_type), rows in sorted(grouped.items()):
        overlap_groups.append({
            "keyword_text": keyword_text,
            "match_type": match_type,
            "rows": rows,
        })

    return render_template(
        "multiloc/overlap.html",
        group=group,
        overlap_groups=overlap_groups,
        label_map=label_map,
        total_overlaps=len(raw_overlaps),
    )


@multiloc_bp.route("/leave", methods=["POST"])
@login_required
def leave():
    from app.models_multiloc import LocationGroup, LocationGroupMember
    from app import db

    aid = current_account_id()

    member_row = LocationGroupMember.query.filter_by(account_id=aid).first()
    if not member_row:
        flash("You are not in a group.", "info")
        return redirect(url_for("multiloc_bp.setup"))

    group_id = member_row.group_id
    group = LocationGroup.query.get(group_id)

    db.session.delete(member_row)
    db.session.flush()

    remaining = LocationGroupMember.query.filter_by(group_id=group_id).all()
    if not remaining:
        db.session.delete(group)
    elif group and group.primary_account_id == aid:
        # Hand off primary to the next remaining member
        group.primary_account_id = remaining[0].account_id

    db.session.commit()

    flash("Left location group", "success")
    return redirect(url_for("multiloc_bp.setup"))


@multiloc_bp.route("/scan", methods=["POST"])
@login_required
def scan():
    flash("Scan queued", "info")
    return redirect(url_for("multiloc_bp.overlap"))
