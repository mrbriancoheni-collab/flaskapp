# app/wp/wp_agents.py
"""
WordPress Operational Agents.

Two agents sit at the operational layer of the three-tier architecture:

    WPSiteHealthAgent
        Checks site health: stale content, missing SEO, low-traffic pages.
        Works by inspecting WPJob error/stale records and KeywordRankSnapshot
        data — no direct WordPress API calls, so it runs even when WP is
        temporarily unreachable.

    WPContentStrategistAgent
        Plans content based on keyword rankings and the directive from the
        strategic orchestrator ('grow' | 'maintain').

        grow     → queue 2-3 ai_generate jobs for high-opportunity keywords
        maintain → queue 1 refresh job for the worst-declining ranking

Both agents accept a `directive` dict (as written by WPChannelProvider.apply_directives
or the orchestrator's organic branch) and return:
    {'decisions_made': int, 'opportunities_found': int}

They are orchestrated by the scheduler in app/tasks/wp_agent_scheduler.py.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_wp_site(account_id: int):
    """Return the WPSite for this account, or None."""
    try:
        from app.models_wp import WPSite
        return WPSite.query.filter_by(account_id=account_id).first()
    except Exception as exc:
        logger.debug("WPSite lookup failed for account %s: %s", account_id, exc)
        return None


def _get_directive_action(directive: Optional[dict]) -> str:
    """Extract the action string from a directive dict; default to 'maintain'."""
    if not directive:
        return "maintain"
    action = directive.get("action") or directive.get("priority") or "maintain"
    return str(action).lower()


# ── WPSiteHealthAgent ─────────────────────────────────────────────────────────

class WPSiteHealthAgent:
    """Checks site health: broken jobs, stale content, missing SEO signals.

    Opportunities found = number of issues detected.
    Decisions made = number of corrective actions queued / logged.
    """

    agent_id = "wp_site_health"
    agent_type = "WPSiteHealthAgent"

    def run(self, account_id: int, directive: Optional[dict] = None) -> Dict[str, Any]:
        """Run site health checks and queue fixes where possible.

        Returns {'decisions_made': int, 'opportunities_found': int}.
        """
        opportunities_found = 0
        decisions_made = 0

        try:
            from app import db
            from app.models_wp import WPSite, WPJob, WPLog

            site = _get_wp_site(account_id)
            if not site:
                logger.info("WPSiteHealthAgent: no WP site for account %s", account_id)
                return {"decisions_made": 0, "opportunities_found": 0}

            # ── 1. Count error jobs (unresolved publish/generate failures) ──
            error_job_count = WPJob.query.filter_by(
                site_id=site.id, status="error"
            ).count()
            if error_job_count > 0:
                opportunities_found += error_job_count
                logger.info(
                    "WPSiteHealthAgent account %s: %d error job(s) found",
                    account_id, error_job_count,
                )
                # Log a health warning (diagnostic only — no auto-fix for error jobs
                # as they may need human review)
                db.session.add(WPLog(
                    site_id=site.id,
                    level="warn",
                    message=(
                        f"[HealthAgent] {error_job_count} unresolved error job(s) detected. "
                        f"Review publisher queue."
                    ),
                ))
                db.session.commit()
                decisions_made += 1  # logged the warning

            # ── 2. Stale content check: posts/ai_generate older than 30 days
            #       with no refresh job queued since ───────────────────────
            cutoff_stale = datetime.utcnow() - timedelta(days=30)
            stale_ai_jobs = WPJob.query.filter(
                WPJob.site_id == site.id,
                WPJob.kind == "ai_generate",
                WPJob.status == "done",
                WPJob.created_at <= cutoff_stale,
            ).count()

            if stale_ai_jobs > 0:
                opportunities_found += 1
                logger.info(
                    "WPSiteHealthAgent account %s: %d stale AI post(s) (>30 days, no refresh)",
                    account_id, stale_ai_jobs,
                )

            # ── 3. SEO opportunity: check for low-ranked keywords (pos > 20)
            #       in the last 30 days ───────────────────────────────────
            try:
                from app.models_wp import KeywordRankSnapshot
                from sqlalchemy import func as sa_func

                cutoff_rank = date.today() - timedelta(days=30)
                poor_rank_count = (
                    KeywordRankSnapshot.query
                    .filter(
                        KeywordRankSnapshot.account_id == account_id,
                        KeywordRankSnapshot.snapshot_date >= cutoff_rank,
                        KeywordRankSnapshot.position > 20,
                        KeywordRankSnapshot.impressions > 10,
                    )
                    .count()
                )
                if poor_rank_count > 0:
                    opportunities_found += poor_rank_count
                    logger.info(
                        "WPSiteHealthAgent account %s: %d keyword(s) ranking below position 20",
                        account_id, poor_rank_count,
                    )
            except Exception as exc:
                logger.debug("WPSiteHealthAgent: keyword rank check failed: %s", exc)

        except Exception as exc:
            logger.exception(
                "WPSiteHealthAgent.run failed for account %s: %s", account_id, exc
            )

        return {
            "decisions_made": decisions_made,
            "opportunities_found": opportunities_found,
        }


# ── WPContentStrategistAgent ──────────────────────────────────────────────────

class WPContentStrategistAgent:
    """Plans and queues content based on keyword rankings and the strategic directive.

    grow     → queue 2-3 ai_generate jobs targeting high-opportunity keywords
    maintain → queue 1 refresh job for the keyword with the worst rank decline
    """

    agent_id = "wp_content_strategist"
    agent_type = "WPContentStrategistAgent"

    # Max posts to queue per run to avoid flooding the site.
    MAX_GROW_POSTS = 3
    MAX_MAINTAIN_POSTS = 1

    def run(self, account_id: int, directive: Optional[dict] = None) -> Dict[str, Any]:
        """Queue content jobs based on the directive and keyword data.

        Returns {'decisions_made': int, 'opportunities_found': int}.
        """
        opportunities_found = 0
        decisions_made = 0

        try:
            from app import db
            from app.models_wp import WPSite, WPJob, KeywordRankSnapshot

            site = _get_wp_site(account_id)
            if not site:
                logger.info("WPContentStrategistAgent: no WP site for account %s", account_id)
                return {"decisions_made": 0, "opportunities_found": 0}

            action = _get_directive_action(directive)
            rationale = (directive or {}).get("rationale", "")

            if action == "grow":
                decisions_made, opportunities_found = self._queue_new_posts(
                    account_id, site, db, rationale,
                )
            else:
                # 'maintain' (or any other value) → refresh worst-declining content
                decisions_made, opportunities_found = self._queue_refresh_posts(
                    account_id, site, db,
                )

        except Exception as exc:
            logger.exception(
                "WPContentStrategistAgent.run failed for account %s: %s", account_id, exc
            )

        return {
            "decisions_made": decisions_made,
            "opportunities_found": opportunities_found,
        }

    # ── internal helpers ──────────────────────────────────────────────────────

    def _queue_new_posts(
        self, account_id: int, site, db, rationale: str
    ) -> tuple:
        """Queue ai_generate jobs for high-opportunity keywords (position 4-20,
        high impressions but not yet ranking well).

        Returns (decisions_made, opportunities_found).
        """
        from app.models_wp import KeywordRankSnapshot, WPJob

        decisions_made = 0
        opportunities_found = 0

        try:
            cutoff = date.today() - timedelta(days=30)
            # High-opportunity: visible (impressions > 50) but not on page 1 yet
            candidates: List[Any] = (
                KeywordRankSnapshot.query
                .filter(
                    KeywordRankSnapshot.account_id == account_id,
                    KeywordRankSnapshot.snapshot_date >= cutoff,
                    KeywordRankSnapshot.position > 10,
                    KeywordRankSnapshot.position <= 30,
                    KeywordRankSnapshot.impressions > 50,
                )
                .order_by(KeywordRankSnapshot.impressions.desc())
                .limit(self.MAX_GROW_POSTS)
                .all()
            )
            opportunities_found = len(candidates)

            # Deduplicate by keyword so we don't queue the same keyword twice
            seen_keywords: set = set()
            queued = 0
            for snap in candidates:
                kw = (snap.keyword or "").strip()
                if not kw or kw in seen_keywords:
                    continue
                seen_keywords.add(kw)

                brief = {
                    "source": "wp_content_strategist",
                    "primary_keyword": kw,
                    "prompt": (
                        f"Write a helpful blog post targeting the keyword: '{kw}'. "
                        f"Strategic context: {rationale}" if rationale else
                        f"Write a helpful blog post targeting the keyword: '{kw}'."
                    ),
                    "require_approval": bool(
                        getattr(site, "autopilot_require_approval", True)
                    ),
                    "needs_approval": True,
                    "status": "draft",
                }
                job = WPJob(site_id=site.id, kind="ai_generate", payload=brief)
                db.session.add(job)
                queued += 1

            if queued:
                db.session.commit()
                decisions_made = queued
                logger.info(
                    "WPContentStrategistAgent [grow]: queued %d ai_generate job(s) for account %s",
                    queued, account_id,
                )
            else:
                logger.info(
                    "WPContentStrategistAgent [grow]: no high-opportunity keywords found for account %s",
                    account_id,
                )

        except Exception as exc:
            logger.warning(
                "WPContentStrategistAgent._queue_new_posts failed for account %s: %s",
                account_id, exc,
            )
            try:
                db.session.rollback()
            except Exception:
                pass

        return decisions_made, opportunities_found

    def _queue_refresh_posts(self, account_id: int, site, db) -> tuple:
        """Queue a refresh job for the keyword with the worst rank decline
        over the last two snapshots.

        Returns (decisions_made, opportunities_found).
        """
        from app.models_wp import KeywordRankSnapshot, WPJob

        decisions_made = 0
        opportunities_found = 0

        try:
            # Find keywords that have declined (position increased) between the
            # most recent snapshot and the one before it.
            cutoff = date.today() - timedelta(days=60)
            recent_snaps: List[Any] = (
                KeywordRankSnapshot.query
                .filter(
                    KeywordRankSnapshot.account_id == account_id,
                    KeywordRankSnapshot.snapshot_date >= cutoff,
                    KeywordRankSnapshot.impressions > 20,
                )
                .order_by(
                    KeywordRankSnapshot.keyword,
                    KeywordRankSnapshot.snapshot_date.desc(),
                )
                .all()
            )

            # Group by keyword and compute position delta (latest vs prior).
            from collections import defaultdict
            by_keyword: Dict[str, List[Any]] = defaultdict(list)
            for s in recent_snaps:
                by_keyword[s.keyword].append(s)

            worst_kw: Optional[str] = None
            worst_url: Optional[str] = None
            worst_delta: float = 0.0

            for kw, snaps in by_keyword.items():
                if len(snaps) < 2:
                    continue
                latest = snaps[0]   # desc order → latest first
                prior = snaps[1]
                if latest.position is None or prior.position is None:
                    continue
                delta = float(latest.position) - float(prior.position)
                if delta > worst_delta:
                    worst_delta = delta
                    worst_kw = kw
                    worst_url = latest.url

            if worst_kw and worst_delta > 0:
                opportunities_found = 1
                logger.info(
                    "WPContentStrategistAgent [maintain]: keyword '%s' declined %.1f positions for account %s",
                    worst_kw, worst_delta, account_id,
                )
                # Queue a refresh job (update meta/title via the existing refresh job kind).
                # We pass the keyword so the operator knows why it was queued.
                refresh_payload = {
                    "source": "wp_content_strategist",
                    "primary_keyword": worst_kw,
                    "post_url": worst_url or "",
                    "reason": f"Keyword '{worst_kw}' declined {worst_delta:.1f} positions",
                }
                job = WPJob(site_id=site.id, kind="ai_generate", payload={
                    **refresh_payload,
                    "prompt": (
                        f"Refresh and improve the existing blog post for keyword: '{worst_kw}'. "
                        f"The post at {worst_url or 'this URL'} has slipped in rankings. "
                        f"Rewrite with updated content, better headings, and stronger keyword focus."
                    ),
                    "require_approval": bool(
                        getattr(site, "autopilot_require_approval", True)
                    ),
                    "needs_approval": True,
                    "status": "draft",
                })
                db.session.add(job)
                db.session.commit()
                decisions_made = 1
            else:
                logger.info(
                    "WPContentStrategistAgent [maintain]: no declining keywords found for account %s",
                    account_id,
                )

        except Exception as exc:
            logger.warning(
                "WPContentStrategistAgent._queue_refresh_posts failed for account %s: %s",
                account_id, exc,
            )
            try:
                db.session.rollback()
            except Exception:
                pass

        return decisions_made, opportunities_found
