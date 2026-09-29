# app/market_research/reddit_researcher.py
"""
Reddit Market Research Module for FieldSprout

Pulls high-signal Reddit threads where homeowners complain about trade
contractors and extracts raw, unfiltered pain language for ad copy.

Usage:
    from app.market_research.reddit_researcher import research_trade
    result = research_trade("hvac", city="Austin")
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_DIR = Path("/tmp/fs_research")
CACHE_TTL_SECONDS = 3 * 24 * 3600  # 3 days

REDDIT_HEADERS = {"User-Agent": "FieldSprout/1.0 (market research)"}

TRADE_SUBREDDITS: Dict[str, List[str]] = {
    "hvac":         ["HVAC", "homeowners", "HomeImprovement", "hvacadvice"],
    "plumbing":     ["Plumbing", "homeowners", "HomeImprovement", "DIY"],
    "electrical":   ["electrical", "homeowners", "HomeImprovement", "askanelectrician"],
    "roofing":      ["Roofing", "homeowners", "HomeImprovement"],
    "landscaping":  ["lawncare", "landscaping", "homeowners", "HomeImprovement"],
    "pest-control": ["pestcontrol", "homeowners", "HomeImprovement"],
    "garage-door":  ["homeowners", "HomeImprovement", "DIY"],
    "pools":        ["pools", "homeowners", "HomeImprovement"],
}

TRADE_SEARCH_TERMS: Dict[str, List[str]] = {
    "hvac": [
        "HVAC contractor", "air conditioning company",
        "hvac quote", "hvac overcharged", "hvac ripoff",
    ],
    "plumbing": [
        "plumber contractor", "plumber no show",
        "plumber overcharged", "plumbing quote",
    ],
    "electrical": [
        "electrician contractor", "electrician quote", "electrician overcharged",
    ],
    "roofing": [
        "roofing contractor", "roofer overcharged",
        "roofer complaints", "roofing scam",
    ],
    "landscaping": [
        "landscaping company", "lawn care company complaints", "landscaper overcharged",
    ],
    "pest-control": [
        "pest control company", "exterminator complaints", "pest control overcharged",
    ],
    "garage-door": [
        "garage door repair", "garage door company scam",
    ],
    "pools": [
        "pool service company", "pool cleaning complaints",
    ],
}

# Frustration qualifiers appended to r/all searches to surface complaint threads
_FRUSTRATION_QUALIFIERS = [
    "nightmare", "scam", "frustrated", "never showed up", "overcharged",
    "no call no show", "worst experience",
]

# ---------------------------------------------------------------------------
# Mock / fallback datasets  (used when Reddit is unreachable in dev/CI)
# ---------------------------------------------------------------------------

_MOCK_DATA: Dict[str, Dict] = {
    "hvac": {
        "top_posts": [
            {
                "title": "HVAC company quoted $800, charged $2,400 after the job — is this normal?",
                "url": "https://www.reddit.com/r/homeowners/comments/mock1",
                "upvotes": 2341,
                "top_comment": (
                    "This happened to me too. They 'discovered' extra work once they opened the unit. "
                    "Get everything in writing upfront. I learned the hard way."
                ),
            },
            {
                "title": "Waited 4 hours and they never called to cancel — HVAC companies are the worst",
                "url": "https://www.reddit.com/r/HVAC/comments/mock2",
                "upvotes": 1876,
                "top_comment": (
                    "I just need someone who shows up when they say they will. That's it. "
                    "I don't think that's too much to ask."
                ),
            },
            {
                "title": "Why is it impossible to get an HVAC quote over the phone?",
                "url": "https://www.reddit.com/r/HomeImprovement/comments/mock3",
                "upvotes": 1543,
                "top_comment": (
                    "Third company I've called and nobody calls back. Meanwhile my house is 90 degrees. "
                    "Why is it so hard to get a straight answer on price?"
                ),
            },
            {
                "title": "HVAC tech came out, said he needed a part, never came back",
                "url": "https://www.reddit.com/r/hvacadvice/comments/mock4",
                "upvotes": 987,
                "top_comment": (
                    "Two weeks without AC, three different techs, and the problem still isn't fixed. "
                    "Every one of them says the last guy made it worse."
                ),
            },
            {
                "title": "How do you even find a trustworthy HVAC company? Serious question.",
                "url": "https://www.reddit.com/r/homeowners/comments/mock5",
                "upvotes": 874,
                "top_comment": (
                    "Took me four tries before I found someone honest. "
                    "The rest either ghosted me, overcharged me, or both."
                ),
            },
        ],
        "raw_text_sample": [
            "waited 4 hours and they never called to cancel",
            "quoted me $800 and charged $2,400",
            "I just need someone who shows up when they say they will",
            "why is it so hard to get a straight answer on price",
            "third company I've called and nobody calls back",
            "two weeks without AC and the problem still isn't fixed",
            "every tech says the last guy made it worse",
            "they discovered extra work once they opened the unit",
            "get everything in writing upfront — learned the hard way",
            "four tries before I found someone honest",
            "ghosted me, overcharged me, or both",
            "told me I needed a whole new unit — second opinion said no",
            "price doubled after they started the job",
            "showed up 3 hours late with no call or text",
            "left the job half-finished and disappeared",
        ],
    },
    "plumbing": {
        "top_posts": [
            {
                "title": "Plumber no-showed twice, now charging me a fee to reschedule",
                "url": "https://www.reddit.com/r/Plumbing/comments/mock1",
                "upvotes": 1654,
                "top_comment": (
                    "They charge YOU a cancellation fee when THEY no-showed. "
                    "I've never experienced anything like it."
                ),
            },
            {
                "title": "Got 5 quotes for a water heater — prices ranged from $600 to $3,200. What?",
                "url": "https://www.reddit.com/r/homeowners/comments/mock2",
                "upvotes": 1402,
                "top_comment": (
                    "Plumbing pricing is a black box. No transparency, no itemized breakdown, "
                    "just a number take it or leave it."
                ),
            },
        ],
        "raw_text_sample": [
            "they charge you a cancellation fee when they no-showed",
            "plumbing pricing is a black box",
            "no transparency, no itemized breakdown",
            "quote over the phone? they won't even discuss it",
            "flooded my basement and denied responsibility",
        ],
    },
    "electrical": {
        "top_posts": [
            {
                "title": "Electrician ghosted after deposit — what are my options?",
                "url": "https://www.reddit.com/r/electrical/comments/mock1",
                "upvotes": 1231,
                "top_comment": (
                    "Same thing happened to me. Paid half upfront, never heard from him again. "
                    "Now I pay nothing until the job is done."
                ),
            },
        ],
        "raw_text_sample": [
            "paid half upfront, never heard from him again",
            "failed the inspection — cost me another $800 to fix his work",
            "took three weeks longer than quoted",
            "I just want someone licensed who will show up",
        ],
    },
    "roofing": {
        "top_posts": [
            {
                "title": "Roofer took my money and the leak is worse now",
                "url": "https://www.reddit.com/r/Roofing/comments/mock1",
                "upvotes": 2100,
                "top_comment": (
                    "Classic. They patch the obvious spot, pocket the check, and six months later "
                    "you've got water damage in the attic."
                ),
            },
        ],
        "raw_text_sample": [
            "patch the obvious spot, pocket the check",
            "water damage in the attic six months later",
            "storm chasers knocked on my door and I made a huge mistake",
            "quote valid for 24 hours — pressure tactics are insane",
        ],
    },
    "landscaping": {
        "top_posts": [
            {
                "title": "Landscaping company raised their price 40% with zero notice",
                "url": "https://www.reddit.com/r/lawncare/comments/mock1",
                "upvotes": 976,
                "top_comment": (
                    "We had the same rate for two years then got a text saying prices changed. "
                    "No call, no explanation."
                ),
            },
        ],
        "raw_text_sample": [
            "raised their price 40% with zero notice",
            "no call, no explanation",
            "skipped us three weeks in a row during summer",
            "I just want my lawn to look like the neighbor's — is that too much?",
        ],
    },
    "pest-control": {
        "top_posts": [
            {
                "title": "Pest control did nothing — bugs worse after treatment",
                "url": "https://www.reddit.com/r/pestcontrol/comments/mock1",
                "upvotes": 843,
                "top_comment": (
                    "Paid for a quarterly plan. Technician was here for 8 minutes. "
                    "Problem is worse than before."
                ),
            },
        ],
        "raw_text_sample": [
            "paid for a quarterly plan — technician was here for 8 minutes",
            "problem is worse than before",
            "they locked me into a contract and won't let me cancel",
            "used the same treatment twice and expected different results",
        ],
    },
    "garage-door": {
        "top_posts": [
            {
                "title": "$89 service call turned into $700 — garage door repair scam?",
                "url": "https://www.reddit.com/r/HomeImprovement/comments/mock1",
                "upvotes": 1567,
                "top_comment": (
                    "The low service call fee is bait. Once they're in your garage they tell you "
                    "everything needs replacing."
                ),
            },
        ],
        "raw_text_sample": [
            "the low service call fee is bait",
            "once they're in your garage they tell you everything needs replacing",
            "$89 turned into $700",
            "spring replacement that should cost $150 quoted at $600",
        ],
    },
    "pools": {
        "top_posts": [
            {
                "title": "Pool service company skips visits but charges every month anyway",
                "url": "https://www.reddit.com/r/pools/comments/mock1",
                "upvotes": 712,
                "top_comment": (
                    "Ring camera shows up in our pool area — technician was here for 4 minutes. "
                    "Pool was green the next week."
                ),
            },
        ],
        "raw_text_sample": [
            "ring camera showed technician was here for 4 minutes",
            "pool was green the next week",
            "charges every month even when they skip",
            "impossible to get them on the phone when something is wrong",
        ],
    },
}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(trade: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{trade}_reddit.json"


def _load_cache(trade: str) -> Optional[Dict]:
    path = _cache_path(trade)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        scraped_at = datetime.fromisoformat(data.get("scraped_at", "1970-01-01T00:00:00"))
        # Make scraped_at timezone-aware if needed
        if scraped_at.tzinfo is None:
            scraped_at = scraped_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - scraped_at).total_seconds()
        if age < CACHE_TTL_SECONDS:
            logger.info("Reddit cache hit for trade=%s (age=%.0fs)", trade, age)
            return data
        logger.info("Reddit cache expired for trade=%s", trade)
    except Exception as exc:
        logger.warning("Could not read Reddit cache for %s: %s", trade, exc)
    return None


def _save_cache(trade: str, data: Dict) -> None:
    try:
        _cache_path(trade).write_text(json.dumps(data, indent=2))
    except Exception as exc:
        logger.warning("Could not write Reddit cache for %s: %s", trade, exc)


# ---------------------------------------------------------------------------
# Reddit fetching helpers
# ---------------------------------------------------------------------------

def _reddit_get(url: str, params: Dict) -> Optional[Dict]:
    """
    GET a Reddit JSON endpoint. Returns parsed JSON or None on error.
    Handles 429 rate-limit responses by returning None immediately so
    callers can move on with partial data rather than crashing.
    """
    try:
        resp = requests.get(url, params=params, headers=REDDIT_HEADERS, timeout=10)
        if resp.status_code == 429:
            logger.warning("Reddit rate-limited (429) on %s", url)
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("Reddit request failed (%s): %s", url, exc)
        return None


def _fetch_top_comment(post_permalink: str) -> str:
    """Fetch the top comment body for a single Reddit post."""
    url = f"https://www.reddit.com{post_permalink}.json"
    data = _reddit_get(url, {"limit": 5, "sort": "top"})
    time.sleep(1)
    if not data or len(data) < 2:
        return ""
    try:
        comments = data[1].get("data", {}).get("children", [])
        for child in comments:
            body = child.get("data", {}).get("body", "")
            if body and body not in ("[removed]", "[deleted]") and len(body) > 20:
                return body.strip()
    except Exception:
        pass
    return ""


def _search_subreddit(subreddit: str, query: str, limit: int = 10) -> List[Dict]:
    """Search a specific subreddit for posts matching query."""
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {"q": query, "sort": "top", "t": "year", "limit": limit, "restrict_sr": 1}
    data = _reddit_get(url, params)
    time.sleep(1)
    if not data:
        return []
    posts = []
    try:
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            posts.append({
                "title": d.get("title", ""),
                "permalink": d.get("permalink", ""),
                "url": f"https://www.reddit.com{d.get('permalink', '')}",
                "upvotes": d.get("ups", 0),
                "selftext": (d.get("selftext") or "")[:500],
            })
    except Exception as exc:
        logger.warning("Error parsing subreddit search results: %s", exc)
    return posts


def _search_all(query: str, limit: int = 10) -> List[Dict]:
    """Search r/all for the given query."""
    url = "https://www.reddit.com/search.json"
    params = {"q": query, "sort": "top", "t": "year", "limit": limit}
    data = _reddit_get(url, params)
    time.sleep(1)
    if not data:
        return []
    posts = []
    try:
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            posts.append({
                "title": d.get("title", ""),
                "permalink": d.get("permalink", ""),
                "url": f"https://www.reddit.com{d.get('permalink', '')}",
                "upvotes": d.get("ups", 0),
                "selftext": (d.get("selftext") or "")[:500],
            })
    except Exception as exc:
        logger.warning("Error parsing r/all search results: %s", exc)
    return posts


def _collect_posts(trade: str, city: Optional[str] = None) -> List[Dict]:
    """
    Collect raw posts from subreddit searches and r/all searches.
    Returns a deduplicated list sorted by upvotes.
    """
    subreddits = TRADE_SUBREDDITS.get(trade, ["homeowners", "HomeImprovement"])
    search_terms = TRADE_SEARCH_TERMS.get(trade, [trade])

    seen_permalinks: set = set()
    all_posts: List[Dict] = []

    # 1. Search per subreddit with primary search terms (first 2 terms, first 3 subreddits)
    for sub in subreddits[:3]:
        for term in search_terms[:2]:
            q = f"{term} frustrated" if city is None else f"{term} {city}"
            logger.debug("Searching r/%s for: %s", sub, q)
            for post in _search_subreddit(sub, q, limit=8):
                if post["permalink"] not in seen_permalinks:
                    seen_permalinks.add(post["permalink"])
                    all_posts.append(post)

    # 2. Search r/all with frustration qualifiers
    for term in search_terms[:2]:
        for qualifier in _FRUSTRATION_QUALIFIERS[:3]:
            q = f"{term} {qualifier}"
            if city:
                q += f" {city}"
            logger.debug("Searching r/all for: %s", q)
            for post in _search_all(q, limit=5):
                if post["permalink"] not in seen_permalinks:
                    seen_permalinks.add(post["permalink"])
                    all_posts.append(post)

    # Sort by upvotes; keep top 25
    all_posts.sort(key=lambda p: p.get("upvotes", 0), reverse=True)
    return all_posts[:25]


# ---------------------------------------------------------------------------
# OpenAI extraction
# ---------------------------------------------------------------------------

def _extract_insights_openai(trade: str, raw_text: str) -> Dict:
    """
    Use OpenAI to extract structured pain-point intelligence from raw Reddit text.
    Returns the structured dict, or an empty dict on failure.
    """
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed — skipping AI extraction")
        return {}

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — skipping AI extraction")
        return {}

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    prompt = f"""You are a direct-response ad copywriter analyzing real homeowner complaints about {trade} contractors.

Below are Reddit post titles and comment excerpts from frustrated homeowners. Extract the most useful market intelligence.

RAW TEXT:
{raw_text}

Return a JSON object with exactly these keys:
{{
  "top_pain_points": [
    // 5-8 short phrases describing the core frustrations (contractor behavior issues)
  ],
  "exact_phrases": [
    // 6-10 verbatim-style quotes or near-quotes from homeowners that capture raw emotion
    // These should sound like something a real person would actually say
  ],
  "core_fears": [
    // 4-6 underlying fears/anxieties driving the frustration (e.g. "being ripped off")
  ],
  "ad_language_goldmine": [
    // 3-5 ready-to-use ad headline ideas inspired by the raw language
    // Write them as benefit-driven statements, not complaints
    // Example: "We quote it upfront. We show up on time. We charge what we said."
  ]
}}

Return ONLY valid JSON, no markdown fences, no explanation.
"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a market research specialist and direct-response ad copywriter. "
                        "You extract pain language from consumer complaints and turn it into "
                        "high-converting ad copy insights. Always return valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        content = (resp.choices[0].message.content or "").strip()
        return json.loads(content)
    except json.JSONDecodeError as exc:
        logger.error("OpenAI returned non-JSON: %s", exc)
    except Exception as exc:
        logger.error("OpenAI extraction failed: %s", exc)
    return {}


# ---------------------------------------------------------------------------
# Mock fallback assembler
# ---------------------------------------------------------------------------

def _build_mock_result(trade: str) -> Dict:
    """
    Return a realistic mock result for the given trade.
    Used when Reddit is unreachable (dev / CI / rate-limited).
    """
    mock = _MOCK_DATA.get(trade, _MOCK_DATA["hvac"])
    top_posts = mock.get("top_posts", [])
    raw_phrases = mock.get("raw_text_sample", [])

    return {
        "trade": trade,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source": "mock",
        "top_pain_points": [
            "contractors give vague non-committal pricing until the job starts",
            "no-shows and last-minute cancellations with no communication",
            "price escalation once the job is already underway",
            "technicians leave jobs unfinished or disappear after deposit",
            "impossible to reach for follow-up questions or callbacks",
        ],
        "exact_phrases": raw_phrases,
        "core_fears": [
            "being overcharged or price-gouged",
            "getting stood up after taking time off work",
            "not knowing the real cost before work starts",
            "poor workmanship that creates a bigger problem",
            "no recourse if something goes wrong",
        ],
        "ad_language_goldmine": [
            "Shows up on time. Fixes it right. Tells you the price first.",
            "Upfront pricing. No surprises after we open the wall.",
            "We call if we're running late — because your time matters.",
            "Get a real quote in 60 seconds. No vague estimates.",
            "Guaranteed price before we start. Period.",
        ],
        "top_posts": top_posts,
        "total_posts_analyzed": len(top_posts),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def research_trade(trade: str, city: Optional[str] = None, force_refresh: bool = False) -> Dict:
    """
    Main entry point. Returns a structured market research dict for the given
    trade (and optional city). Caches results for 3 days.

    Args:
        trade:         One of the keys in TRADE_SUBREDDITS, e.g. "hvac".
        city:          Optional city name to localise searches, e.g. "Austin".
        force_refresh: If True, bypass the cache.

    Returns:
        A dict matching the FieldSprout market research schema.
    """
    trade = trade.lower().strip()

    # Check cache first
    if not force_refresh:
        cached = _load_cache(trade)
        if cached:
            return cached

    logger.info("Running Reddit research for trade=%s city=%s", trade, city)

    # Attempt live Reddit scrape
    posts_raw = []
    reddit_reachable = True
    try:
        posts_raw = _collect_posts(trade, city)
    except Exception as exc:
        logger.warning("Reddit collection failed entirely: %s", exc)
        reddit_reachable = False

    if not reddit_reachable or len(posts_raw) < 3:
        logger.info("Falling back to mock data for trade=%s", trade)
        result = _build_mock_result(trade)
        _save_cache(trade, result)
        return result

    # Fetch top comment for each post (with rate-limit respect)
    top_posts: List[Dict] = []
    for post in posts_raw[:10]:
        top_comment = _fetch_top_comment(post["permalink"])
        top_posts.append({
            "title": post["title"],
            "url": post["url"],
            "upvotes": post["upvotes"],
            "top_comment": top_comment,
        })

    # Build raw text corpus for OpenAI
    text_chunks: List[str] = []
    for post in posts_raw:
        text_chunks.append(f"TITLE: {post['title']}")
        if post.get("selftext"):
            text_chunks.append(f"BODY: {post['selftext']}")
    for tp in top_posts:
        if tp.get("top_comment"):
            text_chunks.append(f"COMMENT: {tp['top_comment']}")

    raw_text_corpus = "\n".join(text_chunks[:120])  # keep under token limits

    # Extract insights via OpenAI
    insights = _extract_insights_openai(trade, raw_text_corpus)

    # If OpenAI is unavailable, pull fallback phrases from mock data
    if not insights:
        mock_fallback = _build_mock_result(trade)
        insights = {
            "top_pain_points":    mock_fallback["top_pain_points"],
            "exact_phrases":      mock_fallback["exact_phrases"],
            "core_fears":         mock_fallback["core_fears"],
            "ad_language_goldmine": mock_fallback["ad_language_goldmine"],
        }

    result: Dict = {
        "trade":      trade,
        "city":       city,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source":     "live",
        "top_pain_points":     insights.get("top_pain_points", []),
        "exact_phrases":       insights.get("exact_phrases", []),
        "core_fears":          insights.get("core_fears", []),
        "ad_language_goldmine": insights.get("ad_language_goldmine", []),
        "top_posts":           top_posts,
        "total_posts_analyzed": len(posts_raw),
    }

    _save_cache(trade, result)
    return result
