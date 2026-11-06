# app/account/rsa_generator_routes.py
"""
On-demand Google Ads RSA copy generator.

Routes:
  GET  /account/ads/rsa-generator  — render the generator UI
  POST /account/ads/rsa-generator  — generate copy via AI, returns JSON
"""
from __future__ import annotations

import logging

from flask import jsonify, render_template, request

from app.account import account_bp
from app.auth.utils import login_required

log = logging.getLogger(__name__)

_FALLBACK_HEADLINES = [
    "Local {trade} Experts",
    "Licensed & Insured {trade}",
    "Same-Day {trade} Service",
    "Free Estimates — Call Now",
    "24/7 Emergency {trade}",
    "Trusted {trade} Pros",
    "Affordable {trade} Repairs",
    "Fast, Reliable {trade}",
    "Top-Rated {trade} Service",
    "Your Local {trade} Team",
    "Quality {trade} Work",
    "Call for Free Quote",
    "Expert {trade} Help",
    "Serving {location}",
    "Book Online Today",
]

_FALLBACK_DESCRIPTIONS = [
    "Licensed, insured {trade} contractors serving {location}. Same-day appointments available. Call for a free estimate.",
    "Expert {trade} service with upfront pricing and no hidden fees. Trusted by homeowners across {location}.",
    "Fast, professional {trade} repairs and installations. Satisfaction guaranteed. Serving {location} for years.",
    "Get a free {trade} estimate today. Experienced technicians, competitive rates, available 24/7 in {location}.",
]

_SYSTEM_PROMPT = """You are an expert Google Ads copywriter specializing in trade contractor businesses (HVAC, plumbing, electrical, roofing, pest control, landscaping, etc.).

Generate RSA (Responsive Search Ad) copy for Google Ads. Return ONLY valid JSON with this exact structure:
{
  "headlines": ["...", ...],
  "descriptions": ["...", ...],
  "quality_notes": ["...", ...]
}

STRICT RULES:
- headlines: exactly 15 strings, each MAXIMUM 30 characters (count carefully — spaces count)
- descriptions: exactly 4 strings, each MAXIMUM 90 characters
- quality_notes: exactly 3 short actionable tips about the specific copy generated
- Every headline and description must be unique
- Use title case for headlines
- Include the local service area (city/region) in at least 2 headlines
- Include at least 2 trust signals (licensed, insured, certified, guaranteed, years of experience)
- Include at least 2 urgency/CTA phrases (call now, book today, same-day, free estimate, 24/7)
- Include the specific trade and service in multiple headlines
- descriptions should expand on headlines with more detail and a clear call to action
- Do NOT use special characters like ™, ®, punctuation that Google blocks
- quality_notes should be specific to the copy you generated — not generic tips"""


def _build_user_prompt(trade: str, service: str, location: str, usps: list[str], tone: str) -> str:
    usp_text = "\n".join(f"- {u}" for u in usps if u.strip())
    return f"""Generate Google Ads RSA copy for this trade contractor:

Trade/industry: {trade}
Specific service: {service}
Service area: {location}
Tone: {tone}
Unique selling points:
{usp_text if usp_text else '- Licensed & Insured\n- Same-day service\n- Free estimates'}

Remember: headlines max 30 chars, descriptions max 90 chars. Return only the JSON object."""


def _fallback_copy(trade: str, location: str) -> dict:
    label = trade.capitalize() if trade else "Contractor"
    headlines = [h.replace("{trade}", label).replace("{location}", location or "Your Area")
                 for h in _FALLBACK_HEADLINES]
    descriptions = [d.replace("{trade}", label.lower()).replace("{location}", location or "your area")
                    for d in _FALLBACK_DESCRIPTIONS]
    return {
        "headlines": headlines,
        "descriptions": descriptions,
        "quality_notes": [
            "Add your specific city name to more headlines for better local relevance.",
            "Include your years in business as a trust signal (e.g. '15+ Years Experience').",
            "Add a specific price point or guarantee to stand out from competitors.",
        ],
        "fallback": True,
    }


@account_bp.route("/ads/rsa-generator", methods=["GET"], endpoint="rsa_generator")
@login_required
def rsa_generator():
    return render_template("account/rsa_generator.html")


@account_bp.route("/ads/rsa-generator", methods=["POST"], endpoint="rsa_generator_generate")
@login_required
def rsa_generator_generate():
    try:
        data = request.get_json(silent=True) or {}
        trade = str(data.get("trade") or "").strip()[:60]
        service = str(data.get("service") or "").strip()[:100]
        location = str(data.get("location") or "").strip()[:80]
        usps = [str(data.get(f"usp{i}") or "").strip()[:100] for i in range(1, 4)]
        tone = str(data.get("tone") or "professional").strip().lower()
        if tone not in ("professional", "urgent", "friendly"):
            tone = "professional"

        if not trade:
            return jsonify({"ok": False, "error": "trade is required"}), 400

        try:
            from app.services.ai_client import generate_json
            user_prompt = _build_user_prompt(trade, service, location, usps, tone)
            result = generate_json(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=1800,
                temperature=0.7,
                prefer_provider="anthropic",
            )
        except Exception as ai_err:
            log.warning("RSA generator AI call failed: %s", ai_err)
            result = {}

        if not result or not isinstance(result.get("headlines"), list):
            copy = _fallback_copy(trade, location)
        else:
            # Enforce char limits — truncate rather than crash
            headlines = [h[:30] for h in result.get("headlines", [])[:15]]
            while len(headlines) < 15:
                headlines.append(f"{trade.title()} {location}"[:30] if location else f"Local {trade.title()}"[:30])
            descriptions = [d[:90] for d in result.get("descriptions", [])[:4]]
            while len(descriptions) < 4:
                descriptions.append(f"Expert {trade} service in {location}. Call for a free estimate today."[:90])
            notes = result.get("quality_notes", [])[:3]
            while len(notes) < 3:
                notes.append("Review each headline for your brand voice and local keywords.")
            copy = {"headlines": headlines, "descriptions": descriptions, "quality_notes": notes, "fallback": False}

        return jsonify({"ok": True, "copy": copy})

    except Exception as e:
        log.exception("rsa_generator_generate error: %s", e)
        return jsonify({"ok": False, "error": "Generation failed — please try again."}), 500
