# app/services/safety_layer.py
"""
Safety Layer for Autonomous Agent Execution.

Three mechanisms that prevent the agent system from doing damage:

1. Cooldown   — blocks re-touching the same entity within X hours after
               an action was taken on it.

2. Anomaly Gate — detects abnormal spend (>40% above/below 7-day average)
                  and forces L2 mode (no high-risk auto-execution) until
                  spend normalises.

3. Rollback Detection — runs daily; flags ai_actions where account CPL
                        worsened >30% in the 48 hours after the action,
                        marking them for human review.  The actual API
                        reversal is triggered via the existing undo UI so
                        a human confirms before the change hits Google.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

log = logging.getLogger(__name__)

# ── Cooldown periods by action type (hours) ───────────────────────────────────
COOLDOWN_HOURS: Dict[str, int] = {
    "negative_keyword_added":   1,
    "negative_keyword_removed": 2,
    "search_term_blocked":      1,
    "bid_adjusted":             4,
    "keyword_paused":          24,
    "keyword_enabled":         12,
    "ad_paused":               12,
    "ad_enabled":               8,
    "campaign_paused":         48,
    "campaign_enabled":        24,
    "budget_reallocated":       6,
    "_default":                 2,
}

# Spend deviation that triggers the anomaly gate (40 %)
ANOMALY_THRESHOLD = 0.40

# CPL degradation that triggers a rollback flag (30 %)
ROLLBACK_CPL_THRESHOLD = 0.30

# Window (hours) within which we measure rollback impact
ROLLBACK_MEASURE_HOURS_MIN = 24
ROLLBACK_MEASURE_HOURS_MAX = 72


# ── 1. Cooldown ────────────────────────────────────────────────────────────────

def _entity_key_from_decision(decision: Any) -> Optional[Dict[str, str]]:
    """
    Build a (entity_type, entity_id, action_type) fingerprint from a decision.
    Returns None if the decision carries no entity info.
    """
    action_type = getattr(decision, "decision_type", "") or ""
    keyword_id  = getattr(decision, "keyword_id",  None)
    ad_group_id = getattr(decision, "ad_group_id", None)
    campaign_id = getattr(decision, "campaign_id", None)

    if keyword_id:
        return {"level": "keyword",   "entity_id": str(keyword_id),  "action_type": action_type}
    if ad_group_id:
        return {"level": "ad_group",  "entity_id": str(ad_group_id), "action_type": action_type}
    if campaign_id:
        return {"level": "campaign",  "entity_id": str(campaign_id), "action_type": action_type}
    return None


def is_in_cooldown(account_id: int, decision: Any) -> Tuple[bool, str]:
    """
    Check whether executing this decision would violate a cooldown window.

    Returns (blocked: bool, reason: str).
    """
    entity = _entity_key_from_decision(decision)
    if not entity:
        return False, ""

    # Map decision_type → ai_actions.action_type so we search the right rows
    dtype_to_atype = {
        "add_negative_keyword":  "negative_keyword_added",
        "pause_keyword":         "keyword_paused",
        "adjust_keyword_bid":    "bid_adjusted",
        "adjust_campaign_bids":  "bid_adjusted",
        "pause_campaign":        "campaign_paused",
        "scale_campaign_budget": "budget_reallocated",
        "reallocate_budget":     "budget_reallocated",
        "pause_ad":              "ad_paused",
    }
    action_type = dtype_to_atype.get(entity["action_type"], entity["action_type"])
    hours = COOLDOWN_HOURS.get(action_type, COOLDOWN_HOURS["_default"])
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    level = entity["level"]
    entity_id = entity["entity_id"]

    # Column to filter on depends on entity level
    col_map = {"keyword": "keyword_id", "ad_group": "ad_group_id", "campaign": "campaign_id"}
    col = col_map.get(level)
    if not col:
        return False, ""

    try:
        from app import db
        sql = text(f"""
            SELECT MAX(executed_at) AS last_exec
            FROM ai_actions
            WHERE account_id  = :aid
              AND {col}        = :eid
              AND action_type  = :atype
              AND status       = 'executed'
              AND executed_at >= :cutoff
        """)
        with db.engine.connect() as conn:
            row = conn.execute(sql, {
                "aid":    account_id,
                "eid":    entity_id,
                "atype":  action_type,
                "cutoff": cutoff,
            }).first()

        if row and row.last_exec:
            next_allowed = row.last_exec + timedelta(hours=hours)
            remaining = int((next_allowed - datetime.utcnow()).total_seconds() / 60)
            return True, (
                f"Cooldown active: {action_type} on {level} {entity_id} "
                f"was executed {hours}h ago. Next allowed in ~{remaining} min."
            )
    except Exception as exc:
        log.warning("Cooldown check failed (allowing execution): %s", exc)

    return False, ""


# ── 2. Anomaly Gate ────────────────────────────────────────────────────────────

def check_anomaly_gate(account_id: int) -> Tuple[bool, str]:
    """
    Compare today's spend to the 7-day rolling average.

    Returns (anomaly_detected: bool, details: str).
    When an anomaly is detected, the caller should drop autonomy_level to 2
    so that high-risk actions go to the approval queue instead of auto-executing.
    """
    try:
        from app import db
        sql = text("""
            SELECT
                date,
                SUM(cost_micros) / 1000000 AS daily_spend
            FROM gads_stats_daily
            WHERE account_id  = :aid
              AND entity_type  = 'account'
              AND date >= DATE_SUB(CURDATE(), INTERVAL 8 DAY)
            GROUP BY date
            ORDER BY date DESC
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id}).fetchall()

        if len(rows) < 3:
            return False, "Insufficient data for anomaly detection"

        today_row = rows[0]
        past_rows = rows[1:]  # yesterday through 7 days ago

        today_spend = float(today_row.daily_spend or 0)
        avg_spend   = sum(float(r.daily_spend or 0) for r in past_rows) / len(past_rows)

        if avg_spend == 0:
            return False, "No historical spend baseline"

        deviation = abs(today_spend - avg_spend) / avg_spend

        if deviation >= ANOMALY_THRESHOLD:
            direction = "spike" if today_spend > avg_spend else "drop"
            return True, (
                f"Spend {direction} detected: today=${today_spend:.2f}, "
                f"7-day avg=${avg_spend:.2f} ({deviation*100:.0f}% deviation)"
            )

        return False, f"Spend normal: ${today_spend:.2f} vs avg ${avg_spend:.2f}"

    except Exception as exc:
        log.warning("Anomaly gate check failed (allowing execution): %s", exc)
        return False, str(exc)


# ── 3. Rollback Detection ──────────────────────────────────────────────────────

def run_rollback_checks(account_id: int) -> List[int]:
    """
    Scan ai_actions executed 24-72 hours ago.  For each one, compare CPL in
    the 3 days before vs. the 3 days after the action date.

    If CPL worsened by more than ROLLBACK_CPL_THRESHOLD, the action is flagged
    as 'pending_review' so it shows in the approval queue for human undo.

    Returns list of ai_action IDs that were flagged.
    """
    now = datetime.utcnow()
    window_min = now - timedelta(hours=ROLLBACK_MEASURE_HOURS_MAX)
    window_max = now - timedelta(hours=ROLLBACK_MEASURE_HOURS_MIN)

    flagged: List[int] = []

    try:
        from app import db

        actions_sql = text("""
            SELECT id, action_type, executed_at, campaign_id
            FROM ai_actions
            WHERE account_id = :aid
              AND status       = 'executed'
              AND executed_at BETWEEN :wmin AND :wmax
              AND can_undo     = 1
        """)
        with db.engine.connect() as conn:
            actions = conn.execute(actions_sql, {
                "aid":  account_id,
                "wmin": window_min,
                "wmax": window_max,
            }).fetchall()

        if not actions:
            return []

        for action in actions:
            action_date = action.executed_at.date()
            before_start = action_date - timedelta(days=3)
            after_end    = action_date + timedelta(days=3)

            cpl_sql = text("""
                SELECT
                    SUM(CASE WHEN date < :action_date THEN cost_micros ELSE 0 END)
                        / 1000000 AS before_cost,
                    SUM(CASE WHEN date < :action_date THEN conversions ELSE 0 END)
                        AS before_conversions,
                    SUM(CASE WHEN date >= :action_date THEN cost_micros ELSE 0 END)
                        / 1000000 AS after_cost,
                    SUM(CASE WHEN date >= :action_date THEN conversions ELSE 0 END)
                        AS after_conversions
                FROM gads_stats_daily
                WHERE account_id  = :aid
                  AND entity_type  = 'account'
                  AND date BETWEEN :bstart AND :aend
            """)
            with db.engine.connect() as conn:
                row = conn.execute(cpl_sql, {
                    "aid":         account_id,
                    "action_date": action_date,
                    "bstart":      before_start,
                    "aend":        after_end,
                }).first()

            if not row:
                continue

            before_conv = float(row.before_conversions or 0)
            after_conv  = float(row.after_conversions  or 0)
            before_cost = float(row.before_cost or 0)
            after_cost  = float(row.after_cost  or 0)

            # Need at least some conversions to make a meaningful comparison
            if before_conv < 1 or after_conv < 1:
                continue

            before_cpl = before_cost / before_conv
            after_cpl  = after_cost  / after_conv

            if before_cpl == 0:
                continue

            degradation = (after_cpl - before_cpl) / before_cpl

            if degradation >= ROLLBACK_CPL_THRESHOLD:
                note = (
                    f"CPL increased {degradation*100:.0f}% after action "
                    f"(${before_cpl:.2f} → ${after_cpl:.2f}). "
                    f"Auto-flagged for review by safety layer."
                )
                _flag_for_review(account_id, action.id, note)
                flagged.append(action.id)
                log.info(
                    "Rollback flag: account=%d action_id=%d CPL %.0f%%↑",
                    account_id, action.id, degradation * 100,
                )

    except Exception as exc:
        log.error("Rollback check failed for account %d: %s", account_id, exc)

    return flagged


def _flag_for_review(account_id: int, ai_action_id: int, note: str) -> None:
    """Mark an executed ai_action as pending_review so it surfaces in the UI."""
    try:
        from app import db
        sql = text("""
            UPDATE ai_actions
            SET status = 'pending_review',
                undo_reason = :note
            WHERE id         = :aid
              AND account_id = :account_id
              AND status     = 'executed'
        """)
        with db.engine.begin() as conn:
            conn.execute(sql, {
                "aid":        ai_action_id,
                "account_id": account_id,
                "note":       note,
            })
    except Exception as exc:
        log.error("Failed to flag action %d for review: %s", ai_action_id, exc)


# ── Public helper used by cron ─────────────────────────────────────────────────

def run_all_safety_checks_for_account(account_id: int) -> Dict[str, Any]:
    """
    Run anomaly gate + rollback checks for one account.
    Returns a summary dict for logging.
    """
    anomaly, anomaly_msg = check_anomaly_gate(account_id)
    rollback_flags = run_rollback_checks(account_id)

    if anomaly:
        log.warning("Anomaly detected for account %d: %s", account_id, anomaly_msg)

    return {
        "account_id":     account_id,
        "anomaly":        anomaly,
        "anomaly_detail": anomaly_msg,
        "rollback_flags": rollback_flags,
    }
