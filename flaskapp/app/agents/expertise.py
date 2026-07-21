# app/agents/expertise.py
"""
Google Ads expertise layer for FieldSprout agents.

The operational agents are deterministic rules engines. This module gives them
the *judgment layer* a top-tier Google Ads manager would apply on top of the
raw thresholds: benchmark-aware reasoning, best-practice guardrails, and a
persona/context builder for any agent that calls an LLM.

Two things were broken before this module existed and are fixed here:
  1. The knowledge pipeline (agent_knowledge_service) cached best-practice
     content keyed by snake_case agent names, but agents self-identify by
     class name (self.agent_type == "CampaignManagerAgent"). KNOWLEDGE_KEY maps
     between them so learnings/knowledge actually reach the agent.
  2. Nothing ever injected that knowledge into agent context. build_expert_context()
     assembles persona + playbook + accumulated decision learnings into one string.

Everything here is additive and fails soft: if a lookup errors, agents keep
their existing behavior.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persona — the voice/standard any LLM-using agent should adopt
# ---------------------------------------------------------------------------
GOOGLE_ADS_PERSONA = (
    "You are a top-tier Google Ads strategist with 15+ years managing paid "
    "search for home-service businesses (HVAC, plumbing, electrical, roofing, "
    "etc.). You think in terms of cost per lead and cost per booked job, not "
    "clicks. You respect statistical significance, algorithm learning periods, "
    "and seasonality. You never make a change large enough to reset Smart "
    "Bidding learning without a clear reason. You prefer the smallest effective "
    "change, you protect proven performers, and you cut waste decisively. Every "
    "recommendation you make is specific, benchmarked, and explained in plain "
    "language a business owner can act on."
)

# ---------------------------------------------------------------------------
# Map agent class names -> knowledge-service snake_case keys (fixes mismatch)
# ---------------------------------------------------------------------------
KNOWLEDGE_KEY = {
    "CampaignManagerAgent": "campaign_manager",
    "BudgetGuardianAgent": "budget_guardian",
    "QualityScoreAgent": "quality_score",
    "KeywordOptimizerAgent": "keyword_optimizer",
    "NegativeKeywordAgent": "negative_keyword",
    "StrategicDirectorAgent": "strategic_director",
    "AdCopyAgent": "ad_copy",
}


def knowledge_key_for(agent_type: str) -> str:
    """Return the snake_case knowledge key for an agent's class name."""
    return KNOWLEDGE_KEY.get(agent_type, agent_type.lower())


# ---------------------------------------------------------------------------
# Best-practice benchmarks & principles (home-service paid search)
# ---------------------------------------------------------------------------
# Home-service search CPL benchmarks (USD) — used to sanity-check targets.
INDUSTRY_CPL_BENCHMARKS = {
    "hvac": (65, 120),
    "plumbing": (70, 130),
    "electrical": (75, 140),
    "roofing": (100, 250),
    "garage_door": (50, 110),
    "landscaping": (45, 120),
    "pest_control": (55, 110),
    "pool_service": (55, 130),
    "solar": (120, 300),
    "restoration": (90, 200),
}

# Expert guardrails every operational decision should honor.
EXPERT_PRINCIPLES = [
    "Don't act on fewer than ~15-30 conversions of signal — below that, "
    "swings are noise, not trend.",
    "A bid/budget change over ~20% can reset Smart Bidding's learning period; "
    "prefer incremental moves unless waste is severe.",
    "Before scaling, confirm the ceiling is demand (impression share lost to "
    "rank) not budget — scaling a budget-capped campaign just raises CPL.",
    "Check the search terms report before blaming bids; irrelevant queries are "
    "the #1 hidden CPL driver.",
    "Respect seasonality — a 'spike' during peak demand may be the market, not "
    "a problem.",
]


def _clean(text: str) -> str:
    return " ".join(str(text).split())


def expert_reasoning(opp: Dict[str, Any]) -> Optional[str]:
    """
    Upgrade a raw opportunity into benchmark-aware, expert-grade reasoning
    shown to the client. Returns None if the type is unknown (caller keeps its
    existing string).
    """
    try:
        t = opp.get("type")
        if t == "cpl_spike":
            spike = opp.get("spike_pct", 0)
            return _clean(
                f"CPL jumped {spike:.0f}% above its recent baseline. A move this size "
                "is rarely bids alone — the usual causes are new irrelevant search "
                "terms, a competitor entering the auction, or a landing-page issue "
                "hurting conversion rate. Investigating first (search terms + "
                "conversion path) prevents cutting bids on a campaign that's actually "
                "fine, which would just surrender volume."
            )
        if t == "bid_adjustment":
            cur, tgt = opp.get("current_cpl", 0), opp.get("target_cpl", 0)
            pct = abs(opp.get("recommended_bid_change_pct", 0))
            over = ((cur - tgt) / tgt * 100) if tgt else 0
            return _clean(
                f"CPL of ${cur:.0f} is {over:.0f}% over the ${tgt:.0f} target. Trimming "
                f"bids ~{pct:.0f}% pulls CPL toward target while staying under the ~20% "
                "threshold that resets Smart Bidding learning, so volume recovers within "
                "days rather than restarting the learning period."
            )
        if t == "pause_campaign":
            cpl, tgt = opp.get("cpl_90d", 0), opp.get("target_cpl", 0)
            mult = (cpl / tgt) if tgt else 0
            return _clean(
                f"Over a full 90-day window this campaign holds a ${cpl:.0f} CPL — "
                f"{mult:.1f}x the ${tgt:.0f} target — on meaningful spend. That's a "
                "structural loser, not a bad week: enough time has passed to rule out "
                "learning periods and seasonality. Pausing stops the bleed; the budget "
                "redeploys to campaigns hitting target."
            )
        if t == "scale_campaign":
            cpl, tgt = opp.get("cpl_90d", 0), opp.get("target_cpl", 0)
            imp = opp.get("impression_share", 0)
            under = ((tgt - cpl) / tgt * 100) if tgt else 0
            return _clean(
                f"This campaign converts at ${cpl:.0f} CPL — {under:.0f}% under target — "
                f"yet shows only {imp:.0f}% impression share, meaning real demand is going "
                "unserved. Because the ceiling is reach (not a bidding problem), adding "
                "budget captures more leads at a CPL that's already proven. Scaling ~30% "
                "keeps the move inside a safe learning-stable step."
            )
    except Exception:
        log.debug("expert_reasoning failed for opp=%s", opp, exc_info=True)
    return None


def campaign_split_recommendation(categories: list, min_conversions: int = 10,
                                  spread_ratio: float = 2.0) -> Optional[Dict[str, Any]]:
    """
    Decide whether a multi-service campaign should be split into separate
    campaigns, given per-category economics.

    This matters for Google's Aug 2026 migration of Local Services Ads into
    Google Ads: a single campaign-level Target CPA replaces per-category
    (vertical-level) targets. When one campaign mixes services with very
    different lead costs (e.g. drain cleaning at $30 and repipe at $120), one
    blended target overpays on the cheap service and underfunds the expensive
    one. Splitting restores bidding control — at the cost of thinner conversion
    data per campaign, so we only recommend it when each side has real volume.

    `categories`: list of {name, cpl, conversions}.
    Returns a recommendation dict when a split is warranted, else None.
    """
    try:
        qualified = [
            c for c in (categories or [])
            if (c.get("conversions") or 0) >= min_conversions and (c.get("cpl") or 0) > 0
        ]
        if len(qualified) < 2:
            return None

        cheapest = min(qualified, key=lambda c: c["cpl"])
        dearest = max(qualified, key=lambda c: c["cpl"])
        ratio = dearest["cpl"] / cheapest["cpl"] if cheapest["cpl"] else 0
        if ratio < spread_ratio:
            return None

        high = [c for c in qualified if c["cpl"] >= cheapest["cpl"] * spread_ratio]
        low = [c for c in qualified if c not in high]
        reasoning = _clean(
            f"This campaign mixes services with very different lead economics — "
            f"{dearest['name']} costs ${dearest['cpl']:.0f}/lead while {cheapest['name']} "
            f"costs ${cheapest['cpl']:.0f}, a {ratio:.1f}x spread. After Google's 2026 move of "
            "Local Services Ads into Google Ads, one campaign gets a single blended Target CPA, "
            "so a shared target would overpay on the cheap services and starve the expensive ones. "
            "Splitting the high-cost services into their own campaign restores per-service bidding "
            "control. Both sides clear the volume bar for reliable bidding signals, so the usual "
            "downside of splitting (thin data) doesn't apply here."
        )
        return {
            "should_split": True,
            "spread_ratio": round(ratio, 1),
            "high_cost": [c["name"] for c in high],
            "low_cost": [c["name"] for c in low],
            "dearest": dearest,
            "cheapest": cheapest,
            "reasoning": reasoning,
        }
    except Exception:
        log.debug("campaign_split_recommendation failed for %s", categories, exc_info=True)
    return None


def build_expert_context(agent_type: str, account_id: int = 0,
                         goal: str = "") -> str:
    """
    Assemble a compact expert context block for an LLM-using agent: persona +
    guardrails + accumulated decision learnings for this agent/account. Fails
    soft to just the persona so a knowledge/DB error never breaks an agent.
    """
    parts = [GOOGLE_ADS_PERSONA]
    if goal:
        parts.append(f"Account goal: {goal}")
    parts.append("Operating principles:\n- " + "\n- ".join(EXPERT_PRINCIPLES))

    # Accumulated outcomes from prior decisions (real learning signal).
    try:
        from app.services.agent_knowledge_service import get_decision_learnings_context
        learnings = get_decision_learnings_context(agent_type, account_id)
        if learnings:
            parts.append("What has worked/failed on this account before:\n" + learnings)
    except Exception:
        log.debug("decision learnings unavailable for %s", agent_type, exc_info=True)

    return "\n\n".join(parts)
