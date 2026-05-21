# app/journey_builder/__init__.py
"""
Visual Journey Builder Module
Allows users to create and visualize marketing funnels.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from flask import (
    Blueprint,
    current_app,
    render_template,
    jsonify,
    request,
    flash,
    redirect,
    url_for,
)
from sqlalchemy import text

from app import db
from app.auth.utils import login_required, current_account_id, is_paid_account

journey_bp = Blueprint("journey_bp", __name__, url_prefix="/account/journeys")


# Pre-built journey templates
JOURNEY_TEMPLATES = {
    "new_customer": {
        "name": "New Customer Acquisition",
        "description": "Attract and convert new customers",
        "icon": "fa-user-plus",
        "color": "blue",
        "stages": [
            {
                "id": "awareness",
                "name": "Awareness",
                "type": "ad",
                "description": "Customer sees your ad",
                "channels": ["Google Ads", "Facebook Ads"],
                "icon": "fa-eye",
                "metrics": ["impressions", "reach"]
            },
            {
                "id": "interest",
                "name": "Interest",
                "type": "landing",
                "description": "Customer clicks and visits website",
                "channels": ["Landing Page"],
                "icon": "fa-mouse-pointer",
                "metrics": ["clicks", "ctr"]
            },
            {
                "id": "consideration",
                "name": "Consideration",
                "type": "nurture",
                "description": "Customer browses, reads reviews",
                "channels": ["Website", "Google Business"],
                "icon": "fa-search",
                "metrics": ["time_on_site", "pages_viewed"]
            },
            {
                "id": "conversion",
                "name": "Conversion",
                "type": "action",
                "description": "Customer calls or fills form",
                "channels": ["Phone", "Form"],
                "icon": "fa-phone",
                "metrics": ["conversions", "calls"]
            },
            {
                "id": "retention",
                "name": "Retention",
                "type": "followup",
                "description": "Follow up for repeat business",
                "channels": ["Email", "SMS"],
                "icon": "fa-heart",
                "metrics": ["repeat_rate", "reviews"]
            }
        ]
    },
    "emergency_service": {
        "name": "Emergency Service Response",
        "description": "Quick response for urgent needs",
        "icon": "fa-bolt",
        "color": "red",
        "stages": [
            {
                "id": "emergency",
                "name": "Emergency Search",
                "type": "ad",
                "description": "Customer has urgent need",
                "channels": ["Google Ads (24/7)", "Local Services Ads"],
                "icon": "fa-magnifying-glass",
                "metrics": ["impressions", "position"]
            },
            {
                "id": "quick_contact",
                "name": "Quick Contact",
                "type": "action",
                "description": "Customer calls immediately",
                "channels": ["Click-to-Call", "Call Extension"],
                "icon": "fa-phone-volume",
                "metrics": ["calls", "answer_rate"]
            },
            {
                "id": "dispatch",
                "name": "Dispatch",
                "type": "service",
                "description": "Technician dispatched",
                "channels": ["SMS Confirmation"],
                "icon": "fa-truck",
                "metrics": ["response_time"]
            },
            {
                "id": "service",
                "name": "Service Complete",
                "type": "action",
                "description": "Problem solved",
                "channels": ["On-site"],
                "icon": "fa-wrench",
                "metrics": ["completion_rate"]
            },
            {
                "id": "review_request",
                "name": "Review Request",
                "type": "followup",
                "description": "Ask for Google review",
                "channels": ["SMS", "Email"],
                "icon": "fa-star",
                "metrics": ["review_rate", "avg_rating"]
            }
        ]
    },
    "seasonal_promo": {
        "name": "Seasonal Promotion",
        "description": "Drive bookings during peak season",
        "icon": "fa-calendar",
        "color": "green",
        "stages": [
            {
                "id": "announce",
                "name": "Announce Offer",
                "type": "ad",
                "description": "Promote seasonal deal",
                "channels": ["Email Blast", "Social Media", "Google Ads"],
                "icon": "fa-bullhorn",
                "metrics": ["reach", "opens"]
            },
            {
                "id": "engage",
                "name": "Engage",
                "type": "landing",
                "description": "Special landing page",
                "channels": ["Promo Page"],
                "icon": "fa-gift",
                "metrics": ["visits", "bounce_rate"]
            },
            {
                "id": "book",
                "name": "Book Appointment",
                "type": "action",
                "description": "Customer schedules service",
                "channels": ["Online Booking", "Phone"],
                "icon": "fa-calendar-check",
                "metrics": ["bookings", "conversion_rate"]
            },
            {
                "id": "remind",
                "name": "Reminder",
                "type": "nurture",
                "description": "Appointment reminder",
                "channels": ["SMS", "Email"],
                "icon": "fa-bell",
                "metrics": ["show_rate"]
            },
            {
                "id": "upsell",
                "name": "Upsell",
                "type": "followup",
                "description": "Offer maintenance plan",
                "channels": ["On-site", "Email"],
                "icon": "fa-arrow-up",
                "metrics": ["upsell_rate", "aov"]
            }
        ]
    },
    "review_generation": {
        "name": "Review Generation",
        "description": "Get more 5-star reviews",
        "icon": "fa-star",
        "color": "yellow",
        "stages": [
            {
                "id": "complete_service",
                "name": "Complete Service",
                "type": "service",
                "description": "Finish job successfully",
                "channels": ["On-site"],
                "icon": "fa-check-circle",
                "metrics": ["satisfaction_score"]
            },
            {
                "id": "immediate_ask",
                "name": "Immediate Ask",
                "type": "action",
                "description": "Tech asks for review",
                "channels": ["In-person"],
                "icon": "fa-comment",
                "metrics": ["ask_rate"]
            },
            {
                "id": "text_followup",
                "name": "Text Follow-up",
                "type": "followup",
                "description": "Send review link via SMS",
                "channels": ["SMS"],
                "icon": "fa-mobile",
                "metrics": ["click_rate"]
            },
            {
                "id": "email_reminder",
                "name": "Email Reminder",
                "type": "followup",
                "description": "2nd reminder if no response",
                "channels": ["Email"],
                "icon": "fa-envelope",
                "metrics": ["open_rate"]
            },
            {
                "id": "review_received",
                "name": "Review Received",
                "type": "action",
                "description": "Customer leaves review",
                "channels": ["Google", "Facebook"],
                "icon": "fa-star",
                "metrics": ["review_rate", "avg_rating"]
            }
        ]
    }
}


def get_journey_templates() -> Dict[str, Dict[str, Any]]:
    """Get all journey templates."""
    return JOURNEY_TEMPLATES


def get_account_journeys(aid: int) -> List[Dict[str, Any]]:
    """Get saved journeys for an account."""
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT id, name, template_key, config, is_active, created_at
                    FROM marketing_journeys
                    WHERE account_id = :aid
                    ORDER BY created_at DESC
                """),
                {"aid": aid}
            ).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        current_app.logger.error(f"Error fetching journeys: {e}")
        return []


# -------------------- Routes --------------------

@journey_bp.route("/", methods=["GET"])
@login_required
def index():
    """Journey builder main page."""
    aid = current_account_id()
    if not aid:
        return redirect(url_for("account_bp.dashboard"))

    templates = get_journey_templates()
    saved_journeys = get_account_journeys(aid)

    return render_template(
        "journey_builder/index.html",
        templates=templates,
        saved_journeys=saved_journeys,
        is_paid=is_paid_account()
    )


@journey_bp.route("/view/<template_key>", methods=["GET"])
@login_required
def view_template(template_key: str):
    """View a specific journey template."""
    template = JOURNEY_TEMPLATES.get(template_key)
    if not template:
        flash("Journey template not found.", "error")
        return redirect(url_for("journey_bp.index"))

    return render_template(
        "journey_builder/view.html",
        template=template,
        template_key=template_key,
        is_paid=is_paid_account()
    )


@journey_bp.route("/api/templates", methods=["GET"])
@login_required
def api_templates():
    """Get all journey templates via API."""
    return jsonify(JOURNEY_TEMPLATES)


@journey_bp.route("/api/template/<template_key>", methods=["GET"])
@login_required
def api_template(template_key: str):
    """Get a specific template via API."""
    template = JOURNEY_TEMPLATES.get(template_key)
    if not template:
        return jsonify({"error": "Template not found"}), 404
    return jsonify(template)


# -------------------- Customer Reactivation Routes --------------------

def _get_overdue_customers(aid: int) -> List[Dict[str, Any]]:
    """
    Return customers whose most recent completed job is older than 12 months.
    Falls back to demo data if no real data exists.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=365)
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        c.id,
                        c.name,
                        c.email,
                        c.phone,
                        c.lifetime_value,
                        c.job_count,
                        MAX(j.completed_date) AS last_service,
                        j.job_type_name AS last_job_type
                    FROM servicetitan_customers c
                    JOIN servicetitan_jobs j
                        ON j.account_id = c.account_id
                        AND j.st_customer_id = c.st_customer_id
                    WHERE c.account_id = :aid
                        AND j.job_status = 'Completed'
                        AND c.email IS NOT NULL
                        AND c.email != ''
                    GROUP BY
                        c.id, c.name, c.email, c.phone,
                        c.lifetime_value, c.job_count, j.job_type_name
                    HAVING MAX(j.completed_date) < :cutoff
                    ORDER BY MAX(j.completed_date) ASC
                    LIMIT 200
                """),
                {"aid": aid, "cutoff": cutoff},
            ).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        current_app.logger.warning(f"Reactivation customer query failed: {e}")
        return []


def _get_sent_count(aid: int) -> int:
    """Return count of reactivation emails already sent for this account."""
    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) AS cnt FROM reactivation_sends WHERE account_id = :aid"
                ),
                {"aid": aid},
            ).fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


def _ensure_reactivation_table() -> None:
    """Create reactivation_sends table if it does not already exist."""
    with db.engine.connect() as conn:
        conn.execute(
            text("""
                CREATE TABLE IF NOT EXISTS reactivation_sends (
                    id          INT AUTO_INCREMENT PRIMARY KEY,
                    account_id  INT          NOT NULL,
                    customer_id INT          NOT NULL,
                    customer_email VARCHAR(255) NOT NULL,
                    subject     VARCHAR(512) NOT NULL,
                    sent_at     DATETIME     NOT NULL,
                    status      VARCHAR(32)  NOT NULL DEFAULT 'sent',
                    INDEX idx_rs_account (account_id),
                    INDEX idx_rs_customer (customer_id)
                )
            """)
        )
        conn.commit()


def _build_reactivation_email(
    customer_name: str,
    service_type: str,
    last_service_str: str,
    custom_message: str,
    business_name: str,
    business_phone: str,
    business_website: str,
) -> tuple[str, str]:
    """Return (subject, html_body) for a reactivation email."""
    first_name = customer_name.split()[0] if customer_name else "there"
    subject = f"It's been a while, {first_name} — time for your annual {service_type}?"

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
  <style>
    body {{ margin:0; padding:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#f9fafb; }}
    .wrapper {{ max-width:600px; margin:32px auto; background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 4px 24px rgba(0,0,0,.08); }}
    .header {{ background:linear-gradient(135deg,#4f46e5,#7c3aed); padding:32px 40px; text-align:center; }}
    .header h1 {{ color:#fff; margin:0; font-size:24px; font-weight:700; }}
    .body {{ padding:32px 40px; color:#374151; line-height:1.7; }}
    .body p {{ margin:0 0 16px; }}
    .highlight {{ background:#eef2ff; border-left:4px solid #4f46e5; padding:14px 18px; border-radius:6px; margin:20px 0; color:#4338ca; font-weight:500; }}
    .cta {{ display:inline-block; margin:8px 0; padding:14px 32px; background:#4f46e5; color:#fff !important; border-radius:8px; text-decoration:none; font-weight:700; font-size:16px; }}
    .cta:hover {{ background:#4338ca; }}
    .footer {{ background:#f3f4f6; padding:20px 40px; text-align:center; font-size:13px; color:#6b7280; }}
  </style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>{business_name}</h1>
  </div>
  <div class="body">
    <p>Hi {first_name},</p>
    <p>We hope you and your family are doing well! It's been a while since we had the pleasure of serving you — your last <strong>{service_type}</strong> with us was back in {last_service_str}.</p>
    <p>As the seasons change, it's the perfect time to schedule your annual <strong>{service_type}</strong> to keep everything running smoothly and avoid unexpected breakdowns.</p>
    <div class="highlight">
      {custom_message if custom_message else f"Regular maintenance on your {service_type} can save you money in the long run and keep your home comfortable all year round."}
    </div>
    <p>We'd love to welcome you back! Give us a call or book online — we'll take great care of you, just like always.</p>
    <p style="text-align:center; margin:28px 0;">
      <a href="tel:{business_phone}" class="cta">&#128222; Call Us: {business_phone}</a>
    </p>
    {"<p style='text-align:center;'><a href='" + business_website + "' style='color:#4f46e5;'>Or book online at " + business_website + "</a></p>" if business_website else ""}
    <p>Looking forward to hearing from you!</p>
    <p>Warm regards,<br><strong>The {business_name} Team</strong></p>
  </div>
  <div class="footer">
    &copy; {datetime.utcnow().year} {business_name}. All rights reserved.<br>
    {business_phone} &nbsp;|&nbsp; {business_website or ""}
  </div>
</div>
</body>
</html>"""

    return subject, html_body


@journey_bp.route("/reactivation", methods=["GET"])
@login_required
def reactivation():
    """Customer Reactivation campaign page."""
    aid = current_account_id()
    if not aid:
        return redirect(url_for("account_bp.dashboard"))

    customers = _get_overdue_customers(aid)
    sent_count = _get_sent_count(aid)

    # Normalise last_service to string for template
    for c in customers:
        ls = c.get("last_service")
        if ls and hasattr(ls, "strftime"):
            c["last_service"] = ls.strftime("%Y-%m-%d")
        elif ls:
            c["last_service"] = str(ls)[:10]

    return render_template(
        "journey_builder/reactivation.html",
        customers=customers,
        total_count=len(customers),
        sent_count=sent_count,
    )


@journey_bp.route("/reactivation/launch", methods=["POST"])
@login_required
def reactivation_launch():
    """Launch a reactivation email campaign for selected customers."""
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    data = request.get_json(force=True, silent=True) or {}
    customer_ids: List[int] = data.get("customer_ids", [])
    message: str = data.get("message", "")
    service_type: str = data.get("service_type", "Annual Service")

    if not customer_ids:
        return jsonify({"ok": False, "error": "No customers selected"}), 400

    # Ensure table exists
    try:
        _ensure_reactivation_table()
    except Exception as e:
        current_app.logger.error(f"Could not create reactivation_sends table: {e}")

    # Fetch business profile
    business_name = "Your Business"
    business_phone = ""
    business_website = ""
    try:
        with db.engine.connect() as conn:
            bp_row = conn.execute(
                text(
                    "SELECT business_name, phone, website FROM business_profiles WHERE account_id=:aid LIMIT 1"
                ),
                {"aid": aid},
            ).fetchone()
            if bp_row:
                business_name = bp_row[0] or business_name
                business_phone = bp_row[1] or ""
                business_website = bp_row[2] or ""
    except Exception as e:
        current_app.logger.warning(f"Could not fetch business profile: {e}")

    # Fetch customer details for the selected IDs
    try:
        with db.engine.connect() as conn:
            placeholders = ",".join([":id_" + str(i) for i in range(len(customer_ids))])
            params: Dict[str, Any] = {"aid": aid}
            for i, cid in enumerate(customer_ids):
                params["id_" + str(i)] = cid
            rows = conn.execute(
                text(f"""
                    SELECT c.id, c.name, c.email,
                           MAX(j.completed_date) AS last_service,
                           j.job_type_name AS last_job_type
                    FROM servicetitan_customers c
                    LEFT JOIN servicetitan_jobs j
                        ON j.account_id = c.account_id
                        AND j.st_customer_id = c.st_customer_id
                        AND j.job_status = 'Completed'
                    WHERE c.account_id = :aid AND c.id IN ({placeholders})
                    GROUP BY c.id, c.name, c.email, j.job_type_name
                """),
                params,
            ).mappings().all()
            customer_map = {r["id"]: dict(r) for r in rows}
    except Exception as e:
        current_app.logger.error(f"Error fetching customers for reactivation: {e}")
        customer_map = {}

    from app.services.email_service import send_email

    sent = 0
    failed = 0

    for cid in customer_ids:
        customer = customer_map.get(cid)
        if not customer:
            failed += 1
            continue

        email_addr = customer.get("email", "")
        if not email_addr:
            failed += 1
            continue

        name = customer.get("name") or "Valued Customer"
        job_type = customer.get("last_job_type") or service_type
        ls = customer.get("last_service")
        if ls and hasattr(ls, "strftime"):
            last_service_str = ls.strftime("%B %Y")
        elif ls:
            last_service_str = str(ls)[:7]
        else:
            last_service_str = "last year"

        subject, html_body = _build_reactivation_email(
            customer_name=name,
            service_type=service_type or job_type,
            last_service_str=last_service_str,
            custom_message=message,
            business_name=business_name,
            business_phone=business_phone,
            business_website=business_website,
        )

        success = False
        try:
            success = send_email(
                to=email_addr,
                subject=subject,
                html_body=html_body,
                use_bulk_credentials=True,
            )
        except Exception as e:
            current_app.logger.error(f"Email send error for customer {cid}: {e}")

        status = "sent" if success else "failed"
        if success:
            sent += 1
        else:
            failed += 1

        try:
            with db.engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO reactivation_sends
                            (account_id, customer_id, customer_email, subject, sent_at, status)
                        VALUES (:aid, :cid, :email, :subject, :now, :status)
                    """),
                    {
                        "aid": aid,
                        "cid": cid,
                        "email": email_addr,
                        "subject": subject,
                        "now": datetime.utcnow(),
                        "status": status,
                    },
                )
                conn.commit()
        except Exception as e:
            current_app.logger.warning(f"Could not record reactivation send: {e}")

    return jsonify({"ok": True, "sent": sent, "failed": failed})


@journey_bp.route("/reactivation/api/customers", methods=["GET"])
@login_required
def reactivation_api_customers():
    """Return JSON list of overdue customers."""
    aid = current_account_id()
    if not aid:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    customers = _get_overdue_customers(aid)
    result = []
    for c in customers:
        ls = c.get("last_service")
        if ls and hasattr(ls, "strftime"):
            ls_str = ls.strftime("%Y-%m-%d")
        elif ls:
            ls_str = str(ls)[:10]
        else:
            ls_str = None

        result.append(
            {
                "id": c.get("id"),
                "name": c.get("name") or "",
                "email": c.get("email") or "",
                "phone": c.get("phone") or "",
                "last_service": ls_str,
                "last_job_type": c.get("last_job_type") or "",
                "lifetime_value": float(c.get("lifetime_value") or 0),
                "job_count": int(c.get("job_count") or 0),
            }
        )

    return jsonify({"ok": True, "customers": result})


# -------------------- Seasonal Intelligence Routes --------------------

_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _get_monthly_data(aid: int) -> List[Dict[str, Any]]:
    """
    Aggregate ad spend and revenue by calendar month (rolling 12 months).
    Returns a list of 12 dicts, one per month.
    """
    monthly: Dict[int, Dict[str, Any]] = {m: {"spend": 0.0, "revenue": 0.0, "count": 0} for m in range(1, 13)}

    # --- Ad spend by month ---
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT MONTH(spend_date) AS mo, SUM(amount) AS total_spend
                    FROM ad_spend
                    WHERE account_id = :aid
                        AND spend_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
                    GROUP BY MONTH(spend_date)
                """),
                {"aid": aid},
            ).fetchall()
            for row in rows:
                mo = int(row[0])
                if 1 <= mo <= 12:
                    monthly[mo]["spend"] += float(row[1] or 0)
    except Exception as e:
        current_app.logger.warning(f"Seasonal spend query failed: {e}")

    # --- Revenue by month ---
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT MONTH(completed_date) AS mo,
                           SUM(total_amount)    AS total_rev,
                           COUNT(*)             AS job_cnt
                    FROM servicetitan_jobs
                    WHERE account_id = :aid
                        AND job_status = 'Completed'
                        AND completed_date >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
                    GROUP BY MONTH(completed_date)
                """),
                {"aid": aid},
            ).fetchall()
            for row in rows:
                mo = int(row[0])
                if 1 <= mo <= 12:
                    monthly[mo]["revenue"] += float(row[1] or 0)
                    monthly[mo]["count"] += int(row[2] or 0)
    except Exception as e:
        current_app.logger.warning(f"Seasonal revenue query failed: {e}")

    # Compute average monthly spend + revenue for recommendation thresholds
    all_spend = [monthly[m]["spend"] for m in range(1, 13)]
    all_revenue = [monthly[m]["revenue"] for m in range(1, 13)]
    avg_spend = sum(all_spend) / 12 if any(all_spend) else 0
    avg_revenue = sum(all_revenue) / 12 if any(all_revenue) else 0

    # If no real data exists, inject demo data
    if avg_spend == 0 and avg_revenue == 0:
        demo_rev = [9200, 8400, 12500, 14800, 18600, 22400, 24100, 21300, 16800, 13200, 10100, 8700]
        demo_spnd = [1800, 1600, 2400, 2800, 3600, 4200, 4500, 4000, 3200, 2600, 2000, 1700]
        for m in range(1, 13):
            monthly[m]["revenue"] = demo_rev[m - 1]
            monthly[m]["spend"] = demo_spnd[m - 1]
            monthly[m]["count"] = max(1, int(demo_rev[m - 1] / 800))
        avg_spend = sum(demo_spnd) / 12
        avg_revenue = sum(demo_rev) / 12

    result = []
    for m in range(1, 13):
        sp = monthly[m]["spend"]
        rv = monthly[m]["revenue"]
        recommended_budget_pct = 100.0
        if avg_spend > 0:
            # Scale budget relative to revenue performance
            if rv > avg_revenue * 1.2:
                recommended_budget_pct = 135.0
            elif rv < avg_revenue * 0.8:
                recommended_budget_pct = 75.0

        result.append(
            {
                "month": m,
                "month_name": _MONTH_NAMES[m - 1],
                "avg_spend": round(sp, 2),
                "avg_revenue": round(rv, 2),
                "job_count": monthly[m]["count"],
                "recommended_budget_pct": recommended_budget_pct,
            }
        )

    return result


def _generate_seasonal_recommendations(monthly_data: List[Dict[str, Any]]) -> List[str]:
    """Generate plain-English AI-style budget recommendations from monthly data."""
    avg_rev = sum(d["avg_revenue"] for d in monthly_data) / 12
    peak_months = [d for d in monthly_data if d["avg_revenue"] > avg_rev * 1.2]
    slow_months = [d for d in monthly_data if d["avg_revenue"] < avg_rev * 0.8]

    recs = []
    if peak_months:
        names = ", ".join(d["month_name"] for d in peak_months)
        recs.append(
            f"Increase ad budget 35% in {names} — these are your highest-revenue months. "
            "Capture more demand while competition heats up."
        )
    if slow_months:
        names = ", ".join(d["month_name"] for d in slow_months)
        recs.append(
            f"Reduce spend 25% in {names} and shift to brand-awareness campaigns. "
            "Lower CPC means cheaper reach during slow season."
        )
    if not recs:
        recs.append(
            "Your revenue is fairly consistent year-round. Maintain a steady budget "
            "but consider slight increases in Q2–Q3 for seasonal service demand."
        )

    recs.append(
        "Set up automated rules to pause underperforming keywords during your slowest weeks "
        "and re-enable them 2 weeks before your peak season begins."
    )
    return recs


@journey_bp.route("/seasonal", methods=["GET"])
@login_required
def seasonal():
    """Seasonal Intelligence page."""
    aid = current_account_id()
    if not aid:
        return redirect(url_for("account_bp.dashboard"))

    monthly_data = _get_monthly_data(aid)
    recommendations = _generate_seasonal_recommendations(monthly_data)

    return render_template(
        "journey_builder/seasonal.html",
        monthly_data=monthly_data,
        recommendations=recommendations,
    )
