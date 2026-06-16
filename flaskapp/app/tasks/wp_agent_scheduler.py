# app/tasks/wp_agent_scheduler.py
"""
WordPress Operational Agent Scheduler.

Runs the two WordPress operational agents (WPSiteHealthAgent +
WPContentStrategistAgent) for every account that has a WP site configured.

Entry point used by background_jobs.py and run_job.py:
    run_wp_operational_agents(app)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_wp_accounts() -> List[Dict[str, Any]]:
    """Return a list of {account_id} dicts for accounts with a WP site."""
    from app import db
    from sqlalchemy import text

    try:
        rows = db.engine.connect().execute(
            text("SELECT DISTINCT account_id FROM wp_sites WHERE account_id IS NOT NULL")
        ).fetchall()
        return [{"account_id": int(r[0])} for r in rows if r[0]]
    except Exception as exc:
        logger.warning("wp_agent_scheduler: failed to list WP accounts: %s", exc)
        return []


def _read_directive(account_id: int) -> Optional[dict]:
    """Read the strategy_directive_wordpress setting for the account."""
    from app import db
    from sqlalchemy import text

    try:
        row = db.engine.connect().execute(
            text(
                "SELECT setting_value FROM account_settings "
                "WHERE account_id = :aid AND setting_key = 'strategy_directive_wordpress'"
            ),
            {"aid": account_id},
        ).fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as exc:
        logger.debug(
            "wp_agent_scheduler: could not read directive for account %s: %s",
            account_id, exc,
        )
    return None


def run_wp_operational_agents(app) -> Dict[str, Any]:
    """Run WordPress operational agents for all accounts with WP sites.

    For each account:
    1. Check cadence (should_run_agent) — skip if not due yet.
    2. Read strategy_directive_wordpress from account_settings.
    3. Run WPSiteHealthAgent + WPContentStrategistAgent.
    4. Record the run via record_agent_run so backoff state is updated.

    Returns a summary dict: {accounts_checked, accounts_run, accounts_skipped, errors}.
    """
    accounts_checked = 0
    accounts_run = 0
    accounts_skipped = 0
    errors = 0

    with app.app_context():
        from app.services.agent_cadence import should_run_agent, record_agent_run
        from app.wp.wp_agents import WPSiteHealthAgent, WPContentStrategistAgent

        accounts = _get_wp_accounts()
        accounts_checked = len(accounts)

        if not accounts:
            logger.info("wp_agent_scheduler: no accounts with WP sites found")
            return {
                "accounts_checked": 0,
                "accounts_run": 0,
                "accounts_skipped": 0,
                "errors": 0,
            }

        logger.info("wp_agent_scheduler: checking %d account(s)", accounts_checked)

        for acct in accounts:
            account_id = acct["account_id"]

            # ── Cadence check ────────────────────────────────────────────────
            run_now, reason = should_run_agent(account_id, "wordpress", "operational")
            if not run_now:
                accounts_skipped += 1
                logger.debug(
                    "wp_agent_scheduler: account %s skipped (%s)", account_id, reason
                )
                continue

            logger.info(
                "wp_agent_scheduler: running agents for account %s (%s)",
                account_id, reason,
            )

            # ── Read directive ───────────────────────────────────────────────
            directive = _read_directive(account_id)

            # ── Run agents ───────────────────────────────────────────────────
            total_decisions = 0
            total_opportunities = 0

            for AgentClass in (WPSiteHealthAgent, WPContentStrategistAgent):
                agent = AgentClass()
                try:
                    result = agent.run(account_id=account_id, directive=directive)
                    total_decisions += int(result.get("decisions_made", 0) or 0)
                    total_opportunities += int(result.get("opportunities_found", 0) or 0)
                    logger.info(
                        "wp_agent_scheduler: %s account %s → decisions=%d opportunities=%d",
                        agent.agent_type, account_id,
                        result.get("decisions_made", 0),
                        result.get("opportunities_found", 0),
                    )
                except Exception as exc:
                    logger.exception(
                        "wp_agent_scheduler: %s failed for account %s: %s",
                        agent.agent_type, account_id, exc,
                    )
                    errors += 1
                    # Continue with next agent rather than aborting.

            # ── Record run (updates backoff state) ───────────────────────────
            try:
                record_agent_run(
                    account_id,
                    "wordpress",
                    "operational",
                    decisions_made=total_decisions,
                    opportunities_found=total_opportunities,
                )
            except Exception as exc:
                logger.warning(
                    "wp_agent_scheduler: record_agent_run failed for account %s: %s",
                    account_id, exc,
                )

            accounts_run += 1

        logger.info(
            "wp_agent_scheduler: done — checked=%d ran=%d skipped=%d errors=%d",
            accounts_checked, accounts_run, accounts_skipped, errors,
        )

    return {
        "accounts_checked": accounts_checked,
        "accounts_run": accounts_run,
        "accounts_skipped": accounts_skipped,
        "errors": errors,
    }
