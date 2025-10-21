# app/team/routes.py
"""
Team management routes for multi-user collaboration.

Features:
- View team members
- Invite new members
- Accept invitations
- Remove team members
- Change member roles
- Seat limit enforcement
"""

from flask import render_template, request, redirect, url_for, flash, current_app, g, jsonify
from datetime import datetime

from app.team import team_bp
from app import db
from app.models import User, Account
from app.models_team import TeamInvite, TeamMember, can_add_team_member, get_account_seat_usage, get_account_seat_limit
from app.models_audit import AuditAction, log_team_action, log_subscription_action
from app.auth.session_utils import login_required
from app.auth.permissions import require_permission, require_admin, check_seat_limit, can_manage_user


@team_bp.route("/members")
@login_required
def members():
    """Display team members page."""
    account = Account.query.get(g.user.account_id)

    # Get all team members
    team_members = User.query.filter_by(account_id=g.user.account_id).order_by(
        User.created_at.asc()
    ).all()

    # Get pending invites
    pending_invites = TeamInvite.query.filter_by(
        account_id=g.user.account_id,
        status="pending"
    ).filter(
        TeamInvite.expires_at > datetime.utcnow()
    ).order_by(TeamInvite.created_at.desc()).all()

    # Get seat limit info
    seat_limit = get_account_seat_limit(account)
    seat_usage = get_account_seat_usage(g.user.account_id)
    can_add, _ = can_add_team_member(account)

    return render_template(
        "team/members.html",
        team_members=team_members,
        pending_invites=pending_invites,
        seat_limit=seat_limit,
        seat_usage=seat_usage,
        can_add_member=can_add,
        account=account
    )


@team_bp.route("/invite", methods=["POST"])
@login_required
@require_permission("invite_users")
@check_seat_limit
def invite():
    """Send a team invitation."""
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "member")

    if not email:
        flash("Email is required", "error")
        return redirect(url_for("team.members"))

    # Validate role
    if role not in ["owner", "admin", "member"]:
        flash("Invalid role", "error")
        return redirect(url_for("team.members"))

    # Only owners can invite other owners or admins
    if role in ["owner", "admin"] and g.user.role != "owner":
        flash("Only account owners can invite admins or other owners", "error")
        return redirect(url_for("team.members"))

    # Check if user already exists in this account
    existing_user = User.query.filter_by(
        email=email,
        account_id=g.user.account_id
    ).first()

    if existing_user:
        flash(f"{email} is already a member of your team", "error")
        return redirect(url_for("team.members"))

    # Check if there's already a pending invite
    existing_invite = TeamInvite.query.filter_by(
        email=email,
        account_id=g.user.account_id,
        status="pending"
    ).filter(
        TeamInvite.expires_at > datetime.utcnow()
    ).first()

    if existing_invite:
        flash(f"An invitation has already been sent to {email}", "warning")
        return redirect(url_for("team.members"))

    # Create invite
    invite = TeamInvite(
        account_id=g.user.account_id,
        email=email,
        role=role,
        invited_by_user_id=g.user.id
    )

    db.session.add(invite)
    db.session.commit()

    # Audit log
    log_team_action(
        AuditAction.TEAM_MEMBER_INVITED,
        account_id=g.user.account_id,
        actor_id=g.user.id,
        email=email,
        role=role,
        invite_id=invite.id
    )

    # Send invitation email
    try:
        send_team_invite_email(invite, g.user)
        flash(f"Invitation sent to {email}", "success")
    except Exception as e:
        current_app.logger.error(f"Failed to send invite email to {email}: {e}", exc_info=True)
        flash(f"Invitation created but email failed to send. Share this link: {get_invite_url(invite)}", "warning")

    return redirect(url_for("team.members"))


@team_bp.route("/invite/<token>")
def accept_invite(token):
    """Accept a team invitation (public, no login required)."""
    invite = TeamInvite.query.filter_by(token=token).first()

    if not invite:
        flash("Invalid invitation link", "error")
        return redirect(url_for("auth_bp.login"))

    if not invite.is_valid():
        if invite.status == "accepted":
            flash("This invitation has already been accepted", "info")
        elif invite.status == "revoked":
            flash("This invitation has been revoked", "error")
        else:
            flash("This invitation has expired", "error")
        return redirect(url_for("auth_bp.login"))

    # If user is logged in
    if g.get('user'):
        # Check if user's email matches invite
        if g.user.email.lower() != invite.email.lower():
            flash("This invitation was sent to a different email address", "error")
            return redirect(url_for("account_bp.dashboard"))

        # Move user to new account
        old_account_id = g.user.account_id
        g.user.account_id = invite.account_id
        g.user.role = invite.role

        # Mark invite as accepted
        invite.accept(g.user.id)

        db.session.commit()

        current_app.logger.info(
            f"User {g.user.id} accepted invite {invite.id}, moved from account {old_account_id} to {invite.account_id}"
        )

        flash(f"Welcome to the team! You've joined as {invite.role}.", "success")
        return redirect(url_for("account_bp.dashboard"))

    # User not logged in - redirect to registration with invite token
    return redirect(url_for("auth_bp.register", invite_token=token))


@team_bp.route("/invite/<int:invite_id>/revoke", methods=["POST"])
@login_required
@require_permission("invite_users")
def revoke_invite(invite_id):
    """Revoke a pending invitation."""
    invite = TeamInvite.query.get(invite_id)

    if not invite:
        return jsonify({"error": "Invite not found"}), 404

    if invite.account_id != g.user.account_id:
        return jsonify({"error": "Unauthorized"}), 403

    invite.revoke()
    db.session.commit()

    flash("Invitation revoked", "success")
    return jsonify({"success": True})


@team_bp.route("/members/<int:user_id>/remove", methods=["POST"])
@login_required
@require_permission("remove_members")
def remove_member(user_id):
    """Remove a team member."""
    target_user = User.query.get(user_id)

    if not target_user:
        return jsonify({"error": "User not found"}), 404

    # Check if can manage this user
    can_manage, reason = can_manage_user(g.user, target_user)
    if not can_manage:
        return jsonify({"error": reason or "Cannot remove this user"}), 403

    # Don't allow removing the last owner
    if target_user.role == "owner":
        owner_count = User.query.filter_by(
            account_id=g.user.account_id,
            role="owner"
        ).count()

        if owner_count <= 1:
            return jsonify({"error": "Cannot remove the last owner"}), 400

    # Remove user (or move to their own account)
    # Option 1: Delete user entirely
    # db.session.delete(target_user)

    # Option 2: Create new account for them and move them there (safer)
    new_account = Account(name=f"{target_user.name}'s Account", plan="free")
    db.session.add(new_account)
    db.session.flush()

    target_user.account_id = new_account.id
    target_user.role = "owner"

    db.session.commit()

    current_app.logger.info(
        f"User {g.user.id} removed user {user_id} from account {g.user.account_id}"
    )

    flash(f"{target_user.name} has been removed from the team", "success")
    return jsonify({"success": True})


@team_bp.route("/members/<int:user_id>/role", methods=["POST"])
@login_required
@require_admin()
def change_role(user_id):
    """Change a team member's role."""
    target_user = User.query.get(user_id)

    if not target_user:
        return jsonify({"error": "User not found"}), 404

    if target_user.account_id != g.user.account_id:
        return jsonify({"error": "User not in your account"}), 403

    new_role = request.form.get("role")
    if new_role not in ["owner", "admin", "member"]:
        return jsonify({"error": "Invalid role"}), 400

    # Only owners can change roles to/from owner
    if (new_role == "owner" or target_user.role == "owner") and g.user.role != "owner":
        return jsonify({"error": "Only owners can manage owner roles"}), 403

    # Don't allow removing the last owner
    if target_user.role == "owner" and new_role != "owner":
        owner_count = User.query.filter_by(
            account_id=g.user.account_id,
            role="owner"
        ).count()

        if owner_count <= 1:
            return jsonify({"error": "Cannot demote the last owner"}), 400

    target_user.role = new_role
    db.session.commit()

    current_app.logger.info(
        f"User {g.user.id} changed user {user_id} role to {new_role} in account {g.user.account_id}"
    )

    flash(f"{target_user.name}'s role updated to {new_role}", "success")
    return jsonify({"success": True, "new_role": new_role})


@team_bp.route("/leave", methods=["POST"])
@login_required
def leave_team():
    """Leave the current team."""
    # Don't allow if user is the only owner
    if g.user.role == "owner":
        owner_count = User.query.filter_by(
            account_id=g.user.account_id,
            role="owner"
        ).count()

        if owner_count <= 1:
            flash("You cannot leave as the only owner. Transfer ownership first or delete the account.", "error")
            return redirect(url_for("team.members"))

    # Create new account for user
    new_account = Account(name=f"{g.user.name}'s Account", plan="free")
    db.session.add(new_account)
    db.session.flush()

    old_account_id = g.user.account_id
    g.user.account_id = new_account.id
    g.user.role = "owner"

    db.session.commit()

    current_app.logger.info(
        f"User {g.user.id} left account {old_account_id}"
    )

    flash("You've left the team and created a new personal account", "success")
    return redirect(url_for("account_bp.dashboard"))


# Helper functions

def send_team_invite_email(invite: TeamInvite, inviter: User):
    """
    Send invitation email to the invitee.

    Args:
        invite: TeamInvite model instance
        inviter: User who sent the invite
    """
    from app.services.email_service import send_team_invite_email as send_invite
    return send_invite(invite, inviter)


def get_invite_url(invite: TeamInvite) -> str:
    """Generate the full invitation URL."""
    from flask import url_for
    base_url = current_app.config.get("BASE_URL", "http://localhost:5000")
    path = url_for("team.accept_invite", token=invite.token)
    return f"{base_url}{path}"
