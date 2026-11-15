"""
Tests for render_digest_structured() — Item 2.

Verifies:
- Output has all required keys
- confidence score reflects data richness
- number_check_passed is True for real digest data
- blocked=True when output contains an invented number
- blocking_reason is set when blocked
- evidence list contains relevant metrics
"""
from __future__ import annotations

import pytest

from app.services.google_ads_digest import render_digest_structured


NORMAL_DIGEST = {
    "account_id": 1,
    "week_start": "2024-01-01",
    "week_end": "2024-01-07",
    "has_data": True,
    "this_week": {"spend": 1200.00, "clicks": 180, "leads": 15.0, "cost_per_lead": 80.0},
    "prior_week": {"spend": 1100.00, "clicks": 160, "leads": 12.0, "cost_per_lead": 91.67},
    "deltas": {"spend_pct": 9.1, "leads_pct": 25.0, "cpl_pct": -12.7},
    "agent": {
        "actions": {"negative_keyword_added": 5, "bid_adjusted": 3},
        "total_actions": 8,
        "estimated_monthly_savings": 95.0,
    },
    "top_keyword": {"text": "emergency plumber", "leads": 6.0, "spend": 480.0, "cost_per_lead": 80.0},
    "biggest_waster": None,
    "next_steps": [],
    "generated_at": "2024-01-08T08:00:00",
}

NO_DATA_DIGEST = {
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
}

INVENTED_DIGEST = {
    # Input says spend=$1,200 but we will monkeypatch an invented number into
    # the highlight text below.
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
}


# ── Required keys ─────────────────────────────────────────────────────────────

def test_structured_has_required_keys():
    result = render_digest_structured(NORMAL_DIGEST)
    for key in ("highlight", "evidence", "recommended_action", "confidence",
                "number_check_passed", "blocked", "blocking_reason", "render_text"):
        assert key in result, f"Missing key '{key}'"


def test_highlight_is_non_empty_string():
    result = render_digest_structured(NORMAL_DIGEST)
    assert isinstance(result["highlight"], str)
    assert result["highlight"].strip()


def test_evidence_is_list_of_dicts():
    result = render_digest_structured(NORMAL_DIGEST)
    assert isinstance(result["evidence"], list)
    assert len(result["evidence"]) > 0
    for item in result["evidence"]:
        assert "metric" in item
        assert "value" in item
        assert "label" in item


def test_recommended_action_is_non_empty_string():
    result = render_digest_structured(NORMAL_DIGEST)
    assert isinstance(result["recommended_action"], str)
    assert result["recommended_action"].strip()


# ── Confidence scores ─────────────────────────────────────────────────────────

def test_confidence_high_when_full_data():
    result = render_digest_structured(NORMAL_DIGEST)
    assert result["confidence"] >= 0.75


def test_confidence_low_when_no_data():
    result = render_digest_structured(NO_DATA_DIGEST)
    assert result["confidence"] <= 0.30


def test_confidence_medium_when_first_week():
    # Remove prior_week; confidence drops vs full-data case but stays above no-data floor
    first_week = {**NORMAL_DIGEST, "prior_week": None}
    full = render_digest_structured(NORMAL_DIGEST)
    first = render_digest_structured(first_week)
    assert first["confidence"] < full["confidence"], "First-week should be less confident than full-data"
    assert first["confidence"] > 0.25, "First-week still has ad data so confidence > no-data floor"


# ── Number check passes for real data ─────────────────────────────────────────

def test_number_check_passes_for_normal_digest():
    result = render_digest_structured(NORMAL_DIGEST)
    assert result["number_check_passed"] is True, (
        f"Number check failed unexpectedly. Blocking reason: {result['blocking_reason']}"
    )
    assert result["blocked"] is False
    assert result["blocking_reason"] is None


def test_number_check_passes_for_no_data_digest():
    result = render_digest_structured(NO_DATA_DIGEST)
    assert result["number_check_passed"] is True


# ── Invented number is blocked ────────────────────────────────────────────────

def test_invented_number_causes_block(monkeypatch):
    """
    Monkeypatch render_digest_text to return an invented $2,400 in the headline
    when input spend=$1,200.  render_digest_structured must detect and block it.
    """
    import app.services.google_ads_digest as mod

    original_render = mod.render_digest_text

    def fake_render(digest):
        result = original_render(digest)
        # Inject invented number — input spend is $1,200, output claims $2,400
        result["headline"] = "Last week you spent $2,400 and got 10 leads — about $240 each."
        return result

    monkeypatch.setattr(mod, "render_digest_text", fake_render)

    result = render_digest_structured(INVENTED_DIGEST)
    assert result["blocked"] is True, "Expected block for invented $2,400"
    assert result["number_check_passed"] is False
    assert result["blocking_reason"] is not None
    assert "2,400" in result["blocking_reason"] or "2400" in result["blocking_reason"]


# ── render_text backward compat ───────────────────────────────────────────────

def test_render_text_contains_legacy_keys():
    result = render_digest_structured(NORMAL_DIGEST)
    for key in ("headline", "summary_lines", "agent_lines", "next_steps", "triage_lines"):
        assert key in result["render_text"], f"Legacy key '{key}' missing from render_text"
