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

    if not accounts:
        # Diagnostic: explain why no accounts found
        diag_query = text("""
            SELECT
                (SELECT COUNT(*) FROM accounts WHERE status IN ('active', 'trial')) as active_accounts,
                (SELECT COUNT(*) FROM accounts WHERE google_ads_customer_id IS NOT NULL) as accounts_with_gads,
                (SELECT COUNT(*) FROM google_oauth_tokens WHERE product = 'ads') as ads_tokens,
                (SELECT COUNT(*) FROM google_oauth_tokens WHERE product = 'ads' AND credentials_json IS NOT NULL) as ads_tokens_with_creds
        """)
        with db.engine.connect() as conn:
            diag = dict(conn.execute(diag_query).first()._mapping)

        print(f"No accounts found for agent execution. Diagnostic:")
        print(f"  Active/trial accounts: {diag['active_accounts']}")
        print(f"  Accounts with google_ads_customer_id: {diag['accounts_with_gads']}")
        print(f"  Google OAuth tokens (ads): {diag['ads_tokens']}")
        print(f"  OAuth tokens with credentials: {diag['ads_tokens_with_creds']}")
        print(f"\nRequirements: account must be active/trial, have google_ads_customer_id set,")
        print(f"and have a Google OAuth token with product='ads' and credentials_json set.")
        return 0, 0

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


def _load_autonomous_settings(account_id: int) -> dict:
    """
    Read autonomous mode settings for an account from account_settings table.
    Falls back to sensible defaults so agents always have a complete config.
    """
    from app import db
    KEYS = [
        'autonomous_mode_enabled', 'autonomy_level', 'growth_mode',
        'target_cpl', 'monthly_budget', 'geo_targets', 'services_priority',
    ]
    DEFAULTS = {
        'autonomous_mode_enabled': '1',
        'autonomy_level': '2',
        'growth_mode': 'balanced',
        'target_cpl': '80',
        'monthly_budget': '0',
        'geo_targets': '',
        'services_priority': '',
    }
    try:
        keys_ph = ", ".join(f"'{k}'" for k in KEYS)
        sql = text(f"""
            SELECT setting_key, setting_value
            FROM account_settings
            WHERE account_id = :aid AND setting_key IN ({keys_ph})
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id})
            stored = {r.setting_key: r.setting_value for r in rows}
    except Exception:
        stored = {}
    settings = {k: stored.get(k, DEFAULTS[k]) for k in KEYS}
    # If autonomous mode is disabled, force L1 (assistive only — log but don't execute)
    if settings['autonomous_mode_enabled'] == '0':
        settings['autonomy_level'] = '1'
    return settings


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

    try:
        from app.agents.executor import GoogleAdsAgentExecutor
    except ImportError as e:
        raise RuntimeError(
            f"Cannot import GoogleAdsAgentExecutor: {e}. "
            f"Install google-ads library with: pip install google-ads"
        )

    # Initialize infrastructure
    event_bus = EventBus()
    decision_log = DecisionLog()

    # Initialize Google Ads client
    dev_token = current_app.config.get('GOOGLE_ADS_DEVELOPER_TOKEN')
    if not dev_token:
        raise RuntimeError(
            f"GOOGLE_ADS_DEVELOPER_TOKEN is not set. "
            f"Configure it in your environment or Flask config."
        )

    try:
        executor = GoogleAdsAgentExecutor(
            refresh_token=refresh_token,
            developer_token=dev_token,
            client_customer_id=customer_id
        )
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Google Ads client: {str(e)}")

    # Load business context from Account model
    from app.models import Account as AccountModel
    account_obj = AccountModel.query.get(account_id)
    business_description = account_obj.get_business_description() or '' if account_obj else ''
    business_services = account_obj.get_business_services() or '' if account_obj else ''

    # Load autonomous mode settings (target_cpl, growth_mode, autonomy_level, etc.)
    autonomous_settings = _load_autonomous_settings(account_id)
    _target_cpl    = float(autonomous_settings.get('target_cpl', 80))
    _autonomy_level = int(autonomous_settings.get('autonomy_level', 2))
    _growth_mode   = autonomous_settings.get('growth_mode', 'balanced')

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
        # Include campaign_id so negative keywords can be added to correct campaigns
        search_terms_list = []
        try:
            st_rows = _ads_query("""
                SELECT
                    search_term_view.search_term,
                    campaign.id,
                    campaign.name,
                    metrics.cost_micros, metrics.conversions,
                    metrics.clicks, metrics.impressions
                FROM search_term_view
                WHERE segments.date DURING LAST_30_DAYS
                ORDER BY metrics.cost_micros DESC
                LIMIT 50
            """)
            for row in st_rows:
                stv = row.get("searchTermView", {})
                camp = row.get("campaign", {})
                m = row.get("metrics", {})
                cost = int(m.get("costMicros", 0)) / 1_000_000
                clicks = int(m.get("clicks", 0))
                impressions = int(m.get("impressions", 0))
                # Extract campaign ID from resource name (e.g., "customers/123/campaigns/456")
                campaign_resource = camp.get("resourceName", "")
                campaign_id = campaign_resource.split("/")[-1] if campaign_resource else ""
                search_terms_list.append({
                    'text': stv.get("searchTerm", ""),
                    'query': stv.get("searchTerm", ""),  # alias for agent compatibility
                    'campaign_id': campaign_id,
                    'campaign_name': camp.get("name", ""),
                    'spend': cost,
                    'cost': cost,  # alias for agent compatibility
                    'conversions': int(float(m.get("conversions", 0))),
                    'ctr': clicks / impressions if impressions > 0 else 0,
                })
        except Exception as e:
            current_app.logger.warning(f"Search terms fetch failed: {e}")

        # 5. Ad groups + ads — needed by AdCopyAgent + LandingPageAnalystAgent
        ad_groups_list = []
        _campaign_landing = {}  # campaign_id → {landing_url, ad_headlines}
        try:
            ad_rows = _ads_query("""
                SELECT
                    ad_group_ad.ad.id,
                    ad_group_ad.ad_group,
                    ad_group_ad.status,
                    ad_group_ad.ad.final_urls,
                    ad_group_ad.ad.responsive_search_ad.headlines,
                    ad_group_ad.ad.expanded_text_ad.headline_part1,
                    ad_group_ad.ad.expanded_text_ad.headline_part2,
                    ad_group.id,
                    ad_group.name,
                    campaign.id,
                    metrics.clicks,
                    metrics.impressions,
                    metrics.ctr,
                    metrics.cost_micros
                FROM ad_group_ad
                WHERE ad_group_ad.status != 'REMOVED'
                  AND segments.date DURING LAST_30_DAYS
                ORDER BY metrics.impressions DESC
                LIMIT 200
            """)
            _ag_map = {}
            for row in ad_rows:
                aga = row.get("adGroupAd", {})
                ag_resource = aga.get("adGroup", "")
                ag_id = ag_resource.split("/")[-1] if ag_resource else ""
                if not ag_id:
                    continue
                ad = aga.get("ad", {})
                ag_info = row.get("adGroup", {})
                m = row.get("metrics", {})
                impressions = int(m.get("impressions", 0))
                ctr = float(m.get("ctr", 0)) * 100
                ad_id = str(ad.get("id", ""))

                # Landing URL
                final_urls = ad.get("finalUrls", [])
                landing_url = final_urls[0] if final_urls else ''

                # Headlines — RSA first, ETA fallback
                rsa = ad.get("responsiveSearchAd", {})
                headlines = [h.get("text", "") for h in rsa.get("headlines", []) if h.get("text")]
                if not headlines:
                    eta = ad.get("expandedTextAd", {})
                    headlines = [h for h in [eta.get("headlinePart1", ""), eta.get("headlinePart2", "")] if h]

                if ag_id not in _ag_map:
                    _ag_map[ag_id] = {
                        'id': ag_id,
                        'name': ag_info.get("name", ""),
                        'campaign_id': str(row.get("campaign", {}).get("id", "")),
                        'ads': [],
                        '_total_ctr': 0.0,
                        '_ad_count': 0,
                        '_landing_urls': set(),
                        '_headlines': [],
                    }
                if landing_url:
                    _ag_map[ag_id]['_landing_urls'].add(landing_url)
                _ag_map[ag_id]['_headlines'].extend(
                    h for h in headlines if h not in _ag_map[ag_id]['_headlines']
                )
                _ag_map[ag_id]['ads'].append({
                    'id': ad_id,
                    'status': str(aga.get("status", "")).split(".")[-1],
                    'impressions': impressions,
                    'ctr': ctr,
                    'clicks': int(m.get("clicks", 0)),
                    'landing_url': landing_url,
                    'headlines': headlines,
                })
                _ag_map[ag_id]['_total_ctr'] += ctr
                _ag_map[ag_id]['_ad_count'] += 1

            for ag in _ag_map.values():
                avg_ctr = ag['_total_ctr'] / ag['_ad_count'] if ag['_ad_count'] > 0 else 0
                ag_landing = next(iter(ag['_landing_urls']), '')
                ad_groups_list.append({
                    'id': ag['id'],
                    'name': ag['name'],
                    'campaign_id': ag['campaign_id'],
                    'avg_ctr': avg_ctr,
                    'landing_url': ag_landing,
                    'ad_headlines': ag['_headlines'],
                    'ads': ag['ads'],
                })
                cid = ag['campaign_id']
                if cid not in _campaign_landing:
                    _campaign_landing[cid] = {'landing_url': ag_landing, 'ad_headlines': list(ag['_headlines'])}

            # Patch landing_url + ad_headlines onto campaigns list
            for c in campaigns:
                cid = c.get('id', '')
                if cid in _campaign_landing:
                    c['landing_url'] = _campaign_landing[cid]['landing_url']
                    c['ad_headlines'] = _campaign_landing[cid]['ad_headlines']

        except Exception as e:
            current_app.logger.warning(f"Ad groups fetch failed: {e}")

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
            'ad_groups': ad_groups_list,
            'total_budget': total_spend / 3,
            'target_cpa': _target_cpl,
            'target_cpl': _target_cpl,
            'growth_mode': _growth_mode,
            'autonomy_level': _autonomy_level,
            'business_goals': {
                'target_roas': 3.0,
                'target_cpl': _target_cpl,
            }
        }

        # Enrich context with performance memory (seasonal + geo patterns)
        try:
            from app.services.performance_memory import get_seasonal_context, get_top_geo_performers
            context['seasonal_memory']  = get_seasonal_context(account_id)
            context['geo_performance']  = get_top_geo_performers(account_id, limit=10)
        except Exception as _mem_exc:
            current_app.logger.debug("Performance memory unavailable: %s", _mem_exc)
            context['seasonal_memory'] = {"available": False}
            context['geo_performance'] = []

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
            'ad_groups': [],
            'total_budget': 0,
            'growth_mode': _growth_mode,
            'autonomy_level': _autonomy_level,
            'business_goals': {'target_roas': 3.0, 'target_cpl': _target_cpl}
        }

    # Common kwargs for all agents
    agent_kwargs = dict(
        event_bus=event_bus,
        decision_log=decision_log,
        account_id=account_id,
        autonomy_level=_autonomy_level,
    )

    # --- ML-powered context enrichment ---
    # Build ML predictions and LLM advice for each agent type
    # NOTE: ML models always train and learn, but only influence decisions if enabled
    ml_decisions_enabled = False
    try:
        from app.ml import is_ml_decisions_enabled
        ml_decisions_enabled = is_ml_decisions_enabled()
    except Exception:
        pass

    ml_context_builder = None
    llm_advisor = None
    context['ml_predictions'] = {}
    context['ml_decisions_enabled'] = ml_decisions_enabled

    if ml_decisions_enabled:
        try:
            from app.ml.context_builder import ContextBuilder
            from app.ml.llm_advisor import LLMAdvisor
            from app.ml.predictor import MLPredictor

            ml_context_builder = ContextBuilder(account_id, context)
            llm_advisor = LLMAdvisor()
            ml_predictor = MLPredictor(account_id)

            # Get summary of all available ML predictions
            ml_summary = ml_predictor.get_all_predictions_summary(context)
            context['ml_predictions'] = ml_summary

            print(f"  ML decisions ENABLED - models available: {len(ml_summary.get('models_available', []))}, "
                  f"unavailable: {len(ml_summary.get('models_unavailable', []))}")

        except Exception as e:
            current_app.logger.warning(f"ML system unavailable for account {account_id}: {e}")
            ml_context_builder = None
            llm_advisor = None
            context['ml_predictions'] = {}
    else:
        print(f"  ML decisions DISABLED - models learning only (enable in Admin > ML Models)")

    # Map agent types to their ML context builder methods
    AGENT_TYPE_MAP = {
        'StrategicDirectorAgent': 'strategic_director',
        'CampaignManagerAgent': 'campaign_manager',
        'BudgetGuardianAgent': 'budget_guardian',
        'QualityScoreAgent': 'quality_score',
        'KeywordOptimizerAgent': 'keyword_optimizer',
        'NegativeKeywordAgent': 'negative_keyword',
        'AdCopyAgent': 'ad_copy',
    }

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
        # NegativeKeywordAgent runs on its own daily schedule (search term data
        # has a 24h reporting delay — running every 2h re-analyses stale data)
        agents = [
            KeywordOptimizerAgent(**agent_kwargs),
            AdCopyAgent(**agent_kwargs),
        ]
    elif layer == 'negative_keyword':
        agents = [
            NegativeKeywordAgent(**agent_kwargs),
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
        # Inject ML context and LLM advice into the agent's context
        agent_class_name = type(agent).__name__
        ml_agent_type = AGENT_TYPE_MAP.get(agent_class_name)

        if ml_context_builder and ml_agent_type:
            try:
                ml_ctx = ml_context_builder.build_context_for_agent(ml_agent_type)
                context['ml_context'] = ml_ctx

                # Get LLM advice guided by ML predictions
                if llm_advisor:
                    llm_advice = llm_advisor.get_advice(ml_agent_type, ml_ctx, context)
                    context['llm_advice'] = llm_advice
                    if llm_advice.get('decisions'):
                        print(f"    LLM provided {len(llm_advice['decisions'])} recommendations for {ml_agent_type}")

            except Exception as e:
                current_app.logger.warning(f"ML/LLM enrichment failed for {ml_agent_type}: {e}")
                context['ml_context'] = ''
                context['llm_advice'] = {}
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
