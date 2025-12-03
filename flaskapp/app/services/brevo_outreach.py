# app/services/brevo_outreach.py
"""
Brevo (Sendinblue) Email Service for Cold Outreach

Handles:
- Email sending via Brevo API v3
- Template personalization
- Sequence management
- Contact management
- Email tracking (opens, clicks)
- Better rate limits than Mailgun (300 emails/day free, higher paid limits)

API Documentation: https://developers.brevo.com/
"""
import os
import logging
from typing import Dict, Optional, List
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


class BrevoOutreachService:
    """Send cold outreach emails via Brevo (Sendinblue) API"""

    def __init__(self):
        self.api_key = os.getenv('BREVO_API_KEY') or os.getenv('SENDINBLUE_API_KEY')
        self.from_email = os.getenv('BREVO_FROM_EMAIL', 'noreply@fieldsprout.io')
        self.from_name = os.getenv('BREVO_FROM_NAME', 'FieldSprout')

        if not self.api_key:
            raise ValueError("BREVO_API_KEY environment variable must be set")

        self.base_url = "https://api.brevo.com/v3"
        self.headers = {
            'accept': 'application/json',
            'api-key': self.api_key,
            'content-type': 'application/json'
        }

    def send_email(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
        track_opens: bool = True,
        track_clicks: bool = True,
        tags: Optional[List[str]] = None,
        custom_vars: Optional[Dict] = None
    ) -> Dict:
        """
        Send email via Brevo API

        Returns dict with:
        - success: bool
        - message_id: str (Brevo message ID)
        - error: str (if failed)
        - retry_after: int (seconds to wait if rate limited)
        """
        try:
            payload = {
                "sender": {
                    "name": self.from_name,
                    "email": self.from_email
                },
                "to": [
                    {
                        "email": to_email
                    }
                ],
                "subject": subject,
                "htmlContent": body_html,
            }

            # Add text version if provided
            if body_text:
                payload["textContent"] = body_text

            # Add tracking
            if not track_opens:
                payload["headers"] = payload.get("headers", {})
                payload["headers"]["X-Mailin-Tag"] = "no-tracking"

            # Add tags
            if tags:
                payload["tags"] = tags

            # Add custom parameters (for tracking/personalization)
            if custom_vars:
                payload["params"] = custom_vars

            response = requests.post(
                f'{self.base_url}/smtp/email',
                headers=self.headers,
                json=payload,
                timeout=30
            )

            if response.status_code == 201:
                result = response.json()
                return {
                    'success': True,
                    'message_id': result.get('messageId'),
                    'message': 'Email sent successfully'
                }
            elif response.status_code == 429:
                # Rate limit exceeded
                retry_after = self._parse_retry_after(response.headers)
                logger.warning(f"Brevo rate limit hit. Retry after {retry_after} seconds")
                return {
                    'success': False,
                    'error': f"Rate limit exceeded. Retry after {retry_after} seconds",
                    'retry_after': retry_after,
                    'rate_limited': True
                }
            else:
                error_data = response.json() if response.text else {}
                error_msg = error_data.get('message', response.text)
                logger.error(f"Brevo error: {response.status_code} - {error_msg}")
                return {
                    'success': False,
                    'error': f"Brevo API error: {response.status_code} - {error_msg}"
                }

        except Exception as e:
            logger.error(f"Failed to send email via Brevo: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def _parse_retry_after(self, headers: Dict) -> int:
        """Parse retry-after time from response headers"""
        # Brevo uses X-RateLimit-Reset header (Unix timestamp)
        reset_time = headers.get('X-RateLimit-Reset')
        if reset_time:
            try:
                reset_timestamp = int(reset_time)
                now_timestamp = int(datetime.utcnow().timestamp())
                seconds_to_wait = max(0, reset_timestamp - now_timestamp)
                return seconds_to_wait
            except Exception as e:
                logger.debug(f"Could not parse retry time: {e}")

        # Fallback: check Retry-After header
        retry_after = headers.get('Retry-After')
        if retry_after:
            try:
                return int(retry_after)
            except Exception:
                pass

        # Default: wait 1 minute (Brevo resets hourly limits)
        return 60

    def create_contact(
        self,
        email: str,
        attributes: Optional[Dict] = None,
        list_ids: Optional[List[int]] = None
    ) -> Dict:
        """
        Create or update a contact in Brevo

        Useful for managing your contact database and segmentation.
        """
        try:
            payload = {
                "email": email,
                "attributes": attributes or {},
                "updateEnabled": True  # Update if contact exists
            }

            if list_ids:
                payload["listIds"] = list_ids

            response = requests.post(
                f'{self.base_url}/contacts',
                headers=self.headers,
                json=payload,
                timeout=30
            )

            if response.status_code in [201, 204]:
                return {
                    'success': True,
                    'message': 'Contact created/updated'
                }
            else:
                error_data = response.json() if response.text else {}
                logger.error(f"Brevo contact creation failed: {response.status_code}")
                return {
                    'success': False,
                    'error': error_data.get('message', 'Failed to create contact')
                }

        except Exception as e:
            logger.error(f"Error creating Brevo contact: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_account_info(self) -> Dict:
        """
        Get Brevo account information including:
        - Email credits remaining
        - Plan details
        - Rate limits
        """
        try:
            response = requests.get(
                f'{self.base_url}/account',
                headers=self.headers,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                plan = data.get('plan', [{}])[0] if data.get('plan') else {}

                return {
                    'success': True,
                    'email': data.get('email'),
                    'plan_type': plan.get('type'),
                    'credits': plan.get('credits'),
                    'credits_used': plan.get('creditsUsed'),
                    'company_name': data.get('companyName')
                }
            else:
                logger.error(f"Failed to get Brevo account info: {response.status_code}")
                return {
                    'success': False,
                    'error': f"API error: {response.status_code}"
                }

        except Exception as e:
            logger.error(f"Error getting Brevo account info: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_email_events(
        self,
        email: Optional[str] = None,
        event_type: Optional[str] = None,
        days: int = 7
    ) -> List[Dict]:
        """
        Get email events (sent, delivered, opened, clicked, bounced, etc.)

        Args:
            email: Filter by recipient email
            event_type: Filter by event type (sent, delivered, opened, clicked, etc.)
            days: Number of days to look back (default: 7)

        Returns:
            List of event dicts
        """
        try:
            params = {
                'limit': 100,
                'offset': 0,
                'days': days
            }

            if email:
                params['email'] = email
            if event_type:
                params['event'] = event_type

            response = requests.get(
                f'{self.base_url}/smtp/statistics/events',
                headers=self.headers,
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                return data.get('events', [])
            else:
                logger.error(f"Failed to fetch Brevo events: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error fetching Brevo events: {e}")
            return []

    def personalize_template(
        self,
        template: str,
        variables: Dict[str, str]
    ) -> str:
        """
        Replace template variables like {{company_name}} with actual values

        Brevo supports template variables in the same format as Mailgun.
        """
        result = template

        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, str(value))

        return result

    def add_unsubscribe_footer(self, html_body: str, unsubscribe_url: str) -> str:
        """Add CAN-SPAM compliant unsubscribe footer"""
        footer = f'''
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ccc; font-size: 12px; color: #666;">
            <p>You received this email because we found your business online and thought our services might be helpful.</p>
            <p><a href="{unsubscribe_url}" style="color: #666;">Unsubscribe from future emails</a></p>
            <p style="margin-top: 10px; font-size: 11px;">
                FieldSprout Inc.<br>
                This is a commercial email. CAN-SPAM Act compliant.
            </p>
        </div>
        '''

        # Add before closing </body> or at end
        if '</body>' in html_body:
            html_body = html_body.replace('</body>', f'{footer}</body>')
        else:
            html_body += footer

        return html_body
