# app/services/email_verification.py
"""
Email Verification Service

Verifies email deliverability using multiple providers:
- Hunter.io Email Verifier
- NeverBounce
- ZeroBounce
- Abstract API
- Fallback regex validation

Returns: valid, risky, invalid, catch-all, unknown
"""
import os
import re
import logging
import requests
from typing import Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class EmailStatus(Enum):
    """Email verification status"""
    VALID = "valid"              # Safe to send
    RISKY = "risky"              # Might bounce, use with caution
    INVALID = "invalid"          # Will bounce, don't send
    CATCH_ALL = "catch_all"      # Domain accepts all emails
    UNKNOWN = "unknown"          # Cannot verify
    DISPOSABLE = "disposable"    # Temporary/disposable email


class EmailVerificationService:
    """Verify email deliverability using multiple providers"""

    def __init__(self):
        # API keys for different providers
        self.hunter_key = os.getenv('HUNTER_API_KEY')
        self.neverbounce_key = os.getenv('NEVERBOUNCE_API_KEY')
        self.zerobounce_key = os.getenv('ZEROBOUNCE_API_KEY')
        self.abstract_key = os.getenv('ABSTRACTAPI_KEY')

    def verify_email(self, email: str) -> Dict:
        """
        Verify email deliverability using waterfall approach

        Tries providers in order until one succeeds:
        1. Hunter.io (most accurate for business emails)
        2. NeverBounce (good for bulk verification)
        3. ZeroBounce (comprehensive checks)
        4. Abstract API (free tier available)
        5. Regex validation (fallback)

        Returns:
            {
                'email': str,
                'status': EmailStatus,
                'score': int (0-100),
                'is_disposable': bool,
                'is_role_based': bool,
                'is_free_provider': bool,
                'provider': str,
                'reason': str
            }
        """
        if not email or '@' not in email:
            return self._invalid_result(email, "Invalid email format")

        # Try Hunter.io first (best for business emails)
        if self.hunter_key:
            result = self._verify_hunter(email)
            if result['status'] != EmailStatus.UNKNOWN:
                return result

        # Try NeverBounce second
        if self.neverbounce_key:
            result = self._verify_neverbounce(email)
            if result['status'] != EmailStatus.UNKNOWN:
                return result

        # Try ZeroBounce third
        if self.zerobounce_key:
            result = self._verify_zerobounce(email)
            if result['status'] != EmailStatus.UNKNOWN:
                return result

        # Try Abstract API fourth (free tier)
        if self.abstract_key:
            result = self._verify_abstract(email)
            if result['status'] != EmailStatus.UNKNOWN:
                return result

        # Fallback to regex validation
        return self._verify_regex(email)

    def _verify_hunter(self, email: str) -> Dict:
        """Verify email using Hunter.io Email Verifier"""
        try:
            response = requests.get(
                'https://api.hunter.io/v2/email-verifier',
                params={'email': email, 'api_key': self.hunter_key},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if 'data' not in data:
                return self._unknown_result(email, "Hunter.io: No data returned")

            result = data['data']
            score = result.get('score', 0)

            # Map Hunter status to our enum
            hunter_status = result.get('status', 'unknown')
            status_map = {
                'valid': EmailStatus.VALID,
                'invalid': EmailStatus.INVALID,
                'accept_all': EmailStatus.CATCH_ALL,
                'webmail': EmailStatus.VALID,
                'disposable': EmailStatus.DISPOSABLE,
                'unknown': EmailStatus.UNKNOWN
            }

            status = status_map.get(hunter_status, EmailStatus.UNKNOWN)

            # If score is low, downgrade to risky
            if status == EmailStatus.VALID and score < 50:
                status = EmailStatus.RISKY

            return {
                'email': email,
                'status': status,
                'score': score,
                'is_disposable': result.get('disposable', False),
                'is_role_based': result.get('role', False),
                'is_free_provider': result.get('webmail', False),
                'provider': 'hunter',
                'reason': result.get('result', 'Unknown'),
                'mx_records': result.get('mx_records', False),
                'smtp_check': result.get('smtp_check', False)
            }

        except Exception as e:
            logger.error(f"Hunter.io verification error: {e}")
            return self._unknown_result(email, f"Hunter.io error: {str(e)}")

    def _verify_neverbounce(self, email: str) -> Dict:
        """Verify email using NeverBounce"""
        try:
            response = requests.get(
                'https://api.neverbounce.com/v4/single/check',
                params={'key': self.neverbounce_key, 'email': email},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            result = data.get('result', 'unknown')

            # Map NeverBounce status to our enum
            status_map = {
                'valid': EmailStatus.VALID,
                'invalid': EmailStatus.INVALID,
                'disposable': EmailStatus.DISPOSABLE,
                'catchall': EmailStatus.CATCH_ALL,
                'unknown': EmailStatus.UNKNOWN
            }

            status = status_map.get(result, EmailStatus.UNKNOWN)

            # Calculate score based on flags
            flags = data.get('flags', [])
            score = 100
            if 'has_dns' not in flags:
                score -= 30
            if 'has_dns_mx' not in flags:
                score -= 20
            if 'smtp_connectable' not in flags:
                score -= 20

            return {
                'email': email,
                'status': status,
                'score': max(0, score),
                'is_disposable': result == 'disposable',
                'is_role_based': 'role_account' in flags,
                'is_free_provider': 'free_email' in flags,
                'provider': 'neverbounce',
                'reason': result,
                'flags': flags
            }

        except Exception as e:
            logger.error(f"NeverBounce verification error: {e}")
            return self._unknown_result(email, f"NeverBounce error: {str(e)}")

    def _verify_zerobounce(self, email: str) -> Dict:
        """Verify email using ZeroBounce"""
        try:
            response = requests.get(
                'https://api.zerobounce.net/v2/validate',
                params={'api_key': self.zerobounce_key, 'email': email},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            result = data.get('status', 'unknown')

            # Map ZeroBounce status to our enum
            status_map = {
                'valid': EmailStatus.VALID,
                'invalid': EmailStatus.INVALID,
                'catch-all': EmailStatus.CATCH_ALL,
                'spamtrap': EmailStatus.INVALID,
                'abuse': EmailStatus.INVALID,
                'do_not_mail': EmailStatus.INVALID,
                'unknown': EmailStatus.UNKNOWN
            }

            status = status_map.get(result, EmailStatus.UNKNOWN)

            # ZeroBounce provides a score from -2 to 10
            zb_score = data.get('sub_status', 0)
            score = min(100, max(0, (zb_score + 2) * 10))  # Normalize to 0-100

            return {
                'email': email,
                'status': status,
                'score': score,
                'is_disposable': data.get('disposable', False),
                'is_role_based': data.get('role_based', False),
                'is_free_provider': data.get('free_email', False),
                'provider': 'zerobounce',
                'reason': result,
                'mx_record': data.get('mx_record', ''),
                'did_you_mean': data.get('did_you_mean')  # Suggested correction
            }

        except Exception as e:
            logger.error(f"ZeroBounce verification error: {e}")
            return self._unknown_result(email, f"ZeroBounce error: {str(e)}")

    def _verify_abstract(self, email: str) -> Dict:
        """Verify email using Abstract API (free tier available)"""
        try:
            response = requests.get(
                'https://emailvalidation.abstractapi.com/v1/',
                params={'api_key': self.abstract_key, 'email': email},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            # Abstract uses quality_score (0-1)
            quality = data.get('quality_score', 0)
            score = int(quality * 100)

            # Determine status based on checks
            is_deliverable = data.get('deliverability') == 'DELIVERABLE'
            is_valid_format = data.get('is_valid_format', {}).get('value', False)
            is_disposable = data.get('is_disposable_email', {}).get('value', False)
            is_catchall = data.get('is_catchall_email', {}).get('value', False)

            if not is_valid_format:
                status = EmailStatus.INVALID
            elif is_disposable:
                status = EmailStatus.DISPOSABLE
            elif is_catchall:
                status = EmailStatus.CATCH_ALL
            elif is_deliverable:
                status = EmailStatus.VALID if score >= 70 else EmailStatus.RISKY
            else:
                status = EmailStatus.RISKY

            return {
                'email': email,
                'status': status,
                'score': score,
                'is_disposable': is_disposable,
                'is_role_based': data.get('is_role_email', {}).get('value', False),
                'is_free_provider': data.get('is_free_email', {}).get('value', False),
                'provider': 'abstract',
                'reason': data.get('deliverability', 'Unknown'),
                'autocorrect': data.get('autocorrect')  # Suggested correction
            }

        except Exception as e:
            logger.error(f"Abstract API verification error: {e}")
            return self._unknown_result(email, f"Abstract API error: {str(e)}")

    def _verify_regex(self, email: str) -> Dict:
        """Fallback: Verify email using regex pattern matching"""
        # RFC 5322 compliant regex (simplified)
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

        is_valid_format = re.match(pattern, email) is not None

        if not is_valid_format:
            return self._invalid_result(email, "Invalid email format")

        # Check for disposable domains (common ones)
        disposable_domains = [
            'tempmail.com', 'guerrillamail.com', 'mailinator.com', '10minutemail.com',
            'throwaway.email', 'temp-mail.org', 'getnada.com', 'maildrop.cc'
        ]

        domain = email.split('@')[1].lower()
        is_disposable = domain in disposable_domains

        # Check for role-based emails
        local_part = email.split('@')[0].lower()
        role_keywords = ['info', 'admin', 'support', 'sales', 'contact', 'noreply', 'no-reply']
        is_role_based = any(keyword in local_part for keyword in role_keywords)

        # Check for free providers
        free_providers = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com']
        is_free = domain in free_providers

        # Assign status based on checks
        if is_disposable:
            status = EmailStatus.DISPOSABLE
        elif is_valid_format:
            status = EmailStatus.RISKY  # Can't verify deliverability without API
        else:
            status = EmailStatus.INVALID

        return {
            'email': email,
            'status': status,
            'score': 50 if is_valid_format else 0,  # Medium score for regex-only validation
            'is_disposable': is_disposable,
            'is_role_based': is_role_based,
            'is_free_provider': is_free,
            'provider': 'regex',
            'reason': 'Format validation only - deliverability not verified'
        }

    def _invalid_result(self, email: str, reason: str) -> Dict:
        """Return invalid email result"""
        return {
            'email': email,
            'status': EmailStatus.INVALID,
            'score': 0,
            'is_disposable': False,
            'is_role_based': False,
            'is_free_provider': False,
            'provider': 'validation',
            'reason': reason
        }

    def _unknown_result(self, email: str, reason: str) -> Dict:
        """Return unknown email result"""
        return {
            'email': email,
            'status': EmailStatus.UNKNOWN,
            'score': 50,
            'is_disposable': False,
            'is_role_based': False,
            'is_free_provider': False,
            'provider': 'unknown',
            'reason': reason
        }

    def should_send_email(self, verification_result: Dict) -> bool:
        """
        Determine if email should be sent based on verification result

        Safe to send: VALID
        Risky but send: RISKY, CATCH_ALL (with high score)
        Don't send: INVALID, DISPOSABLE, UNKNOWN (low score)
        """
        status = verification_result.get('status')
        score = verification_result.get('score', 0)

        if status == EmailStatus.VALID:
            return True
        elif status == EmailStatus.RISKY and score >= 60:
            return True
        elif status == EmailStatus.CATCH_ALL and score >= 50:
            return True
        else:
            return False
