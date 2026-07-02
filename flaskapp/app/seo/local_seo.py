# app/seo/local_seo.py
"""
Local SEO Audit Engine.

Fetches a page and audits it for local SEO signals critical to
local service businesses (HVAC, plumbing, electrical, roofing, etc.):
  - LocalBusiness / Service schema presence + completeness
  - NAP (Name, Address, Phone) in structured data
  - Location keywords in title, H1, and body
  - Phone number and address in visible content
  - Google Maps embed
  - Review / rating schema
  - hCard microdata
Returns a structured result with pass/warn/fail per check + overall score.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

_TIMEOUT = 10
_LOCAL_BUSINESS_TYPES = {
    "LocalBusiness", "Plumber", "HVACBusiness", "Electrician", "Locksmith",
    "HomeAndConstructionBusiness", "RoofingContractor", "PaintingContractor",
    "GeneralContractor", "Landscaper", "HousePainter", "Service",
}
_PHONE_RE = re.compile(
    r"(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})"
)
_ADDR_KEYWORDS = re.compile(
    r"\b(street|st\.?|avenue|ave\.?|road|rd\.?|blvd\.?|boulevard|drive|dr\.?|lane|ln\.?|"
    r"suite|ste\.?|floor|fl\.?|zip|postal)\b", re.IGNORECASE
)
_MAP_EMBED = re.compile(r"google\.com/maps|maps\.google\.|goo\.gl/maps", re.IGNORECASE)


def _get_page(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=_TIMEOUT, headers={"User-Agent": "FieldSprout-LocalSEO/1.0"})
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _extract_json_ld(html: str) -> List[Dict]:
    schemas = []
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                         html, re.DOTALL | re.IGNORECASE):
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj, list):
                schemas.extend(obj)
            else:
                schemas.append(obj)
            # Unwrap @graph
            if "@graph" in obj:
                schemas.extend(obj["@graph"])
        except Exception:
            pass
    return schemas


def _find_local_schema(schemas: List[Dict]) -> Optional[Dict]:
    for s in schemas:
        t = s.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if any(lt in _LOCAL_BUSINESS_TYPES for lt in types):
            return s
    return None


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _check(label: str, status: str, detail: str, fix: str = "") -> Dict:
    return {"label": label, "status": status, "detail": detail, "fix": fix}


def audit_local_seo(url: str, city: str = "", business_name: str = "") -> Dict[str, Any]:
    """
    Run a local SEO audit on `url`.
    Returns {checks, score, schema_data, error}.
    """
    html = _get_page(url)
    if not html:
        return {"checks": [], "score": 0, "schema_data": None,
                "error": f"Could not fetch {url}"}

    text = _strip_tags(html)
    html_lower = html.lower()
    checks: List[Dict] = []

    # ── Schema checks ────────────────────────────────────────────────────────
    schemas = _extract_json_ld(html)
    local_schema = _find_local_schema(schemas)

    checks.append(_check(
        "LocalBusiness Schema",
        "pass" if local_schema else "fail",
        "LocalBusiness (or subtype) JSON-LD found." if local_schema
        else "No LocalBusiness schema detected.",
        "" if local_schema else
        "Add JSON-LD schema with @type: LocalBusiness (or a service-specific subtype like Plumber, HVACBusiness).",
    ))

    if local_schema:
        # NAP in schema
        has_name    = bool(local_schema.get("name"))
        has_address = bool(local_schema.get("address"))
        has_phone   = bool(local_schema.get("telephone"))
        nap_score   = sum([has_name, has_address, has_phone])
        checks.append(_check(
            "NAP in Schema (Name, Address, Phone)",
            "pass" if nap_score == 3 else ("warn" if nap_score >= 1 else "fail"),
            f"Found {nap_score}/3 NAP fields in schema (name={has_name}, address={has_address}, phone={has_phone}).",
            "" if nap_score == 3 else "Add missing NAP fields to your LocalBusiness schema.",
        ))

        # Geo coordinates
        has_geo = bool(local_schema.get("geo") or local_schema.get("latitude"))
        checks.append(_check(
            "Geo Coordinates in Schema",
            "pass" if has_geo else "warn",
            "GeoCoordinates present in schema." if has_geo else "No geo coordinates found.",
            "" if has_geo else
            "Add @type:GeoCoordinates with latitude/longitude to help Google map your location.",
        ))

        # Opening hours
        has_hours = bool(local_schema.get("openingHours") or local_schema.get("openingHoursSpecification"))
        checks.append(_check(
            "Opening Hours in Schema",
            "pass" if has_hours else "warn",
            "Opening hours found in schema." if has_hours else "No opening hours in schema.",
            "" if has_hours else "Add openingHours (e.g. 'Mo-Fr 08:00-17:00') to your LocalBusiness schema.",
        ))

        # Review/rating
        has_rating = bool(local_schema.get("aggregateRating"))
        checks.append(_check(
            "Aggregate Rating in Schema",
            "pass" if has_rating else "warn",
            "AggregateRating found." if has_rating else "No aggregateRating in schema.",
            "" if has_rating else
            "Add aggregateRating with ratingValue and reviewCount if you have reviews.",
        ))
    else:
        for label in ("NAP in Schema", "Geo Coordinates in Schema",
                      "Opening Hours in Schema", "Aggregate Rating in Schema"):
            checks.append(_check(label, "fail",
                                 "Cannot check — no LocalBusiness schema found.",
                                 "Add LocalBusiness schema first."))

    # ── Title / H1 ───────────────────────────────────────────────────────────
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title_text = _strip_tags(title_m.group(1)) if title_m else ""
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    h1_text = _strip_tags(h1_m.group(1)) if h1_m else ""

    city_in_title = city.lower() in title_text.lower() if city else None
    city_in_h1    = city.lower() in h1_text.lower() if city else None

    checks.append(_check(
        "City/Location in Title Tag",
        "pass" if (city_in_title or not city) else "warn",
        f"Title: \"{title_text[:80]}\"" + (f" — '{city}' {'found' if city_in_title else 'NOT found'}" if city else ""),
        "" if (city_in_title or not city) else
        f"Include '{city}' in your title tag, e.g. 'HVAC Repair in {city} | Company Name'.",
    ))

    checks.append(_check(
        "City/Location in H1",
        "pass" if (city_in_h1 or not city) else "warn",
        f"H1: \"{h1_text[:80]}\"" + (f" — '{city}' {'found' if city_in_h1 else 'NOT found'}" if city else ""),
        "" if (city_in_h1 or not city) else
        f"Include '{city}' in your H1 heading.",
    ))

    # ── Phone in content ─────────────────────────────────────────────────────
    phones = _PHONE_RE.findall(text)
    has_phone_content = len(phones) > 0
    checks.append(_check(
        "Phone Number in Content",
        "pass" if has_phone_content else "fail",
        f"Found {len(phones)} phone number(s) on page." if has_phone_content
        else "No phone number detected in page content.",
        "" if has_phone_content else
        "Add your phone number prominently — in the header, footer, and body content.",
    ))

    # ── Address keywords in content ───────────────────────────────────────────
    has_addr = bool(_ADDR_KEYWORDS.search(text))
    checks.append(_check(
        "Physical Address in Content",
        "pass" if has_addr else "warn",
        "Address-like content detected on page." if has_addr
        else "No address keywords found in visible content.",
        "" if has_addr else
        "Add your full street address to the page, ideally in the footer and a contact section.",
    ))

    # ── Google Maps embed ─────────────────────────────────────────────────────
    has_map = bool(_MAP_EMBED.search(html))
    checks.append(_check(
        "Google Maps Embed",
        "pass" if has_map else "warn",
        "Google Maps embed found on page." if has_map
        else "No Google Maps embed detected.",
        "" if has_map else
        "Embed a Google Map of your business location — it reinforces local relevance.",
    ))

    # ── Schema service area ───────────────────────────────────────────────────
    has_service_area = bool(local_schema and local_schema.get("areaServed"))
    checks.append(_check(
        "Service Area in Schema",
        "pass" if has_service_area else "warn",
        "areaServed found in schema." if has_service_area
        else "No areaServed defined in schema.",
        "" if has_service_area else
        "Add areaServed to your LocalBusiness schema listing the cities/regions you serve.",
    ))

    # ── Score ─────────────────────────────────────────────────────────────────
    weights = {"pass": 2, "warn": 1, "fail": 0}
    total_weight = len(checks) * 2
    earned = sum(weights[c["status"]] for c in checks)
    score = round(earned / total_weight * 100) if total_weight else 0

    return {
        "checks":      checks,
        "score":       score,
        "schema_data": local_schema,
        "title":       title_text,
        "h1":          h1_text,
        "error":       None,
    }
