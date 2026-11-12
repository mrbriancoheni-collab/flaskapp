"""
Digest send safety layer (Item 3).

Every outbound digest must pass through SafeDigestSender.check() before
any message is sent or any bid is changed.

Checks in order:
  1. Number-check gate    — block if digest contains invented numbers
  2. Idempotency gate     — one send per (account, date, channel)
  3. Circuit breaker      — pause after CIRCUIT_TRIP_FAILURES consecutive failures
  4. AI spend cap         — per-tenant monthly cap in cents
  5. Approval gate        — queue for human review when:
                             • first N digests for a new tenant
                             • confidence below LOW_CONFIDENCE_THRESHOLD
                             • recommended_action contains a money change

After all gates pass, callers call record_outcome() to update the breaker
and send log.

Usage:
    from app.services.digest_send_safety import SafeDigestSender

    safety = SafeDigestSender(account_id, channel="sms")
    ok, reason, approval_id = safety.check(structured_digest, digest_date)
    if ok:
        # ... send ...
        safety.record_outcome(success=True, digest_date=digest_date,
                              channel="sms", recipient=phone,
                              confidence=structured_digest["confidence"])
    else:
        safety.record_outcome(success=False, digest_date=digest_date,
                              channel="sms", recipient="",
                              blocked_reason=reason,
                              confidence=structured_digest.get("confidence"))
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text

log = logging.getLogger(__name__)

# ── Tunable constants ─────────────────────────────────────────────────────────
CIRCUIT_TRIP_FAILURES: int = 3        # consecutive failures before tripping
CIRCUIT_COOLDOWN_SECONDS: int = 86400  # 24 h default cooldown
NEW_TENANT_APPROVAL_SENDS: int = 2     # first N sends require approval
LOW_CONFIDENCE_THRESHOLD: float = 0.60
MONEY_CHANGE_PATTERN = re.compile(
    r'\b(increase|raise|add|boost|spend|budget|invest)\b.*\$|\$.*\b(increase|raise|add|boost)\b',
    re.IGNORECASE,
)


# ── Safety result ─────────────────────────────────────────────────────────────

class SafetyResult:
    """Returned by SafeDigestSender.check()."""

    def __init__(self, allowed: bool, reason: str = "", approval_id: Optional[int] = None):
        self.allowed = allowed
        self.reason = reason
        self.approval_id = approval_id  # set when queued for approval

    def __bool__(self):
        return self.allowed

    def __repr__(self):
        return f"SafetyResult(allowed={self.allowed}, reason={self.reason!r})"


# ── SafeDigestSender ──────────────────────────────────────────────────────────

class SafeDigestSender:
    """
    Stateless helper (all state is in DB).  One instance per send attempt.
    """

    def __init__(self, account_id: int, channel: str = "sms"):
        self.account_id = account_id
        self.channel = channel

    # ── Public API ────────────────────────────────────────────────────────────

    def check(
        self,
        structured_digest: Dict[str, Any],
        digest_date: date,
        estimated_ai_cost_cents: int = 0,
    ) -> SafetyResult:
        """
        Run all safety checks.  Returns SafetyResult(allowed=True) if the
        digest can be sent immediately, or SafetyResult(allowed=False) with
        a reason.  When approval is required, the row is inserted into
        digest_approval_queue and approval_id is set.
        """
        # 1. Number-check gate (never send invented numbers)
        if structured_digest.get("blocked"):
            return SafetyResult(
                False,
                f"number_check_failed: {structured_digest.get('blocking_reason', '')}",
            )

        # 2. Idempotency
        ok, idem_reason = self._check_idempotent(digest_date)
        if not ok:
            return SafetyResult(False, idem_reason)

        # 3. Circuit breaker
        ok, cb_reason = self._check_circuit_breaker()
        if not ok:
            return SafetyResult(False, cb_reason)

        # 4. AI spend cap
        if estimated_ai_cost_cents > 0:
            ok, cap_reason = self._check_ai_spend_cap(estimated_ai_cost_cents)
            if not ok:
                return SafetyResult(False, cap_reason)

        # 5. Approval gate
        needs, approval_reason = self._needs_approval(structured_digest, digest_date)
        if needs:
            aid = self._queue_for_approval(structured_digest, digest_date, approval_reason)
            return SafetyResult(
                False,
                f"approval_required:{approval_reason}",
                approval_id=aid,
            )

        return SafetyResult(True)

    def record_outcome(
        self,
        success: bool,
        digest_date: date,
        channel: str,
        recipient: str,
        blocked_reason: str = "",
        confidence: Optional[float] = None,
    ) -> None:
        """
        Write to digest_send_log and update the circuit breaker.
        Call once after every send attempt (success or failure).
        """
        from app import db
        status = "sent" if success else ("failed" if not blocked_reason else _status_from_reason(blocked_reason))
        try:
            db.session.execute(text("""
                INSERT IGNORE INTO digest_send_log
                    (account_id, digest_date, channel, recipient, status, blocked_reason, confidence)
                VALUES (:aid, :dt, :ch, :rec, :st, :br, :conf)
            """), {
                "aid": self.account_id,
                "dt": str(digest_date),
                "ch": channel,
                "rec": recipient or "",
                "st": status,
                "br": blocked_reason or None,
                "conf": float(confidence) if confidence is not None else None,
            })
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception("digest_send_log write failed for account %d", self.account_id)

        if success:
            self._reset_circuit_breaker()
        elif not blocked_reason:
            # Only count delivery failures (not blocks) toward the breaker
            self._increment_circuit_breaker()

    # ── Idempotency ───────────────────────────────────────────────────────────

    def _check_idempotent(self, digest_date: date) -> Tuple[bool, str]:
        from app import db
        try:
            row = db.session.execute(text("""
                SELECT status FROM digest_send_log
                WHERE account_id=:aid AND digest_date=:dt AND channel=:ch
                LIMIT 1
            """), {"aid": self.account_id, "dt": str(digest_date), "ch": self.channel}).fetchone()
            if row and row[0] == "sent":
                return False, f"blocked_idempotent: already sent for {digest_date}/{self.channel}"
        except Exception:
            db.session.rollback()
        return True, ""

    # ── Circuit breaker ───────────────────────────────────────────────────────

    def _check_circuit_breaker(self) -> Tuple[bool, str]:
        from app import db
        try:
            row = db.session.execute(text("""
                SELECT consecutive_failures, tripped_at, cooldown_seconds
                FROM digest_circuit_breaker
                WHERE account_id=:aid
            """), {"aid": self.account_id}).fetchone()
            if row and row[1]:  # tripped_at is set
                tripped_at = row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(str(row[1]))
                cooldown = int(row[2] or CIRCUIT_COOLDOWN_SECONDS)
                resume_at = tripped_at + timedelta(seconds=cooldown)
                if datetime.utcnow() < resume_at:
                    return False, (
                        f"blocked_circuit: breaker tripped after {row[0]} failures at {tripped_at.isoformat()}; "
                        f"resumes at {resume_at.isoformat()}"
                    )
                # Cooldown has passed — auto-reset
                self._reset_circuit_breaker()
        except Exception:
            db.session.rollback()
        return True, ""

    def _increment_circuit_breaker(self) -> None:
        from app import db
        try:
            db.session.execute(text("""
                INSERT INTO digest_circuit_breaker (account_id, consecutive_failures, cooldown_seconds)
                VALUES (:aid, 1, :cd)
                ON DUPLICATE KEY UPDATE
                    consecutive_failures = consecutive_failures + 1,
                    tripped_at = IF(consecutive_failures + 1 >= :trip, UTC_TIMESTAMP(), tripped_at)
            """), {
                "aid": self.account_id,
                "cd": CIRCUIT_COOLDOWN_SECONDS,
                "trip": CIRCUIT_TRIP_FAILURES,
            })
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception("circuit breaker increment failed for account %d", self.account_id)

    def _reset_circuit_breaker(self) -> None:
        from app import db
        try:
            db.session.execute(text("""
                INSERT INTO digest_circuit_breaker (account_id, consecutive_failures)
                VALUES (:aid, 0)
                ON DUPLICATE KEY UPDATE
                    consecutive_failures = 0,
                    tripped_at = NULL
            """), {"aid": self.account_id})
            db.session.commit()
        except Exception:
            db.session.rollback()

    # ── AI spend cap ──────────────────────────────────────────────────────────

    def _check_ai_spend_cap(self, cost_cents: int) -> Tuple[bool, str]:
        from app import db
        period = datetime.utcnow().strftime("%Y-%m")
        try:
            row = db.session.execute(text("""
                SELECT spend_cents, cap_cents
                FROM digest_ai_spend
                WHERE account_id=:aid AND period=:p
            """), {"aid": self.account_id, "p": period}).fetchone()
            if row:
                used = int(row[0] or 0)
                cap  = int(row[1] or 500)  # $5.00 default
                if used + cost_cents > cap:
                    return False, (
                        f"blocked_cap: AI spend cap reached for {period} "
                        f"(used={used}c + this={cost_cents}c > cap={cap}c)"
                    )
        except Exception:
            db.session.rollback()
        return True, ""

    def record_ai_spend(self, cost_cents: int) -> None:
        from app import db
        period = datetime.utcnow().strftime("%Y-%m")
        try:
            db.session.execute(text("""
                INSERT INTO digest_ai_spend (account_id, period, spend_cents, cap_cents)
                VALUES (:aid, :p, :c, 500)
                ON DUPLICATE KEY UPDATE spend_cents = spend_cents + VALUES(spend_cents)
            """), {"aid": self.account_id, "p": period, "c": cost_cents})
            db.session.commit()
        except Exception:
            db.session.rollback()

    # ── Approval gate ─────────────────────────────────────────────────────────

    def _needs_approval(
        self,
        structured: Dict[str, Any],
        digest_date: date,
    ) -> Tuple[bool, str]:
        """
        Returns (needs_approval, reason_slug).  Checks in priority order.
        """
        # 1. First N digests for a new tenant
        if self._is_new_tenant():
            return True, "first_digest"

        # 2. Low confidence
        confidence = float(structured.get("confidence") or 0)
        if confidence < LOW_CONFIDENCE_THRESHOLD:
            return True, "low_confidence"

        # 3. Money changes in recommended_action
        action = structured.get("recommended_action") or ""
        if MONEY_CHANGE_PATTERN.search(action):
            return True, "money_change"

        return False, ""

    def _is_new_tenant(self) -> bool:
        from app import db
        try:
            row = db.session.execute(text("""
                SELECT COUNT(*) FROM digest_send_log
                WHERE account_id=:aid AND status='sent'
            """), {"aid": self.account_id}).scalar()
            return int(row or 0) < NEW_TENANT_APPROVAL_SENDS
        except Exception:
            db.session.rollback()
        return False  # fail open to avoid blocking established tenants on DB errors

    def _queue_for_approval(
        self,
        structured: Dict[str, Any],
        digest_date: date,
        reason: str,
    ) -> Optional[int]:
        from app import db
        try:
            safe_json = json.dumps(structured, default=str)
            result = db.session.execute(text("""
                INSERT IGNORE INTO digest_approval_queue
                    (account_id, digest_date, channel, reason, status, structured_json, confidence)
                VALUES (:aid, :dt, :ch, :reason, 'pending', :sj, :conf)
            """), {
                "aid":    self.account_id,
                "dt":     str(digest_date),
                "ch":     self.channel,
                "reason": reason,
                "sj":     safe_json,
                "conf":   structured.get("confidence"),
            })
            db.session.commit()
            return result.lastrowid or None
        except Exception:
            db.session.rollback()
            log.exception("approval queue insert failed for account %d", self.account_id)
        return None


# ── Helper ────────────────────────────────────────────────────────────────────

def _status_from_reason(reason: str) -> str:
    if "idempotent" in reason:
        return "blocked_idempotent"
    if "circuit" in reason:
        return "blocked_circuit"
    if "approval" in reason:
        return "blocked_approval"
    if "cap" in reason:
        return "blocked_cap"
    if "number_check" in reason:
        return "blocked_number_check"
    return "failed"


# ── Convenience wrapper used by send_weekly_digest_all_accounts ───────────────

def safe_send_check(
    account_id: int,
    channel: str,
    structured_digest: Dict[str, Any],
    digest_date: date,
    estimated_ai_cost_cents: int = 0,
) -> SafetyResult:
    """One-call wrapper for the common case."""
    sender = SafeDigestSender(account_id, channel)
    return sender.check(structured_digest, digest_date, estimated_ai_cost_cents)
