# app/services/social_export_service.py
"""
Social Media Export Service

Handles direct export of ad creatives to Facebook/Instagram Ads Manager,
LinkedIn Campaign Manager, and other platforms.
"""
import os
import logging
import requests
from typing import Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SocialExportService:
    """Service for exporting ad creatives to social media platforms"""

    def __init__(self):
        self.facebook_app_id = os.getenv('FACEBOOK_APP_ID')
        self.facebook_app_secret = os.getenv('FACEBOOK_APP_SECRET')
        self.facebook_api_version = os.getenv('FACEBOOK_API_VERSION', 'v19.0')

    def get_facebook_oauth_url(self, redirect_uri: str, state: str = None) -> str:
        """
        Generate Facebook OAuth authorization URL

        Args:
            redirect_uri: URL to redirect to after authorization
            state: Optional state parameter for security

        Returns:
            Facebook OAuth URL
        """
        if not self.facebook_app_id:
            raise ValueError('FACEBOOK_APP_ID not configured')

        # Required permissions for Ads Manager
        permissions = [
            'ads_management',
            'ads_read',
            'business_management',
            'pages_read_engagement',
            'pages_manage_ads'
        ]

        params = {
            'client_id': self.facebook_app_id,
            'redirect_uri': redirect_uri,
            'scope': ','.join(permissions),
            'response_type': 'code',
            'state': state or ''
        }

        query_string = '&'.join([f'{k}={v}' for k, v in params.items()])
        return f'https://www.facebook.com/{self.facebook_api_version}/dialog/oauth?{query_string}'

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict:
        """
        Exchange authorization code for access token

        Args:
            code: Authorization code from OAuth callback
            redirect_uri: Same redirect URI used in authorization

        Returns:
            Dict with access_token, token_type, expires_in
        """
        if not self.facebook_app_id or not self.facebook_app_secret:
            raise ValueError('Facebook credentials not configured')

        try:
            response = requests.get(
                f'https://graph.facebook.com/{self.facebook_api_version}/oauth/access_token',
                params={
                    'client_id': self.facebook_app_id,
                    'client_secret': self.facebook_app_secret,
                    'redirect_uri': redirect_uri,
                    'code': code
                },
                timeout=10
            )

            response.raise_for_status()
            data = response.json()

            # Exchange for long-lived token (60 days)
            long_lived = self.get_long_lived_token(data['access_token'])

            return {
                'success': True,
                'access_token': long_lived['access_token'],
                'token_type': 'bearer',
                'expires_in': long_lived.get('expires_in', 5184000),  # 60 days
                'expires_at': (datetime.utcnow() + timedelta(seconds=long_lived.get('expires_in', 5184000))).isoformat()
            }

        except Exception as e:
            logger.error(f"Error exchanging code for token: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_long_lived_token(self, short_lived_token: str) -> Dict:
        """Exchange short-lived token for long-lived token (60 days)"""
        try:
            response = requests.get(
                f'https://graph.facebook.com/{self.facebook_api_version}/oauth/access_token',
                params={
                    'grant_type': 'fb_exchange_token',
                    'client_id': self.facebook_app_id,
                    'client_secret': self.facebook_app_secret,
                    'fb_exchange_token': short_lived_token
                },
                timeout=10
            )

            response.raise_for_status()
            return response.json()

        except Exception as e:
            logger.error(f"Error getting long-lived token: {e}")
            return {'access_token': short_lived_token}  # Fallback to short-lived

    def get_ad_accounts(self, access_token: str) -> Dict:
        """
        Get user's Facebook Ad Accounts

        Args:
            access_token: User's access token

        Returns:
            Dict with list of ad accounts
        """
        try:
            response = requests.get(
                f'https://graph.facebook.com/{self.facebook_api_version}/me/adaccounts',
                params={
                    'access_token': access_token,
                    'fields': 'id,name,account_id,account_status,currency,timezone_name'
                },
                timeout=10
            )

            response.raise_for_status()
            data = response.json()

            return {
                'success': True,
                'ad_accounts': data.get('data', [])
            }

        except Exception as e:
            logger.error(f"Error fetching ad accounts: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def create_ad_creative(
        self,
        access_token: str,
        ad_account_id: str,
        creative_data: Dict
    ) -> Dict:
        """
        Create ad creative in Facebook Ads Manager

        Args:
            access_token: User's access token
            ad_account_id: Facebook Ad Account ID (format: act_xxxxx)
            creative_data: Dict with creative details

        Returns:
            Dict with created creative ID
        """
        try:
            # Prepare creative payload
            creative_payload = {
                'name': creative_data.get('name', f"Creative {datetime.utcnow().isoformat()}"),
                'object_story_spec': {
                    'page_id': creative_data.get('page_id'),
                    'link_data': {
                        'link': creative_data.get('link_url'),
                        'message': creative_data.get('primary_text'),
                        'name': creative_data.get('headline'),
                        'description': creative_data.get('description'),
                        'call_to_action': {
                            'type': creative_data.get('cta_type', 'LEARN_MORE'),
                            'value': {
                                'link': creative_data.get('link_url')
                            }
                        },
                        'picture': creative_data.get('image_url')
                    }
                },
                'degrees_of_freedom_spec': {
                    'creative_features_spec': {
                        'standard_enhancements': {
                            'enroll_status': 'OPT_IN'
                        }
                    }
                },
                'access_token': access_token
            }

            response = requests.post(
                f'https://graph.facebook.com/{self.facebook_api_version}/{ad_account_id}/adcreatives',
                json=creative_payload,
                timeout=15
            )

            response.raise_for_status()
            data = response.json()

            return {
                'success': True,
                'creative_id': data.get('id'),
                'preview_url': f"https://www.facebook.com/ads/manager/creation/creation/?act={ad_account_id.replace('act_', '')}&creative_id={data.get('id')}"
            }

        except Exception as e:
            logger.error(f"Error creating ad creative: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def upload_image_to_facebook(
        self,
        access_token: str,
        ad_account_id: str,
        image_url: str
    ) -> Dict:
        """
        Upload image to Facebook Ad Account

        Args:
            access_token: User's access token
            ad_account_id: Facebook Ad Account ID
            image_url: URL of image to upload

        Returns:
            Dict with uploaded image hash
        """
        try:
            # Download image first
            img_response = requests.get(image_url, timeout=10)
            img_response.raise_for_status()

            # Upload to Facebook
            upload_response = requests.post(
                f'https://graph.facebook.com/{self.facebook_api_version}/{ad_account_id}/adimages',
                files={
                    'filename': ('ad_image.jpg', img_response.content, 'image/jpeg')
                },
                data={
                    'access_token': access_token
                },
                timeout=20
            )

            upload_response.raise_for_status()
            data = upload_response.json()

            return {
                'success': True,
                'image_hash': data.get('images', {}).get('filename', {}).get('hash'),
                'image_url': data.get('images', {}).get('filename', {}).get('url')
            }

        except Exception as e:
            logger.error(f"Error uploading image: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def export_creative_to_facebook(
        self,
        access_token: str,
        ad_account_id: str,
        page_id: str,
        creative: Dict,
        destination_url: str
    ) -> Dict:
        """
        Complete export workflow: upload image and create creative

        Args:
            access_token: User's access token
            ad_account_id: Facebook Ad Account ID
            page_id: Facebook Page ID to publish from
            creative: Dict with headline, primary_text, description, cta, image_url
            destination_url: Landing page URL

        Returns:
            Dict with success status and creative ID
        """
        # Upload image
        image_result = self.upload_image_to_facebook(
            access_token=access_token,
            ad_account_id=ad_account_id,
            image_url=creative.get('image_url')
        )

        if not image_result.get('success'):
            return image_result

        # Map CTA text to Facebook CTA type
        cta_mapping = {
            'learn more': 'LEARN_MORE',
            'sign up': 'SIGN_UP',
            'book now': 'BOOK_TRAVEL',
            'get quote': 'GET_QUOTE',
            'contact us': 'CONTACT_US',
            'call now': 'CALL_NOW',
            'apply now': 'APPLY_NOW',
            'shop now': 'SHOP_NOW'
        }

        cta_text = creative.get('call_to_action', 'Learn More').lower()
        cta_type = cta_mapping.get(cta_text, 'LEARN_MORE')

        # Create creative
        creative_data = {
            'name': creative.get('name', f"Ad Creative - {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"),
            'page_id': page_id,
            'headline': creative.get('headline'),
            'primary_text': creative.get('primary_text'),
            'description': creative.get('description'),
            'cta_type': cta_type,
            'link_url': destination_url,
            'image_hash': image_result.get('image_hash')
        }

        return self.create_ad_creative(
            access_token=access_token,
            ad_account_id=ad_account_id,
            creative_data=creative_data
        )


class InstagramExportService(SocialExportService):
    """Instagram export uses Facebook Marketing API"""

    def export_creative_to_instagram(
        self,
        access_token: str,
        ad_account_id: str,
        instagram_account_id: str,
        creative: Dict,
        destination_url: str
    ) -> Dict:
        """
        Export creative to Instagram via Facebook Marketing API

        Instagram ads are created through Facebook Ads Manager with
        Instagram placement specified
        """
        # Instagram uses same creative creation as Facebook
        # but with Instagram account specified
        return self.export_creative_to_facebook(
            access_token=access_token,
            ad_account_id=ad_account_id,
            page_id=instagram_account_id,
            creative=creative,
            destination_url=destination_url
        )
