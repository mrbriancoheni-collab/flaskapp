# app/services/lsa_missed_call_service.py
"""
LSA Missed Call Detection Service

Monitors Google Local Services Ads (LSA) calls and detects missed opportunities.
Sends email alerts to business owners when calls are missed.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging

from flask import current_app
from sqlalchemy import and_, or_
from app import db
from app.models_glsa import GLSACallRecord, GLSALead, GLSAAccount
from app.services.email_service import send_email


logger = logging.getLogger(__name__)


class MissedCallAlert:
    """Represents a missed call alert"""

    def __init__(self, call_record: GLSACallRecord, lead: GLSALead):
        self.call_record = call_record
        self.lead = lead
        self.account_id = call_record.account_id
        self.created_at = call_record.created_at

    @property
    def is_missed(self) -> bool:
        """Determine if this call was truly missed"""
        if not self.call_record.outcome_label:
            return False

        # Missed call indicators
        missed_outcomes = [
            'missed',
            'no_answer',
            'unanswered',
            'voicemail',
            'abandoned',
            'not_answered'
        ]

        outcome_lower = self.call_record.outcome_label.lower()
        return any(indicator in outcome_lower for indicator in missed_outcomes)

    @property
    def is_short_duration(self) -> bool:
        """Check if call duration was suspiciously short (likely missed)"""
        if not self.call_record.duration_sec:
            return False

        # Calls under 10 seconds are likely missed/hung up
        return self.call_record.duration_sec < 10

    @property
    def severity(self) -> str:
        """Determine severity of missed call"""
        # High severity if recent (last 24 hours)
        if self.created_at and (datetime.utcnow() - self.created_at) < timedelta(hours=24):
            return 'high'

        # Medium severity if last week
        if self.created_at and (datetime.utcnow() - self.created_at) < timedelta(days=7):
            return 'medium'

        return 'low'

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'id': self.call_record.id,
            'account_id': self.account_id,
            'lead_name': self.lead.name if self.lead else 'Unknown',
            'lead_phone': self.lead.phone if self.lead else None,
            'job_type': self.lead.job_type if self.lead else None,
            'city': self.lead.city if self.lead else None,
            'outcome_label': self.call_record.outcome_label,
            'outcome_reason': self.call_record.outcome_reason,
            'duration_sec': self.call_record.duration_sec,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'severity': self.severity,
            'recording_url': self.call_record.storage_url,
        }


def detect_missed_calls(account_id: int, lookback_hours: int = 24) -> List[MissedCallAlert]:
    """
    Detect missed LSA calls for a given account.

    Args:
        account_id: The account ID to check
        lookback_hours: How many hours back to check (default: 24)

    Returns:
        List of MissedCallAlert objects
    """
    cutoff_time = datetime.utcnow() - timedelta(hours=lookback_hours)

    # Query recent call records
    recent_calls = GLSACallRecord.query.filter(
        and_(
            GLSACallRecord.account_id == account_id,
            GLSACallRecord.created_at >= cutoff_time,
            GLSACallRecord.reviewed == False  # Not yet reviewed
        )
    ).all()

    missed_alerts = []

    for call in recent_calls:
        # Get associated lead
        lead = GLSALead.query.filter_by(id=call.lead_id).first()

        alert = MissedCallAlert(call, lead)

        # Check if this is truly a missed call
        if alert.is_missed or alert.is_short_duration:
            missed_alerts.append(alert)

    logger.info(f"Detected {len(missed_alerts)} missed calls for account {account_id}")
    return missed_alerts


def send_missed_call_notification(
    account_id: int,
    to_email: str,
    missed_calls: List[MissedCallAlert]
) -> bool:
    """
    Send email notification about missed LSA calls.

    Args:
        account_id: The account ID
        to_email: Recipient email address
        missed_calls: List of MissedCallAlert objects

    Returns:
        True if email sent successfully, False otherwise
    """
    if not missed_calls:
        return False

    # Group by severity
    high_severity = [c for c in missed_calls if c.severity == 'high']
    medium_severity = [c for c in missed_calls if c.severity == 'medium']

    # Build email HTML
    html_body = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                color: #333;
                line-height: 1.6;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .header {{
                background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
                color: white;
                padding: 30px;
                border-radius: 8px 8px 0 0;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                font-size: 24px;
            }}
            .content {{
                background: white;
                padding: 30px;
                border: 1px solid #e5e7eb;
                border-top: none;
            }}
            .alert-box {{
                background: #fef2f2;
                border-left: 4px solid #ef4444;
                padding: 15px;
                margin: 20px 0;
                border-radius: 4px;
            }}
            .call-item {{
                background: #f9fafb;
                padding: 15px;
                margin: 10px 0;
                border-radius: 6px;
                border: 1px solid #e5e7eb;
            }}
            .call-header {{
                font-weight: bold;
                color: #1f2937;
                margin-bottom: 8px;
            }}
            .call-detail {{
                font-size: 14px;
                color: #6b7280;
                margin: 4px 0;
            }}
            .severity-high {{
                display: inline-block;
                background: #fee2e2;
                color: #991b1b;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }}
            .cta-button {{
                display: inline-block;
                background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
                color: white;
                padding: 12px 24px;
                text-decoration: none;
                border-radius: 6px;
                font-weight: 600;
                margin: 20px 0;
            }}
            .footer {{
                text-align: center;
                padding: 20px;
                color: #6b7280;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚨 Missed Call Alert - LSA</h1>
                <p style="margin: 10px 0 0 0;">You have {len(missed_calls)} missed call{"s" if len(missed_calls) != 1 else ""} from Google Local Services Ads</p>
            </div>

            <div class="content">
                <div class="alert-box">
                    <strong>⚠️ Action Required:</strong> These potential customers tried to reach you but didn't connect.
                    Follow up ASAP to capture these opportunities!
                </div>
    """

    # Add high severity calls first
    if high_severity:
        html_body += f"""
                <h2 style="color: #dc2626; margin-top: 30px;">🔥 High Priority (Last 24 Hours)</h2>
        """
        for call in high_severity:
            html_body += f"""
                <div class="call-item">
                    <div class="call-header">
                        {call.lead.name if call.lead and call.lead.name else 'Unknown Caller'}
                        <span class="severity-high">HIGH PRIORITY</span>
                    </div>
                    <div class="call-detail">📞 Phone: {call.lead.phone if call.lead and call.lead.phone else 'Not available'}</div>
                    <div class="call-detail">🔧 Job Type: {call.lead.job_type if call.lead and call.lead.job_type else 'Not specified'}</div>
                    <div class="call-detail">📍 Location: {call.lead.city if call.lead and call.lead.city else 'Not specified'}</div>
                    <div class="call-detail">⏱️ Duration: {call.call_record.duration_sec if call.call_record.duration_sec else 0} seconds</div>
                    <div class="call-detail">🚫 Outcome: {call.call_record.outcome_label}</div>
                    <div class="call-detail">📅 Time: {call.created_at.strftime('%B %d, %Y at %I:%M %p') if call.created_at else 'Unknown'}</div>
                </div>
            """

    # Add medium severity calls
    if medium_severity:
        html_body += f"""
                <h2 style="color: #f59e0b; margin-top: 30px;">⚡ Medium Priority (This Week)</h2>
        """
        for call in medium_severity:
            html_body += f"""
                <div class="call-item">
                    <div class="call-header">{call.lead.name if call.lead and call.lead.name else 'Unknown Caller'}</div>
                    <div class="call-detail">📞 Phone: {call.lead.phone if call.lead and call.lead.phone else 'Not available'}</div>
                    <div class="call-detail">🔧 Job Type: {call.lead.job_type if call.lead and call.lead.job_type else 'Not specified'}</div>
                    <div class="call-detail">📍 Location: {call.lead.city if call.lead and call.lead.city else 'Not specified'}</div>
                    <div class="call-detail">⏱️ Duration: {call.call_record.duration_sec if call.call_record.duration_sec else 0} seconds</div>
                    <div class="call-detail">🚫 Outcome: {call.call_record.outcome_label}</div>
                    <div class="call-detail">📅 Time: {call.created_at.strftime('%B %d, %Y at %I:%M %p') if call.created_at else 'Unknown'}</div>
                </div>
            """

    html_body += """
                <div style="text-align: center; margin-top: 30px;">
                    <a href="https://fieldsprout.io/account/google/ads/ai-change-log" class="cta-button">
                        View All Call Details →
                    </a>
                </div>

                <div style="background: #eff6ff; padding: 20px; border-radius: 6px; margin-top: 30px;">
                    <h3 style="margin-top: 0; color: #1e40af;">💡 Pro Tips</h3>
                    <ul style="margin: 0; padding-left: 20px;">
                        <li>Call back within 5 minutes for best results</li>
                        <li>Reference the job type they were calling about</li>
                        <li>Have your calendar ready to schedule immediately</li>
                        <li>If no answer, leave a detailed voicemail and send a follow-up text</li>
                    </ul>
                </div>
            </div>

            <div class="footer">
                <p>This is an automated alert from FieldSprout's AI monitoring system.</p>
                <p style="margin-top: 10px; font-size: 12px;">
                    To stop receiving these alerts, update your notification settings in your dashboard.
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    # Plain text version
    text_body = f"""
    🚨 MISSED CALL ALERT - LSA

    You have {len(missed_calls)} missed call{"s" if len(missed_calls) != 1 else ""} from Google Local Services Ads.

    """

    if high_severity:
        text_body += "\n🔥 HIGH PRIORITY (Last 24 Hours):\n\n"
        for call in high_severity:
            text_body += f"""
            - {call.lead.name if call.lead and call.lead.name else 'Unknown Caller'}
              Phone: {call.lead.phone if call.lead and call.lead.phone else 'Not available'}
              Job Type: {call.lead.job_type if call.lead and call.lead.job_type else 'Not specified'}
              Outcome: {call.call_record.outcome_label}
              Time: {call.created_at.strftime('%B %d, %Y at %I:%M %p') if call.created_at else 'Unknown'}

            """

    text_body += "\nView all details at: https://fieldsprout.io/account/google/ads/ai-change-log"

    # Send email
    try:
        success = send_email(
            to_email=to_email,
            subject=f"🚨 {len(missed_calls)} Missed LSA Call{'s' if len(missed_calls) != 1 else ''} - Follow Up Now!",
            html_body=html_body,
            text_body=text_body
        )

        if success:
            logger.info(f"Sent missed call notification to {to_email} for account {account_id}")
        else:
            logger.error(f"Failed to send missed call notification to {to_email}")

        return success
    except Exception as e:
        logger.exception(f"Error sending missed call notification: {e}")
        return False


def check_and_notify_missed_calls(account_id: int, notification_email: str) -> int:
    """
    Main function to check for missed calls and send notifications.

    Args:
        account_id: The account ID to check
        notification_email: Email address to send alerts to

    Returns:
        Number of missed calls detected
    """
    try:
        # Detect missed calls in last 24 hours
        missed_calls = detect_missed_calls(account_id, lookback_hours=24)

        if missed_calls:
            logger.info(f"Found {len(missed_calls)} missed calls for account {account_id}")

            # Send notification
            send_missed_call_notification(
                account_id=account_id,
                to_email=notification_email,
                missed_calls=missed_calls
            )

            # Mark calls as reviewed (so we don't alert again)
            for alert in missed_calls:
                alert.call_record.reviewed = True

            db.session.commit()

            return len(missed_calls)
        else:
            logger.info(f"No missed calls found for account {account_id}")
            return 0

    except Exception as e:
        logger.exception(f"Error checking missed calls for account {account_id}: {e}")
        db.session.rollback()
        return 0


def get_recent_missed_calls_summary(account_id: int, days: int = 7) -> Dict[str, Any]:
    """
    Get summary of recent missed calls for dashboard display.

    Args:
        account_id: The account ID
        days: Number of days to look back

    Returns:
        Dictionary with summary statistics
    """
    cutoff_time = datetime.utcnow() - timedelta(days=days)

    # Query missed calls
    missed_calls = detect_missed_calls(account_id, lookback_hours=days * 24)

    total_missed = len(missed_calls)
    high_priority = len([c for c in missed_calls if c.severity == 'high'])
    medium_priority = len([c for c in missed_calls if c.severity == 'medium'])

    return {
        'total_missed': total_missed,
        'high_priority': high_priority,
        'medium_priority': medium_priority,
        'missed_calls': [call.to_dict() for call in missed_calls[:10]],  # Latest 10
        'period_days': days,
    }
