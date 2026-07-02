# app/services/agent_cadence.py
"""
Adaptive Cadence Engine for FieldSprout AI agents.

Agent run frequency adapts to the previous run's return: when an account is
quiet (no decisions / no opportunities / low volatility) the interval backs off
exponentially up to a 2-day cap; the moment the account is active again the
interval snaps back to the layer's base interval. State is tracked per
account, per channel, per layer.

Public API (depended on verbatim by other agents):
    should_run_agent(account_id, channel, layer, now=None) -> (bool, str)
    record_agent_run(account_id, channel, layer, decisions_made, opportunities_found,
                     volatility, now=None) -> dict
    force_due(account_id, channel, layer) -> None
    get_cadence_state(account_id, channel, layer) -> dict | None

All DB work fails OPEN: any error leaves agents running on their default
schedule rather than silently stopping them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import text

log = logging.getLogger(__name__)

BASE_INTERVALS_MIN = {
    ('google', 'tactical'): 120,
    ('google', 'operational'): 240,
    ('google', 'strategic'): 10080,
    ('google', 'negative_keyword'): 1440,
    ('facebook', 'tactical'): 240,
    ('facebook', 'operational'): 360,
    ('facebook', 'strategic'): 10080,
    ('wordpress', 'operational'): 1440,
    ('wordpress', 'strategic'): 10080,
}
MAX_INTERVAL_MIN = 2880          # 2-day cap for non-strategic backoff
STRATEGIC_MAX_INTERVAL_MIN = 20160   # strategic layers cap at 2 weeks

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS agent_cadence_state (
  id INT AUTO_INCREMENT PRIMARY KEY,
  account_id INT NOT NULL,
  channel VARCHAR(32) NOT NULL,
  layer VARCHAR(32) NOT NULL,
  next_run_at DATETIME NULL,
  interval_minutes INT NOT NULL DEFAULT 240,
  idle_streak INT NOT NULL DEFAULT 0,
  last_decisions INT NOT NULL DEFAULT 0,
  last_opportunities INT NOT NULL DEFAULT 0,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_cadence (account_id, channel, layer),
  INDEX ix_cadence_due (channel, layer, next_run_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_table_ready = False


def _ensure_cadence_table() -> None:
    global _table_ready
    if _table_ready:
        return
    from app import db
    try:
        with db.engine.begin() as conn:
            conn.execute(text(_TABLE_DDL))
        _table_ready = True
    except Exception as exc:
        log.warning("agent_cadence_state table creation failed: %s", exc)


def _row_to_dict(row) -> dict:
    return dict(row._mapping)


def get_cadence_state(account_id: int, channel: str, layer: str) -> Optional[dict]:
    _ensure_cadence_table()
    from app import db
    try:
        sql = text("""
            SELECT * FROM agent_cadence_state
            WHERE account_id = :aid AND channel = :ch AND layer = :ly
        """)
        with db.engine.connect() as conn:
            row = conn.execute(sql, {"aid": account_id, "ch": channel, "ly": layer}).first()
        return _row_to_dict(row) if row else None
    except Exception as exc:
        log.warning("get_cadence_state failed for %s/%s/%s: %s",
                    account_id, channel, layer, exc)
        return None


def should_run_agent(account_id: int, channel: str, layer: str,
                     now: Optional[datetime] = None) -> Tuple[bool, str]:
    """Return (run_now, reason).

    No state row yet -> (True, 'first run').
    now >= next_run_at -> (True, 'due').
    Otherwise -> (False, 'not due until <ts>').
    Any DB error fails OPEN -> (True, 'cadence error - failing open').
    """
    _ensure_cadence_table()
    if now is None:
        now = datetime.utcnow()
    from app import db
    try:
        sql = text("""
            SELECT next_run_at FROM agent_cadence_state
            WHERE account_id = :aid AND channel = :ch AND layer = :ly
        """)
        with db.engine.connect() as conn:
            row = conn.execute(sql, {"aid": account_id, "ch": channel, "ly": layer}).first()
        if row is None:
            return True, 'first run'
        next_run_at = row._mapping['next_run_at']
        if next_run_at is None or now >= next_run_at:
            return True, 'due'
        return False, f'not due until {next_run_at}'
    except Exception as exc:
        log.warning("should_run_agent failed for %s/%s/%s: %s",
                    account_id, channel, layer, exc)
        return True, 'cadence error - failing open'


def record_agent_run(account_id: int, channel: str, layer: str,
                     decisions_made: int = 0, opportunities_found: int = 0,
                     volatility: float = 0.0,
                     now: Optional[datetime] = None) -> dict:
    """Update backoff state after a run and compute next_run_at.

    active = decisions_made > 0 or opportunities_found > 0 or volatility >= 0.4
    On active: idle_streak resets to 0 and interval snaps back to base.
    On idle: idle_streak increments and interval = min(base * 2**idle_streak, cap).
    Returns the new state dict (always populated, even on DB failure).
    """
    _ensure_cadence_table()
    if now is None:
        now = datetime.utcnow()

    base = BASE_INTERVALS_MIN.get((channel, layer), 240)
    cap = STRATEGIC_MAX_INTERVAL_MIN if layer == 'strategic' else MAX_INTERVAL_MIN
    active = decisions_made > 0 or opportunities_found > 0 or volatility >= 0.4

    from app import db
    prev_idle = 0
    try:
        existing = get_cadence_state(account_id, channel, layer)
        if existing:
            prev_idle = existing.get('idle_streak', 0) or 0
    except Exception:
        prev_idle = 0

    if active:
        idle_streak = 0
        interval = base
    else:
        idle_streak = prev_idle + 1
        interval = min(base * (2 ** idle_streak), cap)

    next_run_at = now + timedelta(minutes=interval)

    state = {
        'account_id': account_id,
        'channel': channel,
        'layer': layer,
        'next_run_at': next_run_at,
        'interval_minutes': interval,
        'idle_streak': idle_streak,
        'last_decisions': decisions_made,
        'last_opportunities': opportunities_found,
    }

    try:
        sql = text("""
            INSERT INTO agent_cadence_state
                (account_id, channel, layer, next_run_at, interval_minutes,
                 idle_streak, last_decisions, last_opportunities)
            VALUES
                (:aid, :ch, :ly, :nra, :ivl, :idle, :dec, :opp)
            ON DUPLICATE KEY UPDATE
                next_run_at = VALUES(next_run_at),
                interval_minutes = VALUES(interval_minutes),
                idle_streak = VALUES(idle_streak),
                last_decisions = VALUES(last_decisions),
                last_opportunities = VALUES(last_opportunities)
        """)
        with db.engine.begin() as conn:
            conn.execute(sql, {
                "aid": account_id, "ch": channel, "ly": layer,
                "nra": next_run_at, "ivl": interval, "idle": idle_streak,
                "dec": decisions_made, "opp": opportunities_found,
            })
    except Exception as exc:
        log.warning("record_agent_run failed for %s/%s/%s: %s",
                    account_id, channel, layer, exc)

    return state


def force_due(account_id: int, channel: str, layer: str) -> None:
    """Reset next_run_at to now (anomaly events or manual 'run now')."""
    _ensure_cadence_table()
    from app import db
    now = datetime.utcnow()
    try:
        sql = text("""
            INSERT INTO agent_cadence_state
                (account_id, channel, layer, next_run_at, interval_minutes, idle_streak)
            VALUES
                (:aid, :ch, :ly, :nra, :ivl, 0)
            ON DUPLICATE KEY UPDATE
                next_run_at = VALUES(next_run_at),
                idle_streak = 0
        """)
        base = BASE_INTERVALS_MIN.get((channel, layer), 240)
        with db.engine.begin() as conn:
            conn.execute(sql, {
                "aid": account_id, "ch": channel, "ly": layer,
                "nra": now, "ivl": base,
            })
    except Exception as exc:
        log.warning("force_due failed for %s/%s/%s: %s",
                    account_id, channel, layer, exc)
