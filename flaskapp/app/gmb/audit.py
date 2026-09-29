# app/gmb/audit.py
"""
Google Business Profile (Maps) optimization audit.

Pulls the real location record, reviews, and photos through the GBP APIs and
scores the profile against the completeness factors that drive local-pack /
Maps ranking for home-service businesses. Every check returns a concrete,
user-facing action so the audit doubles as a to-do list.

All API work fails soft: a failed call downgrades the related checks to
"unknown" rather than erroring the page.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests
from flask import current_app

_BIZINFO = "https://mybusinessbusinessinformation.googleapis.com/v1"
_V4 = "https://mybusiness.googleapis.com/v4"

# Fields we need from the location record to audit it
_READ_MASK = ",".join([
    "name",
    "title",
    "categories",
    "profile",
    "phoneNumbers",
    "websiteUri",
    "regularHours",
    "storefrontAddress",
    "serviceArea",
    "serviceItems",
    "labels",
    "metadata",
])


def get_location_details(access_token: str, location_name: str) -> Optional[Dict[str, Any]]:
    """GET the full location record (location_name like 'locations/123')."""
    try:
        resp = requests.get(
            f"{_BIZINFO}/{location_name}",
            params={"readMask": _READ_MASK},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(3, 30),
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        current_app.logger.exception("GBP get location details failed for %s", location_name)
        return None


def fetch_reviews_summary(access_token: str, account_name: str, location_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch review stats via the v4 API (still the only reviews endpoint).
    Returns {avg_rating, total_count, replied, unreplied, recent_unreplied[]}.
    """
    loc_id = location_name.split("/")[-1]
    acct_id = account_name.split("/")[-1]
    try:
        resp = requests.get(
            f"{_V4}/accounts/{acct_id}/locations/{loc_id}/reviews",
            params={"pageSize": 50, "orderBy": "updateTime desc"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(3, 30),
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        current_app.logger.exception("GBP reviews fetch failed for %s", location_name)
        return None

    reviews = data.get("reviews") or []
    replied = sum(1 for r in reviews if r.get("reviewReply"))
    unreplied = [
        {
            "author": (r.get("reviewer") or {}).get("displayName", "Anonymous"),
            "rating": r.get("starRating", ""),
            "comment": (r.get("comment") or "")[:280],
            "create_time": r.get("createTime"),
        }
        for r in reviews if not r.get("reviewReply")
    ]
    return {
        "avg_rating": data.get("averageRating"),
        "total_count": data.get("totalReviewCount", len(reviews)),
        "sampled": len(reviews),
        "replied": replied,
        "unreplied_count": len(unreplied),
        "recent_unreplied": unreplied[:5],
    }


def fetch_media_count(access_token: str, account_name: str, location_name: str) -> Optional[int]:
    """Count photos/videos on the profile via the v4 media endpoint."""
    loc_id = location_name.split("/")[-1]
    acct_id = account_name.split("/")[-1]
    try:
        resp = requests.get(
            f"{_V4}/accounts/{acct_id}/locations/{loc_id}/media",
            params={"pageSize": 100},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(3, 30),
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("mediaItems") or []
        # totalMediaItemCount is authoritative when present
        return int(data.get("totalMediaItemCount", len(items)))
    except Exception:
        current_app.logger.exception("GBP media fetch failed for %s", location_name)
        return None


def location_to_profile(location: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a GBP API location record into the profile dict the AI optimizer uses."""
    cats = location.get("categories") or {}
    primary = (cats.get("primaryCategory") or {}).get("displayName", "")
    additional = [c.get("displayName", "") for c in (cats.get("additionalCategories") or [])]

    addr = location.get("storefrontAddress") or {}
    addr_str = ", ".join(
        [*(addr.get("addressLines") or []), addr.get("locality", ""), addr.get("administrativeArea", "")]
    ).strip(", ")

    service_area = location.get("serviceArea") or {}
    places = [
        p.get("placeName", "")
        for p in ((service_area.get("places") or {}).get("placeInfos") or [])
    ]

    hours = location.get("regularHours") or {}
    hours_lines = []
    for p in hours.get("periods") or []:
        o, c = p.get("openTime") or {}, p.get("closeTime") or {}
        hours_lines.append(
            f"{p.get('openDay', '').title()}: "
            f"{o.get('hours', 0)}:{o.get('minutes', 0):02d}–{c.get('hours', 0)}:{c.get('minutes', 0):02d}"
        )

    services = []
    for item in location.get("serviceItems") or []:
        sd = item.get("structuredServiceItem") or {}
        fd = item.get("freeFormServiceItem") or {}
        label = sd.get("description") or (fd.get("label") or {}).get("displayName")
        if label:
            services.append(label)

    return {
        "name": location.get("title", ""),
        "primary_category": primary,
        "additional_categories": additional,
        "description": (location.get("profile") or {}).get("description", ""),
        "phone": (location.get("phoneNumbers") or {}).get("primaryPhone", ""),
        "website": location.get("websiteUri", ""),
        "address": addr_str,
        "service_areas": places,
        "hours_text": "\n".join(hours_lines),
        "attributes": location.get("labels") or [],
        "services": services,
    }


def _check(key: str, label: str, max_points: int, passed: Optional[bool],
           detail: str, action: str) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "max_points": max_points,
        "points": max_points if passed else 0,
        "passed": passed,          # None = unknown (API unavailable)
        "detail": detail,
        "action": action,
    }


def build_audit(location: Dict[str, Any],
                reviews: Optional[Dict[str, Any]] = None,
                media_count: Optional[int] = None) -> Dict[str, Any]:
    """
    Score a location 0-100 across the profile factors Google weighs for
    local ranking. Unknown checks (API unavailable) are excluded from the
    denominator so the score stays fair.
    """
    checks: List[Dict[str, Any]] = []

    cats = location.get("categories") or {}
    primary = (cats.get("primaryCategory") or {}).get("displayName")
    additional = cats.get("additionalCategories") or []
    checks.append(_check(
        "primary_category", "Primary category set", 12, bool(primary),
        f"Primary category: {primary or 'missing'}",
        "Choose the single most specific category for your main service "
        "(e.g. 'HVAC contractor', not 'Contractor'). It's the strongest Maps ranking signal.",
    ))
    checks.append(_check(
        "additional_categories", "2+ additional categories", 8, len(additional) >= 2,
        f"{len(additional)} additional categories set",
        "Add a category for every service line you offer (e.g. 'Furnace repair service', "
        "'Air duct cleaning service'). Each one makes you eligible for more searches.",
    ))

    desc = (location.get("profile") or {}).get("description", "") or ""
    checks.append(_check(
        "description", "Description 250+ characters", 10, len(desc) >= 250,
        f"Description length: {len(desc)} characters (750 max)",
        "Write a 400-750 character description covering your services, cities served, "
        "years in business, licensing, and a call to action. Use the AI Optimizer to draft it.",
    ))

    phone = (location.get("phoneNumbers") or {}).get("primaryPhone")
    checks.append(_check(
        "phone", "Phone number listed", 6, bool(phone),
        f"Phone: {phone or 'missing'}",
        "Add your main line — mobile users tap-to-call directly from Maps.",
    ))

    website = location.get("websiteUri")
    checks.append(_check(
        "website", "Website linked", 6, bool(website),
        f"Website: {website or 'missing'}",
        "Link your site; profiles with websites get significantly more clicks and trust.",
    ))

    hours = (location.get("regularHours") or {}).get("periods") or []
    checks.append(_check(
        "hours", "Business hours set", 10, len(hours) > 0,
        f"{len(hours)} day/time periods configured" if hours else "No hours set",
        "Set your hours — 'Open now' is a live filter in Maps, and profiles without hours "
        "look abandoned. Add extended/emergency hours if you offer them.",
    ))

    has_address = bool(location.get("storefrontAddress"))
    has_sa = bool(((location.get("serviceArea") or {}).get("places") or {}).get("placeInfos"))
    checks.append(_check(
        "coverage", "Address or service area defined", 6, has_address or has_sa,
        "Storefront address set" if has_address else
        ("Service area set" if has_sa else "No address or service area"),
        "Define your service area by city/zip so you appear in searches across your "
        "whole coverage zone, not just near your office.",
    ))

    services = location.get("serviceItems") or []
    checks.append(_check(
        "services", "Services listed", 12, len(services) >= 3,
        f"{len(services)} services listed",
        "Add every service you sell with a description and price range. Services show "
        "directly on your profile and match you to specific service searches.",
    ))

    if media_count is None:
        checks.append(_check(
            "photos", "10+ photos uploaded", 10, None,
            "Photo count unavailable", "Upload at least 10 photos: trucks, team, completed jobs, "
            "before/after. Profiles with 10+ photos get ~35% more clicks.",
        ))
    else:
        checks.append(_check(
            "photos", "10+ photos uploaded", 10, media_count >= 10,
            f"{media_count} photos/videos on profile",
            "Upload at least 10 photos: trucks, team, completed jobs, before/after. "
            "Add 2-3 new ones monthly — recency counts.",
        ))

    if reviews is None:
        checks.append(_check(
            "review_count", "10+ reviews", 6, None, "Review data unavailable",
            "Ask every happy customer for a review — use the review request tools on this page.",
        ))
        checks.append(_check(
            "review_rating", "4.5+ average rating", 6, None, "Review data unavailable",
            "Resolve unhappy customers before they review; respond publicly to negative reviews.",
        ))
        checks.append(_check(
            "review_response", "80%+ reviews responded to", 8, None, "Review data unavailable",
            "Respond to every review within 48 hours — response rate is a ranking and trust signal.",
        ))
    else:
        total = reviews.get("total_count") or 0
        avg = reviews.get("avg_rating") or 0
        sampled = max(reviews.get("sampled") or 0, 1)
        response_rate = (reviews.get("replied") or 0) / sampled
        checks.append(_check(
            "review_count", "10+ reviews", 6, total >= 10,
            f"{total} total reviews",
            "Ask every happy customer for a review — use the email/SMS review request tools. "
            "Review count and velocity are top-3 local ranking factors.",
        ))
        checks.append(_check(
            "review_rating", "4.5+ average rating", 6, float(avg or 0) >= 4.5,
            f"Average rating: {avg}",
            "Resolve unhappy customers before they review; respond publicly and professionally "
            "to negative reviews.",
        ))
        checks.append(_check(
            "review_response", "80%+ reviews responded to", 8, response_rate >= 0.8,
            f"{int(response_rate * 100)}% of recent reviews have replies "
            f"({reviews.get('unreplied_count', 0)} unanswered)",
            "Respond to every review within 48 hours. Use AI reply drafting on the Reviews "
            "page to clear the backlog in minutes.",
        ))

    known = [c for c in checks if c["passed"] is not None]
    earned = sum(c["points"] for c in known)
    possible = sum(c["max_points"] for c in known) or 1
    score = round(earned / possible * 100)

    failed = sorted(
        (c for c in checks if c["passed"] is False),
        key=lambda c: c["max_points"], reverse=True,
    )

    return {
        "score": score,
        "checks": checks,
        "top_actions": failed[:5],
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": len(failed),
        "unknown_count": sum(1 for c in checks if c["passed"] is None),
        "reviews": reviews,
        "media_count": media_count,
        "maps_uri": (location.get("metadata") or {}).get("mapsUri"),
        "new_review_uri": (location.get("metadata") or {}).get("newReviewUri"),
    }
