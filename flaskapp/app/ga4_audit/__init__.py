"""GA4 Audit blueprint — /ga4-audit"""
import json
from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash, session, current_app,
)
from flask_login import login_required, current_user

ga4_audit_bp = Blueprint(
    "ga4_audit_bp",
    __name__,
    url_prefix="/ga4-audit",
    template_folder="../../templates",
)

ADMIN_BASE = "https://analyticsadmin.googleapis.com/v1beta"


# ── helpers ─────────────────────────────────────────────────────────────────

def _account_id():
    return getattr(current_user, "account_id", None) or getattr(current_user, "id", None)


def _get_access_token():
    """Return (access_token, error_string)."""
    try:
        from app.google.token_utils import ensure_access_token
        at, _ = ensure_access_token(_account_id(), ("ga",))
        return at, None
    except Exception as exc:
        return None, str(exc)


def _save_report(result):
    """Persist audit result, return report id."""
    try:
        from app import db
        from app.models_ga4_audit import GA4AuditReport
        rpt = GA4AuditReport(
            account_id=_account_id() if current_user.is_authenticated else None,
            property_id=result["property_id"],
            property_name=result["property_name"],
            overall_score=result["overall_score"],
            overall_grade=result["overall_grade"],
            audit_json=json.dumps(result),
        )
        db.session.add(rpt)
        db.session.commit()
        return rpt.id
    except Exception:
        session["ga4_audit_result"] = json.dumps(result)
        return "session"


def _load_report(report_id):
    if str(report_id) == "session":
        raw = session.get("ga4_audit_result")
        return json.loads(raw) if raw else None
    try:
        from app.models_ga4_audit import GA4AuditReport
        rpt = GA4AuditReport.query.get(int(report_id))
        return rpt.get_data() if rpt else None
    except Exception:
        return None


# ── routes ───────────────────────────────────────────────────────────────────

@ga4_audit_bp.route("/", endpoint="index")
def index():
    return render_template("ga4_audit/index.html")


@ga4_audit_bp.route("/connect", endpoint="connect")
@login_required
def connect():
    session["oauth_redirect_after"] = url_for("ga4_audit_bp.analyze")
    try:
        return redirect(url_for("google_bp.connect_analytics", next=url_for("ga4_audit_bp.analyze")))
    except Exception:
        flash("Could not start Google OAuth. Please try again.", "error")
        return redirect(url_for("ga4_audit_bp.index"))


@ga4_audit_bp.route("/analyze", methods=["GET", "POST"], endpoint="analyze")
@login_required
def analyze():
    access_token, err = _get_access_token()
    if not access_token:
        return redirect(url_for("ga4_audit_bp.connect"))

    if request.method == "POST":
        property_id = request.form.get("property_id", "").strip()
        if not property_id:
            flash("Please select a GA4 property.", "error")
            return redirect(url_for("ga4_audit_bp.analyze"))

        try:
            from app.ga4_audit.analyzer import run_audit
            result = run_audit(access_token, property_id)
            report_id = _save_report(result)
            return redirect(url_for("ga4_audit_bp.report", report_id=report_id))
        except Exception as exc:
            current_app.logger.exception("GA4 audit failed: %s", exc)
            flash("Audit failed — please try again or select a different property.", "error")
            return redirect(url_for("ga4_audit_bp.analyze"))

    # GET — list properties
    try:
        from app.ga4_audit.analyzer import list_properties
        properties = list_properties(access_token)
    except Exception:
        properties = []

    if not properties:
        flash("No GA4 properties found. Make sure your Google account has access to at least one GA4 property.", "warning")

    return render_template("ga4_audit/analyze.html", properties=properties)


@ga4_audit_bp.route("/report/<report_id>", endpoint="report")
def report(report_id):
    result = _load_report(report_id)
    if not result:
        flash("Report not found.", "error")
        return redirect(url_for("ga4_audit_bp.index"))

    # Sort checks: critical first, then by status (fail > warning > pass), then by score asc
    severity_order = {"critical": 0, "moderate": 1, "advisory": 2}
    status_order = {"fail": 0, "warning": 1, "pass": 2}
    checks = sorted(
        result.get("checks", []),
        key=lambda c: (severity_order.get(c["severity"], 9), status_order.get(c["status"], 9)),
    )

    return render_template(
        "ga4_audit/report.html",
        result=result,
        checks=checks,
        report_id=report_id,
    )


@ga4_audit_bp.route("/demo", endpoint="demo")
def demo():
    from app.ga4_audit.analyzer import DEMO_RESULT
    result = DEMO_RESULT
    checks = sorted(
        result.get("checks", []),
        key=lambda c: (
            {"critical": 0, "moderate": 1}[c["severity"]],
            {"fail": 0, "warning": 1, "pass": 2}[c["status"]],
        ),
    )
    return render_template(
        "ga4_audit/report.html",
        result=result,
        checks=checks,
        report_id="demo",
        is_demo=True,
    )
