# app/services/google_ads_digest.py
"""
Weekly Plain-English Performance Digest.

Generates a weekly summary written the way a human account manager would
explain it to a business owner: spend, leads, cost per lead with
week-over-week comparisons, what the AI agent did, and what to do next.

generate_weekly_digest(account_id) computes the numbers for the last 7 full
days vs the prior 7 days and stores the result in gads_weekly_digests.
render_digest_text(digest) turns those numbers into plain-English sentences
used by both the weekly email and the cockpit card.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS gads_weekly_digests (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    account_id  INT        NOT NULL,
    week_start  DATE       NOT NULL,
    digest_json MEDIUMTEXT NOT NULL,
    created_at  DATETIME   NOT NULL,
    UNIQUE KEY uq_digest_account_week (account_id, week_start),
    KEY ix_digest_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _ensure_table() -> None:
    from app import db
    try:
        with db.engine.begin() as conn:
            conn.execute(text(TABLE_DDL))
    except Exception as exc:
        logger.warning("gads_weekly_digests table creation failed: %s", exc)


# ── Generation ───────────────────────────────────────────────────────────────

def _week_totals(account_id: int, start: date, end: date) -> Optional[Dict[str, Any]]:
    """Campaign-level totals for [start, end). Returns None if no rows at all."""
    from app import db
    row = db.session.execute(text("""
        SELECT SUM(gs.cost_micros)/1000000.0 AS spend,
               SUM(gs.clicks)               AS clicks,
               SUM(gs.conversions)          AS leads,
               COUNT(*)                     AS row_count
        FROM gads_stats_daily gs
        JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
        WHERE gs.entity_type = 'campaign'
          AND gs.date >= :start AND gs.date < :end
    """), {"aid": account_id, "start": start, "end": end}).mappings().one_or_none()

    if not row or not row["row_count"]:
        return None

    spend = round(float(row["spend"] or 0), 2)
    clicks = int(row["clicks"] or 0)
    leads = round(float(row["leads"] or 0), 1)
    return {
        "spend": spend,
        "clicks": clicks,
        "leads": leads,
        "cost_per_lead": round(spend / leads, 2) if leads > 0 else None,
    }


def _pct_change(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    if current is None or prior is None or prior <= 0:
        return None
    return round((current - prior) / prior * 100, 1)


def _agent_activity(account_id: int, start: datetime, end: datetime) -> Dict[str, Any]:
    from app import db
    actions: Dict[str, int] = {}
    savings = 0.0
    try:
        rows = db.session.execute(text("""
            SELECT action_type, COUNT(*) AS cnt,
                   SUM(COALESCE(estimated_monthly_savings, 0)) AS savings
            FROM ai_actions
            WHERE account_id = :aid
              AND created_at >= :start AND created_at < :end
              AND status NOT IN ('failed', 'undone', 'rejected', 'dismissed')
            GROUP BY action_type
        """), {"aid": account_id, "start": start, "end": end}).mappings().all()
        for r in rows:
            actions[r["action_type"]] = int(r["cnt"] or 0)
            savings += float(r["savings"] or 0)
    except Exception:
        db.session.rollback()
    return {
        "actions": actions,
        "total_actions": sum(actions.values()),
        "estimated_monthly_savings": round(savings, 2),
    }


def _top_and_waster(account_id: int, start: date, end: date):
    from app import db
    top_keyword = None
    biggest_waster = None
    try:
        rows = db.session.execute(text("""
            SELECT k.text AS kw_text,
                   SUM(gs.cost_micros)/1000000.0 AS spend,
                   SUM(gs.conversions)           AS leads,
                   SUM(gs.clicks)                AS clicks
            FROM gads_stats_daily gs
            JOIN keywords k ON k.id = gs.entity_id
            JOIN ad_groups ag ON ag.id = k.ad_group_id
            JOIN ads_campaigns ac ON ac.id = ag.campaign_id
            WHERE gs.entity_type = 'keyword'
              AND ac.account_id = :aid
              AND gs.date >= :start AND gs.date < :end
            GROUP BY k.id, k.text
        """), {"aid": account_id, "start": start, "end": end}).mappings().all()

        converters = [r for r in rows if float(r["leads"] or 0) > 0]
        if converters:
            best = max(converters, key=lambda r: (float(r["leads"]), -float(r["spend"] or 0)))
            spend = round(float(best["spend"] or 0), 2)
            leads = round(float(best["leads"]), 1)
            top_keyword = {
                "text": best["kw_text"],
                "leads": leads,
                "spend": spend,
                "cost_per_lead": round(spend / leads, 2) if leads > 0 else None,
            }

        wasters = [r for r in rows
                   if float(r["leads"] or 0) == 0 and float(r["spend"] or 0) >= 1]
        if wasters:
            worst = max(wasters, key=lambda r: float(r["spend"]))
            biggest_waster = {
                "text": worst["kw_text"],
                "spend": round(float(worst["spend"]), 2),
                "clicks": int(worst["clicks"] or 0),
            }
    except Exception:
        db.session.rollback()
    return top_keyword, biggest_waster


def _next_steps(account_id: int) -> List[Dict[str, Any]]:
    from app import db
    steps: List[Dict[str, Any]] = []
    try:
        rows = db.session.execute(text("""
            SELECT title, expected_impact, category
            FROM optimizer_recommendations
            WHERE account_id = :aid AND status = 'open'
            ORDER BY severity ASC, id DESC
            LIMIT 3
        """), {"aid": account_id}).mappings().all()
        steps = [{"title": r["title"],
                  "expected_impact": r["expected_impact"],
                  "category": r["category"]} for r in rows]
    except Exception:
        db.session.rollback()
    return steps


def generate_weekly_digest(account_id: int) -> Dict[str, Any]:
    """
    Compute the digest for the last 7 full days vs the prior 7 days,
    store it in gads_weekly_digests, and return the digest dict.
    """
    today = date.today()
    week_start = today - timedelta(days=7)
    prior_start = today - timedelta(days=14)

    this_week = _week_totals(account_id, week_start, today)
    prior_week = _week_totals(account_id, prior_start, week_start)

    had_data = this_week is not None
    if this_week is None:
        this_week = {"spend": 0.0, "clicks": 0, "leads": 0.0, "cost_per_lead": None}

    deltas = {
        "spend_pct": _pct_change(this_week["spend"], prior_week["spend"] if prior_week else None),
        "leads_pct": _pct_change(this_week["leads"], prior_week["leads"] if prior_week else None),
        "cpl_pct": _pct_change(
            this_week["cost_per_lead"],
            prior_week["cost_per_lead"] if prior_week else None,
        ),
    }

    top_keyword, biggest_waster = _top_and_waster(account_id, week_start, today)

    digest = {
        "account_id": account_id,
        "week_start": week_start.isoformat(),
        "week_end": (today - timedelta(days=1)).isoformat(),
        "has_data": had_data,
        "this_week": this_week,
        "prior_week": prior_week,
        "deltas": deltas,
        "agent": _agent_activity(
            account_id,
            datetime.combine(week_start, datetime.min.time()),
            datetime.combine(today, datetime.min.time()),
        ),
        "top_keyword": top_keyword,
        "biggest_waster": biggest_waster,
        "next_steps": _next_steps(account_id),
        "generated_at": datetime.utcnow().isoformat(),
    }

    _store_digest(account_id, week_start, digest)
    return digest


def _store_digest(account_id: int, week_start: date, digest: Dict[str, Any]) -> None:
    from app import db
    _ensure_table()
    try:
        with db.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO gads_weekly_digests (account_id, week_start, digest_json, created_at)
                VALUES (:aid, :ws, :dj, UTC_TIMESTAMP())
                ON DUPLICATE KEY UPDATE
                    digest_json = VALUES(digest_json),
                    created_at = VALUES(created_at)
            """), {"aid": account_id, "ws": week_start, "dj": json.dumps(digest)})
    except Exception as exc:
        logger.warning("Failed to store weekly digest for account %s: %s", account_id, exc)


def get_latest_digest(account_id: int) -> Optional[Dict[str, Any]]:
    """Return {'week_start', 'created_at', 'digest'} for the newest stored digest."""
    from app import db
    try:
        row = db.session.execute(text("""
            SELECT week_start, digest_json, created_at
            FROM gads_weekly_digests
            WHERE account_id = :aid
            ORDER BY week_start DESC
            LIMIT 1
        """), {"aid": account_id}).mappings().one_or_none()
        if not row:
            return None
        return {
            "week_start": row["week_start"],
            "created_at": row["created_at"],
            "digest": json.loads(row["digest_json"]),
        }
    except Exception:
        db.session.rollback()
        return None


# ── Plain-English rendering ──────────────────────────────────────────────────

def _money(value: Optional[float]) -> str:
    if value is None:
        return "$0"
    if value >= 20:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def _leads_int(value) -> int:
    return int(round(float(value or 0)))


def _plural(n: int, singular: str, plural: Optional[str] = None) -> str:
    return singular if n == 1 else (plural or singular + "s")


def render_digest_text(digest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Turn digest numbers into plain-English sentences:
    {"headline": str, "summary_lines": [str], "agent_lines": [str], "next_steps": [str]}
    """
    tw = digest.get("this_week") or {}
    pw = digest.get("prior_week")
    deltas = digest.get("deltas") or {}
    spend = float(tw.get("spend") or 0)
    leads = _leads_int(tw.get("leads"))
    clicks = int(tw.get("clicks") or 0)
    cpl = tw.get("cost_per_lead")

    if spend <= 0 and leads == 0:
        headline = "Your ads didn't run last week."
    elif leads > 0:
        headline = (
            f"Last week you spent {_money(spend)} and got {leads} "
            f"{_plural(leads, 'lead')} — about {_money(cpl)} each."
        )
    else:
        headline = (
            f"Last week you spent {_money(spend)} and got {clicks} "
            f"{_plural(clicks, 'click')}, but no leads came through yet."
        )

    summary_lines: List[str] = []

    if spend <= 0 and leads == 0:
        summary_lines.append(
            "No money was spent on ads last week. If that's unexpected, "
            "check that your campaigns are turned on and have budget."
        )
    elif pw is None:
        summary_lines.append(
            "This was your first full week of data, so there's nothing to compare against yet. "
            "Next week's report will show how things are trending."
        )
    else:
        cpl_pct = deltas.get("cpl_pct")
        if cpl_pct is not None and abs(cpl_pct) >= 1:
            if cpl_pct < 0:
                summary_lines.append(
                    f"That's {abs(cpl_pct):.0f}% cheaper per lead than the week before — nice."
                )
            else:
                summary_lines.append(
                    f"Each lead cost about {cpl_pct:.0f}% more than the week before. "
                    "One week isn't a trend, but worth keeping an eye on."
                )

        prior_leads = _leads_int(pw.get("leads"))
        lead_diff = leads - prior_leads
        if lead_diff > 0:
            summary_lines.append(
                f"You got {lead_diff} more {_plural(lead_diff, 'lead')} than the week before "
                f"({prior_leads} → {leads})."
            )
        elif lead_diff < 0:
            summary_lines.append(
                f"You got {abs(lead_diff)} fewer {_plural(abs(lead_diff), 'lead')} than the week before "
                f"({prior_leads} → {leads}). Some weeks are just slower — "
                "the next steps below can help."
            )
        elif leads > 0:
            summary_lines.append(
                f"Lead count held steady at {leads} — consistent weeks are a good sign."
            )

        spend_diff = spend - float(pw.get("spend") or 0)
        if abs(spend_diff) >= 1:
            direction = "more" if spend_diff > 0 else "less"
            summary_lines.append(
                f"You spent {_money(abs(spend_diff))} {direction} than the week before."
            )

    top_kw = digest.get("top_keyword")
    if top_kw and _leads_int(top_kw.get("leads")) > 0:
        kw_leads = _leads_int(top_kw.get("leads"))
        summary_lines.append(
            f'Your best keyword was "{top_kw["text"]}" — it brought in {kw_leads} '
            f"{_plural(kw_leads, 'lead')} for {_money(top_kw.get('spend'))}."
        )

    waster = digest.get("biggest_waster")
    if waster:
        summary_lines.append(
            f'Biggest money-waster: "{waster["text"]}" spent {_money(waster.get("spend"))} '
            "without bringing in a single lead. Worth pausing if it keeps that up."
        )

    agent = digest.get("agent") or {}
    actions = agent.get("actions") or {}
    agent_lines: List[str] = []

    junk = actions.get("negative_keyword_added", 0) + actions.get("search_term_blocked", 0)
    if junk:
        agent_lines.append(
            f"Your AI agent blocked {junk} junk {_plural(junk, 'search', 'searches')} "
            "so you stop paying for clicks that never turn into work."
        )

    kw_paused = actions.get("keyword_paused", 0)
    if kw_paused:
        agent_lines.append(
            f"It paused {kw_paused} {_plural(kw_paused, 'keyword')} that "
            f"{'was' if kw_paused == 1 else 'were'} wasting money."
        )

    ads_paused = actions.get("ad_paused", 0) + actions.get("campaign_paused", 0)
    if ads_paused:
        agent_lines.append(
            f"It paused {ads_paused} underperforming {_plural(ads_paused, 'ad')} "
            "to focus your budget on what works."
        )

    bids = actions.get("bid_adjusted", 0)
    if bids:
        agent_lines.append(
            f"It fine-tuned bids {bids} {_plural(bids, 'time')} to get more out of your budget."
        )

    budget_moves = actions.get("budget_reallocated", 0)
    if budget_moves:
        agent_lines.append(
            f"It moved budget toward your better-performing campaigns "
            f"{budget_moves} {_plural(budget_moves, 'time')}."
        )

    counted = junk + kw_paused + ads_paused + bids + budget_moves
    other = max(0, int(agent.get("total_actions") or 0) - counted)
    if other:
        agent_lines.append(
            f"It made {other} other small {_plural(other, 'improvement')} behind the scenes."
        )

    savings = float(agent.get("estimated_monthly_savings") or 0)
    if savings >= 1:
        agent_lines.append(
            f"All together, that's saving you an estimated {_money(savings)}/month."
        )

    if not agent_lines:
        agent_lines.append(
            "Your AI agent didn't need to make any changes last week — things looked steady."
        )

    next_steps: List[str] = []
    for step in (digest.get("next_steps") or [])[:3]:
        line = step.get("title") or ""
        impact = step.get("expected_impact")
        if impact:
            line = f"{line} ({impact})"
        if line:
            next_steps.append(line)

    return {
        "headline": headline,
        "summary_lines": summary_lines,
        "agent_lines": agent_lines,
        "next_steps": next_steps,
    }
