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
    # Schema: accounts.status = enum('active','canceled','trial')
    #         accounts.plan = enum('free','monthly','annual')
    query = text("""
        SELECT DISTINCT
            a.id as account_id,
            a.google_ads_customer_id as customer_id,
            got.credentials_json
        FROM accounts a
        JOIN google_oauth_tokens got ON a.id = got.account_id
        WHERE got.product = 'ads'
          AND got.credentials_json IS NOT NULL
          AND a.google_ads_customer_id IS NOT NULL
          AND a.status IN ('active', 'trial')
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


def _ensure_agent_tables():
    """Create agent tables if they don't exist, and add missing columns."""
    from app import db
    with db.engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_execution_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                account_id INT NOT NULL,
                agent_id VARCHAR(64) NOT NULL,
                agent_type VARCHAR(64) NOT NULL,
                cycle_start DATETIME NOT NULL,
                cycle_duration_seconds FLOAT NULL,
                opportunities_found INT NULL DEFAULT 0,
                decisions_made INT NULL DEFAULT 0,
                auto_executed INT NULL DEFAULT 0,
                pending_approval INT NULL DEFAULT 0,
                status VARCHAR(32) NOT NULL DEFAULT 'running',
                error_message TEXT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX ix_ael_account (account_id),
                INDEX ix_ael_agent (agent_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                agent_id VARCHAR(64) NOT NULL,
                agent_type VARCHAR(64) NOT NULL,
                decision_type VARCHAR(64) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT NULL,
                reasoning TEXT NULL,
                account_id INT NOT NULL DEFAULT 0,
                customer_id VARCHAR(32) NULL DEFAULT '',
                campaign_id VARCHAR(64) NULL,
                ad_group_id VARCHAR(64) NULL,
                keyword_id VARCHAR(64) NULL,
                action_data JSON NULL,
                risk_level VARCHAR(32) NOT NULL DEFAULT 'medium',
                requires_approval TINYINT(1) NOT NULL DEFAULT 1,
                confidence FLOAT NULL DEFAULT 0.5,
                expected_monthly_savings FLOAT NULL,
                expected_monthly_leads FLOAT NULL,
                expected_improvement_pct FLOAT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                executed_at DATETIME NULL,
                execution_result JSON NULL,
                predicted_outcome JSON NULL,
                actual_outcome JSON NULL,
                prediction_accuracy FLOAT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX ix_ad_account (account_id),
                INDEX ix_ad_agent (agent_id),
                INDEX ix_ad_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_configurations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                account_id INT NULL,
                agent_id VARCHAR(64) NOT NULL,
                agent_type VARCHAR(64) NOT NULL,
                enabled TINYINT(1) NOT NULL DEFAULT 1,
                auto_execute_threshold FLOAT NULL DEFAULT 0.85,
                custom_prompt TEXT NULL,
                risk_overrides JSON NULL,
                business_rules JSON NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_agent_config (account_id, agent_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))
        # Add columns that may be missing if table was created in an earlier version
        for col_def in (
            "ADD COLUMN keyword_id VARCHAR(64) NULL AFTER ad_group_id",
            "ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at",
        ):
            try:
                conn.execute(text(f"ALTER TABLE agent_decisions {col_def}"))
            except Exception:
                pass  # Column already exists


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

    # Ensure required tables exist
    _ensure_agent_tables()

    # Extract refresh token from credentials
    # Note: credentials_json from google_oauth_tokens contains the full OAuth credentials JSON
    if isinstance(credentials_json, str):
        try:
            creds = json.loads(credentials_json)
            refresh_token = creds.get('refresh_token', credentials_json)
        except (json.JSONDecodeError, TypeError):
            refresh_token = credentials_json
    elif isinstance(credentials_json, dict):
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

    # Fetch REAL performance data from Google Ads API (live)
    try:
        from app.google.utils_ads import (
            google_ads_search, resolve_ads_context
        )
        from app.google.token_utils import ensure_access_token

        # Get a fresh access token (auto-refreshes if expired)
        access_token, _prod = ensure_access_token(account_id, ("ads", "lsa"))

        ctx = resolve_ads_context(account_id)
        login_customer_id = ctx.get("login_customer_id")

        def _ads_query(query: str):
            return google_ads_search(
                access_token=access_token,
                customer_id=customer_id,
                query=query,
                login_customer_id=login_customer_id,
                stream=True,
            )

        # 1. Account-level aggregate metrics (last 90 days)
        from datetime import date, timedelta
        _today = date.today()
        _d90 = (_today - timedelta(days=90)).strftime('%Y-%m-%d')
        _d_today = _today.strftime('%Y-%m-%d')
        account_rows = _ads_query(f"""
            SELECT
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value
            FROM customer
            WHERE segments.date BETWEEN '{_d90}' AND '{_d_today}'
        """)

        total_impressions = 0
        total_clicks = 0
        total_cost_micros = 0
        total_conversions = 0.0
        total_conversion_value = 0.0

        for row in account_rows:
            m = row.get("metrics", {})
            total_impressions += int(m.get("impressions", 0))
            total_clicks += int(m.get("clicks", 0))
            total_cost_micros += int(m.get("costMicros", 0))
            total_conversions += float(m.get("conversions", 0))
            total_conversion_value += float(m.get("conversionsValue", 0))

        total_spend = total_cost_micros / 1_000_000
        overall_roas = total_conversion_value / total_spend if total_spend > 0 else 0
        avg_cpa = total_spend / total_conversions if total_conversions > 0 else 0

        # 2. Campaign-level data (last 30 days, top 10 by spend)
        campaign_rows = _ads_query("""
            SELECT
                campaign.id, campaign.name, campaign.status,
                campaign.advertising_channel_type,
                campaign_budget.amount_micros,
                metrics.cost_micros, metrics.conversions, metrics.clicks,
                metrics.impressions, metrics.search_impression_share
            FROM campaign
            WHERE campaign.status != 'REMOVED'
              AND segments.date DURING LAST_30_DAYS
            ORDER BY metrics.cost_micros DESC
            LIMIT 10
        """)

        campaigns = []
        has_search = False
        has_pmax = False
        for row in campaign_rows:
            c = row.get("campaign", {})
            m = row.get("metrics", {})
            budget = row.get("campaignBudget", {})

            cost = int(m.get("costMicros", 0)) / 1_000_000
            conversions = float(m.get("conversions", 0))
            clicks = int(m.get("clicks", 0))
            impressions = int(m.get("impressions", 0))
            conv_value = conversions * 500  # estimate
            roas = conv_value / cost if cost > 0 else 0
            channel = c.get("advertisingChannelType", "")

            if "SEARCH" in channel:
                has_search = True
            if "PERFORMANCE_MAX" in channel:
                has_pmax = True

            search_is = m.get("searchImpressionShare")
            try:
                imp_share = float(search_is) * 100 if search_is else 50
            except (ValueError, TypeError):
                imp_share = 50

            cpl = cost / conversions if conversions > 0 else 0
            ctr = clicks / impressions * 100 if impressions > 0 else 0
            conv_rate = conversions / clicks * 100 if clicks > 0 else 0
            daily_budget_micros = int(budget.get("amountMicros", 0))
            daily_budget = daily_budget_micros / 1_000_000
            monthly_budget = daily_budget * 30.4

            campaigns.append({
                'id': str(c.get("id", "")),
                'name': c.get("name", ""),
                'type': channel.split(".")[-1] if "." in channel else channel,
                'roas': roas,
                'impression_share': imp_share,
                'monthly_spend': cost,
                'monthly_budget': monthly_budget,
                'spend_90d': cost * 3,  # estimate from 30d
                'conversions': int(conversions),
                'cpa': cpl,
                # Keys expected by CampaignManagerAgent
                'cpl_7d': cpl,
                'conversion_rate_7d': conv_rate,
                # Keys expected by BudgetGuardianAgent
                'spend_mtd': cost,  # best estimate from 30d data
                'daily_spend_avg_7d': cost / 30,
                'daily_spend_yesterday': cost / 30,  # estimate
            })

        # 3. Keyword data (last 30 days, top 30 by spend)
        keyword_rows = _ads_query("""
            SELECT
                ad_group_criterion.criterion_id,
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                ad_group_criterion.ad_group,
                metrics.cost_micros, metrics.conversions,
                metrics.clicks, metrics.impressions
            FROM keyword_view
            WHERE ad_group_criterion.status != 'REMOVED'
              AND segments.date DURING LAST_30_DAYS
            ORDER BY metrics.cost_micros DESC
            LIMIT 30
        """)

        keywords_list = []
        for row in keyword_rows:
            kw = row.get("adGroupCriterion", {})
            m = row.get("metrics", {})
            kw_keyword = kw.get("keyword", {})
            cost = int(m.get("costMicros", 0)) / 1_000_000
            conversions = float(m.get("conversions", 0))
            clicks = int(m.get("clicks", 0))
            impressions = int(m.get("impressions", 0))

            # ad_group is a resource name like "customers/123/adGroups/456"
            ad_group_resource = kw.get("adGroup", "")
            ad_group_id = ad_group_resource.split("/")[-1] if ad_group_resource else ""

            kw_cpa = cost / conversions if conversions > 0 else 0
            keywords_list.append({
                'id': str(kw.get("criterionId", "")),
                'text': kw_keyword.get("text", ""),
                'match': kw_keyword.get("matchType", ""),
                'ad_group_id': ad_group_id,
                'spend': cost,
                'conversions': int(conversions),
                'cpa': kw_cpa,
                'ctr': clicks / impressions if impressions > 0 else 0,
                'clicks': clicks,
                # Keys expected by KeywordOptimizerAgent
                'cpa_30d': kw_cpa,
                'conversions_30d': int(conversions),
                'spend_30d': cost,
                # Keys expected by QualityScoreAgent
                'monthly_spend': cost,
                'quality_score': 0,  # not available from this query
            })

        # 4. Search terms (last 30 days, top 20 by spend)
        search_terms_list = []
        try:
            st_rows = _ads_query("""
                SELECT
                    search_term_view.search_term,
                    metrics.cost_micros, metrics.conversions,
                    metrics.clicks, metrics.impressions
                FROM search_term_view
                WHERE segments.date DURING LAST_30_DAYS
                ORDER BY metrics.cost_micros DESC
                LIMIT 20
            """)
            for row in st_rows:
                stv = row.get("searchTermView", {})
                m = row.get("metrics", {})
                cost = int(m.get("costMicros", 0)) / 1_000_000
                clicks = int(m.get("clicks", 0))
                impressions = int(m.get("impressions", 0))
                search_terms_list.append({
                    'text': stv.get("searchTerm", ""),
                    'spend': cost,
                    'conversions': int(float(m.get("conversions", 0))),
                    'ctr': clicks / impressions if impressions > 0 else 0,
                })
        except Exception as e:
            current_app.logger.warning(f"Search terms fetch failed: {e}")

        context = {
            'account_id': account_id,
            'customer_id': customer_id,
            'business_description': business_description,
            'business_services': business_services,
            'performance_90d': {
                'roas': overall_roas,
                'spend': total_spend,
                'conversions': int(total_conversions),
                'cost_per_conversion': avg_cpa,
            },
            'campaigns': campaigns,
            'has_search_campaigns': has_search,
            'has_pmax_campaigns': has_pmax,
            'keywords': keywords_list,
            'search_terms': search_terms_list,
            'total_budget': total_spend / 3,
            'target_cpa': 80,         # top-level for KeywordOptimizerAgent
            'target_cpl': 80,         # top-level for CampaignManagerAgent
            'business_goals': {
                'target_roas': 3.0,
                'target_cpl': 80,
            }
        }

    except Exception as e:
        current_app.logger.error(f"Failed to fetch Google Ads data for account {account_id}: {e}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        # Fallback to minimal context if data fetch fails
        context = {
            'account_id': account_id,
            'customer_id': customer_id,
            'business_description': business_description,
            'business_services': business_services,
            'performance_90d': {},
            'campaigns': [],
            'has_search_campaigns': False,
            'has_pmax_campaigns': False,
            'keywords': [],
            'search_terms': [],
            'total_budget': 0,
            'business_goals': {'target_roas': 3.0, 'target_cpl': 80}
        }

    # Common kwargs for all agents
    agent_kwargs = dict(event_bus=event_bus, decision_log=decision_log, account_id=account_id)

    # Select agents based on layer
    if layer == 'strategic':
        agents = [
            StrategicDirectorAgent(**agent_kwargs),
        ]
    elif layer == 'operational':
        agents = [
            CampaignManagerAgent(**agent_kwargs),
            BudgetGuardianAgent(**agent_kwargs),
            QualityScoreAgent(**agent_kwargs),
        ]
    elif layer == 'tactical':
        agents = [
            KeywordOptimizerAgent(**agent_kwargs),
            NegativeKeywordAgent(**agent_kwargs),
            AdCopyAgent(**agent_kwargs),
        ]
    else:  # 'all'
        agents = [
            StrategicDirectorAgent(**agent_kwargs),
            CampaignManagerAgent(**agent_kwargs),
            BudgetGuardianAgent(**agent_kwargs),
            QualityScoreAgent(**agent_kwargs),
            KeywordOptimizerAgent(**agent_kwargs),
            NegativeKeywordAgent(**agent_kwargs),
            AdCopyAgent(**agent_kwargs),
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
            # Continue running remaining agents instead of stopping
