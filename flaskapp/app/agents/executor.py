# app/agents/executor.py
"""
Agent Executor - Connects agents to Google Ads API for real execution.

Provides concrete implementations of agent actions using the Google Ads API.
"""

from typing import Dict, Any, Optional
import logging
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

logger = logging.getLogger(__name__)


class GoogleAdsAgentExecutor:
    """
    Executes agent decisions using the Google Ads API.

    This class provides the concrete implementation layer that translates
    agent decisions into actual Google Ads API calls.
    """

    def __init__(self, refresh_token: str, developer_token: str, client_customer_id: str):
        """
        Initialize the executor with Google Ads credentials.

        Args:
            refresh_token: OAuth refresh token
            developer_token: Google Ads API developer token
            client_customer_id: Customer ID (without hyphens)
        """
        self.refresh_token = refresh_token
        self.developer_token = developer_token
        self.client_customer_id = client_customer_id
        self.client = None

    def get_client(self) -> GoogleAdsClient:
        """Get or create Google Ads API client."""
        if self.client is None:
            import os
            from flask import current_app

            # Get credentials from Flask config or environment variables
            client_id = (
                current_app.config.get("GOOGLE_ADS_CLIENT_ID") or
                os.getenv("GOOGLE_ADS_CLIENT_ID")
            )
            client_secret = (
                current_app.config.get("GOOGLE_ADS_CLIENT_SECRET") or
                os.getenv("GOOGLE_ADS_CLIENT_SECRET")
            )
            login_customer_id = (
                current_app.config.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or
                os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID") or
                ""
            ).replace("-", "")

            if not client_id or not client_secret:
                raise ValueError("GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET must be configured")

            # Configuration for Google Ads API
            config = {
                "developer_token": self.developer_token,
                "refresh_token": self.refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "login_customer_id": login_customer_id or self.client_customer_id,
                "use_proto_plus": True
            }

            try:
                self.client = GoogleAdsClient.load_from_dict(config)
            except Exception as e:
                logger.error(f"Failed to create Google Ads client: {e}")
                raise

        return self.client

    # ==========================================
    # STRATEGIC LAYER EXECUTIONS
    # ==========================================

    def reallocate_budget(self, from_campaigns: list, to_campaigns: list, amount: float) -> Dict[str, Any]:
        """
        Reallocate budget between campaigns.

        Args:
            from_campaigns: List of campaign IDs to reduce budget from
            to_campaigns: List of campaign IDs to increase budget to
            amount: Total amount to reallocate

        Returns:
            Execution result with details
        """
        client = self.get_client()

        try:
            # Calculate per-campaign adjustments
            reduction_per_campaign = amount / len(from_campaigns)
            increase_per_campaign = amount / len(to_campaigns)

            campaign_service = client.get_service("CampaignService")
            campaign_budget_service = client.get_service("CampaignBudgetService")

            operations = []

            # Reduce budgets
            for campaign_id in from_campaigns:
                campaign_resource_name = campaign_service.campaign_path(
                    self.client_customer_id, campaign_id
                )

                operation = client.get_type("CampaignOperation")
                campaign = operation.update
                campaign.resource_name = campaign_resource_name

                # Note: In reality, need to get current budget and adjust
                # This is simplified for the example

                operations.append(operation)

            # Increase budgets
            for campaign_id in to_campaigns:
                campaign_resource_name = campaign_service.campaign_path(
                    self.client_customer_id, campaign_id
                )

                operation = client.get_type("CampaignOperation")
                campaign = operation.update
                campaign.resource_name = campaign_resource_name

                operations.append(operation)

            # Execute mutations
            if operations:
                response = campaign_service.mutate_campaigns(
                    customer_id=self.client_customer_id,
                    operations=operations
                )

                return {
                    'success': True,
                    'campaigns_updated': len(response.results),
                    'amount_reallocated': amount
                }

            return {'success': False, 'error': 'No operations to execute'}

        except GoogleAdsException as ex:
            logger.error(f"Google Ads API error: {ex}")
            return {
                'success': False,
                'error': str(ex),
                'error_type': 'google_ads_api'
            }

    def scale_campaign_budget(self, campaign_id: str, new_budget: float) -> Dict[str, Any]:
        """
        Increase campaign budget.

        Args:
            campaign_id: Campaign ID to scale
            new_budget: New daily budget amount

        Returns:
            Execution result
        """
        client = self.get_client()

        try:
            campaign_service = client.get_service("CampaignService")
            campaign_budget_service = client.get_service("CampaignBudgetService")

            # Get current campaign to find its budget
            campaign_resource_name = campaign_service.campaign_path(
                self.client_customer_id, campaign_id
            )

            # Create new budget or update existing
            operation = client.get_type("CampaignBudgetOperation")
            budget = operation.update
            budget.amount_micros = int(new_budget * 1_000_000)  # Convert to micros

            response = campaign_budget_service.mutate_campaign_budgets(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'campaign_id': campaign_id,
                'new_budget': new_budget,
                'budget_resource': response.results[0].resource_name
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to scale campaign budget: {ex}")
            return {'success': False, 'error': str(ex)}

    def pause_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """
        Pause a campaign.

        Args:
            campaign_id: Campaign ID to pause

        Returns:
            Execution result
        """
        client = self.get_client()

        try:
            campaign_service = client.get_service("CampaignService")

            operation = client.get_type("CampaignOperation")
            campaign = operation.update
            campaign.resource_name = campaign_service.campaign_path(
                self.client_customer_id, campaign_id
            )
            campaign.status = client.enums.CampaignStatusEnum.PAUSED

            operation.update_mask.paths.append("status")

            response = campaign_service.mutate_campaigns(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'campaign_id': campaign_id,
                'status': 'PAUSED',
                'resource': response.results[0].resource_name
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to pause campaign: {ex}")
            return {'success': False, 'error': str(ex)}

    # ==========================================
    # OPERATIONAL LAYER EXECUTIONS
    # ==========================================

    def adjust_campaign_bids(self, campaign_id: str, bid_change_pct: float) -> Dict[str, Any]:
        """
        Adjust all keyword bids in a campaign by a percentage.

        Args:
            campaign_id: Campaign ID
            bid_change_pct: Percentage to adjust bids by (e.g., -15 for 15% reduction)

        Returns:
            Execution result
        """
        client = self.get_client()

        try:
            ga_service = client.get_service("GoogleAdsService")
            ad_group_criterion_service = client.get_service("AdGroupCriterionService")

            # Query all keywords in the campaign
            query = f"""
                SELECT
                    ad_group_criterion.resource_name,
                    ad_group_criterion.criterion_id,
                    ad_group_criterion.cpc_bid_micros
                FROM ad_group_criterion
                WHERE campaign.id = {campaign_id}
                  AND ad_group_criterion.type = KEYWORD
                  AND ad_group_criterion.status = ENABLED
            """

            response = ga_service.search(customer_id=self.client_customer_id, query=query)

            operations = []
            keywords_updated = 0

            for row in response:
                criterion = row.ad_group_criterion
                current_bid = criterion.cpc_bid_micros

                if current_bid > 0:
                    new_bid = int(current_bid * (1 + bid_change_pct / 100))
                    new_bid = max(10_000, new_bid)  # Minimum bid: $0.01

                    operation = client.get_type("AdGroupCriterionOperation")
                    ad_group_criterion = operation.update
                    ad_group_criterion.resource_name = criterion.resource_name
                    ad_group_criterion.cpc_bid_micros = new_bid

                    operation.update_mask.paths.append("cpc_bid_micros")
                    operations.append(operation)
                    keywords_updated += 1

            # Execute in batches of 100
            if operations:
                for i in range(0, len(operations), 100):
                    batch = operations[i:i+100]
                    ad_group_criterion_service.mutate_ad_group_criteria(
                        customer_id=self.client_customer_id,
                        operations=batch
                    )

            return {
                'success': True,
                'campaign_id': campaign_id,
                'bid_change_pct': bid_change_pct,
                'keywords_updated': keywords_updated
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to adjust campaign bids: {ex}")
            return {'success': False, 'error': str(ex)}

    def adjust_daily_budget(self, campaign_id: str, new_daily_budget: float) -> Dict[str, Any]:
        """
        Adjust campaign daily budget.

        Args:
            campaign_id: Campaign ID
            new_daily_budget: New daily budget amount

        Returns:
            Execution result
        """
        return self.scale_campaign_budget(campaign_id, new_daily_budget)

    # ==========================================
    # TACTICAL LAYER EXECUTIONS
    # ==========================================

    def add_negative_keyword(self, campaign_id: str, keyword_text: str, match_type: str = "PHRASE") -> Dict[str, Any]:
        """
        Add a negative keyword to a campaign.

        Args:
            campaign_id: Campaign ID
            keyword_text: Keyword text to block
            match_type: Match type (BROAD, PHRASE, EXACT)

        Returns:
            Execution result
        """
        client = self.get_client()

        try:
            campaign_criterion_service = client.get_service("CampaignCriterionService")

            operation = client.get_type("CampaignCriterionOperation")
            criterion = operation.create

            criterion.campaign = client.get_service("CampaignService").campaign_path(
                self.client_customer_id, campaign_id
            )
            criterion.negative = True
            criterion.keyword.text = keyword_text
            criterion.keyword.match_type = getattr(
                client.enums.KeywordMatchTypeEnum, match_type
            )

            response = campaign_criterion_service.mutate_campaign_criteria(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'campaign_id': campaign_id,
                'negative_keyword': keyword_text,
                'match_type': match_type,
                'resource': response.results[0].resource_name
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to add negative keyword: {ex}")
            return {'success': False, 'error': str(ex)}

    def pause_keyword(self, ad_group_id: str, keyword_id: str) -> Dict[str, Any]:
        """
        Pause a keyword.

        Args:
            ad_group_id: Ad group ID
            keyword_id: Keyword criterion ID

        Returns:
            Execution result
        """
        if not ad_group_id or not keyword_id:
            return {'success': False, 'error': f'Missing required IDs: ad_group_id={ad_group_id!r}, keyword_id={keyword_id!r}'}

        client = self.get_client()

        try:
            ad_group_criterion_service = client.get_service("AdGroupCriterionService")

            operation = client.get_type("AdGroupCriterionOperation")
            criterion = operation.update
            criterion.resource_name = ad_group_criterion_service.ad_group_criterion_path(
                self.client_customer_id, ad_group_id, keyword_id
            )
            criterion.status = client.enums.AdGroupCriterionStatusEnum.PAUSED

            operation.update_mask.paths.append("status")

            response = ad_group_criterion_service.mutate_ad_group_criteria(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'keyword_id': keyword_id,
                'status': 'PAUSED',
                'resource': response.results[0].resource_name
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to pause keyword: {ex}")
            return {'success': False, 'error': str(ex)}

    def adjust_keyword_bid(self, ad_group_id: str, keyword_id: str, bid_change_pct: float) -> Dict[str, Any]:
        """
        Adjust bid for a specific keyword.

        Args:
            ad_group_id: Ad group ID
            keyword_id: Keyword criterion ID
            bid_change_pct: Percentage to adjust bid by

        Returns:
            Execution result
        """
        client = self.get_client()

        try:
            ad_group_criterion_service = client.get_service("AdGroupCriterionService")
            ga_service = client.get_service("GoogleAdsService")

            # Get current bid
            resource_name = ad_group_criterion_service.ad_group_criterion_path(
                self.client_customer_id, ad_group_id, keyword_id
            )

            query = f"""
                SELECT ad_group_criterion.cpc_bid_micros
                FROM ad_group_criterion
                WHERE ad_group_criterion.resource_name = '{resource_name}'
            """

            response = ga_service.search(customer_id=self.client_customer_id, query=query)
            row = next(iter(response))
            current_bid = row.ad_group_criterion.cpc_bid_micros

            # Calculate new bid
            new_bid = int(current_bid * (1 + bid_change_pct / 100))
            new_bid = max(10_000, new_bid)  # Minimum $0.01

            # Update bid
            operation = client.get_type("AdGroupCriterionOperation")
            criterion = operation.update
            criterion.resource_name = resource_name
            criterion.cpc_bid_micros = new_bid

            operation.update_mask.paths.append("cpc_bid_micros")

            ad_group_criterion_service.mutate_ad_group_criteria(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'keyword_id': keyword_id,
                'old_bid_micros': current_bid,
                'new_bid_micros': new_bid,
                'bid_change_pct': bid_change_pct
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to adjust keyword bid: {ex}")
            return {'success': False, 'error': str(ex)}

    def add_keyword(self, ad_group_id: str, keyword_text: str, match_type: str = "PHRASE") -> Dict[str, Any]:
        """
        Add a new keyword to an ad group.

        Args:
            ad_group_id: Ad group ID
            keyword_text: Keyword text
            match_type: Match type (BROAD, PHRASE, EXACT)

        Returns:
            Execution result
        """
        client = self.get_client()

        try:
            ad_group_criterion_service = client.get_service("AdGroupCriterionService")

            operation = client.get_type("AdGroupCriterionOperation")
            criterion = operation.create

            criterion.ad_group = client.get_service("AdGroupService").ad_group_path(
                self.client_customer_id, ad_group_id
            )
            criterion.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
            criterion.keyword.text = keyword_text
            criterion.keyword.match_type = getattr(
                client.enums.KeywordMatchTypeEnum, match_type
            )

            # Set default bid (can be overridden by ad group default)
            criterion.cpc_bid_micros = 1_000_000  # $1.00 default

            response = ad_group_criterion_service.mutate_ad_group_criteria(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'ad_group_id': ad_group_id,
                'keyword_text': keyword_text,
                'match_type': match_type,
                'resource': response.results[0].resource_name
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to add keyword: {ex}")
            return {'success': False, 'error': str(ex)}

    def pause_ad(self, ad_id: str) -> Dict[str, Any]:
        """
        Pause an ad.

        Args:
            ad_id: Ad group ad ID

        Returns:
            Execution result
        """
        client = self.get_client()

        try:
            ad_group_ad_service = client.get_service("AdGroupAdService")

            # Note: Need ad_group_id and ad_id to construct resource name
            # This is simplified - in production, you'd query first or pass both IDs

            operation = client.get_type("AdGroupAdOperation")
            ad = operation.update
            ad.resource_name = f"customers/{self.client_customer_id}/adGroupAds/{ad_id}"
            ad.status = client.enums.AdGroupAdStatusEnum.PAUSED

            operation.update_mask.paths.append("status")

            response = ad_group_ad_service.mutate_ad_group_ads(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'ad_id': ad_id,
                'status': 'PAUSED',
                'resource': response.results[0].resource_name
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to pause ad: {ex}")
            return {'success': False, 'error': str(ex)}
