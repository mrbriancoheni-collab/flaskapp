# app/services/mailgun_outreach.py
"""
Mailgun Email Service for Cold Outreach

Handles:
- Email sending via Mailgun API
- Template personalization
- Sequence management
- Rate limiting (250/day)
- Unsubscribe handling (CAN-SPAM compliance)
"""
import os
import logging
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import requests
from flask import url_for

logger = logging.getLogger(__name__)


class MailgunOutreachService:
    """Send cold outreach emails via Mailgun with sequences"""

    def __init__(self):
        self.api_key = os.getenv('MAILGUN_API_KEY')
        self.domain = os.getenv('MAILGUN_DOMAIN')
        self.from_email = os.getenv('MAILGUN_FROM_EMAIL', f'noreply@{self.domain}')
        self.from_name = os.getenv('MAILGUN_FROM_NAME', 'FieldSprout')

        if not self.api_key or not self.domain:
            raise ValueError("MAILGUN_API_KEY and MAILGUN_DOMAIN must be set")

        self.base_url = f"https://api.mailgun.net/v3/{self.domain}"

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
        Send email via Mailgun

        Returns dict with:
        - success: bool
        - message_id: str (Mailgun ID)
        - error: str (if failed)
        """
        try:
            data = {
                'from': f'{self.from_name} <{self.from_email}>',
                'to': to_email,
                'subject': subject,
                'html': body_html,
                'o:tracking': 'yes' if track_opens else 'no',
                'o:tracking-clicks': 'yes' if track_clicks else 'no',
            }

            if body_text:
                data['text'] = body_text

            if tags:
                data['o:tag'] = tags

            if custom_vars:
                for key, value in custom_vars.items():
                    data[f'v:{key}'] = value

            response = requests.post(
                f'{self.base_url}/messages',
                auth=('api', self.api_key),
                data=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'message_id': result.get('id'),
                    'message': result.get('message')
                }
            else:
                logger.error(f"Mailgun error: {response.status_code} - {response.text}")
                return {
                    'success': False,
                    'error': f"Mailgun API error: {response.status_code}"
                }

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def personalize_template(
        self,
        template: str,
        variables: Dict[str, str]
    ) -> str:
        """
        Replace template variables like {{company_name}} with actual values

        Available variables:
        - {{company_name}}
        - {{decision_maker_name}}
        - {{decision_maker_title}}
        - {{service_type}}
        - {{location}}
        - {{unsubscribe_url}}
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

    def get_unsubscribe_url(self, email: str, campaign_id: int) -> str:
        """Generate unsubscribe URL"""
        # In production, this would use url_for with _external=True
        # For now, return a placeholder
        from urllib.parse import urlencode
        params = urlencode({'email': email, 'campaign': campaign_id})
        return f"/unsubscribe?{params}"

    def check_daily_limit(self, sent_today: int, limit: int = 250) -> bool:
        """Check if we're within daily sending limit"""
        return sent_today < limit

    def get_events(
        self,
        begin_timestamp: Optional[datetime] = None,
        end_timestamp: Optional[datetime] = None,
        event_type: Optional[str] = None
    ) -> List[Dict]:
        """
        Fetch email events from Mailgun (delivered, opened, clicked, etc.)

        Args:
            begin_timestamp: Start time
            end_timestamp: End time
            event_type: Filter by type (delivered, opened, clicked, etc.)

        Returns:
            List of event dicts
        """
        try:
            params = {}
            if begin_timestamp:
                params['begin'] = begin_timestamp.timestamp()
            if end_timestamp:
                params['end'] = end_timestamp.timestamp()
            if event_type:
                params['event'] = event_type

            response = requests.get(
                f'{self.base_url}/events',
                auth=('api', self.api_key),
                params=params,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                return data.get('items', [])
            else:
                logger.error(f"Failed to fetch events: {response.status_code}")
                return []

        except Exception as e:
            logger.error(f"Error fetching Mailgun events: {e}")
            return []

    def verify_email(self, email: str) -> Dict:
        """
        Verify email address using Mailgun's validation API

        Returns:
        - is_valid: bool
        - is_deliverable: bool
        - is_role_address: bool (info@, sales@, etc.)
        - risk_score: float (0-1, higher = riskier)
        """
        try:
            response = requests.get(
                f'https://api.mailgun.net/v4/address/validate',
                auth=('api', self.api_key),
                params={'address': email},
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                result = data.get('result', 'unknown')
                risk = data.get('risk', 'unknown')

                return {
                    'is_valid': result in ['deliverable', 'do_not_send'] and risk != 'high',
                    'is_deliverable': result == 'deliverable',
                    'is_role_address': data.get('is_role_address', False),
                    'risk_score': {'low': 0.2, 'medium': 0.5, 'high': 0.9}.get(risk, 0.5),
                    'raw_result': result,
                    'raw_risk': risk
                }
            else:
                logger.warning(f"Email validation failed: {response.status_code}")
                return {
                    'is_valid': False,
                    'is_deliverable': False,
                    'is_role_address': False,
                    'risk_score': 1.0
                }

        except Exception as e:
            logger.error(f"Error validating email: {e}")
            return {
                'is_valid': False,
                'is_deliverable': False,
                'is_role_address': False,
                'risk_score': 1.0
            }
