# app/google/competitive_routes.py
"""
Competitive Intelligence Routes - Dashboard and API endpoints for competitive analysis.
"""
from flask import Blueprint, render_template, jsonify, request, session
from sqlalchemy import text
from datetime import datetime, date, timedelta
import logging

from app import db
from app.auth.utils import login_required, current_account_id

# Import competitive intelligence service (optional - may not exist)
try:
    from app.services.competitive_intelligence_service import (
        fetch_auction_insights,
        analyze_competitive_landscape,
        track_competitor_position_changes,
        get_search_term_competitors,
        estimate_competitor_budget
    )
except ImportError:
    # Service not implemented yet - provide stubs
    def fetch_auction_insights(*args, **kwargs):
        return {"success": False, "error": "Competitive intelligence service not configured"}
    def analyze_competitive_landscape(*args, **kwargs):
        return {"success": False, "error": "Competitive intelligence service not configured"}
    def track_competitor_position_changes(*args, **kwargs):
        return {"success": False, "error": "Competitive intelligence service not configured"}
    def get_search_term_competitors(*args, **kwargs):
        return {"success": False, "error": "Competitive intelligence service not configured"}
    def estimate_competitor_budget(*args, **kwargs):
        return 0

competitive_bp = Blueprint("competitive_bp", __name__, url_prefix="/account/google/ads/competitive")


@competitive_bp.route("/")
@login_required
def competitive_dashboard():
    """
    Competitive Intelligence Dashboard - View competitors, market position, and threats.
    """
    account_id = current_account_id()
    campaigns = []
    alerts = []
    setup_required = False

    # Import the function that fetches and caches ads data
    try:
        from app.google import _get_ads_state, _is_connected
    except ImportError:
        logging.error("Could not import _get_ads_state from app.google")
        _get_ads_state = None
        _is_connected = None

    # Check if user is connected to Google Ads
    is_connected = False
    if _is_connected:
        try:
            is_connected = _is_connected(account_id, "ads")
        except Exception as e:
            logging.warning(f"Error checking connection: {e}")

    # Use _get_ads_state to fetch/cache the data (this populates the session)
    if _get_ads_state and is_connected:
        try:
            ads_data = _get_ads_state(account_id)
            raw_campaigns = ads_data.get('campaigns', [])
            for campaign in raw_campaigns:
                campaigns.append({
                    'id': campaign.get('id'),
                    'name': campaign.get('name'),
                    'daily_budget_cents': int(float(campaign.get('daily_budget') or 0) * 100),
                    'google_campaign_id': campaign.get('google_campaign_id') or campaign.get('id'),
                    'google_customer_id': ads_data.get('account_name', ''),
                    'status': campaign.get('status', 'unknown')
                })
            campaigns.sort(key=lambda c: c.get('name', '').lower())
            logging.info(f"Competitive: Found {len(campaigns)} campaigns for account {account_id}")
        except Exception as e:
            logging.error(f"Error fetching ads state: {e}")
    else:
        # Fallback to session if _get_ads_state not available
        ads_state_key = f"ads_state_{account_id}"
        if ads_state_key in session and session[ads_state_key]:
            ads_data = session[ads_state_key]
            raw_campaigns = ads_data.get('campaigns', [])
            for campaign in raw_campaigns:
                campaigns.append({
                    'id': campaign.get('id'),
                    'name': campaign.get('name'),
                    'daily_budget_cents': int(float(campaign.get('daily_budget') or 0) * 100),
                    'google_campaign_id': campaign.get('google_campaign_id') or campaign.get('id'),
                    'google_customer_id': ads_data.get('customer_id', ''),
                    'status': campaign.get('status', 'unknown')
                })
            campaigns.sort(key=lambda c: c.get('name', '').lower())

    # If no session campaigns, try database
    if not campaigns:
        try:
            campaigns_query = text("""
                SELECT id, name, daily_budget_cents, google_campaign_id, google_customer_id
                FROM ads_campaigns
                WHERE account_id = :account_id
                ORDER BY name
            """)
            with db.engine.connect() as conn:
                result = conn.execute(campaigns_query, {"account_id": account_id})
                campaigns = [dict(row._mapping) for row in result]
        except Exception as e:
            logging.warning(f"Could not fetch campaigns from database: {e}")
            # Session was empty and DB failed - show setup message if still no campaigns
            if not campaigns:
                setup_required = True

    # Try to get recent competitive alerts (optional - may fail if tables don't exist)
    try:
        alerts_query = text("""
            SELECT ca.*, ac.name as campaign_name
            FROM competitive_alerts ca
            JOIN ads_campaigns ac ON ac.id = ca.campaign_id
            WHERE ca.account_id = :account_id
              AND ca.is_acknowledged = FALSE
            ORDER BY ca.severity DESC, ca.alert_date DESC
            LIMIT 20
        """)
        with db.engine.connect() as conn:
            result = conn.execute(alerts_query, {"account_id": account_id})
            alerts = [dict(row._mapping) for row in result]
    except Exception as e:
        logging.warning(f"Could not fetch competitive alerts: {e}")
        # Alerts are optional - continue without them

    return render_template(
        "google/competitive_dashboard.html",
        campaigns=campaigns,
        alerts=alerts,
        setup_required=setup_required
    )


@competitive_bp.route("/api/fetch-insights", methods=["POST"])
@login_required
def fetch_insights():
    """Fetch fresh auction insights from Google Ads API."""
    account_id = current_account_id()
    data = request.get_json()

    campaign_id = data.get('campaign_id')
    lookback_days = data.get('lookback_days', 30)

    # Get campaign details
    campaign_query = text("""
        SELECT google_campaign_id, google_customer_id, google_refresh_token
        FROM ads_campaigns ac
        JOIN google_ads_accounts gaa ON gaa.id = ac.google_ads_account_id
        WHERE ac.id = :campaign_id AND ac.account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(campaign_query, {
            "campaign_id": campaign_id,
            "account_id": account_id
        })
        campaign = result.first()

        if not campaign:
            return jsonify({"success": False, "error": "Campaign not found"}), 404

        campaign = dict(campaign._mapping)

    # Fetch insights
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    try:
        result = fetch_auction_insights(
            refresh_token=campaign['google_refresh_token'],
            customer_id=campaign['google_customer_id'],
            campaign_id=campaign['google_campaign_id'],
            start_date=start_date,
            end_date=end_date
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@competitive_bp.route("/api/analyze/<int:campaign_id>", methods=["GET"])
@login_required
def analyze_landscape(campaign_id):
    """Analyze competitive landscape for a campaign."""
    account_id = current_account_id()
    lookback_days = request.args.get('lookback_days', 30, type=int)

    try:
        analysis = analyze_competitive_landscape(
            account_id=account_id,
            campaign_id=campaign_id,
            lookback_days=lookback_days
        )

        return jsonify(analysis)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@competitive_bp.route("/api/track-competitor", methods=["POST"])
@login_required
def track_competitor():
    """Track a specific competitor's position changes over time."""
    account_id = current_account_id()
    data = request.get_json()

    campaign_id = data.get('campaign_id')
    competitor_domain = data.get('competitor_domain')
    days = data.get('days', 30)

    try:
        result = track_competitor_position_changes(
            account_id=account_id,
            campaign_id=campaign_id,
            competitor_domain=competitor_domain,
            days=days
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@competitive_bp.route("/api/search-terms", methods=["POST"])
@login_required
def analyze_search_terms():
    """Analyze search terms for competitive intelligence."""
    account_id = current_account_id()
    data = request.get_json()

    campaign_id = data.get('campaign_id')
    lookback_days = data.get('lookback_days', 30)

    # Get campaign details
    campaign_query = text("""
        SELECT google_campaign_id, google_customer_id, google_refresh_token
        FROM ads_campaigns ac
        JOIN google_ads_accounts gaa ON gaa.id = ac.google_ads_account_id
        WHERE ac.id = :campaign_id AND ac.account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(campaign_query, {
            "campaign_id": campaign_id,
            "account_id": account_id
        })
        campaign = result.first()

        if not campaign:
            return jsonify({"success": False, "error": "Campaign not found"}), 404

        campaign = dict(campaign._mapping)

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    try:
        result = get_search_term_competitors(
            refresh_token=campaign['google_refresh_token'],
            customer_id=campaign['google_customer_id'],
            campaign_id=campaign['google_campaign_id'],
            start_date=start_date,
            end_date=end_date
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@competitive_bp.route("/api/estimate-budget", methods=["POST"])
@login_required
def estimate_budget():
    """Estimate a competitor's budget based on impression share."""
    data = request.get_json()

    competitor_share = data.get('competitor_impression_share', 0)
    your_budget = data.get('your_daily_budget', 0)
    your_share = data.get('your_impression_share', 0)

    try:
        estimated = estimate_competitor_budget(
            competitor_impression_share=competitor_share,
            your_daily_budget=your_budget,
            your_impression_share=your_share
        )

        return jsonify({
            "success": True,
            "estimated_daily_budget": estimated
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@competitive_bp.route("/api/top-competitors", methods=["GET"])
@login_required
def get_top_competitors():
    """Get top competitors across all campaigns."""
    account_id = current_account_id()
    days = request.args.get('days', 30, type=int)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    query = text("""
        SELECT
            cai.competitor_domain,
            COUNT(DISTINCT cai.campaign_id) as campaigns_competing,
            AVG(cai.impression_share) as avg_impression_share,
            AVG(cai.position_above_rate) as avg_position_above,
            AVG(cai.overlap_rate) as avg_overlap,
            MAX(cai.data_date) as last_seen
        FROM competitive_auction_insights cai
        JOIN ads_campaigns ac ON ac.google_campaign_id = cai.campaign_id
        WHERE ac.account_id = :account_id
          AND cai.data_date BETWEEN :start_date AND :end_date
        GROUP BY cai.competitor_domain
        ORDER BY avg_impression_share DESC
        LIMIT 20
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {
            "account_id": account_id,
            "start_date": start_date,
            "end_date": end_date
        })
        competitors = [dict(row._mapping) for row in result]

    return jsonify({
        "success": True,
        "competitors": competitors,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        }
    })


@competitive_bp.route("/api/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@login_required
def acknowledge_alert(alert_id):
    """Mark a competitive alert as acknowledged."""
    account_id = current_account_id()

    query = text("""
        UPDATE competitive_alerts
        SET is_acknowledged = TRUE, acknowledged_at = NOW()
        WHERE id = :alert_id AND account_id = :account_id
    """)

    try:
        with db.engine.begin() as conn:
            conn.execute(query, {
                "alert_id": alert_id,
                "account_id": account_id
            })

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@competitive_bp.route("/api/market-share", methods=["GET"])
@login_required
def get_market_share():
    """Calculate market share analysis."""
    account_id = current_account_id()
    campaign_id = request.args.get('campaign_id', type=int)
    days = request.args.get('days', 30, type=int)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Get your impression share
    your_share_query = text("""
        SELECT AVG(impression_share) as your_share
        FROM campaign_performance_history
        WHERE campaign_id = :campaign_id
          AND account_id = :account_id
          AND date BETWEEN :start_date AND :end_date
    """)

    # Get competitors' total share
    competitors_query = text("""
        SELECT
            SUM(cai.impression_share) as competitors_total_share,
            COUNT(DISTINCT cai.competitor_domain) as competitor_count
        FROM competitive_auction_insights cai
        JOIN ads_campaigns ac ON ac.google_campaign_id = cai.campaign_id
        WHERE ac.id = :campaign_id
          AND ac.account_id = :account_id
          AND cai.data_date BETWEEN :start_date AND :end_date
    """)

    with db.engine.connect() as conn:
        # Your share
        result = conn.execute(your_share_query, {
            "campaign_id": campaign_id,
            "account_id": account_id,
            "start_date": start_date,
            "end_date": end_date
        })
        your_data = result.first()
        your_share = your_data[0] if your_data and your_data[0] else 0

        # Competitors' share
        result = conn.execute(competitors_query, {
            "campaign_id": campaign_id,
            "account_id": account_id,
            "start_date": start_date,
            "end_date": end_date
        })
        comp_data = result.first()
        competitors_share = comp_data[0] if comp_data and comp_data[0] else 0
        competitor_count = comp_data[1] if comp_data and comp_data[1] else 0

    # Calculate market position
    total_known_share = your_share + competitors_share
    your_market_position = (your_share / total_known_share * 100) if total_known_share > 0 else 0

    # Market concentration (Herfindahl-Hirschman Index approximation)
    market_concentration = "fragmented" if competitor_count > 10 else "moderate" if competitor_count > 5 else "concentrated"

    return jsonify({
        "success": True,
        "your_impression_share": round(your_share * 100, 2),
        "competitors_total_share": round(competitors_share * 100, 2),
        "your_market_position_pct": round(your_market_position, 2),
        "competitor_count": competitor_count,
        "market_concentration": market_concentration,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        }
    })
