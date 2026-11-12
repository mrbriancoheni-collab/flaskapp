"""
Weekly digest evaluation runner.

Usage:
    cd flaskapp
    python -m tests.evals.digest_eval [--judge] [--out DIR]

Options:
    --judge     Run model-as-judge in addition to rule scoring (needs ANTHROPIC_API_KEY or OPENAI_API_KEY)
    --out DIR   Directory to write raw output JSON files (default: /tmp/digest_eval_outputs)

Prints pass rate by category to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running from the flaskapp directory without installing the package
_HERE = Path(__file__).parent
_FLASKAPP = _HERE.parent.parent
sys.path.insert(0, str(_FLASKAPP))

from tests.evals.digest_eval_cases import CASES
from tests.evals.digest_scorer import ScorerResult, score_output


# ── Model-as-judge ────────────────────────────────────────────────────────────

JUDGE_SYSTEM = """\
You are an expert evaluator for AI-generated business digest text.
You will be given input data (what the digest knows) and output text (what it wrote).
Judge on three dimensions, scoring each 1–5:

1. accuracy   — Numbers and facts match the input data exactly.
2. clarity    — The writing is plain English a non-technical business owner understands.
3. usefulness — The output helps the owner decide what to do next.

Respond ONLY as valid JSON in this exact shape:
{
  "accuracy": <1-5>,
  "clarity": <1-5>,
  "usefulness": <1-5>,
  "reasoning": "<one sentence>"
}
"""

JUDGE_USER_TMPL = """\
INPUT DATA:
{input_json}

OUTPUT TEXT:
{output_text}
"""


def _judge_output(digest: Dict[str, Any], output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Call a model to judge the digest output quality. Returns None on failure."""
    output_text = "\n".join(
        [output.get("headline", "")]
        + output.get("summary_lines", [])
        + output.get("agent_lines", [])
        + output.get("next_steps", [])
        + output.get("triage_lines", [])
    ).strip()

    input_json = json.dumps({
        "this_week": digest.get("this_week"),
        "prior_week": digest.get("prior_week"),
        "agent": digest.get("agent"),
        "top_keyword": digest.get("top_keyword"),
        "biggest_waster": digest.get("biggest_waster"),
    }, indent=2)

    user_prompt = JUDGE_USER_TMPL.format(input_json=input_json, output_text=output_text)

    # Try Anthropic first, fall back to OpenAI
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
            msg = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=256,
                system=JUDGE_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = msg.content[0].text.strip()
            return json.loads(raw)
        except Exception as exc:
            print(f"  [judge] Anthropic error: {exc}", file=sys.stderr)

    if openai_key:
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=256,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw = resp.choices[0].message.content.strip()
            return json.loads(raw)
        except Exception as exc:
            print(f"  [judge] OpenAI error: {exc}", file=sys.stderr)

    return None


# ── Runner ────────────────────────────────────────────────────────────────────

def run_eval(use_judge: bool = False, out_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    # Import render_digest_text here so the eval can run without a full Flask app
    from app.services.google_ads_digest import render_digest_text

    output_dir = Path(out_dir) if out_dir else Path("/tmp/digest_eval_outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results: List[Dict[str, Any]] = []

    for case in CASES:
        digest = case["digest"]
        expect = case.get("expect", {})
        injected = case.get("injected_output")

        # Use injected output for the hallucination test; otherwise render normally
        if injected is not None:
            output = injected
        else:
            output = render_digest_text(digest)

        result: ScorerResult = score_output(
            case_id=case["id"],
            category=case["category"],
            digest=digest,
            output=output,
            expect=expect,
        )

        judge_scores: Optional[Dict[str, Any]] = None
        if use_judge:
            judge_scores = _judge_output(digest, output)

        row = {
            "case_id": case["id"],
            "category": case["category"],
            "description": case["description"],
            "passed": result.passed,
            "failed_checks": [c.name for c in result.failed_checks],
            "check_details": result.to_dict()["checks"],
            "judge": judge_scores,
            "output_text": {
                "headline": output.get("headline"),
                "summary_lines": output.get("summary_lines"),
                "agent_lines": output.get("agent_lines"),
                "next_steps": output.get("next_steps"),
            },
            "ran_at": datetime.utcnow().isoformat(),
        }
        all_results.append(row)

        # Save per-case raw output
        outfile = output_dir / f"{case['id']}.json"
        outfile.write_text(json.dumps(row, indent=2))

    # Save combined results
    summary_file = output_dir / "_summary.json"
    summary_file.write_text(json.dumps(all_results, indent=2))
    return all_results


def _print_report(results: List[Dict[str, Any]]) -> None:
    # Aggregate by category
    from collections import defaultdict
    cat_pass: Dict[str, int] = defaultdict(int)
    cat_total: Dict[str, int] = defaultdict(int)

    for r in results:
        cat = r["category"]
        cat_total[cat] += 1
        if r["passed"]:
            cat_pass[cat] += 1

    total = len(results)
    total_pass = sum(1 for r in results if r["passed"])

    print("\n" + "=" * 60)
    print("DIGEST EVAL REPORT")
    print("=" * 60)
    print(f"{'Category':<24} {'Pass':>6} {'Total':>6} {'Rate':>8}")
    print("-" * 60)
    for cat in sorted(cat_total):
        p = cat_pass[cat]
        t = cat_total[cat]
        pct = f"{p/t*100:.0f}%"
        print(f"  {cat:<22} {p:>6} {t:>6} {pct:>8}")
    print("-" * 60)
    overall = f"{total_pass/total*100:.0f}%" if total else "n/a"
    print(f"  {'OVERALL':<22} {total_pass:>6} {total:>6} {overall:>8}")
    print("=" * 60)

    # List failures
    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for r in failures:
            print(f"  [{r['category']}] {r['case_id']}")
            for fc in r["failed_checks"]:
                # Find reason
                detail = next((c for c in r["check_details"] if c["name"] == fc), {})
                reason = detail.get("reason", "")
                print(f"      ✗ {fc}: {reason}")
    else:
        print("\nAll cases passed.")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run digest evaluation set")
    parser.add_argument("--judge", action="store_true", help="Enable model-as-judge scoring")
    parser.add_argument("--out", default=None, help="Output directory for raw JSON results")
    args = parser.parse_args()

    print("Running digest eval...")
    results = run_eval(use_judge=args.judge, out_dir=args.out)
    _print_report(results)


if __name__ == "__main__":
    main()
