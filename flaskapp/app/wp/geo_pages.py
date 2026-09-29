# app/wp/geo_pages.py
"""
Geo Landing Page Generator.

For each (service, city) pair, generates a unique, locally-relevant
WordPress page using Claude. Each result is queued as a WPJob so the
existing cron_runner publishes it automatically.

Key design principle: every page must be *genuinely* unique — not just
the city name swapped in. The prompt instructs Claude to:
  - Reference realistic local context (weather, economy, typical homes)
  - Vary structure (intro angle, FAQ questions, CTA phrasing)
  - Include LocalBusiness + Service schema tailored to the city
  - Hit 600-900 words to avoid thin-content penalties
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _make_slug(service: str, city: str, state: str = "") -> str:
    parts = [service, city]
    if state:
        parts.append(state)
    raw = "-".join(parts).lower()
    return _SLUG_RE.sub("-", raw).strip("-")


def build_geo_job_payload(
    service: str,
    city: str,
    state: str,
    business_name: str,
    phone: str,
    extra_context: str = "",
) -> Dict[str, Any]:
    """
    Return a WPJob payload dict (kind='ai_generate') that will produce
    a fully-formed geo landing page when processed by cron_runner.
    """
    location = f"{city}, {state}" if state else city
    slug = _make_slug(service, city, state)
    title = f"{service} in {location}"

    prompt = f"""You are writing a geo-targeted service page for a local business.

Business: {business_name or 'a local service company'}
Service: {service}
Location: {location}
Phone: {phone or 'call us today'}
{('Additional context: ' + extra_context) if extra_context else ''}

Write a complete, publish-ready WordPress page in HTML. Requirements:
- 650-900 words of body content
- H1: "{service} in {location}" (exact)
- 2-3 H2 subheadings relevant to this specific location (mention local climate, typical homes, common issues in this area)
- A natural-sounding intro that references something specific and realistic about {city} (weather, growth, housing stock, etc.)
- A 4-6 item FAQ section using H3 headings with local-specific questions
- A strong CTA paragraph at the end with the phone number
- Embed this JSON-LD schema block in a <script type="application/ld+json"> tag:
  {{
    "@context": "https://schema.org",
    "@type": "Service",
    "serviceType": "{service}",
    "provider": {{
      "@type": "LocalBusiness",
      "name": "{business_name or 'Company Name'}",
      "telephone": "{phone or ''}",
      "areaServed": {{
        "@type": "City",
        "name": "{city}",
        "containedInPlace": {{ "@type": "State", "name": "{state}" }}
      }}
    }},
    "areaServed": "{location}"
  }}

Do NOT use placeholder text like [city] or [phone]. Write real, publishable content.
Return only the HTML body content — no <html>, <head>, or <body> tags."""

    return {
        "title":           title,
        "slug":            slug,
        "primary_keyword": f"{service} {location}",
        "prompt":          prompt,
        "word_count":      "750",
        "topics":          [service, city, location],
        "post_type":       "page",
        "source":          "geo_generator",
    }


def generate_geo_pages(
    service: str,
    cities: List[Dict[str, str]],
    business_name: str,
    phone: str,
    extra_context: str,
    site_id: int,
    db_session: Any,
) -> Dict[str, Any]:
    """Queue one WPJob per city for a single service. Returns summary dict."""
    return generate_geo_pages_multi(
        services=[service],
        cities=cities,
        business_name=business_name,
        phone=phone,
        extra_context=extra_context,
        site_id=site_id,
        db_session=db_session,
    )


def generate_geo_pages_multi(
    services: List[str],
    cities: List[Dict[str, str]],
    business_name: str,
    phone: str,
    extra_context: str,
    site_id: int,
    db_session: Any,
) -> Dict[str, Any]:
    """
    Queue one WPJob per (service, city) pair.
    Returns {"queued": [...], "skipped": [...]} where values are "Service — City" strings.
    """
    from app.models_wp import WPJob

    queued = []
    skipped = []

    for service in services:
        service = service.strip()
        if not service:
            continue
        for loc in cities:
            city  = loc.get("city", "").strip()
            state = loc.get("state", "").strip()
            if not city:
                continue

            payload = build_geo_job_payload(
                service=service,
                city=city,
                state=state,
                business_name=business_name,
                phone=phone,
                extra_context=extra_context,
            )
            label = f"{service} — {city}{', ' + state if state else ''}"

            existing = (
                WPJob.query
                .filter_by(site_id=site_id, kind="ai_generate")
                .filter(WPJob.payload["slug"].astext == payload["slug"])
                .first()
            )
            if existing:
                skipped.append(label)
                continue

            job = WPJob(site_id=site_id, kind="ai_generate", payload=payload)
            db_session.add(job)
            queued.append(label)

    db_session.commit()
    return {"queued": queued, "skipped": skipped}
