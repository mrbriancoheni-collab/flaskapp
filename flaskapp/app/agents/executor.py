# app/agents/executor.py
"""
Agent Executor - Connects agents to Google Ads API for real execution.

Provides concrete implementations of agent actions using the Google Ads API.
"""

from typing import Dict, Any, Optional
import logging

# Lazy import of Google Ads library - may not be installed in all environments
try:
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException
    GOOGLE_ADS_AVAILABLE = True
except ImportError:
    GoogleAdsClient = None
    GoogleAdsException = Exception
    GOOGLE_ADS_AVAILABLE = False

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
        if not GOOGLE_ADS_AVAILABLE:
            raise RuntimeError(
                "google-ads library is not installed. "
                "Install with: pip install google-ads"
            )
        self.refresh_token = refresh_token
        self.developer_token = developer_token
        self.client_customer_id = client_customer_id.replace('-', '')
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
        Reallocate budget between campaigns by querying current budgets and adjusting them.
        """
        client = self.get_client()

        try:
            reduction_per_campaign = amount / len(from_campaigns)
            increase_per_campaign = amount / len(to_campaigns)

            ga_service = client.get_service("GoogleAdsService")
            campaign_budget_service = client.get_service("CampaignBudgetService")

            def _get_budget(campaign_id: str):
                """Return (budget_resource_name, current_amount_micros) for a campaign."""
                query = f"""
                    SELECT campaign.campaign_budget, campaign_budget.amount_micros
                    FROM campaign
                    WHERE campaign.id = {campaign_id}
                """
                resp = ga_service.search(customer_id=self.client_customer_id, query=query)
                for row in resp:
                    return row.campaign.campaign_budget, int(row.campaign_budget.amount_micros)
                return None, 0

            def _budget_op(budget_resource: str, new_micros: int):
                op = client.get_type("CampaignBudgetOperation")
                b = op.update
                b.resource_name = budget_resource
                b.amount_micros = max(10_000, new_micros)
                client.copy_from(op.update_mask, client.get_type("FieldMask")(paths=["amount_micros"]))
                return op

            operations = []
            updates = []

            for cid in from_campaigns:
                resource, current = _get_budget(str(cid))
                if resource:
                    new_micros = int(current - reduction_per_campaign * 1_000_000)
                    operations.append(_budget_op(resource, new_micros))
                    updates.append({"campaign_id": cid, "change": -reduction_per_campaign})

            for cid in to_campaigns:
                resource, current = _get_budget(str(cid))
                if resource:
                    new_micros = int(current + increase_per_campaign * 1_000_000)
                    operations.append(_budget_op(resource, new_micros))
                    updates.append({"campaign_id": cid, "change": +increase_per_campaign})

            if not operations:
                return {'success': False, 'error': 'No budget data found for specified campaigns'}

            campaign_budget_service.mutate_campaign_budgets(
                customer_id=self.client_customer_id,
                operations=operations
            )

            return {
                'success': True,
                'campaigns_updated': len(operations),
                'amount_reallocated': amount,
                'updates': updates
            }

        except GoogleAdsException as ex:
            logger.error(f"Google Ads API error in reallocate_budget: {ex}")
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
            ga_service = client.get_service("GoogleAdsService")
            campaign_budget_service = client.get_service("CampaignBudgetService")

            # First, query to get the campaign's budget resource name
            query = f"""
                SELECT campaign.campaign_budget
                FROM campaign
                WHERE campaign.id = {campaign_id}
            """
            response = ga_service.search(
                customer_id=self.client_customer_id,
                query=query
            )

            budget_resource_name = None
            for row in response:
                budget_resource_name = row.campaign.campaign_budget
                break

            if not budget_resource_name:
                return {
                    'success': False,
                    'error': f'No budget found for campaign {campaign_id}'
                }

            # Create update operation with resource name and field mask
            operation = client.get_type("CampaignBudgetOperation")
            budget = operation.update
            budget.resource_name = budget_resource_name
            budget.amount_micros = int(new_budget * 1_000_000)  # Convert to micros

            # Set field mask to specify which fields we're updating
            client.copy_from(
                operation.update_mask,
                client.get_type("FieldMask")(paths=["amount_micros"])
            )

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

    def create_responsive_search_ad(
        self,
        ad_group_id: str,
        business_description: str = '',
        keyword_theme: str = '',
    ) -> Dict[str, Any]:
        """
        Generate ad copy with Claude and create a new Responsive Search Ad.

        Queries the ad group's existing ads for URL/headline context, then uses
        Claude to write new headlines/descriptions, then POSTs via the API.
        """
        client = self.get_client()

        try:
            ga_service = client.get_service("GoogleAdsService")

            # 1. Fetch existing ads to get final_url and headline context
            query = f"""
                SELECT
                    ad_group_ad.ad.final_urls,
                    ad_group_ad.ad.responsive_search_ad.headlines,
                    ad_group_ad.ad.responsive_search_ad.descriptions,
                    ad_group.name
                FROM ad_group_ad
                WHERE ad_group.id = {ad_group_id}
                  AND ad_group_ad.status != 'REMOVED'
                LIMIT 3
            """
            rows = list(ga_service.search(customer_id=self.client_customer_id, query=query))

            final_url = ''
            existing_headlines = []
            existing_descriptions = []
            ad_group_name = ''

            for row in rows:
                if not final_url:
                    urls = list(row.ad_group_ad.ad.final_urls)
                    if urls:
                        final_url = urls[0]
                ad_group_name = row.ad_group.name
                for h in row.ad_group_ad.ad.responsive_search_ad.headlines:
                    if h.text and h.text not in existing_headlines:
                        existing_headlines.append(h.text)
                for d in row.ad_group_ad.ad.responsive_search_ad.descriptions:
                    if d.text and d.text not in existing_descriptions:
                        existing_descriptions.append(d.text)

            if not final_url:
                return {'success': False, 'error': f'No final URL found for ad group {ad_group_id}'}

            # 2. Generate new ad copy with Claude
            from app.services.ai_client import generate_json

            prompt_system = (
                "You write Google Ads Responsive Search Ad copy. "
                "Return valid JSON only — no markdown, no prose."
            )
            context_lines = []
            if business_description:
                context_lines.append(f"Business: {business_description}")
            if keyword_theme:
                context_lines.append(f"Keyword theme: {keyword_theme}")
            context_lines.append(f"Ad group: {ad_group_name}")
            if existing_headlines:
                context_lines.append(f"Existing headlines (do not duplicate): {', '.join(existing_headlines[:6])}")
            if existing_descriptions:
                context_lines.append(f"Existing descriptions: {', '.join(existing_descriptions[:3])}")

            prompt_user = (
                "\n".join(context_lines) + "\n\n"
                "Write 5 NEW headline variations (max 30 chars each) and "
                "2 NEW description variations (max 90 chars each). "
                'Return JSON: {"headlines": [...], "descriptions": [...]}'
            )

            copy_data = generate_json(prompt_system, prompt_user)
            new_headlines = (copy_data.get('headlines') or [])[:5]
            new_descriptions = (copy_data.get('descriptions') or [])[:2]

            if len(new_headlines) < 3 or len(new_descriptions) < 2:
                return {
                    'success': False,
                    'error': f'Claude returned insufficient copy: {len(new_headlines)} headlines, {len(new_descriptions)} descriptions'
                }

            # 3. Create the RSA
            ad_group_ad_service = client.get_service("AdGroupAdService")
            ad_group_resource = client.get_service("AdGroupService").ad_group_path(
                self.client_customer_id, ad_group_id
            )

            operation = client.get_type("AdGroupAdOperation")
            ad_group_ad = operation.create
            ad_group_ad.status = client.enums.AdGroupAdStatusEnum.ENABLED
            ad_group_ad.ad_group = ad_group_resource

            rsa = ad_group_ad.ad.responsive_search_ad
            for text in new_headlines:
                h = client.get_type("AdTextAsset")
                h.text = text[:30]
                rsa.headlines.append(h)
            for text in new_descriptions:
                d = client.get_type("AdTextAsset")
                d.text = text[:90]
                rsa.descriptions.append(d)

            ad_group_ad.ad.final_urls.append(final_url)

            response = ad_group_ad_service.mutate_ad_group_ads(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'ad_group_id': ad_group_id,
                'resource': response.results[0].resource_name,
                'headlines_created': new_headlines,
                'descriptions_created': new_descriptions,
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to create RSA: {ex}")
            return {'success': False, 'error': str(ex)}

    def improve_keyword_ad_relevance(
        self,
        keyword_text: str,
        keyword_id: str,
        business_description: str = '',
    ) -> Dict[str, Any]:
        """
        Find the ad group for a keyword, then add keyword-focused headlines
        to the existing RSA using Claude to generate the copy.
        """
        client = self.get_client()

        try:
            ga_service = client.get_service("GoogleAdsService")

            # 1. Find ad group for this keyword
            query = f"""
                SELECT
                    ad_group.id,
                    ad_group.name,
                    ad_group_criterion.resource_name
                FROM ad_group_criterion
                WHERE ad_group_criterion.criterion_id = {keyword_id}
                  AND ad_group_criterion.status != 'REMOVED'
                LIMIT 1
            """
            rows = list(ga_service.search(customer_id=self.client_customer_id, query=query))
            if not rows:
                return {'success': False, 'error': f'Keyword {keyword_id} not found in account'}

            ad_group_id = str(rows[0].ad_group.id)
            ad_group_name = rows[0].ad_group.name

            # 2. Get existing RSA to update (pick most-impression RSA)
            ad_query = f"""
                SELECT
                    ad_group_ad.ad.id,
                    ad_group_ad.resource_name,
                    ad_group_ad.ad.final_urls,
                    ad_group_ad.ad.responsive_search_ad.headlines,
                    ad_group_ad.ad.responsive_search_ad.descriptions,
                    metrics.impressions
                FROM ad_group_ad
                WHERE ad_group.id = {ad_group_id}
                  AND ad_group_ad.status = 'ENABLED'
                  AND ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'
                ORDER BY metrics.impressions DESC
                LIMIT 1
            """
            ad_rows = list(ga_service.search(customer_id=self.client_customer_id, query=ad_query))
            if not ad_rows:
                # No existing RSA — create one instead
                return self.create_responsive_search_ad(
                    ad_group_id=ad_group_id,
                    business_description=business_description,
                    keyword_theme=keyword_text,
                )

            ad_row = ad_rows[0]
            rsa_resource = ad_row.ad_group_ad.resource_name
            existing_headlines = [h.text for h in ad_row.ad_group_ad.ad.responsive_search_ad.headlines if h.text]
            existing_descriptions = [d.text for d in ad_row.ad_group_ad.ad.responsive_search_ad.descriptions if d.text]
            final_urls = list(ad_row.ad_group_ad.ad.final_urls)
            final_url = final_urls[0] if final_urls else ''

            # RSA can hold max 15 headlines; only add if there's room
            if len(existing_headlines) >= 15:
                return {
                    'success': True,
                    'note': 'RSA already has 15 headlines (maximum) — no update needed',
                    'ad_group_id': ad_group_id,
                }

            # 3. Generate keyword-focused headlines with Claude
            from app.services.ai_client import generate_json

            prompt_system = (
                "You write Google Ads headlines to improve keyword ad relevance. "
                "Return valid JSON only."
            )
            prompt_user = (
                f"Keyword: {keyword_text}\n"
                f"Ad group: {ad_group_name}\n"
                + (f"Business: {business_description}\n" if business_description else "")
                + f"Existing headlines (do not duplicate): {', '.join(existing_headlines)}\n\n"
                "Write 3 new headlines (max 30 chars each) that prominently include or closely match "
                f'the keyword "{keyword_text}". '
                'Return JSON: {"headlines": ["...", "...", "..."]}'
            )

            copy_data = generate_json(prompt_system, prompt_user)
            new_headlines = [h for h in (copy_data.get('headlines') or []) if h not in existing_headlines][:3]

            if not new_headlines:
                return {'success': False, 'error': 'Claude returned no new headlines for this keyword'}

            # 4. Update the RSA with new headlines appended
            ad_group_ad_service = client.get_service("AdGroupAdService")

            operation = client.get_type("AdGroupAdOperation")
            ad_group_ad = operation.update
            ad_group_ad.resource_name = rsa_resource

            rsa = ad_group_ad.ad.responsive_search_ad
            all_headlines = existing_headlines + new_headlines
            for text in all_headlines:
                h = client.get_type("AdTextAsset")
                h.text = text[:30]
                rsa.headlines.append(h)
            for text in existing_descriptions:
                d = client.get_type("AdTextAsset")
                d.text = text[:90]
                rsa.descriptions.append(d)
            if final_url:
                ad_group_ad.ad.final_urls.append(final_url)

            operation.update_mask.paths.extend(['ad.responsive_search_ad.headlines'])

            response = ad_group_ad_service.mutate_ad_group_ads(
                customer_id=self.client_customer_id,
                operations=[operation]
            )

            return {
                'success': True,
                'keyword': keyword_text,
                'ad_group_id': ad_group_id,
                'resource': response.results[0].resource_name,
                'headlines_added': new_headlines,
            }

        except GoogleAdsException as ex:
            logger.error(f"Failed to improve ad relevance: {ex}")
            return {'success': False, 'error': str(ex)}
