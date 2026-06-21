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
            "device_bid_adjustments": self._get_device_bid_adjustments(),
            "extensions": self._get_ad_extensions(),
            "negative_keywords": self._get_negative_keywords_count(),
            "search_terms": self._get_search_terms(start_date, end_date),
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

    def _get_quality_score_distribution(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get Quality Score distribution and component scores across keywords."""
        query = """
            SELECT
                ad_group_criterion.quality_info.quality_score,
                ad_group_criterion.quality_info.post_click_quality_score,
                ad_group_criterion.quality_info.creative_quality_score,
                ad_group_criterion.quality_info.search_predicted_ctr,
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
        post_click_dist = {"ABOVE_AVERAGE": 0, "AVERAGE": 0, "BELOW_AVERAGE": 0, "UNKNOWN": 0}
        creative_dist = {"ABOVE_AVERAGE": 0, "AVERAGE": 0, "BELOW_AVERAGE": 0, "UNKNOWN": 0}
        total_score = 0
        keyword_count = 0

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                qs = row.ad_group_criterion.quality_info.quality_score
                if qs > 0:
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

                # Component scores (available even when overall QS isn't shown)
                try:
                    post_click = row.ad_group_criterion.quality_info.post_click_quality_score.name
                    post_click_dist[post_click] = post_click_dist.get(post_click, 0) + 1
                except Exception:
                    post_click_dist["UNKNOWN"] = post_click_dist.get("UNKNOWN", 0) + 1

                try:
                    creative = row.ad_group_criterion.quality_info.creative_quality_score.name
                    creative_dist[creative] = creative_dist.get(creative, 0) + 1
                except Exception:
                    creative_dist["UNKNOWN"] = creative_dist.get("UNKNOWN", 0) + 1

            avg_quality_score = (total_score / keyword_count) if keyword_count > 0 else 0

            return {
                "distribution": distribution,
                "average": avg_quality_score,
                "keyword_count": keyword_count,
                "post_click_distribution": post_click_dist,
                "creative_distribution": creative_dist,
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching quality scores: {ex}")
            return {
                "distribution": distribution,
                "average": 0,
                "keyword_count": 0,
                "post_click_distribution": post_click_dist,
                "creative_distribution": creative_dist,
            }

    def _get_keyword_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get keyword-level metrics including long-tail analysis and conversion data."""
        query = """
            SELECT
                ad_group_criterion.keyword.text,
                ad_group_criterion.keyword.match_type,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.conversions,
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
                    "conversions": row.metrics.conversions,
                    "ctr": row.metrics.ctr,
                    "word_count": word_count,
                })

            return {
                "total_keywords": len(keywords),
                "word_count_distribution": word_count_distribution,
                "keywords": keywords[:200],
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching keyword metrics: {ex}")
            return {"total_keywords": 0, "word_count_distribution": word_count_distribution, "keywords": []}

    def _get_ad_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get ad-level performance metrics including RSA ad strength."""
        query = """
            SELECT
                ad_group_ad.ad.type,
                ad_group_ad.ad_strength,
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
        ad_strength_dist = {"EXCELLENT": 0, "GOOD": 0, "AVERAGE": 0, "POOR": 0, "OTHER": 0}

        try:
            response = self.ga_service.search(
                customer_id=self.customer_id,
                query=query
            )

            for row in response:
                ad_type = row.ad_group_ad.ad.type_.name
                ad_type_counts[ad_type] = ad_type_counts.get(ad_type, 0) + 1

                try:
                    strength = row.ad_group_ad.ad_strength.name
                    if strength in ad_strength_dist:
                        ad_strength_dist[strength] += 1
                    else:
                        ad_strength_dist["OTHER"] += 1
                except Exception:
                    ad_strength_dist["OTHER"] += 1

                ads.append({
                    "type": ad_type,
                    "clicks": row.metrics.clicks,
                    "impressions": row.metrics.impressions,
                    "ctr": row.metrics.ctr,
                })

            ads_sorted_by_ctr = sorted(ads, key=lambda x: x["ctr"], reverse=True)

            return {
                "total_ads": len(ads),
                "ad_type_counts": ad_type_counts,
                "ad_strength_distribution": ad_strength_dist,
                "best_ad": ads_sorted_by_ctr[0] if ads_sorted_by_ctr else None,
                "worst_ad": ads_sorted_by_ctr[-1] if ads_sorted_by_ctr else None,
                "avg_ctr": sum(ad["ctr"] for ad in ads) / len(ads) if ads else 0,
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching ad metrics: {ex}")
            return {
                "total_ads": 0,
                "ad_type_counts": {},
                "ad_strength_distribution": ad_strength_dist,
                "best_ad": None,
                "worst_ad": None,
                "avg_ctr": 0,
            }

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
        """Check which ad extensions / assets are in use."""
        # Modern accounts use campaign_asset; legacy accounts use campaign_extension_setting
        asset_types: set = set()

        try:
            query = """
                SELECT campaign_asset.asset_type
                FROM campaign_asset
                WHERE campaign_asset.status = 'ENABLED'
                    AND campaign.status = 'ENABLED'
            """
            response = self.ga_service.search(customer_id=self.customer_id, query=query)
            for row in response:
                try:
                    asset_types.add(row.campaign_asset.asset_type.name)
                except Exception:
                    pass
        except GoogleAdsException:
            # Fall back to legacy extension settings
            try:
                legacy_query = """
                    SELECT campaign_extension_setting.extension_type
                    FROM campaign_extension_setting
                    WHERE campaign.status = 'ENABLED'
                """
                response = self.ga_service.search(customer_id=self.customer_id, query=legacy_query)
                for row in response:
                    try:
                        asset_types.add(row.campaign_extension_setting.extension_type.name)
                    except Exception:
                        pass
            except GoogleAdsException as ex:
                logger.warning(f"Error fetching ad extensions: {ex}")

        return {
            "sitelinks": "SITELINK" in asset_types,
            "callouts": "CALLOUT" in asset_types,
            "call_extensions": "CALL" in asset_types,
            "structured_snippets": "STRUCTURED_SNIPPET" in asset_types,
        }

    def _get_search_terms(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Fetch search terms report to identify wasted spend on irrelevant queries."""
        query = """
            SELECT
                search_term_view.search_term,
                metrics.clicks,
                metrics.impressions,
                metrics.cost_micros,
                metrics.conversions
            FROM search_term_view
            WHERE segments.date BETWEEN '{start}' AND '{end}'
                AND campaign.status = 'ENABLED'
            ORDER BY metrics.cost_micros DESC
            LIMIT 2000
        """.format(
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d")
        )

        # Patterns that strongly indicate non-buyer intent in home services
        WASTE_PATTERNS = [
            # DIY / informational intent
            "how to ", "how do i ", "how do you ", "diy ", "do it yourself",
            "tutorial", "guide", "tips", "step by step", "can i ",
            "should i ", "what is ", "what are ", "why is ", "why does ",
            "definition", "wikipedia", "reddit", "youtube", "forum", "video",
            # Job seekers / employment
            " job", " jobs", "career", "careers", " hiring", "salary",
            "wage", "apprentice", "journeyman", "technician school",
            "electrician school", "hvac school", "plumbing school",
            "how to become", "get certified", "certification exam",
            # Supply / wholesale (wrong buyer type)
            "wholesale", "supply house", "distributor", "buy parts",
            " parts", "equipment for sale", "amazon", "home depot parts",
            "lowes parts", "menards",
            # Clearly informational
            "history of", "types of", "different types",
        ]

        all_terms = []
        waste_terms = []
        total_spend = 0.0
        waste_spend = 0.0

        try:
            response = self.ga_service.search(customer_id=self.customer_id, query=query)

            for row in response:
                term = row.search_term_view.search_term
                term_lower = term.lower()
                cost = row.metrics.cost_micros / 1_000_000
                total_spend += cost

                term_data = {
                    "term": term,
                    "clicks": row.metrics.clicks,
                    "impressions": row.metrics.impressions,
                    "cost": round(cost, 2),
                    "conversions": row.metrics.conversions,
                }
                all_terms.append(term_data)

                is_waste = any(p in term_lower for p in WASTE_PATTERNS)
                if is_waste:
                    waste_terms.append(term_data)
                    waste_spend += cost

            return {
                "total_terms": len(all_terms),
                "total_spend": round(total_spend, 2),
                "waste_terms": waste_terms,
                "waste_term_count": len(waste_terms),
                "waste_spend": round(waste_spend, 2),
                "sample_terms": all_terms[:25],
            }
        except GoogleAdsException as ex:
            logger.error(f"Error fetching search terms: {ex}")
            return {
                "total_terms": 0,
                "total_spend": 0.0,
                "waste_terms": [],
                "waste_term_count": 0,
                "waste_spend": 0.0,
                "sample_terms": [],
            }

    def _get_device_bid_adjustments(self) -> Dict[str, Any]:
        """Fetch device-level bid modifiers to check mobile optimization."""
        query = """
            SELECT
                campaign_criterion.device.type,
                campaign_criterion.bid_modifier,
                campaign_criterion.status
            FROM campaign_criterion
            WHERE campaign_criterion.type = 'DEVICE'
                AND campaign.status = 'ENABLED'
        """

        device_modifiers: Dict[str, list] = {}

        try:
            response = self.ga_service.search(customer_id=self.customer_id, query=query)
            for row in response:
                try:
                    device = row.campaign_criterion.device.type_.name.lower()
                    modifier = row.campaign_criterion.bid_modifier
                    if device not in device_modifiers:
                        device_modifiers[device] = []
                    device_modifiers[device].append(modifier)
                except Exception:
                    pass
        except GoogleAdsException as ex:
            logger.warning(f"Error fetching device bid adjustments: {ex}")
            return {"has_adjustments": False, "mobile": 1.0, "desktop": 1.0, "tablet": 1.0}

        avg_by_device = {
            dev: sum(mods) / len(mods)
            for dev, mods in device_modifiers.items()
        }

        # Any modifier != 1.0 means an active adjustment
        has_adjustments = any(abs(v - 1.0) > 0.01 for v in avg_by_device.values())

        return {
            "has_adjustments": has_adjustments,
            "mobile": avg_by_device.get("mobile", 1.0),
            "desktop": avg_by_device.get("desktop", 1.0),
            "tablet": avg_by_device.get("tablet", 1.0),
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
