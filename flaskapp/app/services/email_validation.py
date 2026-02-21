# app/services/email_validation.py
"""
Central email validation for outreach emails.

Used by EmailDedupService and BrevoOutreachService to reject bad addresses
before they reach Brevo. High bounce rates cause account suspension.

Checks (in order):
  1. Non-empty / basic format (has exactly one @, valid structure)
  2. Consumer/free email domain block (gmail, yahoo, etc.)
  3. Generic/role-based local-part block (info@, admin@, noreply@, etc.)
  4. Minimum local-part and domain sanity
"""
import re
import logging

logger = logging.getLogger(__name__)

# Consumer/free email providers — scraped business contacts should never
# come from these. Sending here risks spam complaints and low engagement.
_FREE_DOMAINS = {
    'gmail.com', 'googlemail.com',
    'yahoo.com', 'yahoo.co.uk', 'yahoo.com.au', 'ymail.com',
    'hotmail.com', 'hotmail.co.uk', 'hotmail.com.au',
    'outlook.com', 'outlook.com.au',
    'live.com', 'live.co.uk',
    'icloud.com', 'me.com', 'mac.com',
    'aol.com', 'msn.com',
    'protonmail.com', 'pm.me',
    'zohomail.com',
}

# Generic role-based local parts — these go to shared inboxes, are rarely
# monitored by a decision-maker, and are common spam traps.
_GENERIC_LOCAL_PARTS = {
    'info', 'information',
    'admin', 'administrator',
    'contact', 'contacts',
    'hello', 'hi',
    'support', 'help', 'helpdesk',
    'sales', 'business',
    'office', 'team',
    'mail', 'email',
    'noreply', 'no-reply', 'no_reply',
    'donotreply', 'do-not-reply', 'do_not_reply',
    'enquiries', 'enquiry', 'enquire',
    'webmaster', 'postmaster',
    'marketing', 'pr',
    'billing', 'accounts', 'accounting', 'invoice', 'invoices',
    'hr', 'recruitment', 'jobs', 'careers',
    'legal', 'compliance',
    'news', 'newsletter',
    'privacy', 'security',
    'abuse', 'spam',
    'feedback',
    'service', 'services',
    'reception', 'general',
    'media',
}

# Minimum acceptable length for the local part (before @)
_MIN_LOCAL_LENGTH = 2


def validate_email_for_outreach(email: str) -> tuple:
    """
    Validate that an email address is safe to send outreach to.

    Returns:
        (valid: bool, reason: str)
        reason is '' when valid, a short error code when invalid.

    Error codes:
        'empty'           — blank or None
        'bad_format'      — fails basic RFC structure check
        'free_domain'     — consumer domain (gmail, yahoo, etc.)
        'generic_local'   — role-based address (info@, admin@, etc.)
        'local_too_short' — local part too short to be a real person
    """
    if not email or not email.strip():
        return False, 'empty'

    email = email.strip().lower()

    # 1. Basic format: one @, non-empty local and domain parts, valid TLD
    pattern = r'^[a-z0-9][a-z0-9._%+\-]*@[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$'
    if not re.match(pattern, email):
        return False, 'bad_format'

    local, domain = email.rsplit('@', 1)

    # 2. Free/consumer email domain
    if domain in _FREE_DOMAINS:
        return False, 'free_domain'

    # 3. Generic role-based local part (exact match or with dots/hyphens stripped)
    normalised_local = re.sub(r'[.\-_]', '', local)
    if local in _GENERIC_LOCAL_PARTS or normalised_local in _GENERIC_LOCAL_PARTS:
        return False, 'generic_local'

    # 4. Local part too short to be a real name
    if len(local) < _MIN_LOCAL_LENGTH:
        return False, 'local_too_short'

    return True, ''


def is_valid_outreach_email(email: str) -> bool:
    """Convenience wrapper — returns bool only."""
    valid, _ = validate_email_for_outreach(email)
    return valid
