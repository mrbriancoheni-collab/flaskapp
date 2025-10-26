# app/fb_ads_grader/facebook_ads_client.py
"""
Facebook Ads API Client for Grader

Fetches comprehensive metrics from Facebook Ads API for performance analysis.
Uses Facebook Marketing API to retrieve:
- Account performance metrics
- Campaign, ad set, and ad-level data
- Audience insights
- Creative performance
- Placement and device breakdowns
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import requests

logger = logging.getLogger(__name__)


class FacebookAdsGraderClient:
    """
    Client for fetching Facebook Ads data for grading purposes.

    Requires a Facebook user access token with ads_read permission.
    """

    GRAPH_API_VERSION = "v20.0"
    GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

    def __init__(self, access_token: str, ad_account_id: str):
        """
        Initialize Facebook Ads client.

        Args:
            access_token: Facebook user access token with ads_read permission
            ad_account_id: Facebook Ad Account ID (with or without 'act_' prefix)
        """
        self.access_token = access_token

        # Ensure ad_account_id has 'act_' prefix
        if not ad_account_id.startswith('act_'):
            ad_account_id = f'act_{ad_account_id}'

        self.ad_account_id = ad_account_id
        logger.info(f"Initialized FacebookAdsGraderClient for account: {ad_account_id}")

    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make a request to Facebook Graph API.

        Args:
            endpoint: API endpoint (e.g., '/me' or '/act_123/campaigns')
            params: Query parameters

        Returns:
            JSON response from API

        Raises:
            Exception: If API request fails
        """
        if params is None:
            params = {}

        params['access_token'] = self.access_token

        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Facebook API request failed: {e}")
            raise Exception(f"Failed to fetch data from Facebook API: {str(e)}")

    def get_account_info(self) -> Dict[str, Any]:
        """
        Get basic ad account information.

        Returns:
            Dict with account name, ID, currency, timezone, business info
        """
        logger.info(f"Fetching account info for {self.ad_account_id}")

        fields = [
            'id',
            'name',
            'account_id',
            'account_status',
            'currency',
            'timezone_name',
            'timezone_offset_hours_utc',
            'business',
            'business_name',
            'created_time',
            'spend_cap',
            'amount_spent',
        ]

        data = self._make_request(
            f"/{self.ad_account_id}",
            params={'fields': ','.join(fields)}
        )

        return {
            'id': data.get('id'),
            'account_id': data.get('account_id'),
            'name': data.get('name'),
            'status': data.get('account_status'),
            'currency': data.get('currency', 'USD'),
            'timezone': data.get('timezone_name'),
            'business_id': data.get('business', {}).get('id') if isinstance(data.get('business'), dict) else data.get('business'),
            'business_name': data.get('business_name'),
            'created_time': data.get('created_time'),
            'spend_cap': float(data.get('spend_cap', 0)) if data.get('spend_cap') else None,
            'amount_spent': float(data.get('amount_spent', 0)) if data.get('amount_spent') else 0,
        }

    def get_account_metrics(self, days: int = 365) -> Dict[str, Any]:
        """
        Fetch comprehensive account metrics for grading.

        Args:
            days: Number of days of historical data to fetch (default: 365)

        Returns:
            Dict containing all metrics needed for grading:
            - account_info
            - performance (clicks, impressions, spend, conversions, etc.)
            - campaigns
            - ad_sets
            - ads
            - audiences
            - creative_performance
            - placement_performance
            - device_performance
        """
        logger.info(f"Fetching {days} days of metrics for {self.ad_account_id}")

        # Date range for insights
        date_preset = 'maximum'  # Get all available data
        if days <= 7:
            date_preset = 'last_7d'
        elif days <= 14:
            date_preset = 'last_14d'
        elif days <= 28:
            date_preset = 'last_28d'
        elif days <= 90:
            date_preset = 'last_90d'

        # For exact 365 days, use time_range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        time_range = {
            'since': start_date.strftime('%Y-%m-%d'),
            'until': end_date.strftime('%Y-%m-%d')
        }

        # Fetch all metrics in parallel (conceptually)
        account_info = self.get_account_info()
        performance = self.get_performance_metrics(time_range=time_range)
        campaigns = self.get_campaigns_data(time_range=time_range)
        ad_sets = self.get_ad_sets_data(time_range=time_range)
        ads = self.get_ads_data(time_range=time_range)
        creative_performance = self.get_creative_performance(time_range=time_range)
        placement_performance = self.get_placement_performance(time_range=time_range)
        device_performance = self.get_device_performance(time_range=time_range)

        return {
            'account_info': account_info,
            'performance': performance,
            'campaigns': campaigns,
            'ad_sets': ad_sets,
            'ads': ads,
            'creative_performance': creative_performance,
            'placement_performance': placement_performance,
            'device_performance': device_performance,
            'date_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': days,
            }
        }

    def get_performance_metrics(self, time_range: Dict[str, str]) -> Dict[str, Any]:
        """
        Get overall account performance metrics.

        Args:
            time_range: Dict with 'since' and 'until' date strings

        Returns:
            Dict with impressions, clicks, spend, conversions, CTR, CPC, etc.
        """
        logger.info("Fetching performance metrics")

        fields = [
            'impressions',
            'clicks',
            'spend',
            'cpc',
            'cpm',
            'cpp',
            'ctr',
            'reach',
            'frequency',
            'actions',
            'conversions',
            'conversion_values',
            'cost_per_action_type',
            'cost_per_conversion',
            'purchase_roas',
        ]

        params = {
            'fields': ','.join(fields),
            'time_range': str(time_range),
            'level': 'account',
        }

        try:
            data = self._make_request(f"/{self.ad_account_id}/insights", params=params)

            if not data.get('data'):
                logger.warning("No performance data returned")
                return self._empty_performance_metrics()

            insights = data['data'][0] if data['data'] else {}

            # Parse actions for conversions
            conversions = 0
            conversion_value = 0
            actions = insights.get('actions', [])

            for action in actions:
                action_type = action.get('action_type', '')
                value = float(action.get('value', 0))

                # Count purchase, lead, complete_registration as conversions
                if action_type in ['purchase', 'lead', 'complete_registration', 'offsite_conversion.fb_pixel_purchase']:
                    conversions += value

                # Get conversion value
                if action_type in ['purchase', 'offsite_conversion.fb_pixel_purchase']:
                    conversion_values = insights.get('conversion_values', [])
                    for cv in conversion_values:
                        if cv.get('action_type') == action_type:
                            conversion_value += float(cv.get('value', 0))

            impressions = int(insights.get('impressions', 0))
            clicks = int(insights.get('clicks', 0))
            spend = float(insights.get('spend', 0))

            return {
                'impressions': impressions,
                'clicks': clicks,
                'spend': spend,
                'conversions': conversions,
                'conversion_value': conversion_value,
                'ctr': float(insights.get('ctr', 0)),
                'cpc': float(insights.get('cpc', 0)),
                'cpm': float(insights.get('cpm', 0)),
                'reach': int(insights.get('reach', 0)),
                'frequency': float(insights.get('frequency', 0)),
                'roas': float(insights.get('purchase_roas', [{}])[0].get('value', 0)) if insights.get('purchase_roas') else 0,
                'conversion_rate': (conversions / clicks * 100) if clicks > 0 else 0,
                'avg_cpa': (spend / conversions) if conversions > 0 else 0,
            }

        except Exception as e:
            logger.error(f"Error fetching performance metrics: {e}")
            return self._empty_performance_metrics()

    def _empty_performance_metrics(self) -> Dict[str, Any]:
        """Return empty performance metrics structure."""
        return {
            'impressions': 0,
            'clicks': 0,
            'spend': 0,
            'conversions': 0,
            'conversion_value': 0,
            'ctr': 0,
            'cpc': 0,
            'cpm': 0,
            'reach': 0,
            'frequency': 0,
            'roas': 0,
            'conversion_rate': 0,
            'avg_cpa': 0,
        }

    def get_campaigns_data(self, time_range: Dict[str, str]) -> Dict[str, Any]:
        """
        Get campaign-level data and insights.

        Returns:
            Dict with campaign count, performance by campaign, etc.
        """
        logger.info("Fetching campaigns data")

        try:
            # Get campaigns
            campaigns_data = self._make_request(
                f"/{self.ad_account_id}/campaigns",
                params={
                    'fields': 'id,name,status,objective,created_time,updated_time',
                    'limit': 500,
                }
            )

            campaigns = campaigns_data.get('data', [])
            active_campaigns = [c for c in campaigns if c.get('status') == 'ACTIVE']

            return {
                'total_campaigns': len(campaigns),
                'active_campaigns': len(active_campaigns),
                'campaigns': campaigns[:50],  # Store top 50 for analysis
            }

        except Exception as e:
            logger.error(f"Error fetching campaigns: {e}")
            return {
                'total_campaigns': 0,
                'active_campaigns': 0,
                'campaigns': [],
            }

    def get_ad_sets_data(self, time_range: Dict[str, str]) -> Dict[str, Any]:
        """Get ad set data."""
        logger.info("Fetching ad sets data")

        try:
            ad_sets_data = self._make_request(
                f"/{self.ad_account_id}/adsets",
                params={
                    'fields': 'id,name,status,optimization_goal,billing_event,targeting',
                    'limit': 500,
                }
            )

            ad_sets = ad_sets_data.get('data', [])
            active_ad_sets = [a for a in ad_sets if a.get('status') == 'ACTIVE']

            # Count unique audiences
            unique_audiences = set()
            for ad_set in ad_sets:
                targeting = ad_set.get('targeting', {})
                # Create a simple hash of targeting to count unique audiences
                if targeting:
                    unique_audiences.add(str(targeting))

            return {
                'total_ad_sets': len(ad_sets),
                'active_ad_sets': len(active_ad_sets),
                'unique_audiences': len(unique_audiences),
                'ad_sets': ad_sets[:50],
            }

        except Exception as e:
            logger.error(f"Error fetching ad sets: {e}")
            return {
                'total_ad_sets': 0,
                'active_ad_sets': 0,
                'unique_audiences': 0,
                'ad_sets': [],
            }

    def get_ads_data(self, time_range: Dict[str, str]) -> Dict[str, Any]:
        """Get individual ad data."""
        logger.info("Fetching ads data")

        try:
            ads_data = self._make_request(
                f"/{self.ad_account_id}/ads",
                params={
                    'fields': 'id,name,status,creative,adset_id,campaign_id',
                    'limit': 500,
                }
            )

            ads = ads_data.get('data', [])
            active_ads = [a for a in ads if a.get('status') == 'ACTIVE']

            # Count unique creatives
            unique_creatives = set()
            for ad in ads:
                creative_id = ad.get('creative', {}).get('id') if isinstance(ad.get('creative'), dict) else ad.get('creative')
                if creative_id:
                    unique_creatives.add(creative_id)

            return {
                'total_ads': len(ads),
                'active_ads': len(active_ads),
                'unique_creatives': len(unique_creatives),
                'ads': ads[:50],
            }

        except Exception as e:
            logger.error(f"Error fetching ads: {e}")
            return {
                'total_ads': 0,
                'active_ads': 0,
                'unique_creatives': 0,
                'ads': [],
            }

    def get_creative_performance(self, time_range: Dict[str, str]) -> Dict[str, Any]:
        """Get creative-level performance insights."""
        logger.info("Fetching creative performance")

        # This would require fetching insights at the ad level and grouping by creative
        # For now, return placeholder
        return {
            'analyzed': False,
            'note': 'Creative performance analysis requires ad-level insights aggregation'
        }

    def get_placement_performance(self, time_range: Dict[str, str]) -> Dict[str, Any]:
        """Get performance by placement (Feed, Stories, Reels, etc.)."""
        logger.info("Fetching placement performance")

        try:
            data = self._make_request(
                f"/{self.ad_account_id}/insights",
                params={
                    'fields': 'impressions,clicks,spend,ctr,cpc',
                    'breakdowns': 'publisher_platform,platform_position',
                    'time_range': str(time_range),
                    'limit': 100,
                }
            )

            placements = data.get('data', [])

            return {
                'placements': placements,
                'total_placements': len(placements),
            }

        except Exception as e:
            logger.error(f"Error fetching placement performance: {e}")
            return {
                'placements': [],
                'total_placements': 0,
            }

    def get_device_performance(self, time_range: Dict[str, str]) -> Dict[str, Any]:
        """Get performance by device (mobile vs desktop)."""
        logger.info("Fetching device performance")

        try:
            data = self._make_request(
                f"/{self.ad_account_id}/insights",
                params={
                    'fields': 'impressions,clicks,spend,ctr,cpc',
                    'breakdowns': 'impression_device',
                    'time_range': str(time_range),
                    'limit': 100,
                }
            )

            devices = data.get('data', [])

            # Aggregate by device type
            mobile_metrics = {'impressions': 0, 'clicks': 0, 'spend': 0}
            desktop_metrics = {'impressions': 0, 'clicks': 0, 'spend': 0}

            for device_data in devices:
                device = device_data.get('impression_device', '').lower()
                impressions = int(device_data.get('impressions', 0))
                clicks = int(device_data.get('clicks', 0))
                spend = float(device_data.get('spend', 0))

                if 'mobile' in device or 'iphone' in device or 'android' in device:
                    mobile_metrics['impressions'] += impressions
                    mobile_metrics['clicks'] += clicks
                    mobile_metrics['spend'] += spend
                elif 'desktop' in device:
                    desktop_metrics['impressions'] += impressions
                    desktop_metrics['clicks'] += clicks
                    desktop_metrics['spend'] += spend

            # Calculate rates
            total_impressions = mobile_metrics['impressions'] + desktop_metrics['impressions']

            return {
                'mobile': {
                    **mobile_metrics,
                    'ctr': (mobile_metrics['clicks'] / mobile_metrics['impressions'] * 100) if mobile_metrics['impressions'] > 0 else 0,
                    'cpc': (mobile_metrics['spend'] / mobile_metrics['clicks']) if mobile_metrics['clicks'] > 0 else 0,
                    'percentage': (mobile_metrics['impressions'] / total_impressions * 100) if total_impressions > 0 else 0,
                },
                'desktop': {
                    **desktop_metrics,
                    'ctr': (desktop_metrics['clicks'] / desktop_metrics['impressions'] * 100) if desktop_metrics['impressions'] > 0 else 0,
                    'cpc': (desktop_metrics['spend'] / desktop_metrics['clicks']) if desktop_metrics['clicks'] > 0 else 0,
                    'percentage': (desktop_metrics['impressions'] / total_impressions * 100) if total_impressions > 0 else 0,
                },
                'raw_devices': devices,
            }

        except Exception as e:
            logger.error(f"Error fetching device performance: {e}")
            return {
                'mobile': {'impressions': 0, 'clicks': 0, 'spend': 0, 'ctr': 0, 'cpc': 0, 'percentage': 0},
                'desktop': {'impressions': 0, 'clicks': 0, 'spend': 0, 'ctr': 0, 'cpc': 0, 'percentage': 0},
                'raw_devices': [],
            }


__all__ = ['FacebookAdsGraderClient']
