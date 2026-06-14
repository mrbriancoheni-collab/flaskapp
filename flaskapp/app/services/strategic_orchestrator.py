# app/services/strategic_orchestrator.py
"""
Cross-Channel Strategic Orchestrator — the umbrella that sits ABOVE every
advertising/marketing channel (Google Ads, Facebook Ads, WordPress, …).

Architecture (from the product owner):
    Strategic (this module)  — one global umbrella per account
        ↓ sets per-channel direction (budget allocation, target CPL, priority)
    Operational (per channel) — channel-specific strategy; already consumes the
                                directives this layer writes into account_settings
        ↓
    Tactical (per channel)    — day-to-day execution

Each channel registers a *provider* under the umbrella via register_channel().
A provider is the only contract a new channel has to satisfy; once registered,
the orchestrator can read its performance and push directives down to it without
knowing anything channel-specific. Google's provider is built in below; Facebook
and WordPress providers self-register on import if their modules are present.

The umbrella's decision flows DOWN into a channel's operational layer with zero
changes to those agents: GoogleChannelProvider.apply_directives() writes the
exact account_settings keys (target_cpl, monthly_budget) the existing Google
operational agents already read.

Public surface:
    CHANNEL_REGISTRY                          name -> provider instance
    register_channel(provider)
    run_strategic_orchestrator(account_id) -> {'channels', 'changed', 'summary'}

Channel-provider contract (what future channels implement):
    name: str                                 'google' | 'facebook' | 'wordpress' | ...
    get_performance_summary(account_id) -> dict
        {'channel': name, 'has_data': bool, 'spend_30d': float,
         'leads_30d': int, 'cpl': float|None, 'trend_pct': float}
    apply_directives(account_id, directives) -> None
        directives = {'target_cpl': float, 'monthly_budget': float,
                      'priority': 'grow'|'maintain'|'cut'}
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ── Channel registry ─────────────────────────────────────────────────────────

CHANNEL_REGISTRY: Dict[str, Any] = {}   # name -> provider instance


def register_channel(provider) -> None:
    """Register a channel provider under the strategic umbrella."""
    CHANNEL_REGISTRY[provider.name] = provider


def _load_providers() -> None:
    """Import channel provider modules so they self-register.

    Each import is isolated in its own try/except so a missing or broken channel
    never breaks the orchestrator — the umbrella simply runs over whatever
    channels are present. Google is built in (registered at the bottom of this
    module); Facebook and WordPress are imported here if their modules exist.
    """
    # Google is built into this module and registered at import time. Importing
    # ourselves is a no-op but keeps the intent explicit and order-independent.
    if 'google' not in CHANNEL_REGISTRY:
        try:
            register_channel(GoogleChannelProvider())
        except Exception as exc:
            logger.warning("Google channel provider failed to register: %s", exc)

    try:
        import app.agents.fb_channel_provider  # noqa: F401  (self-registers on import)
    except Exception as exc:
        logger.debug("Facebook channel provider not available: %s", exc)

    try:
        import app.wp.wp_channel_provider  # noqa: F401  (self-registers on import)
    except Exception as exc:
        logger.debug("WordPress channel provider not available: %s", exc)


# ── account_settings helpers (mirror the codebase's existing pattern) ─────────

def _get_settings(account_id: int, keys: List[str]) -> Dict[str, str]:
    """Read a set of account_settings keys. Returns {} on any error."""
    from app import db
    try:
        keys_ph = ", ".join(f"'{k}'" for k in keys)
        sql = text(f"""
            SELECT setting_key, setting_value
            FROM account_settings
            WHERE account_id = :aid AND setting_key IN ({keys_ph})
        """)
        with db.engine.connect() as conn:
            rows = conn.execute(sql, {"aid": account_id})
            return {r.setting_key: r.setting_value for r in rows}
    except Exception as exc:
        logger.warning("Failed to read account_settings for %s: %s", account_id, exc)
        return {}


def _save_setting(account_id: int, key: str, value: str) -> None:
    """Upsert a single key into account_settings, creating the table on first use."""
    from app import db
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
            logger.warning("Failed to save account_setting %s for %s: %s", key, account_id, exc)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ── Google channel provider (built in) ───────────────────────────────────────

class GoogleChannelProvider:
    """Google Ads provider. Reads performance from local gads_stats_daily and
    pushes directives down by writing the account_settings keys the existing
    Google operational agents already consume."""

    name = 'google'

    @staticmethod
    def _window_totals(account_id: int, start: date, end: date) -> Dict[str, Any]:
        """Campaign-level spend/leads for [start, end). Same data source as the
        weekly digest (gads_stats_daily joined to ads_campaigns)."""
        from app import db
        try:
            row = db.session.execute(text("""
                SELECT SUM(gs.cost_micros)/1000000.0 AS spend,
                       SUM(gs.conversions)           AS leads
                FROM gads_stats_daily gs
                JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
                WHERE gs.entity_type = 'campaign'
                  AND gs.date >= :start AND gs.date < :end
            """), {"aid": account_id, "start": start, "end": end}).mappings().one_or_none()
        except Exception as exc:
            logger.warning("Google window totals failed for %s: %s", account_id, exc)
            try:
                db.session.rollback()
            except Exception:
                pass
            return {"spend": 0.0, "leads": 0.0}
        if not row:
            return {"spend": 0.0, "leads": 0.0}
        return {"spend": round(_to_float(row["spend"]), 2),
                "leads": round(_to_float(row["leads"]), 1)}

    def get_performance_summary(self, account_id: int) -> Dict[str, Any]:
        today = date.today()
        d30 = self._window_totals(account_id, today - timedelta(days=30), today)
        spend_30d = d30["spend"]
        leads_30d = int(round(d30["leads"]))
        cpl = round(spend_30d / d30["leads"], 2) if d30["leads"] > 0 else None

        # trend_pct = week-over-week change in CPL (positive = getting worse).
        this_week = self._window_totals(account_id, today - timedelta(days=7), today)
        prior_week = self._window_totals(account_id, today - timedelta(days=14),
                                         today - timedelta(days=7))
        trend_pct = 0.0
        if this_week["leads"] > 0 and prior_week["leads"] > 0:
            this_cpl = this_week["spend"] / this_week["leads"]
            prior_cpl = prior_week["spend"] / prior_week["leads"]
            if prior_cpl > 0:
                trend_pct = round((this_cpl - prior_cpl) / prior_cpl * 100, 1)

        return {
            "channel": self.name,
            "has_data": spend_30d > 0,
            "spend_30d": spend_30d,
            "leads_30d": leads_30d,
            "cpl": cpl,
            "trend_pct": trend_pct,
        }

    def apply_directives(self, account_id: int, directives: Dict[str, Any]) -> None:
        """Write the keys the existing Google operational agents already read.
        This is the entire integration: no changes to those agents are needed."""
        if "target_cpl" in directives and directives["target_cpl"] is not None:
            _save_setting(account_id, "target_cpl",
                          f"{_to_float(directives['target_cpl']):.2f}")
        if "monthly_budget" in directives and directives["monthly_budget"] is not None:
            _save_setting(account_id, "monthly_budget",
                          f"{_to_float(directives['monthly_budget']):.2f}")


# ── Allocation ───────────────────────────────────────────────────────────────

EFFICIENCY_SPREAD = 1.5      # worst CPL must be >= 1.5x best to call a 'cut'
MAX_SHIFT_FRACTION = 0.15    # move at most 15% of total budget grow<-cut


def _money(value: Optional[float]) -> str:
    """Business-owner-friendly money formatting: $61, $300, $1,200."""
    if value is None:
        return "$0"
    return f"${value:,.0f}"


def _rank_and_allocate(summaries: List[Dict[str, Any]],
                       total_budget: float,
                       account_target_cpl: float) -> List[Dict[str, Any]]:
    """Rank channels by efficiency (CPL ascending) and produce a per-channel plan.

    Returns a list of plan dicts, each with: channel, spend_30d, leads_30d, cpl,
    priority, current_budget, new_budget, target_cpl.
    """
    # Current share = each channel's 30-day spend; this is what we rebalance.
    current_total = sum(s["spend_30d"] for s in summaries) or 0.0

    def _budget_share(s: Dict[str, Any]) -> float:
        if current_total <= 0:
            return total_budget / len(summaries) if summaries else 0.0
        return total_budget * (s["spend_30d"] / current_total)

    plans = []
    for s in summaries:
        plans.append({
            "channel": s["channel"],
            "spend_30d": s["spend_30d"],
            "leads_30d": s["leads_30d"],
            "cpl": s["cpl"],
            "trend_pct": s.get("trend_pct", 0.0),
            "priority": "maintain",
            "current_budget": round(_budget_share(s), 2),
            "new_budget": round(_budget_share(s), 2),
            "target_cpl": round(account_target_cpl, 2),
        })

    # Single channel with data: nothing to rebalance against — leave it alone.
    if len(plans) <= 1:
        return plans

    # Rank by CPL ascending; channels with no leads (cpl None) sort last.
    INF = float("inf")
    ranked = sorted(plans, key=lambda p: p["cpl"] if p["cpl"] is not None else INF)
    best = ranked[0]
    worst = ranked[-1]

    best_cpl = best["cpl"]
    worst_cpl = worst["cpl"]

    # Only declare a winner/loser if the spread is material. A channel with no
    # leads at all is always the worst — treat it as a cut candidate if there's
    # a profitable channel to feed.
    spread_material = (
        best_cpl is not None
        and (worst_cpl is None or (best_cpl > 0 and worst_cpl >= EFFICIENCY_SPREAD * best_cpl))
        and best is not worst
    )

    if not spread_material:
        return plans

    best["priority"] = "grow"
    worst["priority"] = "cut"

    # Shift up to 15% of total budget from the cut channel to the grow channel,
    # bounded so the cut channel never goes negative and the total is preserved.
    shift = min(MAX_SHIFT_FRACTION * total_budget, worst["new_budget"])
    shift = round(max(shift, 0.0), 2)
    if shift > 0:
        worst["new_budget"] = round(worst["new_budget"] - shift, 2)
        best["new_budget"] = round(best["new_budget"] + shift, 2)
        best["_shift"] = shift
        worst["_shift"] = shift
        # Remember who funded the grow channel so the rationale can name it.
        best["_from_channel"] = worst["channel"]
        best["_from_cpl"] = worst["cpl"]

    return plans


def _rationale(plan: Dict[str, Any], best: Dict[str, Any]) -> str:
    """One-line plain-English explanation written for a business owner."""
    name = plan["channel"].capitalize()
    cpl = plan["cpl"]
    priority = plan["priority"]
    shift = plan.get("_shift")

    if priority == "grow" and shift:
        from_channel = plan.get("_from_channel")
        from_cpl = plan.get("_from_cpl")
        if from_channel and cpl is not None and from_cpl is not None:
            return (f"{name} is getting leads at {_money(cpl)} vs "
                    f"{from_channel.capitalize()}'s {_money(from_cpl)} — "
                    f"shifting {_money(shift)}/mo toward {name}.")
        if from_channel and cpl is not None:
            return (f"{name} is getting leads at {_money(cpl)} each while "
                    f"{from_channel.capitalize()} has none — "
                    f"shifting {_money(shift)}/mo toward {name}.")
        return (f"{name} is your most efficient channel right now, "
                f"so we're adding {_money(shift)}/mo to it.")

    if priority == "cut" and shift:
        if cpl is None:
            return (f"{name} hasn't produced any leads in the last 30 days, "
                    f"so we're moving {_money(shift)}/mo to a channel that is.")
        return (f"{name} is costing {_money(cpl)} per lead — more than your other channels — "
                f"so we're moving {_money(shift)}/mo away from it for now.")

    if cpl is not None:
        return f"{name} is steady at {_money(cpl)} per lead — keeping its budget where it is."
    if plan["spend_30d"] > 0:
        return f"{name} is spending but hasn't shown leads yet — holding its budget while it ramps."
    return f"{name} is holding steady for now."


# ── Orchestrator ─────────────────────────────────────────────────────────────

def run_strategic_orchestrator(account_id: int) -> Dict[str, Any]:
    """The weekly umbrella pass for one account.

    Gathers each channel's performance, ranks them by efficiency, shifts budget
    from the weakest toward the strongest, pushes the resulting directives down
    into each channel's operational layer, and records a cross-channel summary.
    """
    _load_providers()

    # 1. Gather performance from every registered provider; keep those with data.
    summaries: List[Dict[str, Any]] = []
    for provider in list(CHANNEL_REGISTRY.values()):
        try:
            summary = provider.get_performance_summary(account_id)
        except Exception as exc:
            logger.warning("Channel %s performance summary failed for account %s: %s",
                           getattr(provider, "name", "?"), account_id, exc)
            continue
        if summary and summary.get("has_data"):
            summaries.append(summary)

    channels_with_data = len(summaries)

    if channels_with_data == 0:
        _log_execution(account_id, opportunities=0, decisions=0)
        return {"channels": 0, "changed": 0, "summary": []}

    # 2. Total monthly budget: explicit total -> single-channel budget -> sum of
    #    current 30-day spend. Account target CPL defaults to 80.
    acct = _get_settings(account_id, ["total_monthly_budget", "monthly_budget", "target_cpl"])
    total_budget = _to_float(acct.get("total_monthly_budget"), 0.0)
    if total_budget <= 0:
        total_budget = _to_float(acct.get("monthly_budget"), 0.0)
    if total_budget <= 0:
        total_budget = round(sum(s["spend_30d"] for s in summaries), 2)
    account_target_cpl = _to_float(acct.get("target_cpl"), 80.0)
    if account_target_cpl <= 0:
        account_target_cpl = 80.0

    # 3. Rank + allocate.
    plans = _rank_and_allocate(summaries, total_budget, account_target_cpl)

    # Identify the best (lowest-CPL) channel for rationale phrasing.
    ranked = sorted(
        plans,
        key=lambda p: p["cpl"] if p["cpl"] is not None else float("inf"),
    )
    best = ranked[0] if ranked else None

    # 4. Push directives down to each channel + persist per-channel directive.
    changed = 0
    summary_out: List[Dict[str, Any]] = []
    for plan in plans:
        provider = CHANNEL_REGISTRY.get(plan["channel"])
        budget_changed = abs(plan["new_budget"] - plan["current_budget"]) >= 0.01
        priority_changed = plan["priority"] != "maintain"
        if budget_changed or priority_changed:
            changed += 1

        directives = {
            "target_cpl": plan["target_cpl"],
            "monthly_budget": plan["new_budget"],
            "priority": plan["priority"],
        }
        if provider is not None:
            try:
                provider.apply_directives(account_id, directives)
            except Exception as exc:
                logger.warning("apply_directives failed for channel %s account %s: %s",
                               plan["channel"], account_id, exc)

        rationale = _rationale(plan, best)
        _save_setting(
            account_id,
            f"strategy_directive_{plan['channel']}",
            json.dumps({**directives, "rationale": rationale,
                        "updated_at": datetime.utcnow().isoformat()}),
        )

        summary_out.append({
            "channel": plan["channel"],
            "spend_30d": plan["spend_30d"],
            "leads_30d": plan["leads_30d"],
            "cpl": plan["cpl"],
            "priority": plan["priority"],
            "current_budget": plan["current_budget"],
            "new_budget": plan["new_budget"],
            "target_cpl": plan["target_cpl"],
            "rationale": rationale,
        })

    # 5. Persist the cross-channel summary.
    _save_setting(account_id, "strategic_orchestration", json.dumps({
        "account_id": account_id,
        "total_monthly_budget": total_budget,
        "account_target_cpl": round(account_target_cpl, 2),
        "channels": summary_out,
        "channels_with_data": channels_with_data,
        "changed": changed,
        "generated_at": datetime.utcnow().isoformat(),
    }))

    # 6. Log to agent_execution_log (strategic layer).
    _log_execution(account_id, opportunities=channels_with_data, decisions=changed)

    # 7. Return.
    return {"channels": channels_with_data, "changed": changed, "summary": summary_out}


def _log_execution(account_id: int, opportunities: int, decisions: int) -> None:
    """Log a StrategicOrchestrator run reusing the Google scheduler's INSERT shape."""
    from app import db
    try:
        with db.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_execution_log
                (account_id, agent_id, agent_type, cycle_start, cycle_duration_seconds,
                 opportunities_found, decisions_made, auto_executed, pending_approval, status)
                VALUES
                (:account_id, :agent_id, :agent_type, :cycle_start, :cycle_duration,
                 :opportunities, :decisions, :auto_exec, :pending, :status)
            """), {
                "account_id": account_id,
                "agent_id": "strategic_orchestrator",
                "agent_type": "StrategicOrchestrator",
                "cycle_start": datetime.utcnow(),
                "cycle_duration": None,
                "opportunities": opportunities,
                "decisions": decisions,
                "auto_exec": decisions,
                "pending": 0,
                "status": "completed",
            })
    except Exception as exc:
        logger.warning("Failed to log StrategicOrchestrator run for %s: %s", account_id, exc)


# Register the built-in Google channel provider at import.
register_channel(GoogleChannelProvider())
