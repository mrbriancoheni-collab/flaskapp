# app/services/email_dedup_service.py
"""
Global Email Deduplication Service

Provides case-insensitive email deduplication checks before sending any email.
Prevents sending duplicate emails to the same address across all campaigns and sequences.

Usage:
    from app.services.email_dedup_service import EmailDedupService

    dedup = EmailDedupService()

    # Before sending any email:
    if dedup.can_send_to(email, sequence_step=1):
        # Send email
        ...
    else:
        logger.info(f"Skipping {email} - already sent this sequence step")
"""
import logging
from typing import Optional, List, Set, Tuple
from datetime import datetime, timedelta
from sqlalchemy import func

from app.extensions import db

logger = logging.getLogger(__name__)


class EmailDedupService:
    """
    Centralized email deduplication service.

    Performs case-insensitive checks against:
    - lead_contact_emails table (main outreach emails)
    - lead_emails_sent table (legacy emails)
    - email_unsubscribes table (unsubscribed addresses)
    """

    def __init__(self):
        self._unsubscribed_cache: Optional[Set[str]] = None
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)  # Refresh cache every 5 minutes

    def _get_unsubscribed_emails(self) -> Set[str]:
        """
        Get set of unsubscribed email addresses (lowercase).
        Uses caching to reduce DB queries.
        """
        now = datetime.utcnow()

        # Check if cache is valid
        if (self._unsubscribed_cache is not None and
            self._cache_time is not None and
            now - self._cache_time < self._cache_ttl):
            return self._unsubscribed_cache

        # Refresh cache
        try:
            from app.models_leads import EmailUnsubscribe

            unsubscribed = db.session.query(
                func.lower(EmailUnsubscribe.email)
            ).all()

            self._unsubscribed_cache = {email[0] for email in unsubscribed}
            self._cache_time = now

            logger.debug(f"Refreshed unsubscribe cache: {len(self._unsubscribed_cache)} addresses")
            return self._unsubscribed_cache

        except Exception as e:
            logger.error(f"Error fetching unsubscribe list: {e}")
            return set()

    def is_unsubscribed(self, email: str) -> bool:
        """
        Check if email address is unsubscribed (case-insensitive).

        Args:
            email: Email address to check

        Returns:
            True if unsubscribed, False otherwise
        """
        if not email:
            return False
        return email.lower().strip() in self._get_unsubscribed_emails()

    def has_received_sequence_step(
        self,
        email: str,
        sequence_step: int,
        contact_id: Optional[int] = None
    ) -> bool:
        """
        Check if email address has already received a specific sequence step (case-insensitive).

        Args:
            email: Email address to check
            sequence_step: The sequence step number (1, 2, 3, etc.)
            contact_id: Optional contact ID for more specific check

        Returns:
            True if already sent, False otherwise
        """
        if not email:
            return False

        email_lower = email.lower().strip()

        try:
            from app.models_leads import LeadContactEmail, LeadEmail

            # Check LeadContactEmail table (primary) - case-insensitive
            query = db.session.query(LeadContactEmail).filter(
                func.lower(LeadContactEmail.to_email) == email_lower,
                LeadContactEmail.sequence_step == sequence_step
            )

            if contact_id:
                query = query.filter(LeadContactEmail.contact_id == contact_id)

            if query.first():
                return True

            # Also check legacy LeadEmail table for step 1 (they don't have sequence_step)
            if sequence_step == 1:
                legacy_exists = db.session.query(LeadEmail).filter(
                    func.lower(LeadEmail.to_email) == email_lower
                ).first()
                if legacy_exists:
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking email history for {email}: {e}")
            # On error, return True to prevent potential duplicate
            return True

    def has_received_any_email(self, email: str) -> bool:
        """
        Check if email address has received ANY email (case-insensitive).

        Args:
            email: Email address to check

        Returns:
            True if any email was sent, False otherwise
        """
        if not email:
            return False

        email_lower = email.lower().strip()

        try:
            from app.models_leads import LeadContactEmail, LeadEmail

            # Check LeadContactEmail table
            if db.session.query(LeadContactEmail).filter(
                func.lower(LeadContactEmail.to_email) == email_lower
            ).first():
                return True

            # Check legacy LeadEmail table
            if db.session.query(LeadEmail).filter(
                func.lower(LeadEmail.to_email) == email_lower
            ).first():
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking email history for {email}: {e}")
            return True  # Return True on error to prevent duplicates

    def can_send_to(
        self,
        email: str,
        sequence_step: int = 1,
        contact_id: Optional[int] = None,
        check_unsubscribed: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if we can send an email to this address (case-insensitive).

        This is the primary method to call before sending any email.

        Args:
            email: Email address to check
            sequence_step: The sequence step number (default: 1)
            contact_id: Optional contact ID for more specific check
            check_unsubscribed: Whether to check unsubscribe list (default: True)

        Returns:
            Tuple of (can_send: bool, reason: Optional[str])
            - (True, None) if email can be sent
            - (False, "reason") if email should not be sent
        """
        if not email or not email.strip():
            return False, "invalid_email"

        email = email.strip()

        # Check unsubscribe list
        if check_unsubscribed and self.is_unsubscribed(email):
            logger.debug(f"Email {email} is unsubscribed")
            return False, "unsubscribed"

        # Check if already received this sequence step
        if self.has_received_sequence_step(email, sequence_step, contact_id):
            logger.debug(f"Email {email} already received sequence step {sequence_step}")
            return False, "already_sent_step"

        return True, None

    def get_unsent_emails(
        self,
        emails: List[str],
        sequence_step: int = 1
    ) -> List[str]:
        """
        Filter a list of emails to only those who haven't received the sequence step.

        Args:
            emails: List of email addresses
            sequence_step: The sequence step to check

        Returns:
            List of email addresses that haven't received this step
        """
        result = []
        for email in emails:
            can_send, _ = self.can_send_to(email, sequence_step)
            if can_send:
                result.append(email)
        return result

    def get_sent_stats(self, email: str) -> dict:
        """
        Get statistics about emails sent to this address.

        Args:
            email: Email address to check

        Returns:
            Dict with send statistics
        """
        if not email:
            return {"total_sent": 0, "steps_sent": []}

        email_lower = email.lower().strip()

        try:
            from app.models_leads import LeadContactEmail, LeadEmail

            # Get all LeadContactEmail records
            contact_emails = db.session.query(LeadContactEmail).filter(
                func.lower(LeadContactEmail.to_email) == email_lower
            ).all()

            # Get legacy emails
            legacy_count = db.session.query(LeadEmail).filter(
                func.lower(LeadEmail.to_email) == email_lower
            ).count()

            steps_sent = sorted(set(e.sequence_step for e in contact_emails))

            return {
                "total_sent": len(contact_emails) + legacy_count,
                "steps_sent": steps_sent,
                "legacy_count": legacy_count,
                "is_unsubscribed": self.is_unsubscribed(email)
            }

        except Exception as e:
            logger.error(f"Error getting send stats for {email}: {e}")
            return {"total_sent": 0, "steps_sent": [], "error": str(e)}

    def clear_cache(self):
        """Clear the unsubscribe cache to force refresh."""
        self._unsubscribed_cache = None
        self._cache_time = None
        logger.debug("Cleared email dedup cache")


# Global instance for convenience
_dedup_service: Optional[EmailDedupService] = None


def get_dedup_service() -> EmailDedupService:
    """Get or create the global EmailDedupService instance."""
    global _dedup_service
    if _dedup_service is None:
        _dedup_service = EmailDedupService()
    return _dedup_service


def can_send_email(
    email: str,
    sequence_step: int = 1,
    contact_id: Optional[int] = None
) -> Tuple[bool, Optional[str]]:
    """
    Convenience function to check if we can send email to an address.

    Uses global EmailDedupService instance.

    Args:
        email: Email address to check
        sequence_step: The sequence step number (default: 1)
        contact_id: Optional contact ID

    Returns:
        Tuple of (can_send: bool, reason: Optional[str])
    """
    return get_dedup_service().can_send_to(email, sequence_step, contact_id)
