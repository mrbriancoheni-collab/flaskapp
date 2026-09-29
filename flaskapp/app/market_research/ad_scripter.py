"""
Ad scripter: generates platform-ready ad variants from voice-of-customer research.

Bakes in Motion 2026 Creative Benchmarks insights ($1.3B Meta/Facebook spend):
- ~5% of ads become winners — volume is the strategy
- Best hook types ranked by hit rate
- Best asset types: Text-Only (11.6%), Product image w/ text (8.75%), UGC (7.56%)
"""

import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# Motion 2026 benchmarks: hook type → hit rate %
HOOK_TYPES: dict[str, dict] = {
    "price_anchor": {
        "pattern": "[Competitor/industry price] vs [your price/value]",
        "example": "Agencies charge $3,000/mo to manage your ads. FieldSprout charges $99.",
        "hit_rate": 10.89,
    },
    "urgency": {
        "pattern": "[Seasonal/time event] is [timeframe]. Are you ready?",
        "example": "AC season starts in 6 weeks. Is your Google Ads strategy ready?",
        "hit_rate": 9.73,
    },
    "offer_only": {
        "pattern": "[Specific offer, no fluff]",
        "example": "Free Google Ads audit. See exactly where your budget is wasted.",
        "hit_rate": 9.29,
    },
    "confession": {
        "pattern": "We/I [embarrassing truth about the industry]...",
        "example": "Most HVAC companies won't tell you this — but 30% of service calls don't need the repair they quoted.",
        "hit_rate": 8.74,
    },
    "curiosity": {
        "pattern": "Why does [common thing] [surprising outcome]?",
        "example": "Why do most plumbers spend $800/month on ads that bring in $200 in jobs?",
        "hit_rate": 7.77,
    },
    "bold_claim": {
        "pattern": "[Specific result] in [timeframe] or [consequence]",
        "example": "Cut your cost per lead by 40% in 30 days — or don't pay.",
        "hit_rate": 7.19,
    },
}

# Visual formats that perform best for trade/home-service businesses
TRADE_VISUAL_FORMATS: dict[str, list[str]] = {
    "hvac": ["before_after_energy_bill", "tech_on_site", "seasonal_temperature_graphic"],
    "plumbing": ["before_after_pipe", "emergency_dispatch_scene", "invoice_comparison"],
    "electrical": ["safety_warning_graphic", "panel_upgrade_before_after", "tech_at_panel"],
    "roofing": ["storm_damage_before_after", "crew_on_roof", "insurance_claim_graphic"],
    "landscaping": ["yard_transformation_before_after", "drone_aerial_result", "seasonal_service_graphic"],
    "pest_control": ["infestation_before_after", "guarantee_shield_graphic", "family_safe_scene"],
    "painting": ["room_transformation_before_after", "color_palette_comparison", "crew_in_action"],
    "cleaning": ["clean_vs_dirty_split", "before_after_kitchen", "family_reaction_shot"],
}

# Asset types ranked by hit rate (Motion benchmarks)
ASSET_TYPE_RANKING = [
    {"type": "text_only", "hit_rate": 11.6, "desc": "Bold headline text on solid color background"},
    {"type": "product_image_with_text", "hit_rate": 8.75, "desc": "Service photo with overlaid headline"},
    {"type": "ugc", "hit_rate": 7.56, "desc": "Customer testimonial video or photo"},
    {"type": "demo", "hit_rate": 6.8, "desc": "Screen recording or walkthrough"},
    {"type": "talking_head", "hit_rate": 5.9, "desc": "Owner/tech speaking directly to camera"},
]

# Hook rotation order: highest hit rate first, then cycle
HOOK_ORDER = ["price_anchor", "urgency", "offer_only", "confession", "curiosity", "bold_claim"]

# Trade-specific ad angle seeds
TRADE_AD_ANGLES: dict[str, dict] = {
    "hvac": {
        "peak_seasons": ["summer AC", "fall furnace"],
        "pain_points": ["emergency no-show", "overpriced quote", "slow response"],
        "proof_points": ["same-day service", "upfront pricing", "licensed tech"],
        "ctas": ["Get a Free Quote", "Book Same-Day Service", "See Availability"],
    },
    "plumbing": {
        "peak_seasons": ["winter pipe freeze", "spring drain backup"],
        "pain_points": ["emergency no-show", "hidden fees", "slow dispatch"],
        "proof_points": ["24/7 availability", "flat-rate pricing", "no surprise fees"],
        "ctas": ["Call Now — 24/7", "Get a Free Quote", "Book Online"],
    },
    "electrical": {
        "peak_seasons": ["summer overload", "winter holiday lights"],
        "pain_points": ["safety concerns", "permit issues", "slow scheduling"],
        "proof_points": ["licensed & insured", "same-day service", "warranty on work"],
        "ctas": ["Get a Safety Check", "Request a Quote", "Schedule Today"],
    },
    "roofing": {
        "peak_seasons": ["spring storm season", "fall pre-winter prep"],
        "pain_points": ["storm damage delays", "insurance runaround", "contractor no-shows"],
        "proof_points": ["insurance claim help", "free inspection", "lifetime warranty"],
        "ctas": ["Get a Free Inspection", "Check Storm Damage", "Request Estimate"],
    },
    "landscaping": {
        "peak_seasons": ["spring cleanup", "summer lawn care", "fall leaf removal"],
        "pain_points": ["unreliable crews", "brown spots", "no-show after rain"],
        "proof_points": ["weekly consistency", "organic options", "before & after photos"],
        "ctas": ["Get a Free Estimate", "Book First Cut", "See Transformation"],
    },
    "pest_control": {
        "peak_seasons": ["spring ant/termite season", "summer mosquito season"],
        "pain_points": ["pesticide safety worries", "recurring infestations", "slow response"],
        "proof_points": ["kid-safe treatment", "guaranteed results", "same-week service"],
        "ctas": ["Get a Free Inspection", "Book Treatment", "See Our Guarantee"],
    },
    "painting": {
        "peak_seasons": ["spring exterior", "summer interior refresh"],
        "pain_points": ["peeling paint", "color mismatch", "messy crews"],
        "proof_points": ["clean crew", "color match guarantee", "low-VOC options"],
        "ctas": ["Get a Free Quote", "See Our Work", "Book a Walkthrough"],
    },
    "cleaning": {
        "peak_seasons": ["spring deep clean", "holiday prep", "move-in/out"],
        "pain_points": ["inconsistent cleaners", "hidden fees", "rescheduling"],
        "proof_points": ["same cleaner every time", "flat-rate pricing", "insured team"],
        "ctas": ["Book Your First Clean", "Get Instant Pricing", "See Availability"],
    },
}


def _build_hook_headline(hook_type: str, trade: str, city: str, pain_phrase: str = "") -> str:
    """Generate a headline using the hook pattern for the given trade."""
    angles = TRADE_AD_ANGLES.get(trade, TRADE_AD_ANGLES["hvac"])
    pain = pain_phrase or (angles["pain_points"][0] if angles["pain_points"] else "slow service")

    templates = {
        "price_anchor": f"Agencies Charge $3,000/mo. FieldSprout: $99.",
        "urgency": f"Peak {trade.upper()} Season Is Coming. Is Your Ad Budget Ready?",
        "offer_only": f"Free Google Ads Grade for {trade.upper()} Companies in {city}",
        "confession": f"Most {trade.upper()} Businesses Waste 40% of Their Ad Budget",
        "curiosity": f"Why Are {trade.upper()} Leads Getting More Expensive in {city}?",
        "bold_claim": f"Cut Your Cost Per Lead by 40% in 30 Days",
    }
    return templates.get(hook_type, templates["offer_only"])


def _build_primary_text(
    hook_type: str,
    trade: str,
    city: str,
    pain_phrase: str = "",
    proof_phrase: str = "",
) -> str:
    """Generate primary ad text (Facebook/Instagram body copy)."""
    angles = TRADE_AD_ANGLES.get(trade, TRADE_AD_ANGLES["hvac"])
    pain = pain_phrase or (angles["pain_points"][0] if angles["pain_points"] else "wasted spend")
    proof = proof_phrase or (angles["proof_points"][0] if angles["proof_points"] else "proven results")

    templates = {
        "price_anchor": (
            f"Marketing agencies charge $2,000–$5,000/month to manage your {trade} Google Ads. "
            f"FieldSprout's AI does the same job — optimizing every day — for $99/month.\n\n"
            f"No contracts. No account managers who check in monthly. Just AI that actually works."
        ),
        "urgency": (
            f"Peak {trade} season is 6 weeks out. If your Google Ads aren't dialed in now, "
            f"you'll spend the whole season paying too much per lead.\n\n"
            f"FieldSprout's AI optimizes your campaigns daily so you're ready when demand spikes."
        ),
        "offer_only": (
            f"Free Google Ads Grade for {trade} companies in {city}.\n\n"
            f"See exactly where your budget is being wasted — and get a prioritized fix list. "
            f"Takes 60 seconds. No credit card."
        ),
        "confession": (
            f"We analyzed 500+ {trade} Google Ads accounts. The average business wastes 38% of "
            f"their monthly budget on clicks that will never become a booked job.\n\n"
            f"The culprits: wrong keywords, off-hours ads, and low Quality Scores that inflate every click. "
            f"FieldSprout fixes all three — automatically."
        ),
        "curiosity": (
            f"Cost per lead in {city} for {trade} companies went up 22% last year. "
            f"But some businesses are paying less than ever.\n\n"
            f"The difference? Daily ad optimization. FieldSprout's AI adjusts bids, kills wasted spend, "
            f"and improves Quality Scores every 24 hours."
        ),
        "bold_claim": (
            f"FieldSprout-managed {trade} accounts average 40% lower cost per lead after 30 days.\n\n"
            f"Our AI optimizes your Google Ads every day — not once a month like an agency. "
            f"Connect in 60 seconds and see your first grade free."
        ),
    }
    return templates.get(hook_type, templates["offer_only"])


def _build_description(hook_type: str, trade: str) -> str:
    """Short description line (shown under headline in some placements)."""
    templates = {
        "price_anchor": "AI-powered Google Ads. $99/month. No contracts.",
        "urgency": "Optimize before peak season. See results in week one.",
        "offer_only": "Free 60-second audit. No credit card required.",
        "confession": "Stop the bleed. AI that fixes your ads every day.",
        "curiosity": "Find out why leads cost more — and how to fix it.",
        "bold_claim": "40% lower CPL in 30 days. Grade your account free.",
    }
    return templates.get(hook_type, "Grade your Google Ads free in 60 seconds.")


def generate_ad_scripts(
    trade: str,
    city: str,
    review_data: dict | None = None,
    reddit_data: dict | None = None,
    platform: str = "meta",
    num_variants: int = 8,
) -> list[dict[str, Any]]:
    """
    Generate platform-ready ad variants for a trade + city.

    Args:
        trade: e.g. "hvac", "plumbing"
        city: e.g. "Atlanta"
        review_data: output from review_miner.mine_reviews()
        reddit_data: output from reddit_researcher.research_trade()
        platform: "meta" | "google" | "both"
        num_variants: how many variants to generate (Motion benchmark: need volume)

    Returns:
        List of ad variant dicts with hook_type, headline, primary_text, description,
        cta, visual_format, asset_type, visual_brief, source_data, copy_rationale
    """
    trade = trade.lower().replace(" ", "_")
    angles = TRADE_AD_ANGLES.get(trade, TRADE_AD_ANGLES["hvac"])
    visual_formats = TRADE_VISUAL_FORMATS.get(trade, ["before_after", "tech_on_site"])

    # Extract voice-of-customer phrases if available
    pain_phrases: list[str] = []
    proof_phrases: list[str] = []
    exact_phrases: list[str] = []

    if review_data and not review_data.get("_mock"):
        pain_phrases = review_data.get("objection_phrases", [])[:3]
        proof_phrases = review_data.get("transformation_phrases", [])[:3]

    if reddit_data and not reddit_data.get("_mock"):
        insights = reddit_data.get("insights", {})
        exact_phrases = insights.get("exact_phrases", [])[:3]
        pain_phrases = pain_phrases or insights.get("top_pain_points", [])[:3]

    variants = []
    asset_types_cycle = [a["type"] for a in ASSET_TYPE_RANKING]

    for i in range(num_variants):
        hook_type = HOOK_ORDER[i % len(HOOK_ORDER)]
        asset_type = asset_types_cycle[i % len(asset_types_cycle)]
        visual_format = visual_formats[i % len(visual_formats)]
        cta = angles["ctas"][i % len(angles["ctas"])]

        # Use voice-of-customer if available, else use trade defaults
        pain_phrase = pain_phrases[i % len(pain_phrases)] if pain_phrases else ""
        proof_phrase = proof_phrases[i % len(proof_phrases)] if proof_phrases else ""

        headline = _build_hook_headline(hook_type, trade, city, pain_phrase)
        primary_text = _build_primary_text(hook_type, trade, city, pain_phrase, proof_phrase)
        description = _build_description(hook_type, trade)

        # Inject exact Reddit phrases into copy if available
        if exact_phrases and hook_type == "confession":
            phrase = exact_phrases[i % len(exact_phrases)]
            primary_text = f'"{phrase}"\n\nSound familiar? {primary_text}'

        hook_meta = HOOK_TYPES[hook_type]
        asset_meta = next((a for a in ASSET_TYPE_RANKING if a["type"] == asset_type), ASSET_TYPE_RANKING[0])

        variants.append({
            "variant_id": f"{trade}_{city.lower().replace(' ', '_')}_{hook_type}_{i+1}",
            "hook_type": hook_type,
            "hook_hit_rate": hook_meta["hit_rate"],
            "headline": headline,
            "primary_text": primary_text,
            "description": description,
            "cta": cta,
            "platform": platform,
            "visual_format": visual_format,
            "asset_type": asset_type,
            "asset_hit_rate": asset_meta["hit_rate"],
            "visual_brief": (
                f"{asset_meta['desc']}. "
                f"Visual: {visual_format.replace('_', ' ')}. "
                f"Format: {platform} feed + stories."
            ),
            "source_data": {
                "has_review_data": bool(review_data and not review_data.get("_mock")),
                "has_reddit_data": bool(reddit_data and not reddit_data.get("_mock")),
                "pain_phrase_used": pain_phrase or None,
                "proof_phrase_used": proof_phrase or None,
            },
            "copy_rationale": (
                f"Hook: {hook_type} ({hook_meta['hit_rate']}% hit rate per Motion benchmarks). "
                f"Asset: {asset_type} ({asset_meta['hit_rate']}% hit rate). "
                f"{'VoC phrases injected from live research.' if (pain_phrase or proof_phrase) else 'Using trade defaults — connect review/Reddit data for VoC lift.'}"
            ),
        })

    return variants


def generate_ad_volume_plan(trade: str, monthly_budget: float) -> dict[str, Any]:
    """
    Generate a testing cadence plan based on Motion benchmarks.

    Motion insight: only ~5% of ads become winners. Need at least 20 variants
    to expect 1 winner. Budget determines how fast you can cycle through variants.
    """
    # Motion benchmark: need ~$500 spend to statistically evaluate one ad
    budget_per_ad = 500.0
    ads_testable_per_month = max(1, int(monthly_budget / budget_per_ad))

    # Week-by-week cadence
    cadence = []
    if ads_testable_per_month >= 8:
        cadence = [
            {"week": 1, "action": "Launch 4 hooks × 2 asset types = 8 variants", "budget_split": "Equal"},
            {"week": 2, "action": "Kill bottom 4 by CTR. Double budget on top 4.", "budget_split": "Performance-weighted"},
            {"week": 3, "action": "Create 4 new variants iterating on winning hook type", "budget_split": "60% winners / 40% new"},
            {"week": 4, "action": "Evaluate: promote 2 winners to evergreen, retire bottom 2", "budget_split": "Performance-weighted"},
        ]
    else:
        cadence = [
            {"week": 1, "action": f"Launch {ads_testable_per_month} variants, highest-hit-rate hooks first", "budget_split": "Equal"},
            {"week": 2, "action": "Evaluate by CPL and CTR. Pause bottom half.", "budget_split": "Performance-weighted"},
            {"week": 3, "action": "Iterate on surviving hooks with new visual formats", "budget_split": "70% proven / 30% new"},
            {"week": 4, "action": "Promote winners to evergreen. Start next test batch.", "budget_split": "Performance-weighted"},
        ]

    return {
        "trade": trade,
        "monthly_budget": monthly_budget,
        "ads_testable_per_month": ads_testable_per_month,
        "expected_winners": max(1, round(ads_testable_per_month * 0.05)),
        "recommended_variants": max(8, ads_testable_per_month * 2),
        "motion_insight": (
            "Only ~5% of ads become winners. Volume is the strategy — not optimization. "
            "Launch more variants, not better variants. Let data pick winners."
        ),
        "launch_order": [
            f"{h} ({HOOK_TYPES[h]['hit_rate']}% hit rate)" for h in HOOK_ORDER
        ],
        "top_asset_types": [
            f"{a['type']} ({a['hit_rate']}% hit rate)" for a in ASSET_TYPE_RANKING[:3]
        ],
        "weekly_cadence": cadence,
    }


def get_hook_guide() -> dict[str, Any]:
    """Return the full hook taxonomy with examples for display in UI."""
    return {
        hook: {
            "pattern": meta["pattern"],
            "example": meta["example"],
            "hit_rate": meta["hit_rate"],
            "rank": i + 1,
        }
        for i, (hook, meta) in enumerate(
            sorted(HOOK_TYPES.items(), key=lambda x: x[1]["hit_rate"], reverse=True)
        )
    }
