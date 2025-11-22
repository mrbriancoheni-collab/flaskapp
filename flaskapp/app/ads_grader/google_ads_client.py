"""
Google Ads API Client for Grader Tool

Handles OAuth authentication and data fetching from Google Ads API.
"""
import logging
import os
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from flask import current_app

logger = logging.getLogger(__name__)


def _get_config(key: str) -> Optional[str]:
    """
    Get configuration value from environment or Flask config.
    Checks environment variables first, then falls back to Flask config.
    This pattern matches app/google/__init__.py approach.
    """
    return os.getenv(key) or current_app.config.get(key)


class GoogleAdsGraderClient:
    """
    Client for fetching Google Ads data for the grader tool.
    """

    def __init__(self, refresh_token: str, customer_id: str, login_customer_id: Optional[str] = None):
        """
        Initialize the Google Ads client.

        Args:
            refresh_token: OAuth refresh token for the user
            customer_id: Google Ads customer ID (format: 123-456-7890)
            login_customer_id: Manager account (MCC) ID for accessing sub-accounts.
                               Required with Basic API access when accessing client accounts.
        """
        self.customer_id = customer_id.replace("-", "")  # API requires no dashes

        # Build credentials dictionary for Google Ads client (env vars first, then Flask config)
        credentials = {
            "developer_token": _get_config("GOOGLE_ADS_DEVELOPER_TOKEN"),
            "client_id": _get_config("GOOGLE_ADS_CLIENT_ID"),
            "client_secret": _get_config("GOOGLE_ADS_CLIENT_SECRET"),
            "refresh_token": refresh_token,
            "use_proto_plus": True,
        }

        # Add login_customer_id if provided (required for MCC/manager account access with Basic API access)
        if login_customer_id:
            credentials["login_customer_id"] = login_customer_id.replace("-", "")

        try:
            self.client = GoogleAdsClient.load_from_dict(credentials)
            self.ga_service = self.client.get_service("GoogleAdsService")
        except Exception as e:
            logger.exception(f"Failed to initialize Google Ads client: {e}")
            raise

    def get_account_metrics(self, days: int = 365) -> Dict[str, Any]:
        """
        Fetch comprehensive account metrics for grading.

        Args:
            days: Number of days of historical data to fetch (default 365)

        Returns:
            Dictionary containing all metrics needed for grading
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        metrics = {
            "account_info": self._get_account_info(),
            "performance": self._get_performance_metrics(start_date, end_date),
            "quality_scores": self._get_quality_score_distribution(start_date, end_date),
            "keywords": self._get_keyword_metrics(start_date, end_date),
            "ads": self._get_ad_metrics(start_date, end_date),
            "campaigns": self._get_campaign_structure(),
            "device_performance": self._get_device_performance(start_date, end_date),
            "extensions": self._get_ad_extensions(),
            "negative_keywords": self._get_negative_keywords_count(),
            "landing_pages": self._get_landing_page_count(start_date, end_date),
            "impression_share": self._get_impression_share_metrics(start_date, end_date),
        }

        return metrics

    def _get_account_info(self) -> Dict[str, Any]:
        """Get basic account information."""
        query = """
            SELECT
                customer.id,
                customer.descriptive_name,
                customer.currency_code,
                customer.time_zone
            FROM customer
            WHERE customer.id = {customer_id}
        """.format(customer_id=self.customer_id)

        try:
            response = self.ga_service.search_stream(
                customer_id=self.customer_id,
                query=query
            )

            for batch in response:
                for row in batch.results:
                    return {
                        "customer_id": row.customer.id,
                        "account_name": row.customer.descriptive_name,
                        "currency": row.customer.currency_code,
                        "timezone": row.customer.time_zone,
                    }
        except GoogleAdsException as ex:
            logger.error(f"Google Ads API error: {ex}")
            raise

        return {}

    def _get_performance_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get overall performance metrics."""
        query = """
            SELECT
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.conversions,
                metrics.average_cpc,
                metrics.ctr,
                metrics.average_cost,
                metrics.conversions_value
            FROM customer
            WHERE segments.date BETWEEN '{start}' AND '{end}'
        """.format(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d")
        )

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            # Aggregate metrics
            total_clicks = 0
            total_impressions = 0
            total_cost = 0
            total_conversions = 0

            for row in response:
                total_clicks += row.metrics.clicks
                total_impressions += row.metrics.impressions
                total_cost += row.metrics.cost_micros / 1_000_000  # Convert to dollars
                total_conversions += row.metrics.conversions

            ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
            avg_cpc = (total_cost / total_clicks) if total_clicks > 0 else 0
            avg_cpa = (total_cost / total_conversions) if total_conversions > 0 else 0

            return {
                "clicks": total_clicks,
                "impressions": total_impressions,
                "cost": total_cost,
                "conversions": total_conversions,
                "ctr": ctr,
                "avg_cpc": avg_cpc,
                "avg_cpa": avg_cpa,
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching performance metrics: {ex}")
            return {}

    def _get_quality_score_distribution(self, start_date: datetime, end_date: datetime) -> Dict[str, int]:
        """Get Quality Score distribution across keywords."""
        query = """
            SELECT
                ad_group_criterion.quality_info.quality_score,
                metrics.impressions
            FROM keyword_view
            WHERE segments.date BETWEEN '{start}' AND '{end}'
                AND ad_group_criterion.status = 'ENABLED'
                AND ad_group.status = 'ENABLED'
                AND campaign.status = 'ENABLED'
        """.format(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d")
        )

        distribution = {"1-3": 0, "4-6": 0, "7-8": 0, "9-10": 0}
        total_score = 0
        keyword_count = 0

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                qs = row.ad_group_criterion.quality_info.quality_score
                if qs > 0:  # Quality score is available
                    keyword_count += 1
                    total_score += qs

                    if qs <= 3:
                        distribution["1-3"] += 1
                    elif qs <= 6:
                        distribution["4-6"] += 1
                    elif qs <= 8:
                        distribution["7-8"] += 1
                    else:
                        distribution["9-10"] += 1

            avg_quality_score = (total_score / keyword_count) if keyword_count > 0 else 0

            return {
                "distribution": distribution,
                "average": avg_quality_score,
                "keyword_count": keyword_count,
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching quality scores: {ex}")
            return {"distribution": distribution, "average": 0, "keyword_count": 0}

    def _get_keyword_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get keyword-level metrics including long-tail analysis."""
        query = """
            SELECT
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.ctr
            FROM keyword_view
            WHERE segments.date BETWEEN '{start}' AND '{end}'
                AND campaign.status = 'ENABLED'
                AND ad_group.status = 'ENABLED'
                AND ad_group_criterion.status = 'ENABLED'
        """.format(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d")
        )

        keywords = []
        word_count_distribution = {"1-word": 0, "2-word": 0, "3+-word": 0}

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                keyword_text = row.ad_group_criterion.keyword.text
                word_count = len(keyword_text.split())

                # Categorize by word count
                if word_count == 1:
                    word_count_distribution["1-word"] += 1
                elif word_count == 2:
                    word_count_distribution["2-word"] += 1
                else:
                    word_count_distribution["3+-word"] += 1

                keywords.append({
                    "text": keyword_text,
                    "match_type": row.ad_group_criterion.keyword.match_type.name,
                    "clicks": row.metrics.clicks,
                    "impressions": row.metrics.impressions,
                    "cost": row.metrics.cost_micros / 1_000_000,
                    "ctr": row.metrics.ctr,
                    "word_count": word_count,
                })

            return {
                "total_keywords": len(keywords),
                "word_count_distribution": word_count_distribution,
                "keywords": keywords[:100],  # Return top 100 for analysis
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching keyword metrics: {ex}")
            return {"total_keywords": 0, "word_count_distribution": word_count_distribution, "keywords": []}

    def _get_ad_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get ad-level performance metrics."""
        query = """
            SELECT
                ad_group_ad.ad.type,
                ad_group_ad.ad.expanded_text_ad.headline_part1,
                ad_group_ad.ad.expanded_text_ad.headline_part2,
                metrics.clicks,
                metrics.impressions,
                metrics.ctr
            FROM ad_group_ad
            WHERE segments.date BETWEEN '{start}' AND '{end}'
                AND campaign.status = 'ENABLED'
                AND ad_group.status = 'ENABLED'
                AND ad_group_ad.status = 'ENABLED'
        """.format(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d")
        )

        ads = []
        ad_type_counts = {}

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                ad_type = row.ad_group_ad.ad.type_.name
                ad_type_counts[ad_type] = ad_type_counts.get(ad_type, 0) + 1

                ads.append({
                    "type": ad_type,
                    "clicks": row.metrics.clicks,
                    "impressions": row.metrics.impressions,
                    "ctr": row.metrics.ctr,
                })

            # Calculate best and worst performing ads
            ads_sorted_by_ctr = sorted(ads, key=lambda x: x["ctr"], reverse=True)

            return {
                "total_ads": len(ads),
                "ad_type_counts": ad_type_counts,
                "best_ad": ads_sorted_by_ctr[0] if ads_sorted_by_ctr else None,
                "worst_ad": ads_sorted_by_ctr[-1] if ads_sorted_by_ctr else None,
                "avg_ctr": sum(ad["ctr"] for ad in ads) / len(ads) if ads else 0,
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching ad metrics: {ex}")
            return {"total_ads": 0, "ad_type_counts": {}, "best_ad": None, "worst_ad": None, "avg_ctr": 0}

    def _get_campaign_structure(self) -> Dict[str, Any]:
        """Get campaign and ad group structure."""
        query = """
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                ad_group.id,
                ad_group.name
            FROM ad_group
            WHERE campaign.status = 'ENABLED'
                AND ad_group.status = 'ENABLED'
        """

        campaigns = {}
        ad_group_count = 0

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                campaign_id = row.campaign.id
                if campaign_id not in campaigns:
                    campaigns[campaign_id] = {
                        "name": row.campaign.name,
                        "ad_groups": []
                    }
                campaigns[campaign_id]["ad_groups"].append(row.ad_group.name)
                ad_group_count += 1

            return {
                "campaign_count": len(campaigns),
                "ad_group_count": ad_group_count,
                "campaigns": list(campaigns.values())[:20],  # Return first 20
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching campaign structure: {ex}")
            return {"campaign_count": 0, "ad_group_count": 0, "campaigns": []}

    def _get_device_performance(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get performance metrics by device type."""
        query = """
            SELECT
                segments.device,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.ctr
            FROM customer
            WHERE segments.date BETWEEN '{start}' AND '{end}'
        """.format(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d")
        )

        device_metrics = {}

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                device = row.segments.device.name.lower()
                device_metrics[device] = {
                    "clicks": row.metrics.clicks,
                    "impressions": row.metrics.impressions,
                    "cost": row.metrics.cost_micros / 1_000_000,
                    "ctr": row.metrics.ctr,
                }

            return device_metrics
        except GoogleAdsException as ex:
            logger.error(f"Error fetching device performance: {ex}")
            return {}

    def _get_ad_extensions(self) -> Dict[str, bool]:
        """Check which ad extensions are being used."""
        # Simplified check - in production, query each extension type
        return {
            "sitelinks": False,  # TODO: Query sitelink extensions
            "callouts": False,   # TODO: Query callout extensions
            "call_extensions": False,  # TODO: Query call extensions
            "structured_snippets": False,  # TODO: Query structured snippet extensions
        }

    def _get_negative_keywords_count(self) -> int:
        """Count total negative keywords across all campaigns."""
        query = """
            SELECT
                campaign_criterion.keyword.text
            FROM campaign_criterion
            WHERE campaign_criterion.type = 'KEYWORD'
                AND campaign_criterion.negative = true
                AND campaign.status = 'ENABLED'
        """

        count = 0

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for _ in response:
                count += 1

            return count
        except GoogleAdsException as ex:
            logger.error(f"Error fetching negative keywords: {ex}")
            return 0

    def _get_landing_page_count(self, start_date: datetime, end_date: datetime) -> int:
        """Count unique landing pages."""
        query = """
            SELECT
                landing_page_view.unexpanded_final_url
            FROM landing_page_view
            WHERE segments.date BETWEEN '{start}' AND '{end}'
        """.format(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d")
        )

        landing_pages = set()

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                landing_pages.add(row.landing_page_view.unexpanded_final_url)

            return len(landing_pages)
        except GoogleAdsException as ex:
            logger.error(f"Error fetching landing pages: {ex}")
            return 0

    def _get_impression_share_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get impression share and lost impression share data."""
        query = """
            SELECT
                metrics.search_impression_share,
                metrics.search_budget_lost_impression_share,
                metrics.search_rank_lost_impression_share
            FROM campaign
            WHERE segments.date BETWEEN '{start}' AND '{end}'
                AND campaign.status = 'ENABLED'
        """.format(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d")
        )

        total_imp_share = 0
        total_budget_lost = 0
        total_rank_lost = 0
        count = 0

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                if row.metrics.search_impression_share > 0:
                    total_imp_share += row.metrics.search_impression_share
                    total_budget_lost += row.metrics.search_budget_lost_impression_share
                    total_rank_lost += row.metrics.search_rank_lost_impression_share
                    count += 1

            return {
                "impression_share": (total_imp_share / count) if count > 0 else 0,
                "budget_lost_share": (total_budget_lost / count) if count > 0 else 0,
                "rank_lost_share": (total_rank_lost / count) if count > 0 else 0,
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching impression share: {ex}")
            return {"impression_share": 0, "budget_lost_share": 0, "rank_lost_share": 0}
