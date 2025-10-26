# app/fb_ads_grader/oauth_helper.py
"""
Facebook OAuth Helper for Ads Grader

Manages OAuth 2.0 flow for Facebook Ads API access.
"""
import os
import logging
import secrets
from typing import Optional, Dict, List
from urllib.parse import urlencode

import requests
from flask import current_app, session

logger = logging.getLogger(__name__)


class FacebookAdsOAuthHelper:
    """
    Helper class for Facebook OAuth 2.0 flow.

    Handles:
    - Authorization URL generation
    - Token exchange
    - Ad account enumeration
    """

    GRAPH_API_VERSION = "v20.0"
    GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
    OAUTH_DIALOG_URL = "https://www.facebook.com/v20.0/dialog/oauth"

    # Permissions needed for ad account read access
    REQUIRED_SCOPES = [
        'ads_read',  # Read ad account data
        'read_insights',  # Read performance insights
    ]

    @staticmethod
    def get_authorization_url() -> str:
        """
        Generate Facebook OAuth authorization URL.

        Returns:
            Authorization URL to redirect user to
        """
        app_id = current_app.config.get('FB_APP_ID') or os.getenv('FB_APP_ID')
        redirect_uri = current_app.config.get('FB_ADS_GRADER_REDIRECT_URI') or \
                      os.getenv('FB_ADS_GRADER_REDIRECT_URI') or \
                      'http://localhost:5000/fb-ads-grader/connect/callback'

        if not app_id:
            raise ValueError("FB_APP_ID not configured")

        # Generate and store state token for CSRF protection
        state_token = secrets.token_urlsafe(32)
        session['fb_ads_oauth_state'] = state_token

        # Build authorization URL
        params = {
            'client_id': app_id,
            'redirect_uri': redirect_uri,
            'state': state_token,
            'scope': ','.join(FacebookAdsOAuthHelper.REQUIRED_SCOPES),
            'response_type': 'code',
        }

        auth_url = f"{FacebookAdsOAuthHelper.OAUTH_DIALOG_URL}?{urlencode(params)}"
        logger.info(f"Generated Facebook OAuth URL: {auth_url}")

        return auth_url

    @staticmethod
    def handle_callback(code: str, state: str) -> Optional[Dict[str, str]]:
        """
        Handle OAuth callback and exchange code for access token.

        Args:
            code: Authorization code from Facebook
            state: State token for CSRF verification

        Returns:
            Dict with access_token and expires_in, or None if failed
        """
        # Verify state token
        stored_state = session.get('fb_ads_oauth_state')
        if not stored_state or stored_state != state:
            logger.error("OAuth state mismatch - possible CSRF attack")
            return None

        # Clear state from session
        session.pop('fb_ads_oauth_state', None)

        # Get configuration
        app_id = current_app.config.get('FB_APP_ID') or os.getenv('FB_APP_ID')
        app_secret = current_app.config.get('FB_APP_SECRET') or os.getenv('FB_APP_SECRET')
        redirect_uri = current_app.config.get('FB_ADS_GRADER_REDIRECT_URI') or \
                      os.getenv('FB_ADS_GRADER_REDIRECT_URI') or \
                      'http://localhost:5000/fb-ads-grader/connect/callback'

        if not app_id or not app_secret:
            logger.error("FB_APP_ID or FB_APP_SECRET not configured")
            return None

        # Exchange code for access token
        token_url = f"{FacebookAdsOAuthHelper.GRAPH_BASE_URL}/oauth/access_token"
        params = {
            'client_id': app_id,
            'client_secret': app_secret,
            'redirect_uri': redirect_uri,
            'code': code,
        }

        try:
            response = requests.get(token_url, params=params, timeout=30)
            response.raise_for_status()
            token_data = response.json()

            access_token = token_data.get('access_token')
            expires_in = token_data.get('expires_in', 5184000)  # 60 days default

            if not access_token:
                logger.error("No access token in response")
                return None

            logger.info("Successfully exchanged code for access token")

            return {
                'access_token': access_token,
                'expires_in': str(expires_in),
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to exchange code for token: {e}")
            return None

    @staticmethod
    def get_ad_accounts(access_token: str) -> List[Dict[str, str]]:
        """
        Get list of ad accounts accessible by the user.

        Args:
            access_token: Facebook access token

        Returns:
            List of dicts with id, name, account_id, account_status
        """
        logger.info("Fetching user's ad accounts")

        try:
            # Get user's ad accounts
            url = f"{FacebookAdsOAuthHelper.GRAPH_BASE_URL}/me/adaccounts"
            params = {
                'access_token': access_token,
                'fields': 'id,name,account_id,account_status,currency',
                'limit': 100,
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            ad_accounts = data.get('data', [])

            logger.info(f"Found {len(ad_accounts)} ad accounts")

            # Format for display
            return [
                {
                    'id': account.get('id'),  # Format: act_123456
                    'account_id': account.get('account_id'),  # Just the number
                    'name': account.get('name', 'Unnamed Account'),
                    'status': account.get('account_status', 'UNKNOWN'),
                    'currency': account.get('currency', 'USD'),
                }
                for account in ad_accounts
                if account.get('account_status') == 'ACTIVE'  # Only return active accounts
            ]

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch ad accounts: {e}")
            return []

    @staticmethod
    def exchange_for_long_lived_token(short_lived_token: str) -> Optional[str]:
        """
        Exchange short-lived token for long-lived token (60 days).

        Args:
            short_lived_token: Short-lived access token

        Returns:
            Long-lived access token, or None if failed
        """
        app_id = current_app.config.get('FB_APP_ID') or os.getenv('FB_APP_ID')
        app_secret = current_app.config.get('FB_APP_SECRET') or os.getenv('FB_APP_SECRET')

        if not app_id or not app_secret:
            logger.error("FB_APP_ID or FB_APP_SECRET not configured")
            return None

        try:
            url = f"{FacebookAdsOAuthHelper.GRAPH_BASE_URL}/oauth/access_token"
            params = {
                'grant_type': 'fb_exchange_token',
                'client_id': app_id,
                'client_secret': app_secret,
                'fb_exchange_token': short_lived_token,
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            long_lived_token = data.get('access_token')
            logger.info("Successfully exchanged for long-lived token")

            return long_lived_token

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to exchange for long-lived token: {e}")
            return short_lived_token  # Return original token as fallback


__all__ = ['FacebookAdsOAuthHelper']
