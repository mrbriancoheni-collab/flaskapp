# app/google/competitive_routes.py
"""
Competitive Intelligence Routes - Dashboard and API endpoints for competitive analysis.
"""
from flask import Blueprint, render_template, jsonify, request, session, current_app
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
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
    COMPETITIVE_SERVICE_AVAILABLE = True
except ImportError:
    COMPETITIVE_SERVICE_AVAILABLE = False
    logging.warning("competitive_intelligence_service not available - using stubs")

    # Service not implemented yet - provide stubs
    def fetch_auction_insights(*args, **kwargs):
        return {"success": False, "error": "Competitive intelligence service not configured. This feature will be available in a future update."}

    def analyze_competitive_landscape(*args, **kwargs):
        return {"success": False, "error": "Competitive intelligence service not configured. This feature will be available in a future update."}

    def track_competitor_position_changes(*args, **kwargs):
        return {"success": False, "error": "Competitive intelligence service not configured. This feature will be available in a future update."}

    def get_search_term_competitors(*args, **kwargs):
        return {"success": False, "error": "Competitive intelligence service not configured. This feature will be available in a future update."}

    def estimate_competitor_budget(*args, **kwargs):
        return 0

competitive_bp = Blueprint("competitive_bp", __name__, url_prefix="/account/google/ads/competitive")


def _table_exists(table_name: str) -> bool:
    """Check if a database table exists."""
    try:
        with db.engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT COUNT(*) FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table_name
                """),
                {"table_name": table_name}
            )
            return result.scalar() > 0
    except Exception as e:
        logging.warning(f"Could not check if table {table_name} exists: {e}")
        return False


def _safe_db_query(query_func, default=None):
    """
    Execute a database query safely, catching table-not-found errors.

    Args:
        query_func: A callable that executes the database query
        default: Default value to return on error

    Returns:
        Query result or default value
    """
    try:
        return query_func()
    except (OperationalError, ProgrammingError) as e:
        error_msg = str(e).lower()
        if "doesn't exist" in error_msg or "does not exist" in error_msg or "no such table" in error_msg:
            logging.warning(f"Database table does not exist: {e}")
        else:
            logging.error(f"Database error: {e}")
        return default
    except Exception as e:
        logging.error(f"Unexpected error in database query: {e}")
        return default


def _transform_campaign_data(campaign, customer_id: str = '') -> dict:
    """
    Safely transform campaign data with null checks.

    Args:
        campaign: Raw campaign data dict
        customer_id: Optional customer ID to include

    Returns:
        Transformed campaign dict with safe defaults
    """
    try:
        daily_budget = campaign.get('daily_budget')
        if daily_budget is None:
            daily_budget = 0

        return {
            'id': campaign.get('id'),
            'name': campaign.get('name') or 'Unnamed Campaign',
            'daily_budget_cents': int(float(daily_budget) * 100),
            'google_campaign_id': campaign.get('google_campaign_id') or campaign.get('id'),
            'google_customer_id': customer_id or campaign.get('google_customer_id', ''),
            'status': campaign.get('status') or 'unknown'
        }
    except (TypeError, ValueError) as e:
        logging.warning(f"Error transforming campaign data: {e}")
        return None


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
    error_message = None
    customer_id = None

    # Import the function that fetches and caches ads data
    _get_ads_state = None
    _is_connected = None
    try:
        from app.google import _get_ads_state, _is_connected
    except ImportError as e:
        logging.error(f"Could not import _get_ads_state from app.google: {e}")

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
            if ads_data:
                raw_campaigns = ads_data.get('campaigns', []) or []
                customer_id = ads_data.get('account_name') or ads_data.get('customer_id', '')

                for campaign in raw_campaigns:
                    transformed = _transform_campaign_data(campaign, customer_id)
                    if transformed:
                        campaigns.append(transformed)

                campaigns.sort(key=lambda c: (c.get('name') or '').lower())
                logging.info(f"Competitive: Found {len(campaigns)} campaigns for account {account_id}")
        except Exception as e:
            logging.error(f"Error fetching ads state: {e}")
            error_message = "Error loading campaign data."

    # Fallback to session if _get_ads_state not available or returned empty
    if not campaigns:
        ads_state_key = f"ads_state_{account_id}"
        try:
            if ads_state_key in session and session[ads_state_key]:
                ads_data = session[ads_state_key]
                raw_campaigns = ads_data.get('campaigns', []) or []
                customer_id = customer_id or ads_data.get('account_name') or ads_data.get('customer_id', '')

                for campaign in raw_campaigns:
                    transformed = _transform_campaign_data(campaign, customer_id)
                    if transformed:
                        campaigns.append(transformed)

                campaigns.sort(key=lambda c: (c.get('name') or '').lower())
                logging.info(f"Competitive: Session fallback - {len(campaigns)} campaigns")
        except Exception as e:
            logging.warning(f"Session access error: {e}")

    # If no session campaigns, try database
    if not campaigns:
        def _fetch_db_campaigns():
            campaigns_query = text("""
                SELECT id, name, daily_budget_cents, google_campaign_id, google_customer_id
                FROM ads_campaigns
                WHERE account_id = :account_id
                ORDER BY name
            """)
            with db.engine.connect() as conn:
                result = conn.execute(campaigns_query, {"account_id": account_id})
                return [dict(row._mapping) for row in result]

        db_campaigns = _safe_db_query(_fetch_db_campaigns, default=[])
        if db_campaigns:
            campaigns = db_campaigns
            logging.info(f"Competitive: DB fallback - {len(campaigns)} campaigns")
        else:
            # All sources failed - show setup message
            setup_required = True

    # Try to get recent competitive alerts (optional - may fail if tables don't exist)
    if _table_exists('competitive_alerts') and _table_exists('ads_campaigns'):
        def _fetch_alerts():
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
                return [dict(row._mapping) for row in result]

        alerts = _safe_db_query(_fetch_alerts, default=[])
    else:
        logging.info("competitive_alerts or ads_campaigns table does not exist, skipping alerts")

    # Add service availability info
    service_available = COMPETITIVE_SERVICE_AVAILABLE

    return render_template(
        "google/competitive_dashboard.html",
        campaigns=campaigns,
        alerts=alerts,
        setup_required=setup_required,
        is_connected=is_connected,
        service_available=service_available,
        error_message=error_message
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

    # Check if required tables exist
    if not _table_exists('competitive_auction_insights') or not _table_exists('ads_campaigns'):
        return jsonify({
            "success": True,
            "competitors": [],
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat()
            },
            "message": "Competitive data not yet available. Data will appear after the first auction insights sync."
        })

    def _fetch_competitors():
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
            return [dict(row._mapping) for row in result]

    competitors = _safe_db_query(_fetch_competitors, default=[])

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

    if not campaign_id:
        return jsonify({
            "success": False,
            "error": "campaign_id is required"
        }), 400

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Default response for when data is not available
    default_response = {
        "success": True,
        "your_impression_share": 0,
        "competitors_total_share": 0,
        "your_market_position_pct": 0,
        "competitor_count": 0,
        "market_concentration": "unknown",
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        },
        "message": "Market share data not yet available."
    }

    # Check if required tables exist
    has_performance_table = _table_exists('campaign_performance_history')
    has_insights_table = _table_exists('competitive_auction_insights')
    has_campaigns_table = _table_exists('ads_campaigns')

    if not has_campaigns_table:
        return jsonify(default_response)

    your_share = 0
    competitors_share = 0
    competitor_count = 0

    # Get your impression share (if table exists)
    if has_performance_table:
        def _get_your_share():
            your_share_query = text("""
                SELECT AVG(impression_share) as your_share
                FROM campaign_performance_history
                WHERE campaign_id = :campaign_id
                  AND account_id = :account_id
                  AND date BETWEEN :start_date AND :end_date
            """)
            with db.engine.connect() as conn:
                result = conn.execute(your_share_query, {
                    "campaign_id": campaign_id,
                    "account_id": account_id,
                    "start_date": start_date,
                    "end_date": end_date
                })
                your_data = result.first()
                return your_data[0] if your_data and your_data[0] else 0

        your_share = _safe_db_query(_get_your_share, default=0) or 0

    # Get competitors' total share (if tables exist)
    if has_insights_table:
        def _get_competitor_share():
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
                result = conn.execute(competitors_query, {
                    "campaign_id": campaign_id,
                    "account_id": account_id,
                    "start_date": start_date,
                    "end_date": end_date
                })
                comp_data = result.first()
                return (
                    comp_data[0] if comp_data and comp_data[0] else 0,
                    comp_data[1] if comp_data and comp_data[1] else 0
                )

        result = _safe_db_query(_get_competitor_share, default=(0, 0))
        if result:
            competitors_share, competitor_count = result

    # Calculate market position
    total_known_share = your_share + competitors_share
    your_market_position = (your_share / total_known_share * 100) if total_known_share > 0 else 0

    # Market concentration (Herfindahl-Hirschman Index approximation)
    if competitor_count == 0:
        market_concentration = "unknown"
    elif competitor_count > 10:
        market_concentration = "fragmented"
    elif competitor_count > 5:
        market_concentration = "moderate"
    else:
        market_concentration = "concentrated"

    return jsonify({
        "success": True,
        "your_impression_share": round(float(your_share) * 100, 2),
        "competitors_total_share": round(float(competitors_share) * 100, 2),
        "your_market_position_pct": round(your_market_position, 2),
        "competitor_count": int(competitor_count),
        "market_concentration": market_concentration,
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        }
    })
