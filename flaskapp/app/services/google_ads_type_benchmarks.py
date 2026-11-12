"""
Google Ads campaign-type benchmarks.

Source: 2026 Google Ads Report (WorkMagic, 100+ retail/eCommerce brands).
All figures are industry medians; account-level overrides belong in
account_settings under the key 'gads_type_benchmarks'.

Usage:
    from app.services.google_ads_type_benchmarks import (
        CAMPAIGN_TYPE_BENCHMARKS, is_upper_funnel, get_halo_pct, effective_roas,
    )
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Type name constants (mirror Google Ads API advertising_channel_type enum)
# ---------------------------------------------------------------------------

SEARCH        = "SEARCH"
PERFORMANCE_MAX = "PERFORMANCE_MAX"
SHOPPING      = "SHOPPING"
DEMAND_GEN    = "DEMAND_GEN"
VIDEO         = "VIDEO"
DISPLAY       = "DISPLAY"

# "UNKNOWN" is a safe catch-all for newly introduced types
UNKNOWN       = "UNKNOWN"

# ---------------------------------------------------------------------------
# Per-type benchmark table
#
# Fields:
#   iroas             — incremental ROAS (WorkMagic lift tests, 50+ tests)
#   payback_ratio     — LTV/CAC ratio for new customers
#   halo_pct          — % of platform revenue that shows up off-platform
#   target_cvr        — median conversion rate
#   target_cpm        — median CPM (upper-funnel formats)
#   target_cpc        — median CPC
#   ctr               — median CTR
#   judge_on          — which metrics to surface in optimizer/digest
#                       cpa/cvr = conversion-focused; cpm/cpc = reach/cost-focused
#   kw_rules_apply    — False for types that have no traditional keywords
# ---------------------------------------------------------------------------

CAMPAIGN_TYPE_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    SEARCH: {
        "iroas":          1.7,
        "payback_ratio":  1.21,
        "halo_pct":       50.9,
        "target_cvr":     0.0224,     # 2.24%
        "target_cpm":     None,
        "target_cpc":     None,
        "ctr":            0.119,       # 11.9%
        "judge_on":       ["cvr", "cpa", "cpl"],
        "kw_rules_apply": True,
    },
    PERFORMANCE_MAX: {
        "iroas":          1.8,
        "payback_ratio":  1.30,
        "halo_pct":       27.9,
        "target_cvr":     0.0164,     # 1.64%
        "target_cpm":     None,
        "target_cpc":     1.03,
        "ctr":            0.0098,     # 0.98%
        "judge_on":       ["cvr", "cpa"],
        "kw_rules_apply": False,       # PMax has no traditional keywords
    },
    SHOPPING: {
        "iroas":          2.1,
        "payback_ratio":  1.52,
        "halo_pct":       None,        # not measured in report
        "target_cvr":     0.0286,     # 2.86% — highest of all types
        "target_cpm":     None,
        "target_cpc":     None,
        "ctr":            0.0079,     # 0.79%
        "judge_on":       ["cvr", "cpa"],
        "kw_rules_apply": False,       # Shopping uses product groups, not keywords
    },
    DEMAND_GEN: {
        "iroas":          None,        # not directly measured
        "payback_ratio":  None,
        "halo_pct":       29.9,
        "target_cvr":     None,
        "target_cpm":     5.30,
        "target_cpc":     0.87,
        "ctr":            None,
        "judge_on":       ["cpm", "cpc"],  # NOT cpa — upper funnel
        "kw_rules_apply": False,
    },
    VIDEO: {
        "iroas":          None,
        "payback_ratio":  None,
        "halo_pct":       15.4,
        "target_cvr":     None,
        "target_cpm":     6.70,
        "target_cpc":     None,
        "ctr":            None,
        "judge_on":       ["cpm"],
        "kw_rules_apply": False,
    },
    DISPLAY: {
        "iroas":          None,
        "payback_ratio":  None,
        "halo_pct":       None,
        "target_cvr":     None,
        "target_cpm":     5.30,
        "target_cpc":     0.68,
        "ctr":            None,
        "judge_on":       ["cpm", "cpc"],
        "kw_rules_apply": False,
    },
    UNKNOWN: {
        "iroas":          None,
        "payback_ratio":  None,
        "halo_pct":       None,
        "target_cvr":     None,
        "target_cpm":     None,
        "target_cpc":     None,
        "ctr":            None,
        "judge_on":       ["cpa"],
        "kw_rules_apply": True,
    },
}

# CVR drop threshold that triggers a Shopping scale-down recommendation
SHOPPING_CVR_DROP_THRESHOLD = 0.15    # -15% week-over-week

# CPM overage that triggers an upper-funnel alert (2× target = likely waste)
CPM_ALERT_MULTIPLIER = 2.0

# Global average CPM for reference (all channels, per report)
GLOBAL_AVG_CPM = 15.0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_benchmark(campaign_type: Optional[str]) -> Dict[str, Any]:
    """Return the benchmark dict for a type, falling back to UNKNOWN."""
    ct = (campaign_type or "").upper()
    return CAMPAIGN_TYPE_BENCHMARKS.get(ct, CAMPAIGN_TYPE_BENCHMARKS[UNKNOWN])


def is_upper_funnel(campaign_type: Optional[str]) -> bool:
    """True for types that should be judged on CPM/CPC, not CPA/CVR."""
    ct = (campaign_type or "").upper()
    bm = get_benchmark(ct)
    return "cpm" in bm.get("judge_on", []) and "cpa" not in bm.get("judge_on", [])


def kw_rules_apply(campaign_type: Optional[str]) -> bool:
    """True when keyword-level optimizer rules are relevant for this type."""
    return get_benchmark(campaign_type).get("kw_rules_apply", True)


def get_halo_pct(campaign_type: Optional[str]) -> Optional[float]:
    """Return the median halo percentage for a campaign type, or None."""
    return get_benchmark(campaign_type).get("halo_pct")


def effective_roas(
    reported_roas: float,
    campaign_type: Optional[str],
    attribution_ratio: float = 1.0,
) -> float:
    """
    Estimate true ROAS by applying the account-level attribution_ratio.

    reported_roas     — last-click ROAS stored in gads_stats_daily
    attribution_ratio — stored on ads_campaigns; default 1.0 (no adjustment)

    For upper-funnel types the adjustment should be larger because
    last-click attribution misses the most impact.
    """
    return round(reported_roas * attribution_ratio, 2)


def period_budget_remaining(
    period_budget_cents: Optional[int],
    period_budget_start,
    period_budget_end,
    spend_to_date_cents: int = 0,
) -> Optional[int]:
    """
    Return remaining period-budget cents.
    Returns None if any argument is missing.
    """
    if period_budget_cents is None or period_budget_start is None or period_budget_end is None:
        return None
    return max(0, period_budget_cents - spend_to_date_cents)
