# app/social_listen/crawler.py
"""
Social content crawler for the social listening system.

Fetches trending marketing / demand-generation content from:
  - google_news  (SerpAPI engine=google_news)
  - google_search  (SerpAPI site:linkedin.com / site:twitter.com)
  - twitter  (Twitter API v2 recent-search — requires TWITTER_BEARER_TOKEN)
  - reddit  (Reddit JSON search API)

All sources are optional; a missing API key → source skipped gracefully.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, quote_plus

import requests

logger = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search.json"
REDDIT_HEADERS = {"User-Agent": "SocialListen/1.0 (marketing research)"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serpapi_key() -> Optional[str]:
    try:
        from flask import current_app
        key = current_app.config.get("SERPAPI_API_KEY") or os.getenv("SERPAPI_API_KEY")
    except RuntimeError:
        key = os.getenv("SERPAPI_API_KEY")
    return (key or "").strip() or None


def _serpapi_get(params: Dict[str, Any]) -> Optional[Dict]:
    key = _serpapi_key()
    if not key:
        return None
    params["api_key"] = key
    try:
        resp = requests.get(SERPAPI_BASE, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("SerpAPI request failed (%s): %s", params.get("engine"), exc)
        return None


# ---------------------------------------------------------------------------
# Source crawlers
# ---------------------------------------------------------------------------

def _crawl_google_news(topic: str, max_items: int) -> List[Dict]:
    data = _serpapi_get({"engine": "google_news", "q": topic})
    if not data:
        return []
    results = []
    for item in (data.get("news_results") or [])[:max_items]:
        source_name = ""
        src = item.get("source")
        if isinstance(src, dict):
            source_name = src.get("name", "")
        elif isinstance(src, str):
            source_name = src
        content = f"{item.get('title', '')} — {item.get('snippet', '')}"
        results.append({
            "source": "google_news",
            "source_url": item.get("link", ""),
            "author": source_name,
            "original_content": content.strip(" —"),
            "topic": topic,
        })
    return results


def _crawl_google_search(topic: str, max_items: int) -> List[Dict]:
    """Use google search to find LinkedIn and Twitter posts about the topic."""
    items: List[Dict] = []
    queries = [
        (f'site:linkedin.com/posts "{topic}"', "linkedin"),
        (f'site:twitter.com "{topic}" marketing', "twitter"),
    ]
    per_query = max(1, max_items // 2)
    for query, platform in queries:
        data = _serpapi_get({"engine": "google", "q": query, "num": per_query})
        if not data:
            continue
        for r in (data.get("organic_results") or [])[:per_query]:
            content = f"{r.get('title', '')} — {r.get('snippet', '')}"
            items.append({
                "source": platform,
                "source_url": r.get("link", ""),
                "author": r.get("displayed_link", ""),
                "original_content": content.strip(" —"),
                "topic": topic,
            })
    return items


def _crawl_twitter(topic: str, max_items: int) -> List[Dict]:
    bearer = os.getenv("TWITTER_BEARER_TOKEN", "").strip()
    if not bearer:
        return []
    query = f"{topic} lang:en -is:retweet"
    params = {
        "query": query,
        "max_results": min(max_items, 10),
        "tweet.fields": "author_id,public_metrics,created_at",
    }
    try:
        resp = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            params=params,
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Twitter API request failed: %s", exc)
        return []

    items = []
    for tweet in (data.get("data") or []):
        items.append({
            "source": "twitter",
            "source_url": f"https://twitter.com/i/web/status/{tweet.get('id', '')}",
            "author": tweet.get("author_id", ""),
            "original_content": tweet.get("text", ""),
            "topic": topic,
        })
    return items


def _crawl_reddit(topic: str, max_items: int) -> List[Dict]:
    url = (
        f"https://www.reddit.com/r/marketing+PPC+SEO/search.json"
        f"?q={quote_plus(topic)}&sort=top&t=week&limit={max_items}"
    )
    try:
        resp = requests.get(url, headers=REDDIT_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Reddit request failed: %s", exc)
        return []

    items = []
    for post in (data.get("data", {}).get("children") or [])[:max_items]:
        pd = post.get("data", {})
        items.append({
            "source": "reddit",
            "source_url": f"https://www.reddit.com{pd.get('permalink', '')}",
            "author": pd.get("author", ""),
            "original_content": f"{pd.get('title', '')} — {pd.get('selftext', '')[:300]}".strip(" —"),
            "topic": topic,
        })
    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def crawl_opportunities(
    topics: List[str],
    sources: List[str],
    max_per_source: int = 10,
) -> List[Dict]:
    """
    Crawl trending marketing/DG content.

    Returns a list of dicts:
        {source, source_url, author, original_content, topic}

    Deduplicates by URL. Total capped at 30.
    """
    _source_fn = {
        "google_news": _crawl_google_news,
        "google_search": _crawl_google_search,
        "twitter": _crawl_twitter,
        "reddit": _crawl_reddit,
    }

    seen_urls: set = set()
    results: List[Dict] = []

    for topic in topics:
        for source in sources:
            fn = _source_fn.get(source)
            if fn is None:
                logger.warning("Unknown source %r — skipping", source)
                continue
            try:
                items = fn(topic, max_per_source)
            except Exception as exc:
                logger.warning("Source %r failed for topic %r: %s", source, topic, exc)
                items = []
            for item in items:
                url = item.get("source_url", "")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                results.append(item)
                if len(results) >= 30:
                    return results

    return results
