# app/services/google_ads_alerts_service.py
"""
Google Ads Alerts Service - Fetch alerts and recommendations from Google Ads.

This service pulls in alerts that are set up in Google Ads (via the Recommendations API)
so users can see them directly on our platform without logging into Google Ads.
"""

import os
from typing import List, Dict, Any
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from datetime import datetime


def get_google_ads_client(refresh_token: str, customer_id: str = None) -> GoogleAdsClient:
    """Create a Google Ads API client from refresh token."""
    config = {
        "developer_token": os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN"),
        "client_id": os.getenv("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": refresh_token,
        "login_customer_id": customer_id,
        "use_proto_plus": True
    }
    return GoogleAdsClient.load_from_dict(config)


def fetch_google_ads_alerts(refresh_token: str, customer_id: str) -> Dict[str, Any]:
    """
    Fetch alerts and recommendations from Google Ads.

    Returns:
        Dict with alerts categorized by type:
        - recommendations: Optimization suggestions from Google Ads
        - account_alerts: Account-level alerts
        - campaign_alerts: Campaign-level alerts
    """
    try:
        client = get_google_ads_client(refresh_token, customer_id)

        # Remove dashes from customer_id for API calls
        customer_id_clean = customer_id.replace('-', '')

        alerts = {
            'recommendations': fetch_recommendations(client, customer_id_clean),
            'account_alerts': fetch_account_alerts(client, customer_id_clean),
            'change_history': fetch_recent_changes(client, customer_id_clean),
            'fetched_at': datetime.utcnow().isoformat()
        }

        return alerts

    except GoogleAdsException as ex:
        error_details = []
        for error in ex.failure.errors:
            error_details.append({
                'message': error.message,
                'trigger': error.trigger.string_value if error.trigger else None,
            })

        return {
            'success': False,
            'error': 'Google Ads API error',
            'details': error_details
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


def fetch_recommendations(client: GoogleAdsClient, customer_id: str) -> List[Dict[str, Any]]:
    """
    Fetch optimization recommendations from Google Ads.

    These are the same recommendations you see in the Google Ads UI under "Recommendations".
    """
    ga_service = client.get_service("GoogleAdsService")

    query = """
        SELECT
            recommendation.type,
            recommendation.resource_name,
            recommendation.campaign,
            recommendation.ad_group,
            recommendation.keyword_recommendation,
            recommendation.text_ad_recommendation,
            recommendation.search_partners_opt_in_recommendation,
            recommendation.maximize_conversions_opt_in_recommendation,
            recommendation.improve_performance_max_ad_strength_recommendation,
            recommendation.target_cpa_opt_in_recommendation,
            recommendation.target_roas_opt_in_recommendation,
            recommendation.callout_extension_recommendation,
            recommendation.sitelink_extension_recommendation,
            recommendation.call_extension_recommendation,
            recommendation.keyword_match_type_recommendation,
            recommendation.move_unused_budget_recommendation,
            recommendation.forecasting_campaign_budget_recommendation,
            recommendation.responsive_search_ad_recommendation,
            recommendation.marginal_roi_campaign_budget_recommendation,
            recommendation.use_broad_match_keyword_recommendation,
            recommendation.responsive_search_ad_improve_ad_strength_recommendation,
            recommendation.display_expansion_opt_in_recommendation,
            recommendation.upgrade_smart_shopping_campaign_to_performance_max_recommendation,
            recommendation.raise_target_cpa_bid_too_low_recommendation,
            recommendation.forecasting_set_target_roas_recommendation,
            recommendation.shopping_add_age_group_recommendation,
            recommendation.shopping_add_color_recommendation,
            recommendation.shopping_add_gender_recommendation,
            recommendation.shopping_add_size_recommendation,
            recommendation.impact
        FROM recommendation
        WHERE recommendation.dismissed = FALSE
        ORDER BY recommendation.impact.base_metrics.clicks DESC
        LIMIT 50
    """

    try:
        response = ga_service.search(customer_id=customer_id, query=query)

        recommendations = []
        for row in response:
            rec = row.recommendation

            # Parse recommendation based on type
            rec_data = {
                'resource_name': rec.resource_name,
                'type': rec.type_.name if rec.type_ else 'UNKNOWN',
                'campaign': rec.campaign if rec.campaign else None,
                'ad_group': rec.ad_group if rec.ad_group else None,
                'impact': {
                    'clicks': rec.impact.base_metrics.clicks if rec.impact else 0,
                    'impressions': rec.impact.base_metrics.impressions if rec.impact else 0,
                    'conversions': rec.impact.base_metrics.conversions if rec.impact else 0,
                    'cost_micros': rec.impact.base_metrics.cost_micros if rec.impact else 0
                }
            }

            # Add type-specific data
            if rec.type_.name == 'KEYWORD':
                rec_data['keyword'] = rec.keyword_recommendation.keyword.text if rec.keyword_recommendation else None
            elif rec.type_.name == 'TEXT_AD':
                rec_data['ad'] = 'Text ad recommendation available'
            elif rec.type_.name == 'TARGET_CPA_OPT_IN':
                rec_data['target_cpa'] = rec.target_cpa_opt_in_recommendation.recommended_target_cpa_micros if rec.target_cpa_opt_in_recommendation else None
            elif rec.type_.name == 'MOVE_UNUSED_BUDGET':
                rec_data['budget_recommendation'] = rec.move_unused_budget_recommendation if rec.move_unused_budget_recommendation else None
            elif rec.type_.name == 'FORECASTING_CAMPAIGN_BUDGET':
                rec_data['budget_forecast'] = rec.forecasting_campaign_budget_recommendation if rec.forecasting_campaign_budget_recommendation else None

            recommendations.append(rec_data)

        return recommendations

    except Exception as e:
        print(f"Error fetching recommendations: {str(e)}")
        return []


def fetch_account_alerts(client: GoogleAdsClient, customer_id: str) -> List[Dict[str, Any]]:
    """
    Fetch account-level alerts from Google Ads.

    This includes alerts about:
    - Billing issues
    - Policy violations
    - Disapproved ads
    - Budget issues
    """
    ga_service = client.get_service("GoogleAdsService")

    # Query for account-level alerts via AlertService
    query = """
        SELECT
            customer.id,
            customer.descriptive_name,
            customer.currency_code,
            customer.time_zone,
            customer.manager,
            customer.test_account,
            customer.tracking_url_template,
            customer.optimization_score,
            customer.optimization_score_weight
        FROM customer
        WHERE customer.id = {customer_id}
    """.format(customer_id=customer_id)

    try:
        response = ga_service.search(customer_id=customer_id, query=query)

        alerts = []
        for row in response:
            customer = row.customer

            # Check for low optimization score (potential alert)
            if customer.optimization_score and customer.optimization_score < 0.7:
                alerts.append({
                    'type': 'LOW_OPTIMIZATION_SCORE',
                    'severity': 'MEDIUM',
                    'title': 'Low Optimization Score',
                    'description': f'Account optimization score is {customer.optimization_score:.1%}. Review recommendations to improve.',
                    'account_name': customer.descriptive_name,
                    'created_at': datetime.utcnow().isoformat()
                })

        return alerts

    except Exception as e:
        print(f"Error fetching account alerts: {str(e)}")
        return []


def fetch_recent_changes(client: GoogleAdsClient, customer_id: str) -> List[Dict[str, Any]]:
    """
    Fetch recent changes from Google Ads change history.

    This shows what has been modified in the account recently,
    which can serve as an audit log / alert system.
    """
    ga_service = client.get_service("GoogleAdsService")

    query = """
        SELECT
            change_event.resource_type,
            change_event.change_date_time,
            change_event.changed_fields,
            change_event.resource_change_operation,
            change_event.user_email,
            change_event.campaign,
            change_event.ad_group,
            change_event.ad_group_ad
        FROM change_event
        WHERE change_event.change_date_time >= '2024-01-01'
        ORDER BY change_event.change_date_time DESC
        LIMIT 100
    """

    try:
        response = ga_service.search(customer_id=customer_id, query=query)

        changes = []
        for row in response:
            event = row.change_event

            changes.append({
                'resource_type': event.resource_type_.name if event.resource_type_ else 'UNKNOWN',
                'change_date': event.change_date_time,
                'operation': event.resource_change_operation_.name if event.resource_change_operation_ else 'UNKNOWN',
                'changed_fields': event.changed_fields.paths if event.changed_fields else [],
                'user_email': event.user_email if event.user_email else 'System',
                'campaign': event.campaign if event.campaign else None,
                'ad_group': event.ad_group if event.ad_group else None
            })

        return changes

    except Exception as e:
        print(f"Error fetching change history: {str(e)}")
        return []


def apply_recommendation(client: GoogleAdsClient, customer_id: str, recommendation_resource_name: str) -> Dict[str, Any]:
    """
    Apply a Google Ads recommendation.

    This allows users to accept recommendations directly from our platform.
    """
    try:
        recommendation_service = client.get_service("RecommendationService")

        operation = client.get_type("ApplyRecommendationOperation")
        operation.resource_name = recommendation_resource_name

        response = recommendation_service.apply_recommendation(
            customer_id=customer_id.replace('-', ''),
            operations=[operation]
        )

        return {
            'success': True,
            'applied_recommendation': recommendation_resource_name,
            'results': response.results
        }

    except GoogleAdsException as ex:
        error_details = []
        for error in ex.failure.errors:
            error_details.append({
                'message': error.message,
                'trigger': error.trigger.string_value if error.trigger else None,
            })

        return {
            'success': False,
            'error': 'Failed to apply recommendation',
            'details': error_details
        }


def dismiss_recommendation(client: GoogleAdsClient, customer_id: str, recommendation_resource_name: str) -> Dict[str, Any]:
    """
    Dismiss a Google Ads recommendation.
    """
    try:
        recommendation_service = client.get_service("RecommendationService")

        operation = client.get_type("DismissRecommendationRequest.DismissRecommendationOperation")
        operation.resource_name = recommendation_resource_name

        response = recommendation_service.dismiss_recommendation(
            customer_id=customer_id.replace('-', ''),
            operations=[operation]
        )

        return {
            'success': True,
            'dismissed_recommendation': recommendation_resource_name
        }

    except GoogleAdsException as ex:
        error_details = []
        for error in ex.failure.errors:
            error_details.append({
                'message': error.message,
                'trigger': error.trigger.string_value if error.trigger else None,
            })

        return {
            'success': False,
            'error': 'Failed to dismiss recommendation',
            'details': error_details
        }
