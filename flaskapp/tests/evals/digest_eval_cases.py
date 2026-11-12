"""
25 synthetic weekly digest inputs for the evaluation harness.

Each case is a dict with:
  id          — unique slug
  category    — primary eval category to attribute failures to
  description — human-readable intent of the case
  digest      — the digest dict as generate_weekly_digest() would return it
  expect      — optional dict of assertions the rule scorer enforces

The final case ("invented_number") has a digest whose this_week numbers do NOT
match what render_digest_text is expected to produce — it is intentionally
set up so a number-check rule catches fabricated evidence.
"""
from __future__ import annotations
from typing import Any, Dict, List

CASES: List[Dict[str, Any]] = [
    # ── 1. Normal profitable week ─────────────────────────────────────────────
    {
        "id": "normal_week_leads_and_spend",
        "category": "accuracy",
        "description": "Typical week: spend $1,200, 15 leads, prior week 12 leads",
        "digest": {
            "account_id": 1,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1200.00, "clicks": 180, "leads": 15.0, "cost_per_lead": 80.0},
            "prior_week": {"spend": 1100.00, "clicks": 160, "leads": 12.0, "cost_per_lead": 91.67},
            "deltas": {"spend_pct": 9.1, "leads_pct": 25.0, "cpl_pct": -12.7},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": {"text": "emergency plumber", "leads": 6.0, "spend": 480.0, "cost_per_lead": 80.0},
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "headline_contains": ["1,200", "15"],
            "numbers_grounded": True,
        },
    },
    # ── 2. No data (quiet week) ───────────────────────────────────────────────
    {
        "id": "quiet_week_no_data",
        "category": "completeness",
        "description": "No spend, no leads — ads didn't run",
        "digest": {
            "account_id": 2,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": False,
            "this_week": {"spend": 0.0, "clicks": 0, "leads": 0.0, "cost_per_lead": None},
            "prior_week": None,
            "deltas": {"spend_pct": None, "leads_pct": None, "cpl_pct": None},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "headline_contains": ["didn't run"],
            "numbers_grounded": True,
        },
    },
    # ── 3. First week (no prior data) ─────────────────────────────────────────
    {
        "id": "first_week_no_prior",
        "category": "completeness",
        "description": "New account, first full week of data, no prior week",
        "digest": {
            "account_id": 3,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 500.00, "clicks": 60, "leads": 4.0, "cost_per_lead": 125.0},
            "prior_week": None,
            "deltas": {"spend_pct": None, "leads_pct": None, "cpl_pct": None},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "headline_contains": ["500", "4"],
            "numbers_grounded": True,
        },
    },
    # ── 4. Lead count improvement ─────────────────────────────────────────────
    {
        "id": "leads_up",
        "category": "accuracy",
        "description": "Leads went from 5 to 10 — summary should mention +5",
        "digest": {
            "account_id": 4,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 800.00, "clicks": 100, "leads": 10.0, "cost_per_lead": 80.0},
            "prior_week": {"spend": 800.00, "clicks": 95, "leads": 5.0, "cost_per_lead": 160.0},
            "deltas": {"spend_pct": 0.0, "leads_pct": 100.0, "cpl_pct": -50.0},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "summary_contains_number": "5",
            "numbers_grounded": True,
        },
    },
    # ── 5. Lead count decline ─────────────────────────────────────────────────
    {
        "id": "leads_down",
        "category": "accuracy",
        "description": "Leads dropped from 10 to 6 — summary should mention decline",
        "digest": {
            "account_id": 5,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 900.00, "clicks": 110, "leads": 6.0, "cost_per_lead": 150.0},
            "prior_week": {"spend": 850.00, "clicks": 100, "leads": 10.0, "cost_per_lead": 85.0},
            "deltas": {"spend_pct": 5.9, "leads_pct": -40.0, "cpl_pct": 76.5},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "summary_contains_number": "4",  # lead_diff absolute
            "numbers_grounded": True,
        },
    },
    # ── 6. CPL improved ───────────────────────────────────────────────────────
    {
        "id": "cpl_improved",
        "category": "accuracy",
        "description": "CPL dropped 15% — should say 'cheaper per lead'",
        "digest": {
            "account_id": 6,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 850.00, "clicks": 100, "leads": 10.0, "cost_per_lead": 85.0},
            "prior_week": {"spend": 1000.00, "clicks": 100, "leads": 10.0, "cost_per_lead": 100.0},
            "deltas": {"spend_pct": -15.0, "leads_pct": 0.0, "cpl_pct": -15.0},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "numbers_grounded": True,
        },
    },
    # ── 7. CPL degraded ───────────────────────────────────────────────────────
    {
        "id": "cpl_worsened",
        "category": "accuracy",
        "description": "CPL increased 30% — should flag it",
        "digest": {
            "account_id": 7,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1300.00, "clicks": 100, "leads": 10.0, "cost_per_lead": 130.0},
            "prior_week": {"spend": 1000.00, "clicks": 100, "leads": 10.0, "cost_per_lead": 100.0},
            "deltas": {"spend_pct": 30.0, "leads_pct": 0.0, "cpl_pct": 30.0},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "numbers_grounded": True,
        },
    },
    # ── 8. Biggest waster keyword ─────────────────────────────────────────────
    {
        "id": "biggest_waster",
        "category": "accuracy",
        "description": "Keyword 'free hvac' spent $220 with zero leads",
        "digest": {
            "account_id": 8,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 900.00, "clicks": 95, "leads": 7.0, "cost_per_lead": 128.6},
            "prior_week": {"spend": 870.00, "clicks": 90, "leads": 7.0, "cost_per_lead": 124.3},
            "deltas": {"spend_pct": 3.4, "leads_pct": 0.0, "cpl_pct": 3.5},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": {"text": "emergency plumber", "leads": 4.0, "spend": 320.0, "cost_per_lead": 80.0},
            "biggest_waster": {"text": "free hvac", "spend": 220.0, "clicks": 28},
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "summary_contains": ["free hvac", "220"],
            "numbers_grounded": True,
        },
    },
    # ── 9. Agent: negative keywords added ────────────────────────────────────
    {
        "id": "agent_negative_keywords",
        "category": "accuracy",
        "description": "Agent blocked 12 junk searches",
        "digest": {
            "account_id": 9,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 950.00, "clicks": 115, "leads": 9.0, "cost_per_lead": 105.6},
            "prior_week": {"spend": 980.00, "clicks": 130, "leads": 9.0, "cost_per_lead": 108.9},
            "deltas": {"spend_pct": -3.1, "leads_pct": 0.0, "cpl_pct": -3.0},
            "agent": {
                "actions": {"negative_keyword_added": 8, "search_term_blocked": 4},
                "total_actions": 12,
                "estimated_monthly_savings": 95.0,
            },
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "agent_contains_number": "12",
            "numbers_grounded": True,
        },
    },
    # ── 10. Agent: bid adjustments ────────────────────────────────────────────
    {
        "id": "agent_bid_adjustments",
        "category": "accuracy",
        "description": "Agent made 7 bid adjustments, estimated $120/month savings",
        "digest": {
            "account_id": 10,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1050.00, "clicks": 120, "leads": 11.0, "cost_per_lead": 95.5},
            "prior_week": {"spend": 1100.00, "clicks": 118, "leads": 10.0, "cost_per_lead": 110.0},
            "deltas": {"spend_pct": -4.5, "leads_pct": 10.0, "cpl_pct": -13.2},
            "agent": {
                "actions": {"bid_adjusted": 7},
                "total_actions": 7,
                "estimated_monthly_savings": 120.0,
            },
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "agent_contains_number": "7",
            "numbers_grounded": True,
        },
    },
    # ── 11. Agent: keywords paused ────────────────────────────────────────────
    {
        "id": "agent_keywords_paused",
        "category": "accuracy",
        "description": "Agent paused 3 keywords",
        "digest": {
            "account_id": 11,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 780.00, "clicks": 95, "leads": 8.0, "cost_per_lead": 97.5},
            "prior_week": {"spend": 840.00, "clicks": 105, "leads": 8.0, "cost_per_lead": 105.0},
            "deltas": {"spend_pct": -7.1, "leads_pct": 0.0, "cpl_pct": -7.1},
            "agent": {
                "actions": {"keyword_paused": 3},
                "total_actions": 3,
                "estimated_monthly_savings": 60.0,
            },
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "agent_contains_number": "3",
            "numbers_grounded": True,
        },
    },
    # ── 12. Agent: budget reallocation ────────────────────────────────────────
    {
        "id": "agent_budget_reallocation",
        "category": "accuracy",
        "description": "Agent moved budget 2 times",
        "digest": {
            "account_id": 12,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1400.00, "clicks": 160, "leads": 14.0, "cost_per_lead": 100.0},
            "prior_week": {"spend": 1400.00, "clicks": 148, "leads": 11.0, "cost_per_lead": 127.3},
            "deltas": {"spend_pct": 0.0, "leads_pct": 27.3, "cpl_pct": -21.4},
            "agent": {
                "actions": {"budget_reallocated": 2},
                "total_actions": 2,
                "estimated_monthly_savings": 0.0,
            },
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "agent_contains_number": "2",
            "numbers_grounded": True,
        },
    },
    # ── 13. Agent: campaign paused ────────────────────────────────────────────
    {
        "id": "agent_campaign_paused",
        "category": "accuracy",
        "description": "Agent paused 1 underperforming campaign",
        "digest": {
            "account_id": 13,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 650.00, "clicks": 80, "leads": 7.0, "cost_per_lead": 92.9},
            "prior_week": {"spend": 1050.00, "clicks": 130, "leads": 7.0, "cost_per_lead": 150.0},
            "deltas": {"spend_pct": -38.1, "leads_pct": 0.0, "cpl_pct": -38.1},
            "agent": {
                "actions": {"campaign_paused": 1},
                "total_actions": 1,
                "estimated_monthly_savings": 400.0,
            },
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "agent_contains_number": "1",
            "numbers_grounded": True,
        },
    },
    # ── 14. High savings agent ────────────────────────────────────────────────
    {
        "id": "agent_high_savings",
        "category": "accuracy",
        "description": "Agent actions totalling $450/month savings",
        "digest": {
            "account_id": 14,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1100.00, "clicks": 130, "leads": 13.0, "cost_per_lead": 84.6},
            "prior_week": {"spend": 1500.00, "clicks": 160, "leads": 10.0, "cost_per_lead": 150.0},
            "deltas": {"spend_pct": -26.7, "leads_pct": 30.0, "cpl_pct": -43.6},
            "agent": {
                "actions": {"bid_adjusted": 5, "keyword_paused": 4, "negative_keyword_added": 10},
                "total_actions": 19,
                "estimated_monthly_savings": 450.0,
            },
            "top_keyword": {"text": "plumber near me", "leads": 7.0, "spend": 490.0, "cost_per_lead": 70.0},
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "agent_contains_number": "450",
            "numbers_grounded": True,
        },
    },
    # ── 15. No agent actions ──────────────────────────────────────────────────
    {
        "id": "no_agent_actions",
        "category": "completeness",
        "description": "Agent made no changes — steady week",
        "digest": {
            "account_id": 15,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1000.00, "clicks": 120, "leads": 10.0, "cost_per_lead": 100.0},
            "prior_week": {"spend": 1000.00, "clicks": 118, "leads": 10.0, "cost_per_lead": 100.0},
            "deltas": {"spend_pct": 0.0, "leads_pct": 0.0, "cpl_pct": 0.0},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "numbers_grounded": True,
        },
    },
    # ── 16. Spend only, no leads yet ──────────────────────────────────────────
    {
        "id": "spend_no_leads",
        "category": "accuracy",
        "description": "Spend but zero leads — headline covers clicks",
        "digest": {
            "account_id": 16,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 350.00, "clicks": 42, "leads": 0.0, "cost_per_lead": None},
            "prior_week": None,
            "deltas": {"spend_pct": None, "leads_pct": None, "cpl_pct": None},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "headline_contains": ["350", "42"],
            "numbers_grounded": True,
        },
    },
    # ── 17. Steady leads ──────────────────────────────────────────────────────
    {
        "id": "steady_leads",
        "category": "accuracy",
        "description": "Leads flat at 8 for two weeks",
        "digest": {
            "account_id": 17,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 720.00, "clicks": 88, "leads": 8.0, "cost_per_lead": 90.0},
            "prior_week": {"spend": 718.00, "clicks": 86, "leads": 8.0, "cost_per_lead": 89.75},
            "deltas": {"spend_pct": 0.3, "leads_pct": 0.0, "cpl_pct": 0.3},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "summary_contains": ["steady"],
            "numbers_grounded": True,
        },
    },
    # ── 18. Next steps present ────────────────────────────────────────────────
    {
        "id": "next_steps_present",
        "category": "completeness",
        "description": "Three optimizer recommendations present",
        "digest": {
            "account_id": 18,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 980.00, "clicks": 115, "leads": 9.0, "cost_per_lead": 108.9},
            "prior_week": {"spend": 950.00, "clicks": 110, "leads": 10.0, "cost_per_lead": 95.0},
            "deltas": {"spend_pct": 3.2, "leads_pct": -10.0, "cpl_pct": 14.6},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [
                {"title": "Add negative keywords for 'free'", "expected_impact": "Save $50/mo", "category": "waste"},
                {"title": "Increase budget for top campaign", "expected_impact": "+3 leads/mo", "category": "growth"},
                {"title": "Enable call tracking", "expected_impact": "Better attribution", "category": "tracking"},
            ],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "next_steps_count_min": 1,
            "numbers_grounded": True,
        },
    },
    # ── 19. Very high CPL week ────────────────────────────────────────────────
    {
        "id": "high_cpl",
        "category": "accuracy",
        "description": "CPL=$400 — above normal, should be mentioned",
        "digest": {
            "account_id": 19,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1200.00, "clicks": 60, "leads": 3.0, "cost_per_lead": 400.0},
            "prior_week": {"spend": 1200.00, "clicks": 100, "leads": 10.0, "cost_per_lead": 120.0},
            "deltas": {"spend_pct": 0.0, "leads_pct": -70.0, "cpl_pct": 233.3},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "headline_contains": ["400"],
            "numbers_grounded": True,
        },
    },
    # ── 20. Many agent action types ───────────────────────────────────────────
    {
        "id": "many_agent_types",
        "category": "accuracy",
        "description": "All agent action types fired in one week",
        "digest": {
            "account_id": 20,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1500.00, "clicks": 180, "leads": 16.0, "cost_per_lead": 93.75},
            "prior_week": {"spend": 2000.00, "clicks": 200, "leads": 12.0, "cost_per_lead": 166.67},
            "deltas": {"spend_pct": -25.0, "leads_pct": 33.3, "cpl_pct": -43.75},
            "agent": {
                "actions": {
                    "negative_keyword_added": 15,
                    "search_term_blocked": 5,
                    "keyword_paused": 4,
                    "ad_paused": 2,
                    "campaign_paused": 1,
                    "bid_adjusted": 8,
                    "budget_reallocated": 3,
                },
                "total_actions": 38,
                "estimated_monthly_savings": 600.0,
            },
            "top_keyword": {"text": "ac repair near me", "leads": 8.0, "spend": 600.0, "cost_per_lead": 75.0},
            "biggest_waster": {"text": "hvac certification", "spend": 180.0, "clicks": 22},
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "numbers_grounded": True,
        },
    },
    # ── 21. Single lead week ──────────────────────────────────────────────────
    {
        "id": "single_lead",
        "category": "accuracy",
        "description": "Only 1 lead this week — plural handling check",
        "digest": {
            "account_id": 21,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 320.00, "clicks": 40, "leads": 1.0, "cost_per_lead": 320.0},
            "prior_week": {"spend": 300.00, "clicks": 38, "leads": 2.0, "cost_per_lead": 150.0},
            "deltas": {"spend_pct": 6.7, "leads_pct": -50.0, "cpl_pct": 113.3},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "headline_contains": ["320", "1"],
            "numbers_grounded": True,
        },
    },
    # ── 22. Campaign triage present ───────────────────────────────────────────
    {
        "id": "campaign_triage",
        "category": "completeness",
        "description": "2 campaigns need action — triage_lines should be non-empty",
        "digest": {
            "account_id": 22,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1100.00, "clicks": 130, "leads": 11.0, "cost_per_lead": 100.0},
            "prior_week": {"spend": 1050.00, "clicks": 125, "leads": 10.0, "cost_per_lead": 105.0},
            "deltas": {"spend_pct": 4.8, "leads_pct": 10.0, "cpl_pct": -4.8},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "campaign_triage": {
                "needs_action": 2,
                "total": 5,
                "actions_needed": ["Pause Brand campaign — zero leads, $340 spent"],
                "summary_text": "2 of your 5 campaigns need attention.",
            },
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "triage_lines_non_empty": True,
            "numbers_grounded": True,
        },
    },
    # ── 23. Large spend delta ─────────────────────────────────────────────────
    {
        "id": "large_spend_increase",
        "category": "accuracy",
        "description": "Spend jumped $500 from prior week — summary should mention it",
        "digest": {
            "account_id": 23,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 2000.00, "clicks": 220, "leads": 18.0, "cost_per_lead": 111.1},
            "prior_week": {"spend": 1500.00, "clicks": 180, "leads": 14.0, "cost_per_lead": 107.1},
            "deltas": {"spend_pct": 33.3, "leads_pct": 28.6, "cpl_pct": 3.7},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "summary_contains_number": "500",
            "numbers_grounded": True,
        },
    },
    # ── 24. Zero spend but prior data ─────────────────────────────────────────
    {
        "id": "zero_spend_with_prior",
        "category": "completeness",
        "description": "Ads paused this week but ran last week",
        "digest": {
            "account_id": 24,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": False,
            "this_week": {"spend": 0.0, "clicks": 0, "leads": 0.0, "cost_per_lead": None},
            "prior_week": {"spend": 1200.00, "clicks": 140, "leads": 11.0, "cost_per_lead": 109.1},
            "deltas": {"spend_pct": -100.0, "leads_pct": -100.0, "cpl_pct": None},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        "expect": {
            "numbers_grounded": True,
        },
    },
    # ── 25. INVENTED NUMBER — must FAIL number grounding ─────────────────────
    # This case simulates a digest where the input says spend=$1,200 but the
    # output text claims "$2,400" — an invented number not in evidence.
    # The number-check rule must flag this as a failure.
    {
        "id": "invented_number_hallucination",
        "category": "no_hallucination",
        "description": "Output contains $2,400 but input spend is only $1,200 — must FAIL",
        "digest": {
            "account_id": 99,
            "week_start": "2024-01-01",
            "week_end": "2024-01-07",
            "has_data": True,
            "this_week": {"spend": 1200.00, "clicks": 140, "leads": 10.0, "cost_per_lead": 120.0},
            "prior_week": {"spend": 1100.00, "clicks": 130, "leads": 9.0, "cost_per_lead": 122.2},
            "deltas": {"spend_pct": 9.1, "leads_pct": 11.1, "cpl_pct": -1.8},
            "agent": {"actions": {}, "total_actions": 0, "estimated_monthly_savings": 0},
            "top_keyword": None,
            "biggest_waster": None,
            "next_steps": [],
            "generated_at": "2024-01-08T08:00:00",
        },
        # Injected output overrides what render_digest_text would produce.
        # The scorer sees this pre-baked output and must detect "$2,400" is not in evidence.
        "injected_output": {
            "headline": "Last week you spent $2,400 and got 10 leads — about $240 each.",
            "summary_lines": ["Each lead cost about 2% less than the week before."],
            "agent_lines": ["Your AI agent didn't need to make any changes last week."],
            "next_steps": [],
            "triage_lines": [],
        },
        "expect": {
            "numbers_grounded": False,  # MUST fail — $2,400 not in evidence
        },
    },
]
