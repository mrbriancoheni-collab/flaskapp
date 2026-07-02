# app/services/agent_knowledge_service.py
"""
Agent Knowledge Service

Fetches content from admin-approved external sources (Google Ads best practices,
SEMrush, industry blogs, etc.), summarizes with Claude Haiku, and caches the
result in agent_knowledge_cache for injection into agent context windows.

Also surfaces recent decision outcomes from the decision log so agents can
learn from accumulated results.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default knowledge sources seeded on first run (require admin approval)
# ---------------------------------------------------------------------------
DEFAULT_SOURCES = [
    # ---- Google Ads agents ------------------------------------------------
    {
        "agent_type": "strategic_director",
        "title": "Google Ads Best Practices: Campaign Strategy",
        "url": "https://support.google.com/google-ads/answer/6146252",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "strategic_director",
        "title": "WordStream Google Ads Benchmarks by Industry",
        "url": "https://www.wordstream.com/blog/ws/2016/02/29/google-adwords-industry-benchmarks",
        "source_type": "webpage",
        "category": "benchmarks",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "campaign_manager",
        "title": "Google Ads Quality Score Guide",
        "url": "https://support.google.com/google-ads/answer/6167118",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "campaign_manager",
        "title": "Search Engine Land: Google Ads News",
        "url": "https://searchengineland.com/category/paid-search/google-ads",
        "source_type": "webpage",
        "category": "news",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "budget_guardian",
        "title": "Google Ads Smart Bidding Guide",
        "url": "https://support.google.com/google-ads/answer/7065882",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "keyword_optimizer",
        "title": "Google Ads Keyword Match Types",
        "url": "https://support.google.com/google-ads/answer/7243169",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "negative_keyword",
        "title": "Google Ads Negative Keywords Guide",
        "url": "https://support.google.com/google-ads/answer/2453972",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "ad_copy",
        "title": "Google Ads Responsive Search Ads Best Practices",
        "url": "https://support.google.com/google-ads/answer/7684791",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "quality_score",
        "title": "Google Ads Landing Page Experience Guide",
        "url": "https://support.google.com/google-ads/answer/2404197",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    # ---- SEO / Content agents --------------------------------------------
    {
        "agent_type": "seo_agent",
        "title": "SEMrush: Answer Engine Optimization Guide",
        "url": "https://www.semrush.com/blog/answer-engine-optimization/",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "seo_agent",
        "title": "Backlinko: How to Rank in AI Search (AEO)",
        "url": "https://backlinko.com/hub/seo/aeo",
        "source_type": "webpage",
        "category": "research",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "content_strategist",
        "title": "ServiceTitan Blog: Field Service Industry Insights",
        "url": "https://www.servicetitan.com/blog/",
        "source_type": "webpage",
        "category": "news",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "content_strategist",
        "title": "Local Service Business Content Strategy (AEO 2026)",
        "url": "https://searchengineland.com/local-seo/",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    # ---- Facebook Ads agents ---------------------------------------------
    {
        "agent_type": "fb_strategic",
        "title": "Meta Business: Campaign Strategy Guide",
        "url": "https://www.facebook.com/business/help/1619591508182978",
        "source_type": "webpage",
        "category": "best_practices",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
    {
        "agent_type": "fb_operational",
        "title": "Social Media Examiner: Facebook Ads",
        "url": "https://www.socialmediaexaminer.com/category/facebook-marketing/",
        "source_type": "webpage",
        "category": "news",
        "refresh_frequency": "weekly",
        "is_default": True,
    },
]


def seed_default_sources() -> int:
    """Seed DEFAULT_SOURCES into DB if not already present. Returns count added."""
    try:
        from app.models_knowledge import AgentKnowledgeSource
        from app import db

        added = 0
        for s in DEFAULT_SOURCES:
            existing = AgentKnowledgeSource.query.filter_by(url=s["url"]).first()
            if not existing:
                src = AgentKnowledgeSource(
                    agent_type=s["agent_type"],
                    title=s["title"],
                    url=s["url"],
                    source_type=s.get("source_type", "webpage"),
                    category=s.get("category", "best_practices"),
                    refresh_frequency=s.get("refresh_frequency", "weekly"),
                    is_default=s.get("is_default", False),
                    is_approved=False,  # require explicit admin approval
                )
                db.session.add(src)
                added += 1

        if added:
            db.session.commit()
        return added
    except Exception:
        logger.exception("Failed to seed default knowledge sources")
        return 0


def refresh_knowledge_source(source) -> bool:
    """
    Fetch content from a single AgentKnowledgeSource, summarize with Claude Haiku,
    and save to AgentKnowledgeCache. Returns True on success.
    """
    try:
        import requests as _req
        from app.ai_clients import get_ai_client
        from app.models_knowledge import AgentKnowledgeCache
        from app import db

        headers = {"User-Agent": "FieldSprout-AgentKnowledge/1.0 (site:fieldsprout.io)"}
        resp = _req.get(source.url, headers=headers, timeout=20, allow_redirects=True)
        resp.raise_for_status()

        # Strip HTML to text (rudimentary but avoids extra dependency)
        import re as _re
        html = resp.text
        text = _re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r'<[^>]+>', ' ', text)
        text = _re.sub(r'\s+', ' ', text).strip()
        # Truncate to ~6000 chars to keep tokens manageable
        text = text[:6000]

        if len(text) < 100:
            logger.warning("Knowledge source %d returned too little text (%d chars)", source.id, len(text))
            source.fetch_error = "Content too short after stripping HTML"
            source.last_fetched_at = datetime.utcnow()
            db.session.commit()
            return False

        client = get_ai_client()
        system = (
            f"You are a knowledge summarizer for an AI marketing agent called '{source.agent_type.replace('_', ' ').title()}'. "
            "Extract only the most actionable, role-relevant insights from the provided content."
        )
        prompt = (
            f"Source: {source.title}\n"
            f"URL: {source.url}\n\n"
            f"Content:\n{text}\n\n"
            "Produce:\n"
            "1. A 3-5 sentence summary of the most important takeaways relevant to this agent's role.\n"
            "2. A JSON array of 5-8 bullet-point key insights (strings, each < 120 chars).\n\n"
            "Return JSON: {\"summary\": \"...\", \"key_insights\": [\"...\", ...]}"
        )

        resp_ai = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp_ai.content[0].text.strip()

        import json as _json
        # Extract JSON if wrapped in markdown
        import re as _re2
        m = _re2.search(r'\{.*\}', raw, _re2.DOTALL)
        data = _json.loads(m.group()) if m else {"summary": raw, "key_insights": []}

        # Upsert cache entry
        cache = AgentKnowledgeCache.query.filter_by(source_id=source.id).first()
        if not cache:
            cache = AgentKnowledgeCache(agent_type=source.agent_type, source_id=source.id)
            db.session.add(cache)

        cache.summary = data.get("summary", "")
        cache.key_insights = data.get("key_insights", [])
        cache.refreshed_at = datetime.utcnow()
        cache.token_count = resp_ai.usage.output_tokens if resp_ai.usage else 0

        source.last_fetched_at = datetime.utcnow()
        source.fetch_error = None
        db.session.commit()

        logger.info("Refreshed knowledge source %d (%s) for agent %s", source.id, source.title, source.agent_type)
        return True

    except Exception as exc:
        logger.exception("Failed to refresh knowledge source %d: %s", source.id, exc)
        try:
            from app import db
            source.fetch_error = str(exc)[:500]
            source.last_fetched_at = datetime.utcnow()
            db.session.commit()
        except Exception:
            pass
        return False


def refresh_all_approved_sources(force: bool = False) -> Dict[str, int]:
    """
    Refresh all approved knowledge sources that are due for refresh.
    Called by cron_tasks daily. Returns {success, skipped, failed} counts.
    """
    try:
        from app.models_knowledge import AgentKnowledgeSource
    except Exception:
        logger.warning("AgentKnowledgeSource model not available — run migration first")
        return {"success": 0, "skipped": 0, "failed": 0}

    sources = AgentKnowledgeSource.query.filter_by(is_approved=True, is_active=True).all()
    counts = {"success": 0, "skipped": 0, "failed": 0}

    now = datetime.utcnow()
    for source in sources:
        # Determine if due for refresh
        if not force and source.last_fetched_at:
            interval = timedelta(days=1) if source.refresh_frequency == "daily" else timedelta(days=7)
            if now - source.last_fetched_at < interval:
                counts["skipped"] += 1
                continue

        ok = refresh_knowledge_source(source)
        counts["success" if ok else "failed"] += 1

    return counts


def get_decision_learnings_context(agent_type: str, account_id: int, limit: int = 10) -> str:
    """
    Query recent DecisionLog entries for this agent and account, summarize outcomes,
    and format as a learnings section for injection into the agent's context.
    """
    try:
        from sqlalchemy import text
        from app import db

        rows = db.session.execute(
            text("""
                SELECT decision_type, action_taken, outcome, confidence, created_at
                FROM agent_decision_log
                WHERE agent_type = :agent_type
                  AND account_id  = :account_id
                  AND outcome IS NOT NULL
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"agent_type": agent_type, "account_id": account_id, "lim": limit},
        ).fetchall()

        if not rows:
            return ""

        lines = ["## Recent Decision Outcomes (Agent Learning)", ""]
        for r in rows:
            outcome_emoji = "✅" if (r[2] or "").lower() in ("success", "positive", "improved") else "⚠️"
            lines.append(
                f"{outcome_emoji} [{r[3]:.0%} conf] {r[0]}: {r[1] or 'action taken'} → {r[2] or 'pending'}"
                f" ({r[4].strftime('%b %d') if r[4] else 'recently'})"
            )
        lines.append("")
        return "\n".join(lines)

    except Exception:
        return ""
