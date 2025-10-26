# app/auth/google_oauth.py
"""
Google OAuth Helper for User Authentication

Handles "Sign in with Google" functionality for user accounts.
This is different from the Google Ads API OAuth (which is for API access).
"""
import os
import logging
import secrets
from typing import Optional, Dict
from urllib.parse import urlencode

import requests
from flask import current_app, session

logger = logging.getLogger(__name__)


class GoogleAuthHelper:
    """
    Helper class for Google OAuth 2.0 user authentication.

    Handles "Sign in with Google" and "Sign up with Google" flows.
    """

    # Google OAuth endpoints
    OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
    OAUTH_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    # Scopes needed for user authentication
    REQUIRED_SCOPES = [
        'openid',
        'email',
        'profile',
    ]

    @staticmethod
    def get_authorization_url(redirect_uri: Optional[str] = None) -> str:
        """
        Generate Google OAuth authorization URL for user sign-in.

        Args:
            redirect_uri: Optional custom redirect URI

        Returns:
            Authorization URL to redirect user to
        """
        client_id = current_app.config.get('GOOGLE_CLIENT_ID') or os.getenv('GOOGLE_CLIENT_ID')

        if not redirect_uri:
            redirect_uri = current_app.config.get('GOOGLE_AUTH_REDIRECT_URI') or \
                          os.getenv('GOOGLE_AUTH_REDIRECT_URI') or \
                          'http://localhost:5000/auth/google/callback'

        if not client_id:
            raise ValueError("GOOGLE_CLIENT_ID not configured")

        # Generate and store state token for CSRF protection
        state_token = secrets.token_urlsafe(32)
        session['google_auth_state'] = state_token

        # Build authorization URL
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(GoogleAuthHelper.REQUIRED_SCOPES),
            'state': state_token,
            'access_type': 'online',  # We don't need offline access for authentication
            'prompt': 'select_account',  # Always show account selector
        }

        auth_url = f"{GoogleAuthHelper.OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
        logger.info(f"Generated Google auth URL")

        return auth_url

    @staticmethod
    def handle_callback(code: str, state: str, redirect_uri: Optional[str] = None) -> Optional[Dict[str, str]]:
        """
        Handle OAuth callback and exchange code for user info.

        Args:
            code: Authorization code from Google
            state: State token for CSRF verification
            redirect_uri: Optional custom redirect URI

        Returns:
            Dict with user info (google_id, email, name, picture) or None if failed
        """
        # Verify state token
        stored_state = session.get('google_auth_state')
        if not stored_state or stored_state != state:
            logger.error("OAuth state mismatch - possible CSRF attack")
            return None

        # Clear state from session
        session.pop('google_auth_state', None)

        # Get configuration
        client_id = current_app.config.get('GOOGLE_CLIENT_ID') or os.getenv('GOOGLE_CLIENT_ID')
        client_secret = current_app.config.get('GOOGLE_CLIENT_SECRET') or os.getenv('GOOGLE_CLIENT_SECRET')

        if not redirect_uri:
            redirect_uri = current_app.config.get('GOOGLE_AUTH_REDIRECT_URI') or \
                          os.getenv('GOOGLE_AUTH_REDIRECT_URI') or \
                          'http://localhost:5000/auth/google/callback'

        if not client_id or not client_secret:
            logger.error("GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not configured")
            return None

        # Exchange code for access token
        token_data = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }

        try:
            # Get access token
            token_response = requests.post(
                GoogleAuthHelper.OAUTH_TOKEN_URL,
                data=token_data,
                timeout=30
            )
            token_response.raise_for_status()
            tokens = token_response.json()

            access_token = tokens.get('access_token')
            if not access_token:
                logger.error("No access token in response")
                return None

            # Get user info
            userinfo_response = requests.get(
                GoogleAuthHelper.OAUTH_USERINFO_URL,
                headers={'Authorization': f'Bearer {access_token}'},
                timeout=30
            )
            userinfo_response.raise_for_status()
            userinfo = userinfo_response.json()

            logger.info(f"Successfully authenticated Google user: {userinfo.get('email')}")

            return {
                'google_id': userinfo.get('id'),
                'email': userinfo.get('email'),
                'name': userinfo.get('name'),
                'given_name': userinfo.get('given_name'),
                'family_name': userinfo.get('family_name'),
                'picture': userinfo.get('picture'),
                'email_verified': userinfo.get('verified_email', False),
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to exchange code for token or get user info: {e}")
            return None


__all__ = ['GoogleAuthHelper']
