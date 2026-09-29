# app/agent_approval/__init__.py
"""
One-tap agent action approval (Viktor-inspired).

When an AI agent proposes a high-stakes action (bid change, budget reallocation,
campaign pause), it calls `send_approval_request()` which:
  1. Generates a signed token stored on the AIAction row.
  2. Emails + SMSes the account owner with Approve / Reject links.
  3. The owner taps the link — no login required — and the action executes
     (or is dismissed) immediately.

Public routes (no login required — token IS the credential):
  GET /agent/approve/<token>   — mark approved + execute
  GET /agent/reject/<token>    — mark rejected

Auth-required routes:
  GET /account/agent-actions   — list pending actions with approve/reject UI
  POST /api/agent-actions/<id>/approve
  POST /api/agent-actions/<id>/reject
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from typing import Optional

from flask import (
    Blueprint, abort, current_app, jsonify, redirect, render_template,
    request, session, url_for,
)
from sqlalchemy import text

from app import db
from app.models_ai_actions import AIAction

log = logging.getLogger(__name__)

agent_approval_bp = Blueprint("agent_approval_bp", __name__)

# Actions that require owner approval before execution
HIGH_STAKES_ACTION_TYPES = {
    "budget_reallocated",
    "campaign_paused",
    "campaign_enabled",
    "bid_adjusted",
}
HIGH_STAKES_THRESHOLD_DOLLARS = 50.0   # changes >= $50 estimated impact require approval


# ── Auth helper ────────────────────────────────────────────────────────────────

def _current_account_id() -> Optional[int]:
    aid = session.get("account_id") or session.get("aid")
    if aid:
        try:
            return int(aid)
        except Exception:
            pass
    uid = session.get("user_id")
    if not uid:
        return None
    try:
        row = db.session.execute(
            text("SELECT account_id FROM users WHERE id=:id"), {"id": uid}
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def _login_required(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*a, **kw):
        if not _current_account_id():
            return redirect(url_for("auth_bp.login", next=request.path))
        return f(*a, **kw)
    return wrapper


# ── Public: token-based approve / reject ──────────────────────────────────────

@agent_approval_bp.route("/agent/approve/<token>")
def approve_action(token: str):
    action = AIAction.query.filter_by(approval_token=token).first_or_404()

    if action.status not in ("pending", "pending_approval"):
        return render_template("agent_approval/result.html",
                               success=False,
                               message="This action has already been processed.",
                               action=action)

    action.status = "approved"
    action.approved_at = datetime.utcnow()
    db.session.commit()

    # Execute the action
    _execute_action(action)

    return render_template("agent_approval/result.html",
                           success=True,
                           message="Action approved and executed.",
                           action=action)


@agent_approval_bp.route("/agent/reject/<token>")
def reject_action(token: str):
    action = AIAction.query.filter_by(approval_token=token).first_or_404()

    if action.status not in ("pending", "pending_approval"):
        return render_template("agent_approval/result.html",
                               success=False,
                               message="This action has already been processed.",
                               action=action)

    action.status = "dismissed"
    action.rejected_at = datetime.utcnow()
    db.session.commit()

    return render_template("agent_approval/result.html",
                           success=True,
                           message="Action rejected. The agent will not apply this change.",
                           action=action)


# ── Auth-required: pending actions dashboard ──────────────────────────────────

@agent_approval_bp.route("/account/agent-actions")
@_login_required
def pending_actions():
    account_id = _current_account_id()
    actions = (
        AIAction.query
        .filter_by(account_id=account_id)
        .filter(AIAction.status.in_(["pending", "pending_approval"]))
        .order_by(AIAction.created_at.desc())
        .limit(50)
        .all()
    )
    return render_template("agent_approval/pending.html", actions=actions)


@agent_approval_bp.route("/api/agent-actions/<int:action_id>/approve", methods=["POST"])
@_login_required
def approve_action_api(action_id: int):
    account_id = _current_account_id()
    action = AIAction.query.filter_by(id=action_id, account_id=account_id).first_or_404()
    if action.status not in ("pending", "pending_approval"):
        return jsonify({"ok": False, "error": "already processed"}), 400
    action.status = "approved"
    action.approved_at = datetime.utcnow()
    db.session.commit()
    _execute_action(action)
    return jsonify({"ok": True})


@agent_approval_bp.route("/api/agent-actions/<int:action_id>/reject", methods=["POST"])
@_login_required
def reject_action_api(action_id: int):
    account_id = _current_account_id()
    action = AIAction.query.filter_by(id=action_id, account_id=account_id).first_or_404()
    if action.status not in ("pending", "pending_approval"):
        return jsonify({"ok": False, "error": "already processed"}), 400
    action.status = "dismissed"
    action.rejected_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})


# ── Public helper: send approval request ──────────────────────────────────────

def send_approval_request(action: AIAction, to_email: str, to_phone: Optional[str] = None) -> bool:
    """
    Generate a one-use token, store it on the action, and notify the owner.
    Call this from agent code instead of executing directly for high-stakes actions.
    """
    if not action.approval_token:
        action.approval_token = secrets.token_urlsafe(32)
    action.status = "pending_approval"
    action.approval_sent_at = datetime.utcnow()
    db.session.commit()

    base_url = os.getenv("BASE_PUBLIC_URL", "https://app.fieldsprout.io").rstrip("/")
    approve_url = f"{base_url}/agent/approve/{action.approval_token}"
    reject_url = f"{base_url}/agent/reject/{action.approval_token}"

    impact = ""
    if action.estimated_monthly_savings:
        impact = f"Estimated impact: ${action.estimated_monthly_savings:,.0f}/mo savings. "
    elif action.estimated_monthly_value:
        impact = f"Estimated impact: ${action.estimated_monthly_value:,.0f}/mo value. "

    _send_approval_email(to_email, action, approve_url, reject_url, impact)
    if to_phone:
        _send_approval_sms(to_phone, action, approve_url, reject_url)

    log.info("Approval request sent for action %s to %s", action.id, to_email)
    return True


def needs_approval(action: AIAction) -> bool:
    """Return True if this action should be queued for owner approval."""
    if action.action_type in HIGH_STAKES_ACTION_TYPES:
        return True
    impact = action.estimated_monthly_savings or action.estimated_monthly_value or 0
    return impact >= HIGH_STAKES_THRESHOLD_DOLLARS


# ── Email + SMS delivery ───────────────────────────────────────────────────────

def _send_approval_email(to_email: str, action: AIAction, approve_url: str, reject_url: str, impact: str) -> None:
    html_body = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:520px;margin:0 auto">
      <div style="background:linear-gradient(135deg,#7c3aed,#4f46e5);padding:28px 32px;border-radius:12px 12px 0 0">
        <h1 style="color:#fff;margin:0;font-size:20px">AI Agent Action — Your Approval Needed</h1>
        <p style="color:rgba(255,255,255,.8);margin:8px 0 0;font-size:14px">FieldSprout · {datetime.utcnow().strftime('%b %-d, %Y')}</p>
      </div>
      <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;padding:28px 32px;border-radius:0 0 12px 12px">
        <h2 style="font-size:16px;color:#111827;margin:0 0 4px">{action.title}</h2>
        <p style="color:#374151;font-size:14px;margin:0 0 16px">{action.description}</p>
        {'<p style="color:#059669;font-size:13px;font-weight:600">' + impact + '</p>' if impact else ''}
        {('<div style="background:#f3f4f6;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:13px;color:#374151">' + action.reasoning + '</div>') if action.reasoning else ''}
        <div style="display:flex;gap:12px;margin-top:20px">
          <a href="{approve_url}"
             style="flex:1;background:#16a34a;color:#fff;padding:13px 20px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;text-align:center;display:block">
            ✓ Approve &amp; Execute
          </a>
          <a href="{reject_url}"
             style="flex:1;background:#f3f4f6;color:#374151;padding:13px 20px;border-radius:8px;text-decoration:none;font-weight:600;font-size:15px;text-align:center;display:block">
            ✗ Reject
          </a>
        </div>
        <p style="color:#9ca3af;font-size:12px;margin-top:16px;text-align:center">
          Tap Approve or Reject — no login required. This link expires in 72 hours.
        </p>
      </div>
    </div>
    """
    try:
        from app.services.email_service import send_email
        send_email(
            to_email=to_email,
            subject=f"⚡ Agent Action: {action.title} — tap to approve",
            html_body=html_body,
            text_body=f"{action.title}\n\n{action.description}\n\nApprove: {approve_url}\nReject: {reject_url}",
        )
    except Exception:
        log.exception("Failed to send approval email for action %s", action.id)


def _send_approval_sms(to_phone: str, action: AIAction, approve_url: str, reject_url: str) -> None:
    import requests as _req
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    tok = os.getenv("TWILIO_AUTH_TOKEN")
    frm = os.getenv("TWILIO_FROM_NUMBER")
    body = (
        f"FieldSprout Agent: {action.title}. "
        f"Approve: {approve_url}  |  Reject: {reject_url}"
    )
    if not (sid and tok and frm):
        log.info("Approval SMS (simulated) to %s", to_phone)
        return
    try:
        _req.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={"From": frm, "To": to_phone, "Body": body},
            auth=(sid, tok),
            timeout=10,
        )
    except Exception:
        log.exception("Approval SMS failed for action %s", action.id)


def _execute_action(action: AIAction) -> None:
    """Dispatch execution to the auto-executor if available."""
    try:
        from app.services.google_ads_auto_executor import execute_ai_action
        execute_ai_action(action.id)
    except Exception:
        log.exception("Failed to auto-execute action %s after approval", action.id)
