"""
Facebook OAuth Helper for User Authentication (Sign in with Facebook)

This is separate from the Facebook Ads Grader OAuth which is for API access.
This module handles Facebook Login for user authentication.
"""

import os
import secrets
from typing import Optional, Dict
from flask import session, url_for, request
import requests


class FacebookAuthHelper:
    """
    Facebook OAuth 2.0 helper for user authentication (Facebook Login).

    Separate from Facebook Ads Grader which uses Marketing API.
    This is for 'Sign in with Facebook' functionality.
    """

    OAUTH_AUTHORIZE_URL = "https://www.facebook.com/v20.0/dialog/oauth"
    OAUTH_TOKEN_URL = "https://graph.facebook.com/v20.0/oauth/access_token"
    GRAPH_API_ME_URL = "https://graph.facebook.com/v20.0/me"

    # Scopes for user authentication (NOT ads management)
    REQUIRED_SCOPES = ['email', 'public_profile']

    @staticmethod
    def get_authorization_url(redirect_uri: Optional[str] = None) -> str:
        """
        Generate Facebook OAuth authorization URL for user login.

        Args:
            redirect_uri: Override default redirect URI

        Returns:
            Facebook OAuth authorization URL
        """
        app_id = os.getenv('FB_APP_ID')
        if not app_id:
            raise ValueError("FB_APP_ID environment variable not set")

        # Default redirect URI for user authentication
        if not redirect_uri:
            redirect_uri = url_for('auth_bp.facebook_callback', _external=True)

        # Generate and store CSRF state token
        state_token = secrets.token_urlsafe(32)
        session['facebook_auth_state'] = state_token

        # Build authorization URL
        params = {
            'client_id': app_id,
            'redirect_uri': redirect_uri,
            'state': state_token,
            'scope': ','.join(FacebookAuthHelper.REQUIRED_SCOPES),
            'response_type': 'code'
        }

        # Convert params to query string
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        auth_url = f"{FacebookAuthHelper.OAUTH_AUTHORIZE_URL}?{query_string}"

        return auth_url

    @staticmethod
    def handle_callback(code: str, state: str) -> Optional[Dict[str, str]]:
        """
        Handle Facebook OAuth callback, exchange code for token and fetch user info.

        Args:
            code: Authorization code from Facebook
            state: CSRF state token to verify

        Returns:
            Dict with user info: {
                'facebook_id': str,
                'email': str,
                'name': str,
                'picture': str (URL)
            }
            Or None if validation fails
        """
        # Verify CSRF state token
        stored_state = session.get('facebook_auth_state')
        if not stored_state or state != stored_state:
            return None

        # Clear state token (one-time use)
        session.pop('facebook_auth_state', None)

        # Exchange code for access token
        app_id = os.getenv('FB_APP_ID')
        app_secret = os.getenv('FB_APP_SECRET')

        if not app_id or not app_secret:
            raise ValueError("FB_APP_ID or FB_APP_SECRET environment variable not set")

        redirect_uri = url_for('auth_bp.facebook_callback', _external=True)

        token_params = {
            'client_id': app_id,
            'client_secret': app_secret,
            'redirect_uri': redirect_uri,
            'code': code
        }

        try:
            # Exchange code for access token
            token_response = requests.get(
                FacebookAuthHelper.OAUTH_TOKEN_URL,
                params=token_params,
                timeout=10
            )
            token_response.raise_for_status()
            token_data = token_response.json()

            access_token = token_data.get('access_token')
            if not access_token:
                return None

            # Fetch user profile information
            profile_params = {
                'fields': 'id,email,name,picture.type(large)',
                'access_token': access_token
            }

            profile_response = requests.get(
                FacebookAuthHelper.GRAPH_API_ME_URL,
                params=profile_params,
                timeout=10
            )
            profile_response.raise_for_status()
            profile_data = profile_response.json()

            # Extract user info
            facebook_id = profile_data.get('id')
            email = profile_data.get('email')
            name = profile_data.get('name')

            # Extract picture URL
            picture_url = None
            if 'picture' in profile_data and 'data' in profile_data['picture']:
                picture_url = profile_data['picture']['data'].get('url')

            # Email might not be available if user denied permission
            if not facebook_id:
                return None

            return {
                'facebook_id': facebook_id,
                'email': email,  # May be None
                'name': name,
                'picture': picture_url
            }

        except requests.RequestException as e:
            # Log error (in production use proper logging)
            print(f"Facebook OAuth error: {e}")
            return None

    @staticmethod
    def is_configured() -> bool:
        """
        Check if Facebook OAuth is properly configured.

        Returns:
            True if FB_APP_ID and FB_APP_SECRET are set
        """
        return bool(os.getenv('FB_APP_ID') and os.getenv('FB_APP_SECRET'))
