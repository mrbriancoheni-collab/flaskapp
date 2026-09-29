# app/market_research/review_miner.py
"""
Review Miner — pulls and classifies Google reviews for competitors in a
given trade + city to extract ad copy language for FieldSprout.

Public entry point
------------------
    from app.market_research.review_miner import mine_reviews

    result = mine_reviews(trade="hvac", city="Dallas TX")

Returns the structured schema documented in mine_reviews().
Caches results in /tmp/fs_research/ for 7 days to avoid re-hitting APIs.
Falls back to a mock dataset when SerpAPI is unavailable.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trade → search query templates
# ---------------------------------------------------------------------------

TRADE_SEARCH_QUERIES: Dict[str, List[str]] = {
    "hvac": [
        "hvac company {city}",
        "air conditioning repair {city}",
        "heating repair {city}",
    ],
    "plumbing": [
        "plumber {city}",
        "plumbing company {city}",
    ],
    "electrical": [
        "electrician {city}",
        "electrical contractor {city}",
    ],
    "roofing": [
        "roofing company {city}",
        "roofer {city}",
    ],
    "landscaping": [
        "landscaping company {city}",
        "lawn care {city}",
    ],
    "pest-control": [
        "pest control {city}",
        "exterminator {city}",
    ],
    "garage-door": [
        "garage door repair {city}",
        "garage door company {city}",
    ],
    "pools": [
        "pool service {city}",
        "pool cleaning {city}",
    ],
}

# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

_CACHE_DIR = "/tmp/fs_research"
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


def _cache_key(trade: str, city: str) -> str:
    safe = lambda s: s.lower().replace(" ", "_").replace(",", "").replace("/", "-")
    return os.path.join(_CACHE_DIR, f"reviews_{safe(trade)}_{safe(city)}.json")


def _load_from_cache(trade: str, city: str) -> Optional[Dict[str, Any]]:
    path = _cache_key(trade, city)
    try:
        if not os.path.exists(path):
            return None
        age = time.time() - os.path.getmtime(path)
        if age > _CACHE_TTL_SECONDS:
            log.debug("Cache expired for %s / %s (%.0fh old)", trade, city, age / 3600)
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        log.info("Returning cached review data for %s / %s", trade, city)
        return data
    except Exception as exc:
        log.warning("Cache read failed: %s", exc)
        return None


def _save_to_cache(trade: str, city: str, data: Dict[str, Any]) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        path = _cache_key(trade, city)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        log.debug("Cached review data → %s", path)
    except Exception as exc:
        log.warning("Cache write failed: %s", exc)


# ---------------------------------------------------------------------------
# SerpAPI helpers
# ---------------------------------------------------------------------------

_SERPAPI_BASE = "https://serpapi.com/search"


def _get_serpapi_key() -> Optional[str]:
    """Return the SerpAPI key from Flask config or env, or None."""
    try:
        from flask import current_app
        key = current_app.config.get("SERPAPI_API_KEY") or os.getenv("SERPAPI_API_KEY")
    except RuntimeError:
        key = os.getenv("SERPAPI_API_KEY")
    return (key or "").strip() or None


def _serpapi_get(params: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    """
    Execute a SerpAPI request and return the parsed JSON.
    Raises requests.RequestException on non-200 or network errors.
    """
    response = requests.get(_SERPAPI_BASE, params=params, timeout=timeout)
    if response.status_code != 200:
        try:
            err = response.json().get("error", response.text[:200])
        except Exception:
            err = response.text[:200]
        raise requests.RequestException(f"SerpAPI {response.status_code}: {err}")
    return response.json()


def _fetch_businesses(queries: List[str], location: str, max_per_query: int = 5) -> List[Dict[str, Any]]:
    """
    Use the google_maps engine to discover competitor businesses.
    Returns a deduplicated list of {name, data_id, place_id, rating, review_count}.
    """
    api_key = _get_serpapi_key()
    if not api_key:
        raise ValueError("SERPAPI_API_KEY is not configured")

    seen: set = set()
    businesses: List[Dict[str, Any]] = []

    for query in queries[:2]:  # Limit to 2 queries to conserve quota
        try:
            data = _serpapi_get({
                "api_key": api_key,
                "engine": "google_maps",
                "q": query,
                "type": "search",
                "hl": "en",
                "gl": "us",
            })

            for place in data.get("local_results", [])[:max_per_query]:
                data_id = place.get("data_id") or place.get("place_id")
                name = place.get("title", "").strip()
                if not data_id or not name or data_id in seen:
                    continue
                seen.add(data_id)
                businesses.append({
                    "name": name,
                    "data_id": data_id,
                    "place_id": place.get("place_id"),
                    "rating": place.get("rating"),
                    "review_count": place.get("reviews"),
                    "address": place.get("address"),
                })
            log.info("google_maps '%s' → %d places", query, len(data.get("local_results", [])))

        except Exception as exc:
            log.warning("google_maps search failed for '%s': %s", query, exc)

    return businesses


def _fetch_reviews_for_place(data_id: str, api_key: str, max_reviews: int = 20) -> List[Dict[str, Any]]:
    """
    Use the google_maps_reviews engine to pull reviews for a single place.
    Returns a list of {rating, text, date} dicts.
    """
    reviews: List[Dict[str, Any]] = []
    try:
        data = _serpapi_get({
            "api_key": api_key,
            "engine": "google_maps_reviews",
            "data_id": data_id,
            "hl": "en",
            "sort_by": "ratingHigh",  # surface 5-stars first
        })
        for r in data.get("reviews", [])[:max_reviews]:
            text = (r.get("snippet") or r.get("text") or "").strip()
            if text:
                reviews.append({
                    "rating": r.get("rating"),
                    "text": text,
                    "date": r.get("date", ""),
                })
        # Also pull low-star reviews in a second pass
        data_low = _serpapi_get({
            "api_key": api_key,
            "engine": "google_maps_reviews",
            "data_id": data_id,
            "hl": "en",
            "sort_by": "ratingLow",
        })
        seen_texts = {r["text"] for r in reviews}
        for r in data_low.get("reviews", [])[:max_reviews]:
            text = (r.get("snippet") or r.get("text") or "").strip()
            if text and text not in seen_texts:
                reviews.append({
                    "rating": r.get("rating"),
                    "text": text,
                    "date": r.get("date", ""),
                })
                seen_texts.add(text)
    except Exception as exc:
        log.warning("google_maps_reviews failed for data_id=%s: %s", data_id, exc)
    return reviews


# ---------------------------------------------------------------------------
# AI classification helpers
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM = (
    "You are an expert copywriter and consumer-psychology analyst. "
    "You extract verbatim and paraphrased phrases from customer reviews to help "
    "a home-services company write compelling ads."
)


def _classify_batch(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Send a batch of up to 10 reviews to the AI and get back classified phrases.
    Returns a partial result dict that is merged into the final output.
    """
    from app.services.ai_client import generate_json  # deferred to avoid circular imports at module load

    # Separate by rating bucket
    five_star = [r for r in reviews if r.get("rating") == 5]
    one_star = [r for r in reviews if r.get("rating") == 1]
    three_star = [r for r in reviews if r.get("rating") == 3]

    partial: Dict[str, Any] = {
        "five_star": {"phrases": [], "transformation_words": [], "what_surprised_them": []},
        "one_star": {"objections": [], "core_fears": [], "specific_complaints": []},
        "three_star": {"gaps": []},
    }

    if not any([five_star, one_star, three_star]):
        return partial

    review_text = json.dumps(
        {
            "five_star_reviews": [r["text"] for r in five_star],
            "one_star_reviews": [r["text"] for r in one_star],
            "three_star_reviews": [r["text"] for r in three_star],
        },
        ensure_ascii=False,
    )

    user_prompt = f"""Analyze these home-services customer reviews and extract phrases.

Reviews:
{review_text}

Return JSON with this exact structure:
{{
  "five_star": {{
    "phrases": ["short verbatim or near-verbatim phrases that show delight, max 8"],
    "transformation_words": ["power words like 'finally', 'relief', 'back to normal', max 6"],
    "what_surprised_them": ["things the customer didn't expect but loved, max 6"]
  }},
  "one_star": {{
    "objections": ["short phrases describing what went wrong, max 8"],
    "core_fears": ["the underlying fear or loss the customer felt, max 6"],
    "specific_complaints": ["verbatim complaints worth noting for competitive ads, max 6"]
  }},
  "three_star": {{
    "gaps": ["'good X but Y' style phrases showing unmet expectations, max 6"]
  }}
}}

Keep all phrases short (under 12 words). Extract only phrases actually present in the reviews."""

    result = generate_json(_CLASSIFY_SYSTEM, user_prompt, max_tokens=1200, temperature=0.2)

    # Safely merge, tolerating partial AI responses
    for bucket in ("five_star", "one_star", "three_star"):
        if bucket in result and isinstance(result[bucket], dict):
            for key, val in result[bucket].items():
                if isinstance(val, list):
                    partial[bucket].setdefault(key, [])
                    partial[bucket][key].extend(val)

    return partial


# ---------------------------------------------------------------------------
# Mock data fallback
# ---------------------------------------------------------------------------

def _generate_mock_data(trade: str, city: str) -> Dict[str, Any]:
    """Return plausible mock review phrases when SerpAPI is unavailable."""
    log.info("Returning mock review data (no SerpAPI key or quota exhausted)")
    now = datetime.now(timezone.utc).isoformat()

    trade_phrases: Dict[str, Dict[str, Any]] = {
        "hvac": {
            "five_star": {
                "phrases": [
                    "showed up in 45 minutes",
                    "fixed it the same day",
                    "no surprise charges",
                    "had the part on the truck",
                    "ice cold within the hour",
                ],
                "transformation_words": ["finally", "relief", "back to normal", "so fast", "wow"],
                "what_surprised_them": [
                    "called back immediately",
                    "explained everything clearly",
                    "no upsell attempt",
                    "cleaned up after themselves",
                ],
            },
            "one_star": {
                "objections": [
                    "never showed up",
                    "price changed after the quote",
                    "took 3 days to finish",
                    "didn't fix the problem",
                ],
                "core_fears": [
                    "wasted money",
                    "left without AC for days",
                    "felt ripped off",
                    "still broken after they left",
                ],
                "specific_complaints": [
                    "charged a diagnostic fee and fixed nothing",
                    "gave a quote then doubled it on site",
                ],
            },
            "three_star": {
                "gaps": [
                    "good work but really expensive",
                    "showed up late but fixed it right",
                    "tech was knowledgeable but office is hard to reach",
                ],
            },
        },
        "plumbing": {
            "five_star": {
                "phrases": [
                    "found the leak in minutes",
                    "done in under an hour",
                    "fair price upfront",
                ],
                "transformation_words": ["relief", "finally dry", "saved us", "right away"],
                "what_surprised_them": [
                    "wore shoe covers inside",
                    "showed me the issue on video",
                    "no mess left behind",
                ],
            },
            "one_star": {
                "objections": [
                    "still leaking after the repair",
                    "charged emergency rate for regular hours",
                    "didn't call back for two days",
                ],
                "core_fears": [
                    "water damage spreading",
                    "charged for nothing",
                    "had to call someone else",
                ],
                "specific_complaints": [
                    "said they'd be there at 9am and showed up at 4pm",
                ],
            },
            "three_star": {
                "gaps": [
                    "fixed the pipe but left a mess",
                    "professional but pricier than expected",
                ],
            },
        },
    }

    default_phrases = {
        "five_star": {
            "phrases": ["very professional", "got the job done fast", "fair price"],
            "transformation_words": ["finally", "relief", "great"],
            "what_surprised_them": ["showed up on time", "explained the work", "clean work area"],
        },
        "one_star": {
            "objections": ["didn't show up", "overcharged", "poor communication"],
            "core_fears": ["wasted money", "problem not fixed", "felt ignored"],
            "specific_complaints": ["no-show on appointment day", "price doubled on site"],
        },
        "three_star": {
            "gaps": ["good work but slow", "professional but expensive"],
        },
    }

    phrases = trade_phrases.get(trade, default_phrases)

    return {
        "trade": trade,
        "city": city,
        "scraped_at": now,
        "five_star": phrases["five_star"],
        "one_star": phrases["one_star"],
        "three_star": phrases["three_star"],
        "competitor_names_found": ["Mock Competitor A", "Mock Competitor B"],
        "total_reviews_analyzed": 0,
        "_mock": True,
    }


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def mine_reviews(
    trade: str,
    city: str,
    competitor_name: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """
    Pull and classify Google reviews for competitors in a given trade + city.

    Parameters
    ----------
    trade : str
        Trade key from TRADE_SEARCH_QUERIES (e.g. "hvac", "plumbing").
        Unknown trades fall back to a generic search of "<trade> company {city}".
    city : str
        City + state string, e.g. "Dallas TX" or "Austin, TX".
    competitor_name : str, optional
        If provided, this name is searched first and prioritised.
    force_refresh : bool
        Skip the cache and re-fetch from the API.

    Returns
    -------
    dict with schema::

        {
            "trade": str,
            "city": str,
            "scraped_at": ISO-8601 str,
            "five_star": {
                "phrases": [...],
                "transformation_words": [...],
                "what_surprised_them": [...],
            },
            "one_star": {
                "objections": [...],
                "core_fears": [...],
                "specific_complaints": [...],
            },
            "three_star": {
                "gaps": [...],
            },
            "competitor_names_found": [...],
            "total_reviews_analyzed": int,
        }
    """
    trade = trade.lower().strip()
    city = city.strip()

    # 1. Cache check
    if not force_refresh:
        cached = _load_from_cache(trade, city)
        if cached:
            return cached

    # 2. Resolve search queries for this trade
    base_queries = TRADE_SEARCH_QUERIES.get(trade, [f"{trade} company {{city}}"])
    queries = [q.format(city=city) for q in base_queries]

    # If a specific competitor was requested, prepend a targeted search
    if competitor_name:
        queries = [f"{competitor_name} {city}"] + queries

    # 3. Try SerpAPI; fall back to mock on any failure
    api_key = _get_serpapi_key()
    if not api_key:
        log.warning("SERPAPI_API_KEY not set — returning mock review data")
        result = _generate_mock_data(trade, city)
        _save_to_cache(trade, city, result)
        return result

    try:
        # --- Discover businesses ---
        businesses = _fetch_businesses(queries, city, max_per_query=5)
        if not businesses:
            log.warning("No businesses found via SerpAPI for %s / %s", trade, city)
            result = _generate_mock_data(trade, city)
            _save_to_cache(trade, city, result)
            return result

        # --- Collect raw reviews ---
        all_reviews: List[Dict[str, Any]] = []
        competitor_names: List[str] = []

        for biz in businesses[:6]:  # Cap at 6 businesses to limit quota usage
            competitor_names.append(biz["name"])
            reviews = _fetch_reviews_for_place(biz["data_id"], api_key, max_reviews=15)
            for r in reviews:
                r["_source"] = biz["name"]
            all_reviews.extend(reviews)
            log.info("Fetched %d reviews for '%s'", len(reviews), biz["name"])

        if not all_reviews:
            log.warning("No reviews returned by SerpAPI — using mock data")
            result = _generate_mock_data(trade, city)
            _save_to_cache(trade, city, result)
            return result

        # --- Classify in batches of 10 ---
        merged: Dict[str, Any] = {
            "five_star": {"phrases": [], "transformation_words": [], "what_surprised_them": []},
            "one_star": {"objections": [], "core_fears": [], "specific_complaints": []},
            "three_star": {"gaps": []},
        }

        batch_size = 10
        for i in range(0, len(all_reviews), batch_size):
            batch = all_reviews[i : i + batch_size]
            partial = _classify_batch(batch)
            for bucket, sub in partial.items():
                for key, items in sub.items():
                    merged[bucket].setdefault(key, [])
                    merged[bucket][key].extend(items)

        # Deduplicate phrase lists (preserve order, case-insensitive)
        def _dedup(lst: List[str]) -> List[str]:
            seen_lower: set = set()
            out = []
            for item in lst:
                k = item.lower().strip()
                if k and k not in seen_lower:
                    seen_lower.add(k)
                    out.append(item)
            return out

        for bucket in merged:
            for key in merged[bucket]:
                if isinstance(merged[bucket][key], list):
                    merged[bucket][key] = _dedup(merged[bucket][key])

        # --- Build final result ---
        result: Dict[str, Any] = {
            "trade": trade,
            "city": city,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "five_star": merged["five_star"],
            "one_star": merged["one_star"],
            "three_star": merged["three_star"],
            "competitor_names_found": _dedup(competitor_names),
            "total_reviews_analyzed": len(all_reviews),
        }

        _save_to_cache(trade, city, result)
        return result

    except Exception as exc:
        log.error("mine_reviews failed (%s/%s): %s — returning mock data", trade, city, exc)
        result = _generate_mock_data(trade, city)
        _save_to_cache(trade, city, result)
        return result
