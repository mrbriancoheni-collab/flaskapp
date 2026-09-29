# app/public/maps_audit.py
"""
Public (no-login) Google Maps visibility audit — lead-gen funnel.

Visitor enters their business name + city, we look the business up with the
Google Places API (New) and grade the publicly visible profile signals.
The result page shows a teaser score plus locked checks that require a GBP
connection, driving registration → the full audit at /account/gmb/audit.

Requires GOOGLE_PLACES_API_KEY (or GOOGLE_MAPS_API_KEY) in the environment.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests
from flask import current_app, render_template, request, session

from . import public_bp

_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.rating",
    "places.userRatingCount",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.regularOpeningHours",
    "places.photos",
    "places.types",
    "places.businessStatus",
    "places.googleMapsUri",
])

_MAX_LOOKUPS_PER_HOUR = 10


def _api_key() -> Optional[str]:
    return (
        os.getenv("GOOGLE_PLACES_API_KEY")
        or current_app.config.get("GOOGLE_PLACES_API_KEY")
        or os.getenv("GOOGLE_MAPS_API_KEY")
        or current_app.config.get("GOOGLE_MAPS_API_KEY")
    )


def _throttled() -> bool:
    """Cheap per-session throttle so the public form can't drain API quota."""
    now = time.time()
    stamps = [t for t in session.get("maps_audit_lookups", []) if now - t < 3600]
    if len(stamps) >= _MAX_LOOKUPS_PER_HOUR:
        session["maps_audit_lookups"] = stamps
        return True
    stamps.append(now)
    session["maps_audit_lookups"] = stamps
    return False


def _search_place(query: str) -> Optional[Dict[str, Any]]:
    """Return the best-matching place for the query, or None."""
    key = _api_key()
    if not key:
        return None
    try:
        resp = requests.post(
            _SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": _FIELD_MASK,
            },
            json={"textQuery": query[:200], "maxResultCount": 1},
            timeout=(3, 15),
        )
        resp.raise_for_status()
        places = resp.json().get("places") or []
        return places[0] if places else None
    except Exception:
        current_app.logger.exception("Places text search failed")
        return None


def _grade_public_profile(place: Dict[str, Any]) -> Dict[str, Any]:
    """Score the publicly visible profile signals (teaser for the full audit)."""
    rating = float(place.get("rating") or 0)
    review_count = int(place.get("userRatingCount") or 0)
    photo_count = len(place.get("photos") or [])   # capped at 10 by the API — enough for the check
    has_hours = bool((place.get("regularOpeningHours") or {}).get("periods"))
    website = place.get("websiteUri")
    phone = place.get("nationalPhoneNumber")

    checks: List[Dict[str, Any]] = [
        {
            "label": "4.5+ star average rating",
            "passed": rating >= 4.5,
            "detail": f"Your rating: {rating or 'none'}",
            "action": "Resolve issues with unhappy customers before they review, and make "
                      "leaving a review effortless for happy ones.",
            "max_points": 15,
        },
        {
            "label": "10+ Google reviews",
            "passed": review_count >= 10,
            "detail": f"You have {review_count} reviews",
            "action": "Review count and recency are top-3 local ranking factors. Ask every "
                      "completed job for a review by text or email.",
            "max_points": 15,
        },
        {
            "label": "10+ photos on your profile",
            "passed": photo_count >= 10,
            "detail": f"{photo_count}{'+' if photo_count >= 10 else ''} photos visible",
            "action": "Upload trucks, team, and before/after job photos. Profiles with 10+ "
                      "photos get ~35% more clicks.",
            "max_points": 15,
        },
        {
            "label": "Business hours listed",
            "passed": has_hours,
            "detail": "Hours are set" if has_hours else "No hours listed",
            "action": "'Open now' is a live Maps filter — without hours you're invisible to it.",
            "max_points": 15,
        },
        {
            "label": "Website linked",
            "passed": bool(website),
            "detail": website or "No website on profile",
            "action": "Profiles with a website get significantly more clicks and trust.",
            "max_points": 10,
        },
        {
            "label": "Phone number listed",
            "passed": bool(phone),
            "detail": phone or "No phone on profile",
            "action": "Mobile users tap-to-call straight from Maps.",
            "max_points": 10,
        },
    ]

    earned = sum(c["max_points"] for c in checks if c["passed"])
    possible = sum(c["max_points"] for c in checks)
    score = round(earned / possible * 100)

    # Checks we can only grade with an authorized GBP connection — the upsell
    locked = [
        "Business description quality & keywords",
        "Service list completeness",
        "Review response rate (a direct ranking signal)",
        "Primary & additional category selection",
        "Search keywords you appear for",
        "Calls & website clicks from Maps (28-day trend)",
    ]

    return {
        "score": score,
        "checks": checks,
        "locked": locked,
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "rating": rating,
        "review_count": review_count,
    }


@public_bp.route("/maps-audit", methods=["GET", "POST"], endpoint="maps_audit")
def maps_audit():
    ctx: Dict[str, Any] = {
        "result": None,
        "place": None,
        "query": "",
        "error": None,
        "available": bool(_api_key()),
    }

    if request.method == "POST":
        business = (request.form.get("business") or "").strip()
        city = (request.form.get("city") or "").strip()
        ctx["query"] = business

        if not ctx["available"]:
            ctx["error"] = "The audit tool is temporarily unavailable. Please try again later."
        elif not business:
            ctx["error"] = "Enter your business name to run the audit."
        elif _throttled():
            ctx["error"] = "You've reached the lookup limit for now — try again in an hour."
        else:
            place = _search_place(f"{business} {city}".strip())
            if not place:
                ctx["error"] = (
                    "We couldn't find that business on Google Maps. "
                    "Try adding your city, or check the spelling."
                )
            else:
                ctx["place"] = {
                    "name": (place.get("displayName") or {}).get("text", business),
                    "address": place.get("formattedAddress", ""),
                    "maps_uri": place.get("googleMapsUri"),
                }
                ctx["result"] = _grade_public_profile(place)

    return render_template("public/maps_audit.html", **ctx)
