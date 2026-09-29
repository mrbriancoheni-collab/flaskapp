# app/wp/wp_channel_provider.py
"""
WordPress Channel Provider for the Cross-Channel Strategic Orchestrator.

WordPress is an organic channel: no paid spend, no CPL. Performance is
measured by organic clicks (from Google Search Console / KeywordRankSnapshot).

The provider self-registers with the strategic orchestrator on import.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Dict

logger = logging.getLogger(__name__)


class WPChannelProvider:
    """WordPress organic channel provider.

    Organic channel contract:
        name  = 'wordpress'
        paid  = False              — signals to the orchestrator: no spend / no CPL
        get_performance_summary()  — returns GSC-based organic click count as leads_30d
        apply_directives()         — persists strategy_directive_wordpress to account_settings
    """

    name = 'wordpress'
    paid = False  # organic channel — no budget allocated here

    # ── Performance summary ───────────────────────────────────────────────────

    def get_performance_summary(self, account_id: int) -> Dict[str, Any]:
        """Return a performance summary for the strategic orchestrator.

        Uses KeywordRankSnapshot (GSC clicks) as a proxy for organic leads.
        Falls back to 0 if no GSC data is available — the orchestrator will
        treat this as 'no data' and skip ranking/budget logic for this channel.

        Returns:
            {
                'channel': 'wordpress',
                'name': 'wordpress',        # alias kept for compatibility
                'paid': False,
                'has_data': bool,
                'spend_30d': 0.0,           # organic — no spend
                'leads_30d': int,           # GSC organic clicks as lead proxy
                'cpl': 0.0,                 # no cost per lead for organic
                'available_budget': 0.0,
                'raw': dict,
            }
        """
        clicks_30d = 0
        raw: Dict[str, Any] = {}

        try:
            from app.models_wp import KeywordRankSnapshot
            from sqlalchemy import func
            from app import db

            cutoff = date.today() - timedelta(days=30)
            row = (
                db.session.query(func.sum(KeywordRankSnapshot.clicks))
                .filter(
                    KeywordRankSnapshot.account_id == account_id,
                    KeywordRankSnapshot.snapshot_date >= cutoff,
                )
                .scalar()
            )
            clicks_30d = int(row or 0)
            raw['source'] = 'keyword_rank_snapshots'
            raw['snapshot_clicks_30d'] = clicks_30d
        except Exception as exc:
            logger.warning(
                "WPChannelProvider: KeywordRankSnapshot query failed for account %s: %s",
                account_id, exc,
            )
            try:
                from app import db as _db
                _db.session.rollback()
            except Exception:
                pass
            raw['error'] = str(exc)

        # Also try to count wp_sites rows so has_data reflects whether a WP
        # site is configured even when GSC data is empty.
        has_wp_site = False
        try:
            from app.models_wp import WPSite
            has_wp_site = (
                WPSite.query.filter_by(account_id=account_id).count() > 0
            )
            raw['has_wp_site'] = has_wp_site
        except Exception as exc:
            logger.debug("WPChannelProvider: WPSite check failed for %s: %s", account_id, exc)

        has_data = has_wp_site or clicks_30d > 0

        return {
            'channel': self.name,
            'name': self.name,
            'paid': self.paid,
            'has_data': has_data,
            'spend_30d': 0.0,
            'leads_30d': clicks_30d,
            'cpl': 0.0,
            'available_budget': 0.0,
            'raw': raw,
        }

    # ── Apply directives ──────────────────────────────────────────────────────

    def apply_directives(self, account_id: int, directive: dict) -> None:
        """Persist the strategic directive to account_settings.

        Writes 'strategy_directive_wordpress' so the WP operational agents
        can read the umbrella's decision ('grow' | 'maintain') and rationale.
        """
        from app.services.strategic_orchestrator import _save_setting
        try:
            _save_setting(
                account_id,
                'strategy_directive_wordpress',
                json.dumps({
                    **directive,
                    'channel': self.name,
                }),
            )
        except Exception as exc:
            logger.warning(
                "WPChannelProvider: apply_directives failed for account %s: %s",
                account_id, exc,
            )


# ── Self-register on import ───────────────────────────────────────────────────

provider = WPChannelProvider()

try:
    from app.services.strategic_orchestrator import register_channel
    register_channel(provider)
    logger.debug("WordPress channel provider registered with strategic orchestrator.")
except Exception as _reg_exc:
    logger.warning("WordPress channel provider could not self-register: %s", _reg_exc)
