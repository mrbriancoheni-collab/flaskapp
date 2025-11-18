# app/account/competitive_routes.py
"""
Competitive Intelligence Routes

Provides UI and API endpoints for competitive analysis.
"""

from flask import Blueprint, render_template, request, jsonify, g
from app.auth.session_helpers import login_required
from app.services.competitive_intelligence_service import CompetitiveIntelligenceService
from app.db import get_db
from datetime import datetime, timedelta, date
import logging

logger = logging.getLogger(__name__)

competitive_bp = Blueprint("competitive", __name__, url_prefix="/account/competitive")


@competitive_bp.route("/")
@login_required
def dashboard():
    """Competitive intelligence dashboard page."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    return render_template("account/competitive_dashboard.html", user=user, account_id=account_id)


@competitive_bp.route("/api/competitors", methods=["GET"])
@login_required
def get_competitors():
    """Get competitor data."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    customer_id = request.args.get('customer_id', '')
    campaign_id = request.args.get('campaign_id')
    report_date_str = request.args.get('report_date')

    if not account_id or not customer_id:
        return jsonify({"error": "Missing account_id or customer_id"}), 400

    try:
        db = get_db()
        service = CompetitiveIntelligenceService(db)

        report_date = None
        if report_date_str:
            report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()

        competitors = service.get_competitors(account_id, customer_id, campaign_id, report_date)

        # Convert Decimal to float for JSON
        for comp in competitors:
            for key, value in comp.items():
                if hasattr(value, '__float__'):
                    comp[key] = float(value)
                elif isinstance(value, date):
                    comp[key] = value.isoformat()
                elif isinstance(value, datetime):
                    comp[key] = value.isoformat()

        return jsonify({"success": True, "competitors": competitors})

    except Exception as e:
        logger.error(f"Error getting competitors: {e}")
        return jsonify({"error": str(e)}), 500


@competitive_bp.route("/api/save-insights", methods=["POST"])
@login_required
def save_insights():
    """Save auction insights data."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')
    campaign_id = data.get('campaign_id', '')
    report_date_str = data.get('report_date')
    competitors = data.get('competitors', [])

    if not account_id or not customer_id or not campaign_id:
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date() if report_date_str else date.today()

        db = get_db()
        service = CompetitiveIntelligenceService(db)

        success = service.save_auction_insights(
            account_id,
            customer_id,
            campaign_id,
            report_date,
            competitors
        )

        if success:
            return jsonify({"success": True, "message": "Insights saved successfully"})
        else:
            return jsonify({"error": "Failed to save insights"}), 500

    except Exception as e:
        logger.error(f"Error saving insights: {e}")
        return jsonify({"error": str(e)}), 500


@competitive_bp.route("/api/alerts", methods=["GET"])
@login_required
def get_alerts():
    """Get competitive alerts."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None
    customer_id = request.args.get('customer_id', '')
    unaddressed_only = request.args.get('unaddressed_only', 'true').lower() == 'true'
    limit = int(request.args.get('limit', 50))

    if not account_id or not customer_id:
        return jsonify({"error": "Missing account_id or customer_id"}), 400

    try:
        db = get_db()
        service = CompetitiveIntelligenceService(db)

        alerts = service.get_alerts(account_id, customer_id, unaddressed_only, limit)

        # Convert Decimal/datetime to JSON-serializable
        for alert in alerts:
            for key, value in alert.items():
                if hasattr(value, '__float__'):
                    alert[key] = float(value)
                elif isinstance(value, datetime):
                    alert[key] = value.isoformat()
                elif isinstance(value, date):
                    alert[key] = value.isoformat()

        return jsonify({"success": True, "alerts": alerts})

    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        return jsonify({"error": str(e)}), 500


@competitive_bp.route("/api/market-share", methods=["POST"])
@login_required
def get_market_share():
    """Get market share analysis."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')
    campaign_id = data.get('campaign_id', '')
    your_impression_share = float(data.get('your_impression_share', 0))

    if not account_id or not customer_id or not campaign_id:
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        db = get_db()
        service = CompetitiveIntelligenceService(db)

        analysis = service.get_market_share_analysis(
            account_id,
            customer_id,
            campaign_id,
            your_impression_share
        )

        # Convert nested dicts
        def convert_values(obj):
            if isinstance(obj, dict):
                return {k: convert_values(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_values(item) for item in obj]
            elif hasattr(obj, '__float__'):
                return float(obj)
            elif isinstance(obj, (date, datetime)):
                return obj.isoformat()
            return obj

        analysis = convert_values(analysis)

        return jsonify({"success": True, "analysis": analysis})

    except Exception as e:
        logger.error(f"Error getting market share: {e}")
        return jsonify({"error": str(e)}), 500


@competitive_bp.route("/api/mark-addressed/<int:alert_id>", methods=["POST"])
@login_required
def mark_addressed(alert_id):
    """Mark an alert as addressed."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    try:
        db = get_db()
        service = CompetitiveIntelligenceService(db)

        success = service.mark_alert_addressed(alert_id, account_id)

        if success:
            return jsonify({"success": True, "message": "Alert marked as addressed"})
        else:
            return jsonify({"error": "Failed to mark alert"}), 500

    except Exception as e:
        logger.error(f"Error marking alert: {e}")
        return jsonify({"error": str(e)}), 500


@competitive_bp.route("/api/add-competitor", methods=["POST"])
@login_required
def add_competitor():
    """Manually add a competitor to track."""
    user = g.user
    account_id = user.account_id if user and hasattr(user, 'account_id') else None

    data = request.get_json()
    customer_id = data.get('customer_id', '')
    competitor_domain = data.get('competitor_domain', '').strip()
    company_name = data.get('company_name', '').strip()
    notes = data.get('notes', '').strip()

    if not account_id or not customer_id or not competitor_domain:
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        db = get_db()
        cursor = db.cursor()

        # Insert manually tracked competitor (we'll create a new table for this)
        # For now, create a placeholder entry in auction_insights with zeros
        cursor.execute("""
            INSERT INTO auction_insights
            (account_id, customer_id, competitor_domain, report_date, impression_share,
             overlap_rate, position_above_rate, top_of_page_rate, notes)
            VALUES (%s, %s, %s, CURDATE(), 0, 0, 0, 0, %s)
            ON DUPLICATE KEY UPDATE notes = VALUES(notes)
        """, (account_id, customer_id, competitor_domain,
              f"{company_name or ''} - {notes or 'Manually tracked competitor'}"))

        db.commit()
        cursor.close()

        return jsonify({"success": True, "message": "Competitor added successfully"})

    except Exception as e:
        logger.error(f"Error adding competitor: {e}")
        db.rollback()
        return jsonify({"error": str(e)}), 500
