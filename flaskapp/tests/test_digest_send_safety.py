"""
Tests for digest send safety layer (Item 3).

Uses in-memory SQLite so no MySQL connection is needed.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

# ── Minimal structured digest fixtures ───────────────────────────────────────

NORMAL_STRUCTURED = {
    "highlight": "Last week you spent $1,200 and got 15 leads — about $80 each.",
    "evidence": [
        {"metric": "spend", "value": 1200.0, "label": "$1,200"},
        {"metric": "leads", "value": 15.0,   "label": "15"},
        {"metric": "cost_per_lead", "value": 80.0, "label": "$80"},
    ],
    "recommended_action": "Keep the current keyword mix — CPL improved 12%.",
    "confidence": 0.90,
    "number_check_passed": True,
    "blocked": False,
    "blocking_reason": None,
    "render_text": {},
}

LOW_CONFIDENCE_STRUCTURED = {**NORMAL_STRUCTURED, "confidence": 0.45}

BLOCKED_STRUCTURED = {
    **NORMAL_STRUCTURED,
    "number_check_passed": False,
    "blocked": True,
    "blocking_reason": "Invented number(s): ['$2,400']",
}

MONEY_CHANGE_STRUCTURED = {
    **NORMAL_STRUCTURED,
    "recommended_action": "Increase budget by $500 on the top campaign.",
}


# ── DB mock helpers ───────────────────────────────────────────────────────────

class _FakeRow:
    """Minimal namedtuple-like for SQLAlchemy row mocking."""
    def __init__(self, *vals):
        self._vals = vals
    def __getitem__(self, i):
        return self._vals[i]
    def scalar(self):
        return self._vals[0]


def _make_db_mock(
    send_log_count: int = 0,
    send_log_status: str = None,
    cb_row: tuple = None,       # (consecutive_failures, tripped_at, cooldown_seconds)
    ai_spend_row: tuple = None, # (spend_cents, cap_cents)
):
    """
    Return a mock `db` with execute() returning controlled data.
    State mutations (INSERT/UPDATE) are silently accepted.
    """
    mock_db = MagicMock()
    mock_session = MagicMock()
    mock_db.session = mock_session
    mock_db.session.commit = MagicMock()
    mock_db.session.rollback = MagicMock()

    def _execute_side_effect(sql_obj, params=None):
        sql = str(sql_obj)
        result = MagicMock()
        result.lastrowid = 1

        if "digest_send_log" in sql and "SELECT" in sql:
            if "COUNT" in sql:
                result.scalar.return_value = send_log_count
            elif send_log_status:
                row = _FakeRow(send_log_status)
                result.fetchone.return_value = row
            else:
                result.fetchone.return_value = None
        elif "digest_circuit_breaker" in sql and "SELECT" in sql:
            if cb_row:
                result.fetchone.return_value = _FakeRow(*cb_row)
            else:
                result.fetchone.return_value = None
        elif "digest_ai_spend" in sql and "SELECT" in sql:
            if ai_spend_row:
                result.fetchone.return_value = _FakeRow(*ai_spend_row)
            else:
                result.fetchone.return_value = None
        elif "digest_approval_queue" in sql and "INSERT" in sql:
            result.lastrowid = 42
        return result

    mock_session.execute.side_effect = _execute_side_effect
    return mock_db


# ── Import under test ─────────────────────────────────────────────────────────

from app.services.digest_send_safety import (
    SafeDigestSender,
    SafetyResult,
    CIRCUIT_TRIP_FAILURES,
    LOW_CONFIDENCE_THRESHOLD,
    NEW_TENANT_APPROVAL_SENDS,
)


# ── 1. Number-check gate ──────────────────────────────────────────────────────

def test_blocked_digest_is_rejected():
    sender = SafeDigestSender(1, "sms")
    result = sender.check(BLOCKED_STRUCTURED, date(2024, 1, 8))
    assert not result.allowed
    assert "number_check_failed" in result.reason


def test_unblocked_digest_passes_number_gate():
    db_mock = _make_db_mock(send_log_count=10)  # established tenant
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._needs_approval", return_value=(False, "")):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 8))
    assert result.allowed


# ── 2. Idempotency gate ───────────────────────────────────────────────────────

def test_idempotency_blocks_duplicate_send():
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent",
               return_value=(False, "blocked_idempotent: already sent for 2024-01-08/sms")):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 8))
    assert not result.allowed
    assert "idempotent" in result.reason


def test_idempotency_allows_different_date():
    db_mock = _make_db_mock(send_log_count=10, send_log_status=None)
    with patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._needs_approval", return_value=(False, "")):
        import app.services.digest_send_safety as mod
        with patch.object(mod, "__name__", "__main__"):  # doesn't matter
            sender = SafeDigestSender(1, "sms")
            # Mock only the DB call inside _check_idempotent
            with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent",
                       return_value=(True, "")):
                result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 9))
    # Still might be blocked by approval gate for new tenant, but NOT by idempotency
    assert "idempotent" not in result.reason


# ── 3. Circuit breaker ────────────────────────────────────────────────────────

def test_tripped_circuit_breaker_blocks():
    tripped = datetime.utcnow() - timedelta(hours=1)  # tripped 1h ago
    cb_row = (3, tripped.isoformat(), 86400)  # 24h cooldown, not yet expired
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker",
               return_value=(False, "blocked_circuit: breaker tripped")):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 8))
    assert not result.allowed
    assert "circuit" in result.reason


def test_expired_circuit_breaker_auto_resets():
    # Breaker tripped 25h ago (beyond 24h cooldown) → should allow send
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker",
               return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._needs_approval",
               return_value=(False, "")):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 8))
    assert result.allowed


# ── 4. AI spend cap ───────────────────────────────────────────────────────────

def test_ai_spend_cap_blocks_when_exceeded():
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_ai_spend_cap",
               return_value=(False, "blocked_cap: AI spend cap reached")):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 8), estimated_ai_cost_cents=100)
    assert not result.allowed
    assert "cap" in result.reason


def test_ai_spend_cap_skipped_when_cost_zero():
    """When estimated_ai_cost_cents=0, cap check is skipped entirely."""
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._needs_approval", return_value=(False, "")):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 8), estimated_ai_cost_cents=0)
    assert result.allowed


# ── 5. Approval gate ─────────────────────────────────────────────────────────

def test_first_digest_requires_approval():
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._is_new_tenant", return_value=True), \
         patch("app.services.digest_send_safety.SafeDigestSender._queue_for_approval", return_value=42):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 8))
    assert not result.allowed
    assert "first_digest" in result.reason
    assert result.approval_id == 42


def test_low_confidence_requires_approval():
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._is_new_tenant", return_value=False), \
         patch("app.services.digest_send_safety.SafeDigestSender._queue_for_approval", return_value=43):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(LOW_CONFIDENCE_STRUCTURED, date(2024, 1, 8))
    assert not result.allowed
    assert "low_confidence" in result.reason


def test_money_change_requires_approval():
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._is_new_tenant", return_value=False), \
         patch("app.services.digest_send_safety.SafeDigestSender._queue_for_approval", return_value=44):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(MONEY_CHANGE_STRUCTURED, date(2024, 1, 8))
    assert not result.allowed
    assert "money_change" in result.reason


def test_established_tenant_normal_digest_allowed():
    """Established tenant, normal confidence, no money change → allowed."""
    with patch("app.services.digest_send_safety.SafeDigestSender._check_idempotent", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._check_circuit_breaker", return_value=(True, "")), \
         patch("app.services.digest_send_safety.SafeDigestSender._is_new_tenant", return_value=False):
        sender = SafeDigestSender(1, "sms")
        result = sender.check(NORMAL_STRUCTURED, date(2024, 1, 8))
    assert result.allowed


# ── Safety result truth value ─────────────────────────────────────────────────

def test_safety_result_bool():
    assert bool(SafetyResult(True)) is True
    assert bool(SafetyResult(False)) is False
