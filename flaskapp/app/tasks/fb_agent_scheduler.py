# app/tasks/fb_agent_scheduler.py
"""
Facebook Ads Agent Scheduler — runs Facebook AI agents on a cadence-gated
schedule for all accounts that have a valid Facebook token.

Architecture:
    operational (every 6 h base)  — FBStrategicDirectorAgent,
                                    FBAccountStructureAgent,
                                    FBCampaignManagerAgent,
                                    FBBudgetGuardianAgent,
                                    FBCreativeAnalystAgent,
                                    FBSpendOptimizerAgent,
                                    FBDaypartingAgent,
                                    FBGeoOptimizerAgent,
                                    FBRetargetingAgent,
                                    FBPixelHealthAgent
    tactical    (every 4 h base)  — FBAudienceOptimizerAgent,
                                    FBPlacementOptimizerAgent,
                                    FBBidOptimizerAgent,
                                    FBCreativeOptimizerAgent

Cadence is adaptive: the agent_cadence engine backs off quiet accounts and
snaps back to the base interval the moment they show activity again.

Public entry points (called by background_jobs.py and run_job.py):
    run_fb_operational_agents(app)
    run_fb_tactical_agents(app)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_fb_accounts() -> List[Dict[str, Any]]:
    """Return all accounts with a non-expired Facebook access token."""
    from app import db

    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT ft.account_id, ft.access_token
                FROM facebook_tokens ft
                WHERE ft.expires_at IS NULL OR ft.expires_at > NOW()
            """)).fetchall()
        return [{"account_id": r[0], "access_token": r[1]} for r in rows]
    except Exception as exc:
        logger.error("fb_agent_scheduler: could not query facebook_tokens — %s", exc)
        return []


def _read_directive(account_id: int) -> Optional[Dict[str, Any]]:
    """Read the latest strategy_directive_facebook from account_settings."""
    from app import db

    try:
        with db.engine.connect() as conn:
            row = conn.execute(text("""
                SELECT setting_value
                FROM account_settings
                WHERE account_id = :aid AND setting_key = 'strategy_directive_facebook'
                LIMIT 1
            """), {"aid": account_id}).mappings().one_or_none()

        if row and row["setting_value"]:
            return json.loads(row["setting_value"])
    except Exception as exc:
        logger.debug("fb_agent_scheduler: failed to read directive for %s: %s", account_id, exc)
    return None


def _read_fb_settings(account_id: int) -> Dict[str, Any]:
    """Read fb_target_cpl and fb_monthly_budget from account_settings."""
    from app import db

    defaults = {"fb_target_cpl": 80.0, "fb_monthly_budget": 0.0}
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT setting_key, setting_value
                FROM account_settings
                WHERE account_id = :aid
                  AND setting_key IN ('fb_target_cpl', 'fb_monthly_budget')
            """), {"aid": account_id}).fetchall()
        for key, val in rows:
            try:
                defaults[key] = float(val)
            except (TypeError, ValueError):
                pass
    except Exception as exc:
        logger.debug("fb_agent_scheduler: failed to read fb settings for %s: %s", account_id, exc)
    return defaults


def _log_agent_execution(account_id: int, agent_id: str, agent_type: str,
                          opportunities: int, decisions: int, status: str = "completed",
                          error: Optional[str] = None) -> None:
    """Insert a row into agent_execution_log (best-effort)."""
    from app import db

    try:
        with db.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_execution_log
                (account_id, agent_id, agent_type, cycle_start,
                 opportunities_found, decisions_made, auto_executed,
                 pending_approval, status, error_message)
                VALUES
                (:account_id, :agent_id, :agent_type, :cycle_start,
                 :opportunities, :decisions, :auto_exec,
                 :pending, :status, :error)
            """), {
                "account_id": account_id,
                "agent_id": agent_id,
                "agent_type": agent_type,
                "cycle_start": datetime.utcnow(),
                "opportunities": opportunities,
                "decisions": decisions,
                "auto_exec": decisions,
                "pending": 0,
                "status": status,
                "error": error,
            })
    except Exception as exc:
        logger.debug("fb_agent_scheduler: log insert failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Per-account agent runner
# ─────────────────────────────────────────────────────────────────────────────

def run_fb_agents_for_account(
    account_id: int,
    layer: str = "operational",
    directive: Optional[Dict[str, Any]] = None,
    access_token: Optional[str] = None,
) -> Dict[str, int]:
    """Run Facebook AI agents for a single account.

    Args:
        account_id: FieldSprout account ID.
        layer: 'operational' or 'tactical'.
        directive: Parsed strategy_directive_facebook dict (optional).
        access_token: FB access token (optional, used for future live-API calls).

    Returns:
        {'decisions': int, 'opportunities': int}
    """
    from app.agents.event_bus import AgentEventBus
    from app.agents.decision_log import DecisionLog

    # Read account settings for context
    fb_settings = _read_fb_settings(account_id)
    target_cpl = fb_settings["fb_target_cpl"]
    monthly_budget = fb_settings["fb_monthly_budget"]

    # Build a minimal context dict (no live FB API call here — agents work off
    # locally-synced data written by fbads_sync, which runs nightly)
    context: Dict[str, Any] = {
        "account_id": account_id,
        "target_cpa": target_cpl,
        "target_cpl": target_cpl,
        "monthly_budget": monthly_budget,
        "campaigns": [],
        "ad_sets": [],
        "ads": [],
        "audiences": [],
        "pixel_data": {},
        "spend_mtd": 0.0,
    }

    # Inject strategic directive so agents know the top-level action
    if directive:
        context["strategy_directive"] = directive
        context["strategic_action"] = directive.get("action") or directive.get("priority", "maintain")
        context["strategic_rationale"] = directive.get("rationale", "")

    event_bus = AgentEventBus()
    decision_log = DecisionLog()

    agent_kwargs = dict(
        event_bus=event_bus,
        decision_log=decision_log,
        account_id=account_id,
        autonomy_level=2,
    )

    # Select agent set based on layer
    agents = _build_agent_list(layer, agent_kwargs)

    totals = {"decisions": 0, "opportunities": 0}

    for agent in agents:
        try:
            # Agents use run_cycle(context, executor=None) — executor is only
            # needed for mutating live-API calls which require explicit approval.
            result = agent.run_cycle(context, executor=None)

            decisions = int(result.get("decisions_made", 0) or 0)
            opps = int(result.get("opportunities_found", 0) or 0)
            totals["decisions"] += decisions
            totals["opportunities"] += opps

            _log_agent_execution(
                account_id=account_id,
                agent_id=result.get("agent_id", agent.agent_id),
                agent_type=result.get("agent_type", agent.agent_type),
                opportunities=opps,
                decisions=decisions,
                status="completed",
            )

            logger.info(
                "fb_agent_scheduler: account %s %s agent %s — %d decisions, %d opps",
                account_id, layer, agent.agent_id, decisions, opps,
            )

        except Exception as exc:
            logger.warning(
                "fb_agent_scheduler: account %s layer=%s agent=%s failed: %s",
                account_id, layer, agent.agent_id, exc,
            )
            _log_agent_execution(
                account_id=account_id,
                agent_id=agent.agent_id,
                agent_type=agent.agent_type,
                opportunities=0,
                decisions=0,
                status="failed",
                error=str(exc)[:1000],
            )

    return totals


def _build_agent_list(layer: str, agent_kwargs: Dict[str, Any]) -> list:
    """Instantiate and return the correct agent list for the given layer.

    Only imports agent classes that actually exist in the codebase.
    """
    agents = []

    if layer == "operational":
        try:
            from app.agents.fbads_strategic import (
                FBStrategicDirectorAgent,
                FBAccountStructureAgent,
            )
            agents.extend([
                FBStrategicDirectorAgent(**agent_kwargs),
                FBAccountStructureAgent(**agent_kwargs),
            ])
        except ImportError as exc:
            logger.warning("fb_agent_scheduler: fbads_strategic import failed: %s", exc)

        try:
            from app.agents.fbads_operational import (
                FBCampaignManagerAgent,
                FBBudgetGuardianAgent,
                FBCreativeAnalystAgent,
            )
            agents.extend([
                FBCampaignManagerAgent(**agent_kwargs),
                FBBudgetGuardianAgent(**agent_kwargs),
                FBCreativeAnalystAgent(**agent_kwargs),
            ])
        except ImportError as exc:
            logger.warning("fb_agent_scheduler: fbads_operational import failed: %s", exc)

        try:
            from app.agents.fbads_advanced import (
                FBSpendOptimizerAgent,
                FBDaypartingAgent,
                FBGeoOptimizerAgent,
                FBRetargetingAgent,
                FBPixelHealthAgent,
            )
            agents.extend([
                FBSpendOptimizerAgent(**agent_kwargs),
                FBDaypartingAgent(**agent_kwargs),
                FBGeoOptimizerAgent(**agent_kwargs),
                FBRetargetingAgent(**agent_kwargs),
                FBPixelHealthAgent(**agent_kwargs),
            ])
        except ImportError as exc:
            logger.warning("fb_agent_scheduler: fbads_advanced import failed: %s", exc)

    elif layer == "tactical":
        try:
            from app.agents.fbads_tactical import (
                FBAudienceOptimizerAgent,
                FBPlacementOptimizerAgent,
                FBBidOptimizerAgent,
                FBCreativeOptimizerAgent,
            )
            agents.extend([
                FBAudienceOptimizerAgent(**agent_kwargs),
                FBPlacementOptimizerAgent(**agent_kwargs),
                FBBidOptimizerAgent(**agent_kwargs),
                FBCreativeOptimizerAgent(**agent_kwargs),
            ])
        except ImportError as exc:
            logger.warning("fb_agent_scheduler: fbads_tactical import failed: %s", exc)

    return agents


# ─────────────────────────────────────────────────────────────────────────────
# Public entry points (called from background_jobs.py)
# ─────────────────────────────────────────────────────────────────────────────

def run_fb_operational_agents(app) -> tuple:
    """Run Facebook operational agents for all accounts with valid FB tokens.

    Cadence-gated: base interval 6 h, backs off to 2 days on quiet accounts.

    Returns:
        (success_count, error_count)
    """
    from app.services.agent_cadence import should_run_agent, record_agent_run

    accounts = _get_fb_accounts()
    if not accounts:
        logger.info("fb_agent_scheduler (operational): no accounts with FB token found")
        return 0, 0

    logger.info("fb_agent_scheduler (operational): %d account(s) to check", len(accounts))

    success_count = 0
    error_count = 0
    skip_count = 0

    for acct in accounts:
        account_id = acct["account_id"]

        run_now, reason = should_run_agent(account_id, "facebook", "operational")
        if not run_now:
            skip_count += 1
            logger.debug("fb_agent_scheduler (operational): account %s skipped — %s",
                         account_id, reason)
            continue

        try:
            directive = _read_directive(account_id)
            totals = run_fb_agents_for_account(
                account_id=account_id,
                layer="operational",
                directive=directive,
                access_token=acct.get("access_token"),
            )
            record_agent_run(
                account_id, "facebook", "operational",
                decisions_made=int(totals.get("decisions", 0) or 0),
                opportunities_found=int(totals.get("opportunities", 0) or 0),
            )
            success_count += 1
            logger.info(
                "fb_agent_scheduler (operational): account %s — %d decisions, %d opps",
                account_id, totals["decisions"], totals["opportunities"],
            )
        except Exception as exc:
            error_count += 1
            logger.error(
                "fb_agent_scheduler (operational): account %s failed — %s",
                account_id, exc, exc_info=True,
            )

    logger.info(
        "fb_agent_scheduler (operational): done — ran=%d, skipped=%d, errors=%d",
        success_count, skip_count, error_count,
    )
    return success_count, error_count


def run_fb_tactical_agents(app) -> tuple:
    """Run Facebook tactical agents for all accounts with valid FB tokens.

    Cadence-gated: base interval 4 h, backs off to 2 days on quiet accounts.

    Returns:
        (success_count, error_count)
    """
    from app.services.agent_cadence import should_run_agent, record_agent_run

    accounts = _get_fb_accounts()
    if not accounts:
        logger.info("fb_agent_scheduler (tactical): no accounts with FB token found")
        return 0, 0

    logger.info("fb_agent_scheduler (tactical): %d account(s) to check", len(accounts))

    success_count = 0
    error_count = 0
    skip_count = 0

    for acct in accounts:
        account_id = acct["account_id"]

        run_now, reason = should_run_agent(account_id, "facebook", "tactical")
        if not run_now:
            skip_count += 1
            logger.debug("fb_agent_scheduler (tactical): account %s skipped — %s",
                         account_id, reason)
            continue

        try:
            directive = _read_directive(account_id)
            totals = run_fb_agents_for_account(
                account_id=account_id,
                layer="tactical",
                directive=directive,
                access_token=acct.get("access_token"),
            )
            record_agent_run(
                account_id, "facebook", "tactical",
                decisions_made=int(totals.get("decisions", 0) or 0),
                opportunities_found=int(totals.get("opportunities", 0) or 0),
            )
            success_count += 1
            logger.info(
                "fb_agent_scheduler (tactical): account %s — %d decisions, %d opps",
                account_id, totals["decisions"], totals["opportunities"],
            )
        except Exception as exc:
            error_count += 1
            logger.error(
                "fb_agent_scheduler (tactical): account %s failed — %s",
                account_id, exc, exc_info=True,
            )

    logger.info(
        "fb_agent_scheduler (tactical): done — ran=%d, skipped=%d, errors=%d",
        success_count, skip_count, error_count,
    )
    return success_count, error_count
