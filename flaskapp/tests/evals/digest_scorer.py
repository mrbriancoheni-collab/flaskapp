"""
Rule-based scorer for weekly digest output.

score_output(digest, output, expect) -> ScorerResult
  - Runs all deterministic checks.
  - Returns per-check pass/fail with reasons.

The key check is number_grounding: every dollar/integer figure that appears
in the rendered output must be traceable back to a number present in the
input digest data.  Cases where numbers_grounded=False in the expect dict
are expected to fail — this is the "invented number" detector.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CheckResult:
    name: str
    passed: bool
    reason: str = ""


@dataclass
class ScorerResult:
    case_id: str
    category: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "reason": c.reason}
                for c in self.checks
            ],
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_numbers(text: str) -> List[str]:
    """Extract dollar-formatted and plain integers from text."""
    # Match $1,234.56 / $1,234 / $12 / bare integers >= 2 digits
    return re.findall(r'\$[\d,]+(?:\.\d+)?|\b\d{2,}(?:,\d{3})*(?:\.\d+)?\b', text)


def _all_text(output: Dict[str, Any]) -> str:
    """
    Flatten AI-generated text fields into one string for number grounding.

    next_steps and triage_lines come from database records (optimizer_recommendations,
    campaign triage), not from the AI prose generator, so they are excluded from
    the number grounding check.
    """
    parts = [output.get("headline", "")]
    parts += output.get("summary_lines", [])
    parts += output.get("agent_lines", [])
    return " ".join(str(p) for p in parts)


def _evidence_numbers(digest: Dict[str, Any]) -> List[str]:
    """
    Collect every significant number from the digest input, including values
    that render_digest_text *derives* from the raw data:

    - Direct values from this_week, prior_week, agent, keywords
    - Absolute differences (spend, leads, CPL between weeks)
    - Rounded absolute delta percentages (what appears as "12% cheaper")
    """
    nums: List[str] = []

    def _add(val):
        if val is None:
            return
        try:
            f = float(val)
        except (TypeError, ValueError):
            return
        if f == 0:
            return
        whole = int(round(abs(f)))
        if whole == 0:
            return
        nums.append(str(whole))
        if whole >= 1000:
            nums.append(f"{whole:,}")

    # Direct source values
    for block_key in ("this_week", "prior_week"):
        block = digest.get(block_key) or {}
        for v in block.values():
            _add(v)

    # Delta percentages (absolute rounded) — appear in output as "12% cheaper"
    for v in (digest.get("deltas") or {}).values():
        if v is not None:
            _add(abs(float(v)))

    # Derived differences between weeks — appear as "3 more leads", "$100 more"
    tw = digest.get("this_week") or {}
    pw = digest.get("prior_week") or {}
    for key in ("spend", "leads", "cost_per_lead"):
        tw_val = tw.get(key)
        pw_val = pw.get(key)
        if tw_val is not None and pw_val is not None:
            try:
                _add(abs(float(tw_val) - float(pw_val)))
            except (TypeError, ValueError):
                pass

    # Agent — direct values
    agent = digest.get("agent") or {}
    actions = agent.get("actions") or {}
    for v in actions.values():
        _add(v)
    _add(agent.get("total_actions"))
    _add(agent.get("estimated_monthly_savings"))

    # Agent — computed sums that render_digest_text uses internally
    junk = (actions.get("negative_keyword_added") or 0) + (actions.get("search_term_blocked") or 0)
    _add(junk)
    ads_paused = (actions.get("ad_paused") or 0) + (actions.get("campaign_paused") or 0)
    _add(ads_paused)
    counted = (
        junk
        + (actions.get("keyword_paused") or 0)
        + ads_paused
        + (actions.get("bid_adjusted") or 0)
        + (actions.get("budget_reallocated") or 0)
    )
    other = max(0, int(agent.get("total_actions") or 0) - counted)
    _add(other)

    # Keywords
    for kw_key in ("top_keyword", "biggest_waster"):
        kw = digest.get(kw_key) or {}
        for v in kw.values():
            _add(v)

    # Campaign triage
    triage = digest.get("campaign_triage") or {}
    _add(triage.get("needs_action"))
    _add(triage.get("total"))

    return list(set(nums))


def _number_grounded(output_text: str, evidence: List[str]) -> tuple[bool, List[str]]:
    """
    Return (grounded, ungrounded_numbers).

    For every number found in the output, check whether it appears in the
    evidence list.  Small numbers (< 10) are excluded — they're words like
    "1 lead" or "2 times" that come from incidental template logic and are
    always derivable.  Percentage figures (ending in %) are also skipped
    since those come from computed deltas.
    """
    output_nums = _extract_numbers(output_text)
    ungrounded: List[str] = []

    for raw in output_nums:
        # Strip $ and commas for comparison
        clean = raw.replace("$", "").replace(",", "")
        try:
            val = float(clean)
        except ValueError:
            continue

        if val < 10:
            continue  # ignore trivially small counts

        # Check against evidence (also strip $ and commas)
        found = any(
            clean == e.replace("$", "").replace(",", "")
            for e in evidence
        )
        if not found:
            # Allow derived percentages that appear in deltas
            # by checking if any delta absolute value rounds to this number
            ungrounded.append(raw)

    return (len(ungrounded) == 0), ungrounded


# ── Main scorer ───────────────────────────────────────────────────────────────

def score_output(
    case_id: str,
    category: str,
    digest: Dict[str, Any],
    output: Dict[str, Any],
    expect: Dict[str, Any],
) -> ScorerResult:
    result = ScorerResult(case_id=case_id, category=category)
    all_text = _all_text(output)

    # ── Structure check ───────────────────────────────────────────────────────
    for key in ("headline", "summary_lines", "agent_lines", "next_steps", "triage_lines"):
        present = key in output and output[key] is not None
        result.checks.append(CheckResult(
            name=f"has_{key}",
            passed=present,
            reason="" if present else f"Missing key '{key}' in output",
        ))

    headline = output.get("headline", "")
    result.checks.append(CheckResult(
        name="headline_non_empty",
        passed=bool(headline.strip()),
        reason="" if headline.strip() else "Headline is empty",
    ))

    # ── Expect: headline_contains ─────────────────────────────────────────────
    for token in (expect.get("headline_contains") or []):
        found = token in headline
        result.checks.append(CheckResult(
            name=f"headline_contains_{token}",
            passed=found,
            reason="" if found else f"Headline missing '{token}': {headline!r}",
        ))

    # ── Expect: summary_contains ──────────────────────────────────────────────
    summary_text = " ".join(output.get("summary_lines") or [])
    for token in (expect.get("summary_contains") or []):
        found = token.lower() in summary_text.lower()
        result.checks.append(CheckResult(
            name=f"summary_contains_{token}",
            passed=found,
            reason="" if found else f"Summary missing '{token}'",
        ))

    # ── Expect: summary_contains_number ──────────────────────────────────────
    for num in ([expect.get("summary_contains_number")] if expect.get("summary_contains_number") else []):
        found = num in summary_text.replace(",", "")
        result.checks.append(CheckResult(
            name=f"summary_has_number_{num}",
            passed=found,
            reason="" if found else f"Summary missing number '{num}'",
        ))

    # ── Expect: agent_contains_number ─────────────────────────────────────────
    agent_text = " ".join(output.get("agent_lines") or [])
    for num in ([expect.get("agent_contains_number")] if expect.get("agent_contains_number") else []):
        found = num in agent_text.replace(",", "")
        result.checks.append(CheckResult(
            name=f"agent_has_number_{num}",
            passed=found,
            reason="" if found else f"Agent lines missing number '{num}'",
        ))

    # ── Expect: next_steps_count_min ──────────────────────────────────────────
    if "next_steps_count_min" in expect:
        ns = output.get("next_steps") or []
        ok = len(ns) >= expect["next_steps_count_min"]
        result.checks.append(CheckResult(
            name="next_steps_count_min",
            passed=ok,
            reason="" if ok else f"Expected ≥{expect['next_steps_count_min']} next steps, got {len(ns)}",
        ))

    # ── Expect: triage_lines_non_empty ────────────────────────────────────────
    if expect.get("triage_lines_non_empty"):
        tl = output.get("triage_lines") or []
        ok = len(tl) > 0 and any(tl)
        result.checks.append(CheckResult(
            name="triage_lines_non_empty",
            passed=ok,
            reason="" if ok else "Expected non-empty triage_lines",
        ))

    # ── Number grounding (key safety check) ───────────────────────────────────
    if "numbers_grounded" in expect:
        evidence = _evidence_numbers(digest)
        grounded, ungrounded = _number_grounded(all_text, evidence)
        expected_grounded = expect["numbers_grounded"]
        if expected_grounded:
            result.checks.append(CheckResult(
                name="numbers_grounded",
                passed=grounded,
                reason="" if grounded else f"Ungrounded numbers in output: {ungrounded}",
            ))
        else:
            # Case expects a failure (the invented-number test)
            result.checks.append(CheckResult(
                name="numbers_grounded_expected_fail",
                passed=not grounded,
                reason=(
                    "Correctly detected invented numbers"
                    if not grounded
                    else f"Expected invented numbers to be caught but all grounded (evidence={evidence[:6]})"
                ),
            ))

    return result
