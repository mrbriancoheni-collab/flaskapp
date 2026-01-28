"""
Agent Scheduler - Runs AI agents periodically for all active accounts.

This module provides functions to run agents on a schedule:
- Strategic agents: Daily at 6am
- Operational agents: Every 4 hours
- Tactical agents: Hourly

Usage:
    flask run-agents --layer tactical
    flask run-agents --layer operational
    flask run-agents --layer strategic
    flask run-agents --all
"""
import os
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy import text
from flask import current_app


def run_agents_for_all_accounts(layer: str = 'all'):
    """
    Run AI agents for all active accounts with Google Ads connected.

    Args:
        layer: Which layer to run ('strategic', 'operational', 'tactical', or 'all')
    """
    from app import db

    # Get all active accounts with Google Ads connected
    query = text("""
        SELECT DISTINCT
            a.id as account_id,
            gaa.customer_id,
            gaa.refresh_token as credentials_json
        FROM accounts a
        JOIN google_ads_auth gaa ON a.id = gaa.account_id
        WHERE gaa.refresh_token IS NOT NULL
          AND gaa.customer_id IS NOT NULL
          AND a.plan IN ('pro', 'team', 'enterprise')
          AND (a.stripe_status IN ('active', 'trialing') OR a.plan = 'enterprise')
    """)

    with db.engine.connect() as conn:
        accounts = [dict(row._mapping) for row in conn.execute(query)]

    print(f"Running {layer} agents for {len(accounts)} accounts...")

    success_count = 0
    error_count = 0

    for account in accounts:
        try:
            run_agents_for_account(
                account_id=account['account_id'],
                customer_id=account['customer_id'],
                credentials_json=account['credentials_json'],
                layer=layer
            )
            success_count += 1
            print(f"✓ Account {account['account_id']} completed")
        except Exception as e:
            error_count += 1
            print(f"✗ Account {account['account_id']} failed: {str(e)}")

    print(f"\nCompleted: {success_count} succeeded, {error_count} failed")
    return success_count, error_count


def run_agents_for_account(
    account_id: int,
    customer_id: str,
    credentials_json: Any,
    layer: str = 'all'
):
    """
    Run agents for a single account.

    Args:
        account_id: Account ID
        customer_id: Google Ads customer ID
        credentials_json: Google Ads credentials (JSON or dict)
        layer: Which layer to run ('strategic', 'operational', 'tactical', or 'all')
    """
    from app import db
    import json

    # Extract refresh token from credentials
    # Note: credentials_json is now the refresh_token directly from google_ads_auth table
    if isinstance(credentials_json, str):
        refresh_token = credentials_json
    elif isinstance(credentials_json, dict):
        # Fallback for old format (if somehow still present)
        refresh_token = credentials_json.get('refresh_token')
    else:
        refresh_token = None

    if not refresh_token:
        raise ValueError(f"No refresh token for account {account_id}")

    # Import agents
    from app.agents import (
        StrategicDirectorAgent,
        CampaignManagerAgent,
        BudgetGuardianAgent,
        QualityScoreAgent,
        KeywordOptimizerAgent,
        NegativeKeywordAgent,
        AdCopyAgent,
        EventBus,
        DecisionLog
    )
    from app.agents.executor import GoogleAdsAgentExecutor

    # Initialize infrastructure
    event_bus = EventBus()
    decision_log = DecisionLog()

    # Initialize Google Ads client
    try:
        executor = GoogleAdsAgentExecutor(
            refresh_token=refresh_token,
            developer_token=current_app.config.get('GOOGLE_ADS_DEVELOPER_TOKEN'),
            client_customer_id=customer_id
        )
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Google Ads client: {str(e)}")

    # Load business context from Account model
    from app.models import Account as AccountModel
    account_obj = AccountModel.query.get(account_id)
    business_description = account_obj.get_business_description() or '' if account_obj else ''
    business_services = account_obj.get_business_services() or '' if account_obj else ''

    # Fetch REAL performance data from Google Ads
    try:
        from app.services.google_ads_insights import get_account_performance_data

        perf_data = get_account_performance_data(account_id, days=90)

        # Extract campaigns and calculate ROAS
        campaigns = []
        for c in perf_data.get('campaigns', []):
            spend = c.get('spend', 0)
            conversions = c.get('conversions', 0)
            conversion_value = conversions * 500
            roas = conversion_value / spend if spend > 0 else 0

            campaigns.append({
                'id': str(c.get('id', '')),
                'name': c.get('name', ''),
                'roas': roas,
                'impression_share': 70,
                'monthly_spend': spend / 3,
                'spend_90d': spend,
                'conversions': conversions,
                'cpa': c.get('cpa', 0)
            })

        summary = perf_data.get('account_summary', {})
        total_spend = summary.get('total_spend', 0)
        total_conversions = summary.get('total_conversions', 0)
        conversion_value = total_conversions * 500
        overall_roas = conversion_value / total_spend if total_spend > 0 else 0

        context = {
            'account_id': account_id,
            'customer_id': customer_id,
            'business_description': business_description,
            'business_services': business_services,
            'performance_90d': {
                'roas': overall_roas,
                'spend': total_spend,
                'conversions': total_conversions,
                'cost_per_conversion': summary.get('avg_cpa', 0)
            },
            'campaigns': campaigns,
            'keywords': perf_data.get('keywords', []),
            'search_terms': perf_data.get('search_terms', []),
            'total_budget': total_spend / 3,
            'business_goals': {
                'target_roas': 3.0,
                'target_cpl': 80
            }
        }

    except Exception as e:
        print(f"Failed to fetch Google Ads data: {str(e)}")
        # Fallback to minimal context if data fetch fails
        context = {
            'account_id': account_id,
            'customer_id': customer_id,
            'business_description': business_description,
            'business_services': business_services,
            'performance_90d': {},
            'campaigns': [],
            'keywords': [],
            'search_terms': [],
            'total_budget': 0,
            'business_goals': {'target_roas': 3.0, 'target_cpl': 80}
        }

    # Select agents based on layer
    if layer == 'strategic':
        agents = [
            StrategicDirectorAgent(event_bus=event_bus, decision_log=decision_log),
        ]
    elif layer == 'operational':
        agents = [
            CampaignManagerAgent(event_bus=event_bus, decision_log=decision_log),
            BudgetGuardianAgent(event_bus=event_bus, decision_log=decision_log),
            QualityScoreAgent(event_bus=event_bus, decision_log=decision_log),
        ]
    elif layer == 'tactical':
        agents = [
            KeywordOptimizerAgent(event_bus=event_bus, decision_log=decision_log),
            NegativeKeywordAgent(event_bus=event_bus, decision_log=decision_log),
            AdCopyAgent(event_bus=event_bus, decision_log=decision_log),
        ]
    else:  # 'all'
        agents = [
            StrategicDirectorAgent(event_bus=event_bus, decision_log=decision_log),
            CampaignManagerAgent(event_bus=event_bus, decision_log=decision_log),
            BudgetGuardianAgent(event_bus=event_bus, decision_log=decision_log),
            QualityScoreAgent(event_bus=event_bus, decision_log=decision_log),
            KeywordOptimizerAgent(event_bus=event_bus, decision_log=decision_log),
            NegativeKeywordAgent(event_bus=event_bus, decision_log=decision_log),
            AdCopyAgent(event_bus=event_bus, decision_log=decision_log),
        ]

    # Run agents and log execution
    for agent in agents:
        try:
            result = agent.run_cycle(context, executor)

            # Log execution to database
            log_query = text("""
                INSERT INTO agent_execution_log
                (account_id, agent_id, agent_type, cycle_start, cycle_duration_seconds,
                 opportunities_found, decisions_made, auto_executed, pending_approval, status)
                VALUES
                (:account_id, :agent_id, :agent_type, :cycle_start, :cycle_duration,
                 :opportunities, :decisions, :auto_exec, :pending, :status)
            """)

            with db.engine.begin() as conn:
                conn.execute(log_query, {
                    'account_id': account_id,
                    'agent_id': result['agent_id'],
                    'agent_type': result['agent_type'],
                    'cycle_start': result['cycle_start'],
                    'cycle_duration': result['cycle_duration_seconds'],
                    'opportunities': result['opportunities_found'],
                    'decisions': result['decisions_made'],
                    'auto_exec': len(result['auto_executed']),
                    'pending': len(result['pending_approval']),
                    'status': 'completed'
                })

            print(f"  ✓ {agent.agent_type}: {result['decisions_made']} decisions")

        except Exception as e:
            # Log error to database
            error_query = text("""
                INSERT INTO agent_execution_log
                (account_id, agent_id, agent_type, cycle_start, status, error_message)
                VALUES
                (:account_id, :agent_id, :agent_type, NOW(), 'failed', :error)
            """)

            with db.engine.begin() as conn:
                conn.execute(error_query, {
                    'account_id': account_id,
                    'agent_id': agent.agent_id,
                    'agent_type': agent.agent_type,
                    'error': str(e)
                })

            print(f"  ✗ {agent.agent_type} failed: {str(e)}")
            raise
