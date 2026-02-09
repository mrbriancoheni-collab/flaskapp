# app/google/agents_routes.py
"""
Routes for AI Agent management - Approval Queue and Dashboard.
"""
from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for, current_app
from sqlalchemy import text
from datetime import datetime

from app import db
from app.auth.utils import login_required, current_account_id

agents_bp = Blueprint("agents_bp", __name__, url_prefix="/account/google/ads/agents")


def _get_account_ads_settings(account_id: int) -> dict:
    """
    Get account-specific Google Ads settings (customer value, goals, etc.).
    Falls back to sensible defaults if not configured.
    """
    try:
        # Try to get from account_settings table if it exists
        settings_query = text("""
            SELECT setting_key, setting_value
            FROM account_settings
            WHERE account_id = :account_id
              AND setting_key IN ('ads_customer_value', 'ads_target_roas', 'ads_target_cpl')
        """)

        with db.engine.connect() as conn:
            result = conn.execute(settings_query, {"account_id": account_id})
            settings = {row.setting_key: row.setting_value for row in result}

        return {
            'customer_value': float(settings.get('ads_customer_value', 500)),
            'target_roas': float(settings.get('ads_target_roas', 3.0)),
            'target_cpl': float(settings.get('ads_target_cpl', 80))
        }
    except Exception:
        # Table might not exist or other error - return defaults
        return {
            'customer_value': 500,
            'target_roas': 3.0,
            'target_cpl': 80
        }


def _fetch_impression_share(refresh_token: str, customer_id: str) -> dict:
    """
    Fetch impression share metrics from Google Ads API.
    Returns dict with campaign_id -> metrics mapping.
    """
    import os
    from flask import current_app

    try:
        from google.ads.googleads.client import GoogleAdsClient

        client_id = current_app.config.get("GOOGLE_ADS_CLIENT_ID") or os.getenv("GOOGLE_ADS_CLIENT_ID")
        client_secret = current_app.config.get("GOOGLE_ADS_CLIENT_SECRET") or os.getenv("GOOGLE_ADS_CLIENT_SECRET")
        developer_token = current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN") or os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")
        login_customer_id = (
            current_app.config.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or
            os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or ""
        ).replace("-", "")

        cfg = {
            "developer_token": developer_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "login_customer_id": login_customer_id,
            "use_proto_plus": True
        }

        client = GoogleAdsClient.load_from_dict(cfg)
        ga_service = client.get_service("GoogleAdsService")

        # Query for campaign-level impression share (last 30 days)
        query = """
            SELECT
                campaign.id,
                campaign.name,
                metrics.search_impression_share,
                metrics.search_top_impression_share,
                metrics.search_absolute_top_impression_share,
                metrics.search_budget_lost_impression_share,
                metrics.search_rank_lost_impression_share
            FROM campaign
            WHERE segments.date DURING LAST_30_DAYS
              AND campaign.status = 'ENABLED'
        """

        result = {}
        total_impressions = 0
        weighted_impression_share = 0

        response = ga_service.search(customer_id=customer_id, query=query)
        for row in response:
            campaign_id = str(row.campaign.id)
            # Impression share is returned as a fraction (0.0 - 1.0)
            search_is = row.metrics.search_impression_share
            if search_is is not None and search_is > 0:
                result[campaign_id] = {
                    'name': row.campaign.name,
                    'search_impression_share': round(search_is * 100, 1),  # Convert to percentage
                    'search_top_impression_share': round((row.metrics.search_top_impression_share or 0) * 100, 1),
                    'search_absolute_top_impression_share': round((row.metrics.search_absolute_top_impression_share or 0) * 100, 1),
                    'budget_lost_impression_share': round((row.metrics.search_budget_lost_impression_share or 0) * 100, 1),
                    'rank_lost_impression_share': round((row.metrics.search_rank_lost_impression_share or 0) * 100, 1)
                }
                # For account-level, we'd need impressions to weight properly
                # For now, simple average
                weighted_impression_share += search_is
                total_impressions += 1

        # Calculate account-level average
        if total_impressions > 0:
            result['account'] = {
                'search_impression_share': round((weighted_impression_share / total_impressions) * 100, 1)
            }

        return result

    except Exception as e:
        current_app.logger.warning(f"Failed to fetch impression share: {e}")
        return {}  # Return empty - agents will handle None values


def _execute_agent_decision(account_id: int, decision_row) -> dict:
    """
    Execute an agent decision via the Google Ads API.

    Args:
        account_id: Account ID
        decision_row: Database row with decision details

    Returns:
        dict with 'success' key and either 'result' or 'error'
    """
    import json
    import os
    from flask import current_app

    decision_type = decision_row['decision_type']
    action_data = decision_row.get('action_data')

    # Parse action_data if it's JSON
    if action_data and isinstance(action_data, str):
        try:
            action_data = json.loads(action_data)
        except json.JSONDecodeError:
            action_data = {}
    elif not action_data:
        action_data = {}

    # Get Google Ads credentials
    try:
        creds_query = text("""
            SELECT a.google_ads_customer_id as customer_id, got.credentials_json
            FROM google_oauth_tokens got
            JOIN accounts a ON a.id = got.account_id
            WHERE got.account_id = :account_id AND got.product = 'ads'
            ORDER BY got.id DESC LIMIT 1
        """)

        with db.engine.connect() as conn:
            result = conn.execute(creds_query, {"account_id": account_id})
            creds_row = result.mappings().first()

        if not creds_row:
            return {'success': False, 'error': 'No Google Ads credentials found'}

        customer_id = creds_row['customer_id']
        creds = json.loads(creds_row['credentials_json']) if isinstance(creds_row['credentials_json'], str) else creds_row['credentials_json']
        refresh_token = creds.get('refresh_token')

        if not refresh_token:
            return {'success': False, 'error': 'No refresh token found'}

        # Initialize executor
        from app.agents.executor import GoogleAdsAgentExecutor

        developer_token = current_app.config.get('GOOGLE_ADS_DEVELOPER_TOKEN') or os.getenv('GOOGLE_ADS_DEVELOPER_TOKEN')
        if not developer_token:
            return {'success': False, 'error': 'GOOGLE_ADS_DEVELOPER_TOKEN not configured'}

        executor = GoogleAdsAgentExecutor(
            refresh_token=refresh_token,
            developer_token=developer_token,
            client_customer_id=customer_id
        )

        # Execute based on decision type
        if decision_type == 'add_negative_keyword':
            campaign_id = decision_row.get('campaign_id') or action_data.get('campaign_id')
            keyword_text = action_data.get('keyword_text')
            match_type = action_data.get('match_type', 'PHRASE')

            if not campaign_id or not keyword_text:
                return {'success': False, 'error': 'Missing campaign_id or keyword_text'}

            return executor.add_negative_keyword(str(campaign_id), keyword_text, match_type)

        elif decision_type == 'pause_keyword':
            ad_group_id = decision_row.get('ad_group_id') or action_data.get('ad_group_id')
            keyword_id = decision_row.get('keyword_id') or action_data.get('keyword_id')

            if not ad_group_id or not keyword_id:
                return {'success': False, 'error': 'Missing ad_group_id or keyword_id'}

            return executor.pause_keyword(str(ad_group_id), str(keyword_id))

        elif decision_type == 'adjust_keyword_bid':
            ad_group_id = decision_row.get('ad_group_id') or action_data.get('ad_group_id')
            keyword_id = decision_row.get('keyword_id') or action_data.get('keyword_id')
            bid_change_pct = action_data.get('bid_change_pct', 0)

            if not ad_group_id or not keyword_id:
                return {'success': False, 'error': 'Missing ad_group_id or keyword_id'}

            return executor.adjust_keyword_bid(str(ad_group_id), str(keyword_id), bid_change_pct)

        elif decision_type == 'adjust_campaign_bids':
            campaign_id = decision_row.get('campaign_id') or action_data.get('campaign_id')
            bid_change_pct = action_data.get('bid_change_pct', 0)

            if not campaign_id:
                return {'success': False, 'error': 'Missing campaign_id'}

            return executor.adjust_campaign_bids(str(campaign_id), bid_change_pct)

        elif decision_type == 'adjust_daily_budget':
            campaign_id = decision_row.get('campaign_id') or action_data.get('campaign_id')
            new_budget = action_data.get('new_budget')

            if not campaign_id or new_budget is None:
                return {'success': False, 'error': 'Missing campaign_id or new_budget'}

            return executor.adjust_daily_budget(str(campaign_id), float(new_budget))

        elif decision_type == 'pause_campaign':
            campaign_id = decision_row.get('campaign_id') or action_data.get('campaign_id')

            if not campaign_id:
                return {'success': False, 'error': 'Missing campaign_id'}

            return executor.pause_campaign(str(campaign_id))

        elif decision_type == 'scale_campaign_budget':
            campaign_id = decision_row.get('campaign_id') or action_data.get('campaign_id')
            new_budget = action_data.get('new_budget')

            if not campaign_id or new_budget is None:
                return {'success': False, 'error': 'Missing campaign_id or new_budget'}

            return executor.scale_campaign_budget(str(campaign_id), float(new_budget))

        elif decision_type == 'reallocate_budget':
            from_campaigns = action_data.get('from_campaigns', [])
            to_campaigns = action_data.get('to_campaigns', [])
            amount = action_data.get('amount', 0)

            if not from_campaigns or not to_campaigns:
                return {'success': False, 'error': 'Missing from_campaigns or to_campaigns'}

            return executor.reallocate_budget(from_campaigns, to_campaigns, float(amount))

        elif decision_type == 'add_keyword':
            ad_group_id = decision_row.get('ad_group_id') or action_data.get('ad_group_id')
            keyword_text = action_data.get('keyword_text')
            match_type = action_data.get('match_type', 'PHRASE')

            if not ad_group_id or not keyword_text:
                return {'success': False, 'error': 'Missing ad_group_id or keyword_text'}

            return executor.add_keyword(str(ad_group_id), keyword_text, match_type)

        else:
            # For unhandled decision types, return as manual action
            return {
                'success': True,
                'result': f'Decision type "{decision_type}" acknowledged (manual action required)',
                'manual': True
            }

    except Exception as e:
        current_app.logger.error(f"Failed to execute agent decision: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


@agents_bp.route("/approvals")
@login_required
def approval_queue():
    """
    Approval Queue - View and approve/reject high-risk agent decisions.
    """
    account_id = current_account_id()

    # Fetch pending decisions requiring approval
    query = text("""
        SELECT
            id, agent_id, agent_type, decision_type,
            title, description, reasoning,
            campaign_id, ad_group_id,
            risk_level, confidence,
            expected_monthly_savings, expected_monthly_leads, expected_improvement_pct,
            created_at, expires_at
        FROM agent_decisions
        WHERE account_id = :account_id
          AND status = 'pending'
          AND requires_approval = TRUE
        ORDER BY
            CASE risk_level
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                WHEN 'medium' THEN 3
                ELSE 4
            END,
            created_at DESC
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {"account_id": account_id})
        pending_decisions = [dict(row._mapping) for row in result]

    # Group by risk level for better UI
    decisions_by_risk = {
        'critical': [],
        'high': [],
        'medium': [],
        'low': []
    }

    for decision in pending_decisions:
        risk_level = decision['risk_level']
        decisions_by_risk[risk_level].append(decision)

    return render_template(
        "google/agents_approval_queue.html",
        pending_decisions=pending_decisions,
        decisions_by_risk=decisions_by_risk,
        total_pending=len(pending_decisions)
    )


@agents_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Agent Performance Dashboard - View agent performance metrics and stats.
    """
    account_id = current_account_id()

    # Get agent performance stats
    stats_query = text("""
        SELECT
            agent_type,
            COUNT(*) as total_decisions,
            SUM(CASE WHEN status = 'executed' THEN 1 ELSE 0 END) as executed_count,
            SUM(CASE WHEN status = 'approved' OR status = 'executed' THEN 1 ELSE 0 END) as approved_count,
            SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected_count,
            AVG(confidence) as avg_confidence,
            AVG(prediction_accuracy) as avg_accuracy,
            SUM(expected_monthly_savings) as total_expected_savings,
            SUM(expected_monthly_leads) as total_expected_leads
        FROM agent_decisions
        WHERE account_id = :account_id
        GROUP BY agent_type
        ORDER BY total_decisions DESC
    """)

    # Get recent activity
    recent_query = text("""
        SELECT
            id, agent_id, agent_type, decision_type,
            title, status, confidence, prediction_accuracy,
            expected_monthly_savings, expected_monthly_leads,
            created_at, executed_at
        FROM agent_decisions
        WHERE account_id = :account_id
        ORDER BY created_at DESC
        LIMIT 20
    """)

    # Get auto-execution stats
    auto_exec_query = text("""
        SELECT
            decision_type,
            COUNT(*) as count,
            AVG(confidence) as avg_confidence,
            SUM(expected_monthly_savings) as total_savings
        FROM agent_decisions
        WHERE account_id = :account_id
          AND requires_approval = FALSE
          AND status = 'executed'
        GROUP BY decision_type
        ORDER BY count DESC
        LIMIT 10
    """)

    with db.engine.connect() as conn:
        agent_stats = [dict(row._mapping) for row in conn.execute(stats_query, {"account_id": account_id})]
        recent_activity = [dict(row._mapping) for row in conn.execute(recent_query, {"account_id": account_id})]
        auto_exec_stats = [dict(row._mapping) for row in conn.execute(auto_exec_query, {"account_id": account_id})]

    # Calculate overall metrics
    total_decisions = sum(s['total_decisions'] for s in agent_stats)
    total_executed = sum(s['executed_count'] for s in agent_stats)
    total_savings = sum(s['total_expected_savings'] or 0 for s in agent_stats)
    total_leads = sum(s['total_expected_leads'] or 0 for s in agent_stats)

    return render_template(
        "google/agents_dashboard.html",
        agent_stats=agent_stats,
        recent_activity=recent_activity,
        auto_exec_stats=auto_exec_stats,
        total_decisions=total_decisions,
        total_executed=total_executed,
        total_savings=total_savings,
        total_leads=total_leads
    )


@agents_bp.route("/api/decisions/<int:decision_id>/approve", methods=["POST"])
@login_required
def approve_decision(decision_id):
    """Approve a pending agent decision and execute it."""
    from flask import current_app
    import json

    account_id = current_account_id()

    # First, get the decision details
    get_query = text("""
        SELECT id, decision_type, action_data, campaign_id, ad_group_id, keyword_id
        FROM agent_decisions
        WHERE id = :decision_id
          AND account_id = :account_id
          AND status = 'pending'
    """)

    with db.engine.connect() as conn:
        decision_row = conn.execute(get_query, {"decision_id": decision_id, "account_id": account_id}).mappings().first()

    if not decision_row:
        return jsonify({"success": False, "error": "Decision not found or already processed"}), 404

    # Mark as approved first
    approve_query = text("""
        UPDATE agent_decisions
        SET status = 'approved',
            updated_at = NOW()
        WHERE id = :decision_id
          AND account_id = :account_id
    """)

    with db.engine.begin() as conn:
        conn.execute(approve_query, {"decision_id": decision_id, "account_id": account_id})

    # Execute the decision via the executor
    execution_result = _execute_agent_decision(account_id, decision_row)

    # Update decision with execution result
    if execution_result.get('success'):
        final_query = text("""
            UPDATE agent_decisions
            SET status = 'executed',
                executed_at = NOW(),
                execution_result = :result,
                updated_at = NOW()
            WHERE id = :decision_id
        """)
        status_msg = "Decision approved and executed successfully"
    else:
        final_query = text("""
            UPDATE agent_decisions
            SET status = 'execution_failed',
                execution_result = :result,
                updated_at = NOW()
            WHERE id = :decision_id
        """)
        status_msg = f"Decision approved but execution failed: {execution_result.get('error', 'Unknown error')}"

    with db.engine.begin() as conn:
        conn.execute(final_query, {
            "decision_id": decision_id,
            "result": json.dumps(execution_result)
        })

    return jsonify({
        "success": execution_result.get('success', False),
        "message": status_msg,
        "execution_result": execution_result
    })


@agents_bp.route("/api/decisions/<int:decision_id>/reject", methods=["POST"])
@login_required
def reject_decision(decision_id):
    """Reject a pending agent decision."""
    account_id = current_account_id()

    reason = request.json.get("reason", "User rejected") if request.is_json else "User rejected"

    query = text("""
        UPDATE agent_decisions
        SET status = 'rejected',
            execution_result = :reason,
            updated_at = NOW()
        WHERE id = :decision_id
          AND account_id = :account_id
          AND status = 'pending'
    """)

    with db.engine.begin() as conn:
        result = conn.execute(query, {
            "decision_id": decision_id,
            "account_id": account_id,
            "reason": reason
        })

        if result.rowcount == 0:
            return jsonify({"success": False, "error": "Decision not found or already processed"}), 404

    return jsonify({"success": True, "message": "Decision rejected"})


@agents_bp.route("/api/decisions/auto-execute-low-risk", methods=["POST"])
@login_required
def auto_execute_low_risk():
    """
    Auto-approve and execute all pending LOW-risk decisions with high confidence.
    This catches up decisions that should have auto-executed but didn't.
    """
    import json as _json
    account_id = current_account_id()

    # Find all pending low-risk decisions
    find_query = text("""
        SELECT id, decision_type, action_data, campaign_id, ad_group_id, keyword_id,
               risk_level, confidence
        FROM agent_decisions
        WHERE account_id = :account_id
          AND status = 'pending'
          AND risk_level = 'low'
          AND confidence >= 0.80
    """)

    with db.engine.connect() as conn:
        rows = conn.execute(find_query, {"account_id": account_id}).mappings().all()

    if not rows:
        return jsonify({"success": True, "message": "No low-risk pending decisions to auto-execute", "executed": 0, "failed": 0, "total_found": 0})

    executed = 0
    failed = 0
    skipped = 0
    errors = []

    for row in rows:
        try:
            # Mark as approved
            with db.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE agent_decisions
                    SET status = 'approved', updated_at = NOW()
                    WHERE id = :id AND account_id = :account_id
                """), {"id": row['id'], "account_id": account_id})

            # Execute
            result = _execute_agent_decision(account_id, row)

            if result.get('success'):
                with db.engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE agent_decisions
                        SET status = 'executed', executed_at = NOW(),
                            execution_result = :result, updated_at = NOW()
                        WHERE id = :id
                    """), {"id": row['id'], "result": _json.dumps(result)})
                executed += 1
            else:
                with db.engine.begin() as conn:
                    conn.execute(text("""
                        UPDATE agent_decisions
                        SET status = 'execution_failed',
                            execution_result = :result, updated_at = NOW()
                        WHERE id = :id
                    """), {"id": row['id'], "result": _json.dumps(result)})
                failed += 1
                errors.append({
                    "decision_id": row['id'],
                    "type": row.get('decision_type'),
                    "error": result.get('error', 'Unknown error')
                })

        except Exception as e:
            current_app.logger.error(f"Failed to auto-execute decision {row['id']}: {e}")
            failed += 1
            errors.append({
                "decision_id": row['id'],
                "type": row.get('decision_type'),
                "error": str(e)
            })

    return jsonify({
        "success": True,
        "message": f"Auto-executed {executed} low-risk decisions ({failed} failed, {skipped} skipped)",
        "total_found": len(rows),
        "executed": executed,
        "failed": failed,
        "errors": errors[:10]  # Limit to first 10 errors for readability
    })


@agents_bp.route("/api/decisions/<int:decision_id>")
@login_required
def get_decision(decision_id):
    """Get details for a specific decision."""
    account_id = current_account_id()

    query = text("""
        SELECT *
        FROM agent_decisions
        WHERE id = :decision_id
          AND account_id = :account_id
    """)

    with db.engine.connect() as conn:
        result = conn.execute(query, {"decision_id": decision_id, "account_id": account_id})
        row = result.first()

        if not row:
            return jsonify({"error": "Decision not found"}), 404

        return jsonify(dict(row._mapping))


@agents_bp.route("/api/run", methods=["POST"])
@login_required
def run_agents():
    """
    Manually trigger agent analysis cycle for the current account.

    This is the AGENT RUNNER - it:
    1. Fetches Google Ads performance data
    2. Runs all 7 AI agents to analyze it
    3. Agents create decisions (appear in approval queue)
    4. Low-risk decisions auto-execute immediately
    """
    try:
        return _run_agents_internal()
    except Exception as e:
        current_app.logger.error(f"Run agents failed with error: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"Agent execution failed: {str(e)}"
        }), 500


def _run_agents_internal():
    """Internal implementation of run_agents with full error details."""
    account_id = current_account_id()

    # Get Google Ads credentials
    creds_query = text("""
        SELECT a.google_ads_customer_id as customer_id, got.credentials_json
        FROM google_oauth_tokens got
        JOIN accounts a ON a.id = got.account_id
        WHERE got.account_id = :account_id AND got.product = 'ads'
        LIMIT 1
    """)

    with db.engine.connect() as conn:
        result = conn.execute(creds_query, {"account_id": account_id})
        row = result.first()

        if not row:
            return jsonify({
                "success": False,
                "error": "Google Ads not connected. Please connect Google Ads first."
            }), 400

    customer_id = row.customer_id

    # Extract refresh token from credentials JSON
    import json
    try:
        creds = json.loads(row.credentials_json) if isinstance(row.credentials_json, str) else row.credentials_json
        refresh_token = creds.get('refresh_token')
        if not refresh_token:
            return jsonify({
                "success": False,
                "error": "No refresh token found in Google Ads credentials"
            }), 400
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Error parsing credentials: {str(e)}"
        }), 400

    # Import agents and infrastructure
    from app.agents import (
        StrategicDirectorAgent,
        CampaignManagerAgent,
        BudgetGuardianAgent,
        QualityScoreAgent,
        KeywordOptimizerAgent,
        NegativeKeywordAgent,
        AdCopyAgent,
        LandingPageAnalystAgent,
        EventBus,
        DecisionLog
    )
    from app.agents.executor import GoogleAdsAgentExecutor

    # Initialize infrastructure
    event_bus = EventBus()
    decision_log = DecisionLog()

    # Initialize Google Ads API executor
    try:
        executor = GoogleAdsAgentExecutor(
            refresh_token=refresh_token,
            developer_token=current_app.config.get('GOOGLE_ADS_DEVELOPER_TOKEN'),
            client_customer_id=customer_id
        )
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Failed to initialize Google Ads client: {str(e)}"
        }), 500

    # Fetch REAL performance data from Google Ads (using existing service)
    try:
        from app.services.google_ads_insights import get_account_performance_data

        perf_data = get_account_performance_data(account_id, days=90)

        # Get account-specific settings (conversion value, goals) from database
        account_settings = _get_account_ads_settings(account_id)
        customer_value = account_settings.get('customer_value', 500)  # Default $500 if not set
        target_roas = account_settings.get('target_roas', 3.0)
        target_cpl = account_settings.get('target_cpl', 80)

        # Fetch impression share from Google Ads API
        impression_share_data = _fetch_impression_share(refresh_token, customer_id)

        # Extract campaigns and calculate ROAS
        campaigns = []
        for c in perf_data.get('campaigns', []):
            spend = c.get('spend', 0)
            conversions = c.get('conversions', 0)

            # Calculate ROAS using account's actual customer value
            conversion_value = conversions * customer_value
            roas = conversion_value / spend if spend > 0 else 0

            # Get campaign-specific impression share if available
            campaign_id = str(c.get('id', ''))
            campaign_impression_share = impression_share_data.get(campaign_id, {}).get('search_impression_share')

            campaigns.append({
                'id': campaign_id,
                'name': c.get('name', ''),
                'roas': roas,
                'impression_share': campaign_impression_share,  # Real data or None
                'monthly_spend': spend / 3,  # 90 days / 3 = monthly
                'spend_90d': spend,
                'conversions': conversions,
                'cpa': c.get('cpa', 0)
            })

        summary = perf_data.get('account_summary', {})
        total_spend = summary.get('total_spend', 0)
        total_conversions = summary.get('total_conversions', 0)

        # Calculate overall ROAS using real customer value
        total_conversion_value = total_conversions * customer_value
        overall_roas = total_conversion_value / total_spend if total_spend > 0 else 0

        # Get account-level impression share
        account_impression_share = impression_share_data.get('account', {}).get('search_impression_share')

        context = {
            'account_id': account_id,
            'customer_id': customer_id,
            'customer_value': customer_value,  # Include for transparency
            'performance_90d': {
                'roas': overall_roas,
                'spend': total_spend,
                'conversions': total_conversions,
                'cost_per_conversion': summary.get('avg_cpa', 0),
                'impression_share': account_impression_share
            },
            'campaigns': campaigns,
            'keywords': perf_data.get('keywords', []),
            'search_terms': perf_data.get('search_terms', []),
            'total_budget': total_spend / 3,  # Monthly budget estimate
            'business_goals': {
                'target_roas': target_roas,
                'target_cpl': target_cpl,
                'customer_value': customer_value
            }
        }

    except Exception as e:
        current_app.logger.error(f"Failed to fetch Google Ads data: {str(e)}")
        # Fallback to minimal context if data fetch fails
        context = {
            'account_id': account_id,
            'customer_id': customer_id,
            'performance_90d': {},
            'campaigns': [],
            'keywords': [],
            'search_terms': [],
            'total_budget': 0,
            'business_goals': {'target_roas': 3.0, 'target_cpl': 80}
        }

    # Run all agents
    results = []
    agents = [
        StrategicDirectorAgent(event_bus=event_bus, decision_log=decision_log),
        CampaignManagerAgent(event_bus=event_bus, decision_log=decision_log),
        BudgetGuardianAgent(event_bus=event_bus, decision_log=decision_log),
        QualityScoreAgent(event_bus=event_bus, decision_log=decision_log),
        KeywordOptimizerAgent(event_bus=event_bus, decision_log=decision_log),
        NegativeKeywordAgent(event_bus=event_bus, decision_log=decision_log),
        AdCopyAgent(event_bus=event_bus, decision_log=decision_log),
        LandingPageAnalystAgent(event_bus=event_bus, decision_log=decision_log),
    ]

    total_decisions = 0
    total_auto_executed = 0
    total_pending_approval = 0

    for agent in agents:
        try:
            cycle_result = agent.run_cycle(context, executor)
            results.append(cycle_result)

            total_decisions += cycle_result['decisions_made']
            total_auto_executed += len(cycle_result['auto_executed'])
            total_pending_approval += len(cycle_result['pending_approval'])

        except Exception as e:
            current_app.logger.error(f"Error running agent {agent.agent_id}: {str(e)}")
            results.append({
                'agent_id': agent.agent_id,
                'agent_type': agent.agent_type,
                'error': str(e)
            })

    return jsonify({
        "success": True,
        "message": f"Ran {len(agents)} agents successfully",
        "summary": {
            "total_decisions": total_decisions,
            "auto_executed": total_auto_executed,
            "pending_approval": total_pending_approval
        },
        "results": results
    })
