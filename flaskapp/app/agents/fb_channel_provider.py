# app/agents/fb_channel_provider.py
"""
Facebook channel provider for the cross-channel strategic orchestrator.

Implements the channel-provider contract defined in
app/services/strategic_orchestrator.py so the umbrella can:
  - read Facebook's 30-day performance (spend, leads, CPL)
  - push directives (budget shift, action) back down into the Facebook
    operational layer via account_settings

Registration happens automatically at module import time via the call to
register_channel() at the bottom of this file. The orchestrator's
_load_providers() does:
    import app.agents.fb_channel_provider   # self-registers
so there is nothing else to wire up.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Maximum monthly budget cap (safety ceiling for 'grow' directives)
_MAX_MONTHLY_BUDGET = 50_000.0


class FBChannelProvider:
    """Facebook Ads channel provider for the strategic orchestrator umbrella."""

    name = 'facebook'
    paid = True

    # ------------------------------------------------------------------ #
    # Performance summary                                                  #
    # ------------------------------------------------------------------ #

    def get_performance_summary(self, account_id: int) -> Dict[str, Any]:
        """Return 30-day Facebook performance for this account.

        Queries FBDailyInsight rows (written by fbads_sync), reads the
        configured monthly budget from account_settings, and returns the
        standard provider summary dict.

        Returns:
            {
                'channel': 'facebook',
                'has_data': bool,
                'spend_30d': float,
                'leads_30d': int,
                'cpl': float | None,
                'trend_pct': float,
                'available_budget': float,
                'name': 'facebook',
                'paid': True,
                'raw': dict,
            }
        """
        today = date.today()
        start_30d = today - timedelta(days=30)

        spend_30d = 0.0
        leads_30d = 0
        raw: Dict[str, Any] = {}

        try:
            from app.models_fbads import FBDailyInsight
            from app import db
            from sqlalchemy import text

            row = db.session.execute(text("""
                SELECT
                    COALESCE(SUM(spend), 0)  AS spend,
                    COALESCE(SUM(leads), 0)  AS leads
                FROM fb_daily_insights
                WHERE account_id = :aid
                  AND date >= :start
                  AND date < :end
            """), {"aid": account_id, "start": start_30d, "end": today}).mappings().one_or_none()

            if row:
                spend_30d = float(row["spend"] or 0)
                leads_30d = int(round(float(row["leads"] or 0)))

            raw = {"spend_30d": spend_30d, "leads_30d": leads_30d}

        except Exception as exc:
            logger.warning("FBChannelProvider: failed to read fb_daily_insights for account %s: %s",
                           account_id, exc)
            try:
                from app import db
                db.session.rollback()
            except Exception:
                pass

        cpl = round(spend_30d / leads_30d, 2) if leads_30d > 0 else None

        # Week-over-week CPL trend (positive = CPL getting worse)
        trend_pct = self._cpl_trend(account_id, today)

        # Available budget from account_settings
        available_budget = self._read_monthly_budget(account_id)

        return {
            "channel": self.name,
            "name": self.name,
            "paid": self.paid,
            "has_data": spend_30d > 0,
            "spend_30d": round(spend_30d, 2),
            "leads_30d": leads_30d,
            "cpl": cpl,
            "trend_pct": trend_pct,
            "available_budget": available_budget,
            "raw": raw,
        }

    def _cpl_trend(self, account_id: int, today: date) -> float:
        """Return week-over-week CPL change percent (positive = CPL rose = worse)."""
        try:
            from app import db
            from sqlalchemy import text

            def _window(start: date, end: date):
                r = db.session.execute(text("""
                    SELECT
                        COALESCE(SUM(spend), 0) AS spend,
                        COALESCE(SUM(leads), 0) AS leads
                    FROM fb_daily_insights
                    WHERE account_id = :aid
                      AND date >= :start AND date < :end
                """), {"aid": account_id, "start": start, "end": end}).mappings().one_or_none()
                return (float(r["spend"] or 0), int(float(r["leads"] or 0))) if r else (0.0, 0)

            this_spend, this_leads = _window(today - timedelta(days=7), today)
            prev_spend, prev_leads = _window(today - timedelta(days=14), today - timedelta(days=7))

            if this_leads > 0 and prev_leads > 0:
                this_cpl = this_spend / this_leads
                prev_cpl = prev_spend / prev_leads
                if prev_cpl > 0:
                    return round((this_cpl - prev_cpl) / prev_cpl * 100, 1)
        except Exception as exc:
            logger.debug("FBChannelProvider: CPL trend calc failed for %s: %s", account_id, exc)
            try:
                from app import db
                db.session.rollback()
            except Exception:
                pass
        return 0.0

    def _read_monthly_budget(self, account_id: int) -> float:
        """Read fb_monthly_budget from account_settings. Returns 0.0 if absent."""
        try:
            from app import db
            from sqlalchemy import text

            row = db.session.execute(text("""
                SELECT setting_value
                FROM account_settings
                WHERE account_id = :aid AND setting_key = 'fb_monthly_budget'
                LIMIT 1
            """), {"aid": account_id}).mappings().one_or_none()

            if row and row["setting_value"]:
                return float(row["setting_value"])
        except Exception as exc:
            logger.debug("FBChannelProvider: failed to read fb_monthly_budget for %s: %s",
                         account_id, exc)
            try:
                from app import db
                db.session.rollback()
            except Exception:
                pass
        return 0.0

    # ------------------------------------------------------------------ #
    # Directives                                                           #
    # ------------------------------------------------------------------ #

    def apply_directives(self, account_id: int, directive: Dict[str, Any]) -> None:
        """Apply orchestrator directives to the Facebook channel.

        Reads directive keys:
            action ('grow' | 'cut' | 'maintain')
            budget_shift_amount (float, optional)
            monthly_budget (float, optional — direct new target from planner)
            target_cpl (float, optional)
            rationale (str, optional)

        Saves:
            strategy_directive_facebook — full directive JSON
            fb_monthly_budget — adjusted budget (if action is grow/cut)
            fb_target_cpl — updated target CPL (if provided)
        """
        import json
        from datetime import datetime

        action = directive.get("action") or directive.get("priority", "maintain")
        budget_shift = float(directive.get("budget_shift_amount", 0) or 0)

        # If the planner provided an explicit new_budget / monthly_budget use it
        # directly; otherwise compute from the shift delta.
        new_budget_explicit = directive.get("monthly_budget") or directive.get("new_budget")

        if new_budget_explicit is not None:
            new_budget = float(new_budget_explicit)
        else:
            current_budget = self._read_monthly_budget(account_id)
            if action == "grow":
                new_budget = current_budget + budget_shift
            elif action == "cut":
                new_budget = max(0.0, current_budget - budget_shift)
            else:
                new_budget = current_budget  # maintain — leave unchanged

        # Safety ceiling
        new_budget = min(new_budget, _MAX_MONTHLY_BUDGET)

        # Persist directive JSON so the FB scheduler can read it
        _save_setting(account_id, "strategy_directive_facebook", json.dumps({
            **directive,
            "action": action,
            "updated_at": datetime.utcnow().isoformat(),
        }))

        # Update budget if meaningful change
        if new_budget_explicit is not None or budget_shift > 0 or action in ("grow", "cut"):
            _save_setting(account_id, "fb_monthly_budget", f"{new_budget:.2f}")

        # Update target CPL if provided
        target_cpl = directive.get("target_cpl")
        if target_cpl is not None:
            _save_setting(account_id, "fb_target_cpl", f"{float(target_cpl):.2f}")

        logger.info(
            "FBChannelProvider: account %s — action=%s new_budget=%.2f",
            account_id, action, new_budget,
        )


# ── Shared account_settings helper (mirrors strategic_orchestrator.py) ────────

def _save_setting(account_id: int, key: str, value: str) -> None:
    """Upsert a single key into account_settings."""
    from app import db
    from sqlalchemy import text

    sql = text("""
        INSERT INTO account_settings (account_id, setting_key, setting_value)
        VALUES (:aid, :key, :val)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
    """)
    try:
        with db.engine.begin() as conn:
            conn.execute(sql, {"aid": account_id, "key": key, "val": value})
    except Exception as exc:
        err = str(exc).lower()
        if "doesn't exist" in err or "no such table" in err:
            # Table may not yet exist — create it then retry
            with db.engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS account_settings (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        account_id INT NOT NULL,
                        setting_key VARCHAR(100) NOT NULL,
                        setting_value TEXT,
                        UNIQUE KEY uq_account_setting (account_id, setting_key)
                    )
                """))
                conn.execute(sql, {"aid": account_id, "key": key, "val": value})
        else:
            logger.warning("_save_setting failed (%s / %s): %s", account_id, key, exc)


# ── Self-register with the strategic orchestrator ─────────────────────────────

provider = FBChannelProvider()

try:
    from app.services.strategic_orchestrator import register_channel
    register_channel(provider)
    logger.debug("FBChannelProvider registered with strategic orchestrator")
except Exception as _reg_exc:
    logger.warning("FBChannelProvider: could not register with orchestrator: %s", _reg_exc)
