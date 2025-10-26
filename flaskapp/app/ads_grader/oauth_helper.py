"""
OAuth 2.0 Helper for Google Ads Connection

Handles the OAuth flow for connecting Google Ads accounts.
"""
import logging
import secrets
from typing import Optional, Dict, Any
from flask import session, url_for, current_app
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

# Google Ads API OAuth scopes
SCOPES = ['https://www.googleapis.com/auth/adwords']


class GoogleAdsOAuthHelper:
    """
    Manages OAuth 2.0 flow for Google Ads API access.
    """

    @staticmethod
    def get_authorization_url() -> str:
        """
        Generate Google OAuth authorization URL.

        Returns:
            Authorization URL to redirect user to
        """
        # Generate state token for CSRF protection
        state = secrets.token_urlsafe(32)
        session['oauth_state'] = state

        # Get OAuth credentials from config
        client_config = {
            "web": {
                "client_id": current_app.config.get("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": current_app.config.get("GOOGLE_ADS_CLIENT_SECRET"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [current_app.config.get("GOOGLE_ADS_REDIRECT_URI")],
            }
        }

        # Create OAuth flow
        flow = Flow.from_client_config(
            client_config,
            scopes=SCOPES,
            state=state
        )

        # Set redirect URI
        flow.redirect_uri = current_app.config.get("GOOGLE_ADS_REDIRECT_URI")

        # Generate authorization URL
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'  # Force consent screen to get refresh token
        )

        return authorization_url

    @staticmethod
    def handle_callback(authorization_response: str, state: str) -> Optional[Dict[str, str]]:
        """
        Handle OAuth callback and exchange code for tokens.

        Args:
            authorization_response: Full callback URL with code and state
            state: State parameter from callback

        Returns:
            Dictionary with access_token and refresh_token, or None if failed
        """
        # Verify state to prevent CSRF
        session_state = session.get('oauth_state')
        if not session_state or session_state != state:
            logger.error("OAuth state mismatch - possible CSRF attack")
            return None

        # Clear state from session
        session.pop('oauth_state', None)

        try:
            # Get OAuth credentials from config
            client_config = {
                "web": {
                    "client_id": current_app.config.get("GOOGLE_ADS_CLIENT_ID"),
                    "client_secret": current_app.config.get("GOOGLE_ADS_CLIENT_SECRET"),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [current_app.config.get("GOOGLE_ADS_REDIRECT_URI")],
                }
            }

            # Create OAuth flow
            flow = Flow.from_client_config(
                client_config,
                scopes=SCOPES,
                state=state
            )

            # Set redirect URI (must match the one used in authorization)
            flow.redirect_uri = current_app.config.get("GOOGLE_ADS_REDIRECT_URI")

            # Exchange authorization code for tokens
            flow.fetch_token(authorization_response=authorization_response)

            # Get credentials
            credentials = flow.credentials

            return {
                "access_token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "token_uri": credentials.token_uri,
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "scopes": credentials.scopes,
            }

        except Exception as e:
            logger.exception(f"Error exchanging OAuth code for tokens: {e}")
            return None

    @staticmethod
    def refresh_access_token(refresh_token: str) -> Optional[str]:
        """
        Refresh an expired access token.

        Args:
            refresh_token: The refresh token from initial authorization

        Returns:
            New access token, or None if refresh failed
        """
        try:
            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=current_app.config.get("GOOGLE_ADS_CLIENT_ID"),
                client_secret=current_app.config.get("GOOGLE_ADS_CLIENT_SECRET"),
                scopes=SCOPES
            )

            # Refresh the token
            from google.auth.transport.requests import Request
            credentials.refresh(Request())

            return credentials.token

        except Exception as e:
            logger.exception(f"Error refreshing access token: {e}")
            return None

    @staticmethod
    def get_customer_ids(access_token: str) -> List[Dict[str, str]]:
        """
        Fetch all Google Ads customer IDs accessible with this token.

        Args:
            access_token: Valid OAuth access token

        Returns:
            List of dictionaries with customer_id and name
        """
        try:
            from google.ads.googleads.client import GoogleAdsClient

            credentials_dict = {
                "developer_token": current_app.config.get("GOOGLE_ADS_DEVELOPER_TOKEN"),
                "client_id": current_app.config.get("GOOGLE_ADS_CLIENT_ID"),
                "client_secret": current_app.config.get("GOOGLE_ADS_CLIENT_SECRET"),
                "refresh_token": access_token,
                "use_proto_plus": True,
            }

            client = GoogleAdsClient.load_from_dict(credentials_dict)
            customer_service = client.get_service("CustomerService")

            # List accessible customers
            accessible_customers = customer_service.list_accessible_customers()

            customers = []
            for resource_name in accessible_customers.resource_names:
                # Extract customer ID from resource name (format: customers/1234567890)
                customer_id = resource_name.split('/')[-1]

                # Get customer details
                ga_service = client.get_service("GoogleAdsService")
                query = f"""
                    SELECT
                        customer.id,
                        customer.descriptive_name
                    FROM customer
                    WHERE customer.id = {customer_id}
                """

                response = ga_service.search(customer_id=customer_id, query=query)

                for row in response:
                    customers.append({
                        "customer_id": str(row.customer.id),
                        "name": row.customer.descriptive_name or f"Account {row.customer.id}",
                    })

            return customers

        except Exception as e:
            logger.exception(f"Error fetching customer IDs: {e}")
            return []
