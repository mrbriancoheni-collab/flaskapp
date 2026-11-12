"""
Tests for the digest evaluation harness (Item 1).

Key assertions:
- The invented-number case (injected output with $2,400 when input has $1,200)
  is correctly detected as a failure by the number-grounding rule.
- All other cases produce a valid ScorerResult dict (structure check).
- Overall pass rate for non-hallucination cases is >= 80%.
"""
from __future__ import annotations

import pytest

from app.services.google_ads_digest import render_digest_text
from tests.evals.digest_eval_cases import CASES
from tests.evals.digest_scorer import score_output, _evidence_numbers, _number_grounded


# ── Invented number must be caught ───────────────────────────────────────────

def test_invented_number_fails():
    """$2,400 injected into output when input spend=$1,200 must trigger failure."""
    case = next(c for c in CASES if c["id"] == "invented_number_hallucination")
    digest = case["digest"]
    output = case["injected_output"]
    expect = case["expect"]

    result = score_output(
        case_id=case["id"],
        category=case["category"],
        digest=digest,
        output=output,
        expect=expect,
    )

    # The case expect says numbers_grounded=False → scorer should PASS when it
    # detects ungrounded numbers (i.e. the detection itself is the passing behaviour)
    assert result.passed, (
        f"Hallucination detector did not catch invented number. "
        f"Failed checks: {[c.name + ': ' + c.reason for c in result.failed_checks]}"
    )


def test_invented_number_evidence_does_not_contain_fabricated_value():
    """Evidence extracted from the input should contain 1200 but not 2400."""
    case = next(c for c in CASES if c["id"] == "invented_number_hallucination")
    evidence = _evidence_numbers(case["digest"])
    cleaned = [e.replace(",", "").replace("$", "") for e in evidence]
    assert "1200" in cleaned, f"Expected 1200 in evidence; got {evidence}"
    assert "2400" not in cleaned, f"Did not expect 2400 in evidence; got {evidence}"


def test_grounded_output_passes():
    """A correctly rendered output for a normal case should be grounded."""
    case = next(c for c in CASES if c["id"] == "normal_week_leads_and_spend")
    output = render_digest_text(case["digest"])
    evidence = _evidence_numbers(case["digest"])
    from tests.evals.digest_scorer import _all_text
    all_text = _all_text(output)
    grounded, ungrounded = _number_grounded(all_text, evidence)
    assert grounded, f"Unexpected ungrounded numbers: {ungrounded}"


# ── All cases produce valid structure ─────────────────────────────────────────

@pytest.mark.parametrize("case", [c for c in CASES if "injected_output" not in c], ids=[c["id"] for c in CASES if "injected_output" not in c])
def test_render_produces_required_keys(case):
    """render_digest_text must return all required keys for every non-injected case."""
    output = render_digest_text(case["digest"])
    for key in ("headline", "summary_lines", "agent_lines", "next_steps", "triage_lines"):
        assert key in output, f"Missing key '{key}' in output for case {case['id']}"
    assert isinstance(output["headline"], str) and output["headline"].strip(), (
        f"Empty headline for case {case['id']}"
    )
    assert isinstance(output["summary_lines"], list)
    assert isinstance(output["agent_lines"], list)


# ── Overall pass rate >= 80% for non-hallucination categories ─────────────────

def test_overall_pass_rate():
    """
    Non-hallucination cases should pass rule scoring at >= 80%.
    If this fails, a regression was introduced in render_digest_text.
    """
    non_hallucination = [c for c in CASES if c["category"] != "no_hallucination"]
    passed = 0
    failures = []

    for case in non_hallucination:
        output = render_digest_text(case["digest"])
        result = score_output(
            case_id=case["id"],
            category=case["category"],
            digest=case["digest"],
            output=output,
            expect=case.get("expect", {}),
        )
        if result.passed:
            passed += 1
        else:
            failures.append(f"{case['id']}: {[c.name for c in result.failed_checks]}")

    total = len(non_hallucination)
    rate = passed / total if total else 0
    assert rate >= 0.80, (
        f"Pass rate {rate:.0%} below 80% threshold. Failures:\n"
        + "\n".join(f"  {f}" for f in failures)
    )
