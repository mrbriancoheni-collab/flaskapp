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
import re
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


def _week_totals_by_type(account_id: int, start: date, end: date) -> List[Dict[str, Any]]:
    """Per campaign_type totals for [start, end). Returns list sorted by spend desc."""
    from app import db
    try:
        rows = db.session.execute(text("""
            SELECT COALESCE(ac.campaign_type, 'UNKNOWN') AS campaign_type,
                   COUNT(DISTINCT ac.id)                 AS campaign_count,
                   SUM(gs.cost_micros)/1000000.0         AS spend,
                   SUM(gs.clicks)                        AS clicks,
                   SUM(gs.conversions)                   AS leads
            FROM gads_stats_daily gs
            JOIN ads_campaigns ac ON ac.id = gs.entity_id AND ac.account_id = :aid
            WHERE gs.entity_type = 'campaign'
              AND gs.date >= :start AND gs.date < :end
            GROUP BY COALESCE(ac.campaign_type, 'UNKNOWN')
            ORDER BY spend DESC
        """), {"aid": account_id, "start": start, "end": end}).mappings().all()

        from app.services.google_ads_type_benchmarks import get_halo_pct
        result = []
        for r in rows:
            spend = round(float(r["spend"] or 0), 2)
            leads = round(float(r["leads"] or 0), 1)
            ct = r["campaign_type"]
            result.append({
                "campaign_type":    ct,
                "campaign_count":   int(r["campaign_count"] or 0),
                "spend":            spend,
                "clicks":           int(r["clicks"] or 0),
                "leads":            leads,
                "cost_per_lead":    round(spend / leads, 2) if leads > 0 else None,
                "halo_pct":         get_halo_pct(ct),
            })
        return result
    except Exception:
        db.session.rollback()
        return []


def _new_customer_pct(account_id: int, start: date, end: date) -> Optional[float]:
    """
    Returns % of ServiceTitan revenue in the period that came from new customers.
    Returns None if ServiceTitan data is not available.
    """
    from app import db
    try:
        job_rows = db.session.execute(text("""
            SELECT j.st_customer_id,
                   COALESCE(j.total_amount, 0) AS revenue
            FROM servicetitan_jobs j
            WHERE j.account_id = :aid
              AND j.job_status IN ('Completed', 'completed', 'Done', 'done')
              AND j.completed_date >= :s AND j.completed_date < :e
        """), {"aid": account_id, "s": start, "e": end}).mappings().all()

        if not job_rows:
            return None

        cust_ids = list({r["st_customer_id"] for r in job_rows if r["st_customer_id"]})
        if not cust_ids:
            return None

        placeholders = ",".join([f":c{i}" for i in range(len(cust_ids))])
        params = {"aid": account_id, "s": str(start)}
        params.update({f"c{i}": cid for i, cid in enumerate(cust_ids)})
        repeat_rows = db.session.execute(text(f"""
            SELECT DISTINCT st_customer_id
            FROM servicetitan_jobs
            WHERE account_id = :aid
              AND st_customer_id IN ({placeholders})
              AND job_status IN ('Completed', 'completed', 'Done', 'done')
              AND completed_date < :s
        """), params).fetchall()
        repeat_set = {r[0] for r in repeat_rows}

        total_rev = new_rev = 0.0
        for r in job_rows:
            rev = float(r["revenue"] or 0)
            total_rev += rev
            if r["st_customer_id"] not in repeat_set:
                new_rev += rev

        return round(new_rev / total_rev * 100, 1) if total_rev > 0 else None
    except Exception:
        db.session.rollback()
        return None


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
    by_type = _week_totals_by_type(account_id, week_start, today)
    new_cust_pct = _new_customer_pct(account_id, week_start, today)

    # Dominant-type halo estimate: use the type with the most spend
    halo_estimate_pct = None
    if by_type:
        dom = by_type[0]
        halo_estimate_pct = dom.get("halo_pct")

    digest = {
        "account_id": account_id,
        "week_start": week_start.isoformat(),
        "week_end": (today - timedelta(days=1)).isoformat(),
        "has_data": had_data,
        "this_week": this_week,
        "prior_week": prior_week,
        "deltas": deltas,
        "by_type": by_type,
        "new_customer_pct": new_cust_pct,
        "halo_estimate_pct": halo_estimate_pct,
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

    # Campaign triage — surfaces per-campaign action items for the digest
    try:
        from app.campaign_health.triage import run_triage, triage_summary_text
        triage = run_triage(account_id)
        digest["campaign_triage"] = {
            "needs_action": triage["summary"]["needs_action"],
            "total":        triage["summary"]["total"],
            "actions_needed": triage["actions_needed"][:5],
            "summary_text": triage_summary_text(triage),
        }
    except Exception:
        logger.warning("campaign triage failed for account %s — skipping", account_id, exc_info=True)

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

    # New-customer percentage from ServiceTitan
    new_cust_pct = digest.get("new_customer_pct")
    if new_cust_pct is not None:
        if new_cust_pct >= 50:
            summary_lines.append(
                f"{new_cust_pct:.0f}% of this week's ServiceTitan revenue came from new customers — "
                "your ads are driving healthy new business growth."
            )
        elif new_cust_pct >= 25:
            summary_lines.append(
                f"{new_cust_pct:.0f}% of this week's ServiceTitan revenue was from new customers. "
                "Your repeat customer base is strong — keep an eye on new-customer campaigns to maintain flow."
            )
        else:
            summary_lines.append(
                f"Only {new_cust_pct:.0f}% of this week's ServiceTitan revenue was from new customers. "
                "Your business is leaning toward repeat customers — consider increasing new-customer campaign budget."
            )

    # Halo estimate note for upper-funnel campaigns
    halo_pct = digest.get("halo_estimate_pct")
    if halo_pct:
        summary_lines.append(
            f"Note: {halo_pct:.0f}% of the value from your dominant campaign type may show up "
            f"off-platform (search, direct, organic) rather than in last-click conversions. "
            f"Your true ROAS is likely higher than reported."
        )

    # Campaign type breakdown (top 3 types by spend)
    by_type = digest.get("by_type") or []
    if len(by_type) > 1:
        type_parts = []
        for t in by_type[:3]:
            ct = t.get("campaign_type", "UNKNOWN")
            sp = _money(t.get("spend"))
            lds = _leads_int(t.get("leads"))
            type_parts.append(f"{ct}: {sp}" + (f", {lds} leads" if lds > 0 else ""))
        summary_lines.append("By campaign type — " + " · ".join(type_parts) + ".")

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

    # Campaign triage lines
    triage_lines: List[str] = []
    triage = digest.get("campaign_triage") or {}
    if triage.get("needs_action", 0) > 0:
        triage_lines.append(triage.get("summary_text", ""))

    return {
        "headline": headline,
        "summary_lines": summary_lines,
        "agent_lines": agent_lines,
        "next_steps": next_steps,
        "triage_lines": triage_lines,
    }


# ── Structured digest with number check (Item 2) ─────────────────────────────

def _confidence_score(digest: Dict[str, Any]) -> float:
    """
    0.0–1.0 reflecting how much data backs this digest.

    1.0 = current-week data + prior week + keyword detail + agent activity
    0.75 = current-week + prior week
    0.50 = current-week only (first week)
    0.25 = no ad data at all
    """
    if not digest.get("has_data"):
        return 0.25
    score = 0.50
    if digest.get("prior_week"):
        score += 0.25
    if digest.get("top_keyword") or digest.get("biggest_waster"):
        score += 0.15
    agent = digest.get("agent") or {}
    if int(agent.get("total_actions") or 0) > 0:
        score += 0.10
    return min(1.0, round(score, 2))


def _extract_cited_numbers(text: str) -> List[str]:
    """Return dollar amounts and plain integers (≥10) found in text."""
    return re.findall(r'\$[\d,]+(?:\.\d+)?|\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b', text)


def _build_evidence(digest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return a flat list of {metric, value, label} dicts.
    Every number that render_digest_text *could* mention must have an entry here.
    """
    evidence: List[Dict[str, Any]] = []

    def _ev(metric: str, value, label: str):
        if value is None:
            return
        try:
            f = float(value)
        except (TypeError, ValueError):
            return
        if f == 0:
            return
        evidence.append({"metric": metric, "value": round(f, 2), "label": label})

    tw = digest.get("this_week") or {}
    pw = digest.get("prior_week") or {}

    _ev("spend",         tw.get("spend"),         _money(tw.get("spend")))
    _ev("leads",         tw.get("leads"),          str(_leads_int(tw.get("leads"))))
    _ev("clicks",        tw.get("clicks"),         str(int(tw.get("clicks") or 0)))
    _ev("cost_per_lead", tw.get("cost_per_lead"),  _money(tw.get("cost_per_lead")))

    if pw:
        _ev("prior_spend",   pw.get("spend"),         _money(pw.get("spend")))
        _ev("prior_leads",   pw.get("leads"),          str(_leads_int(pw.get("leads"))))
        _ev("prior_cpl",     pw.get("cost_per_lead"),  _money(pw.get("cost_per_lead")))

        # Derived differences
        for key, label_fn in (
            ("spend",         lambda d: _money(abs(d))),
            ("leads",         lambda d: str(int(round(abs(d))))),
            ("cost_per_lead", lambda d: _money(abs(d))),
        ):
            tw_val = tw.get(key)
            pw_val = pw.get(key)
            if tw_val is not None and pw_val is not None:
                try:
                    diff = float(tw_val) - float(pw_val)
                    if abs(diff) >= 1:
                        _ev(f"delta_{key}", abs(diff), label_fn(diff))
                except (TypeError, ValueError):
                    pass

    # Delta percentages (absolute rounded)
    for k, v in (digest.get("deltas") or {}).items():
        if v is not None:
            try:
                pct = round(abs(float(v)))
                if pct >= 1:
                    _ev(f"pct_{k}", pct, f"{pct}%")
            except (TypeError, ValueError):
                pass

    # Agent
    agent = digest.get("agent") or {}
    actions = agent.get("actions") or {}
    for action_type, count in actions.items():
        _ev(f"agent_{action_type}", count, str(count))
    _ev("agent_total",    agent.get("total_actions"),           str(agent.get("total_actions") or 0))
    _ev("agent_savings",  agent.get("estimated_monthly_savings"), _money(agent.get("estimated_monthly_savings")))

    # Computed agent sums render_digest_text uses
    junk = (actions.get("negative_keyword_added") or 0) + (actions.get("search_term_blocked") or 0)
    _ev("agent_junk",    junk, str(junk))
    ads_p = (actions.get("ad_paused") or 0) + (actions.get("campaign_paused") or 0)
    _ev("agent_ads_paused", ads_p, str(ads_p))
    counted = junk + (actions.get("keyword_paused") or 0) + ads_p + (actions.get("bid_adjusted") or 0) + (actions.get("budget_reallocated") or 0)
    other = max(0, int(agent.get("total_actions") or 0) - counted)
    _ev("agent_other", other, str(other))

    # Keywords
    for kw_key in ("top_keyword", "biggest_waster"):
        kw = digest.get(kw_key) or {}
        prefix = kw_key
        _ev(f"{prefix}_leads",  kw.get("leads"),   str(_leads_int(kw.get("leads"))))
        _ev(f"{prefix}_spend",  kw.get("spend"),   _money(kw.get("spend")))
        _ev(f"{prefix}_cpl",    kw.get("cost_per_lead"), _money(kw.get("cost_per_lead")))
        _ev(f"{prefix}_clicks", kw.get("clicks"),  str(int(kw.get("clicks") or 0)))

    # Campaign triage
    triage = digest.get("campaign_triage") or {}
    _ev("triage_needs_action", triage.get("needs_action"), str(triage.get("needs_action") or 0))
    _ev("triage_total",        triage.get("total"),        str(triage.get("total") or 0))

    return evidence


def _number_check(text: str, evidence: List[Dict[str, Any]]) -> tuple:
    """
    Return (passed: bool, ungrounded: list[str]).

    Every number ≥10 found in `text` must match a value in evidence (after
    stripping $ and commas).  Numbers < 10 are skipped — they're trivially
    small counts derivable from any arithmetic.
    """
    cited = _extract_cited_numbers(text)
    evidence_values = set(
        str(int(round(e["value"]))).replace(",", "")
        for e in evidence
        if e.get("value") is not None
    )
    # Also add comma-formatted and dollar variants
    for e in evidence:
        try:
            v = float(e["value"])
            evidence_values.add(str(int(round(abs(v)))))
            evidence_values.add(f"{int(round(abs(v))):,}".replace(",", ""))
        except (TypeError, ValueError):
            pass

    ungrounded = []
    for raw in cited:
        clean = raw.replace("$", "").replace(",", "")
        try:
            val = float(clean)
        except ValueError:
            continue
        if val < 10:
            continue
        whole = str(int(round(val)))
        if whole not in evidence_values:
            ungrounded.append(raw)

    return (len(ungrounded) == 0), ungrounded


def _pick_highlight_and_action(digest: Dict[str, Any], text: Dict[str, Any]) -> tuple:
    """
    Choose the single most important insight and a concrete recommended action.
    Returns (highlight: str, recommended_action: str).
    """
    tw = digest.get("this_week") or {}
    pw = digest.get("prior_week") or {}

    spend = float(tw.get("spend") or 0)
    leads = _leads_int(tw.get("leads"))
    cpl = tw.get("cost_per_lead")
    deltas = digest.get("deltas") or {}
    cpl_pct = deltas.get("cpl_pct")
    lead_pct = deltas.get("leads_pct")

    if spend <= 0 and leads == 0:
        highlight = "Your ads didn't run last week — no spend recorded."
        action = "Check that your campaigns are active and have remaining budget."
    elif pw is None:
        highlight = text.get("headline", "")
        action = "This is your first full week of data. Next week will show trends."
    elif leads > 0 and cpl_pct is not None and cpl_pct <= -10:
        highlight = text.get("headline", "")
        action = f"Cost per lead improved {abs(cpl_pct):.0f}% — keep the current keyword mix."
    elif leads > 0 and cpl_pct is not None and cpl_pct >= 20:
        prior_cpl = pw.get("cost_per_lead")
        highlight = text.get("headline", "")
        action = (
            f"Cost per lead rose {cpl_pct:.0f}% week-over-week. "
            "Review search terms and pause any zero-conversion keywords."
        )
    elif lead_pct is not None and lead_pct <= -20:
        highlight = text.get("headline", "")
        prior_leads = _leads_int(pw.get("leads"))
        action = (
            f"Lead volume dropped from {prior_leads} to {leads}. "
            "Check impression share and budget pacing."
        )
    elif lead_pct is not None and lead_pct >= 20:
        highlight = text.get("headline", "")
        action = "Lead volume is up — consider increasing budget on the top-performing campaigns."
    else:
        highlight = text.get("headline", "")
        action = "; ".join(text.get("next_steps") or []) or "No urgent actions this week."

    return highlight, action


def render_digest_structured(digest: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a structured digest with number-grounding check.

    Shape:
        {
          "highlight":          str,   # single most important insight sentence
          "evidence":           list,  # [{metric, value, label}] — numbers cited
          "recommended_action": str,
          "confidence":         float, # 0.0–1.0
          "number_check_passed": bool,
          "blocked":            bool,  # True when number_check fails
          "blocking_reason":    str|None,
          "render_text":        dict,  # backward-compat render_digest_text output
        }

    If blocked=True the caller must NOT send this digest without human review.
    """
    text = render_digest_text(digest)
    evidence = _build_evidence(digest)
    confidence = _confidence_score(digest)
    highlight, action = _pick_highlight_and_action(digest, text)

    combined = f"{highlight} {action}"
    passed, ungrounded = _number_check(combined, evidence)

    blocked = not passed
    blocking_reason = None
    if blocked:
        blocking_reason = f"Invented number(s) in digest text: {ungrounded}"
        logger.warning(
            "Digest number check FAILED for account %s — blocking send. Ungrounded: %s",
            digest.get("account_id"),
            ungrounded,
        )

    return {
        "highlight": highlight,
        "evidence": evidence,
        "recommended_action": action,
        "confidence": confidence,
        "number_check_passed": passed,
        "blocked": blocked,
        "blocking_reason": blocking_reason,
        "render_text": text,
    }
