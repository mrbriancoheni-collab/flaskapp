# app/models_knowledge.py
"""
Agent Knowledge Base models.

AgentKnowledgeSource — admin-approved URLs/RSS feeds per agent type.
AgentKnowledgeCache  — daily-refreshed summaries injected into agent context.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List

from app import db


AGENT_TYPES = [
    "strategic_director",
    "campaign_manager",
    "budget_guardian",
    "quality_score",
    "keyword_optimizer",
    "negative_keyword",
    "ad_copy",
    "content_strategist",
    "seo_agent",
    "fb_strategic",
    "fb_operational",
]


class AgentKnowledgeSource(db.Model):
    __tablename__ = "agent_knowledge_sources"

    id = db.Column(db.Integer, primary_key=True)
    agent_type = db.Column(db.String(64), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    url = db.Column(db.Text, nullable=False)
    source_type = db.Column(db.String(32), default="webpage")  # webpage | rss | api
    category = db.Column(db.String(64), default="best_practices")  # best_practices | benchmarks | news | research
    refresh_frequency = db.Column(db.String(16), default="weekly")  # daily | weekly
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)  # pre-seeded defaults
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    last_fetched_at = db.Column(db.DateTime, nullable=True)
    fetch_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "agent_type": self.agent_type,
            "title": self.title,
            "url": self.url,
            "source_type": self.source_type,
            "category": self.category,
            "refresh_frequency": self.refresh_frequency,
            "is_approved": self.is_approved,
            "is_active": self.is_active,
            "last_fetched_at": self.last_fetched_at.isoformat() if self.last_fetched_at else None,
            "fetch_error": self.fetch_error,
        }

    @classmethod
    def approved_for_agent(cls, agent_type: str) -> List["AgentKnowledgeSource"]:
        return cls.query.filter_by(agent_type=agent_type, is_approved=True, is_active=True).all()

    @classmethod
    def pending_approval(cls) -> List["AgentKnowledgeSource"]:
        return cls.query.filter_by(is_approved=False, is_active=True).order_by(cls.created_at.desc()).all()


class AgentKnowledgeCache(db.Model):
    __tablename__ = "agent_knowledge_cache"

    id = db.Column(db.Integer, primary_key=True)
    agent_type = db.Column(db.String(64), nullable=False, index=True)
    source_id = db.Column(db.Integer, db.ForeignKey("agent_knowledge_sources.id"), nullable=True)
    summary = db.Column(db.Text, nullable=False)
    key_insights = db.Column(db.JSON, nullable=True)  # list of bullet-point strings
    refreshed_at = db.Column(db.DateTime, default=datetime.utcnow)
    token_count = db.Column(db.Integer, default=0)

    source = db.relationship("AgentKnowledgeSource", backref="cache_entries")

    @classmethod
    def get_context_for_agent(cls, agent_type: str, max_sources: int = 5) -> str:
        """Return formatted knowledge context string for injection into agent context."""
        entries = (
            cls.query
            .filter_by(agent_type=agent_type)
            .order_by(cls.refreshed_at.desc())
            .limit(max_sources)
            .all()
        )
        if not entries:
            return ""

        lines = ["## Expert Knowledge & Best Practices (Current)", ""]
        for e in entries:
            src_title = e.source.title if e.source else "Knowledge Source"
            lines.append(f"### {src_title}")
            lines.append(e.summary)
            if e.key_insights:
                for insight in e.key_insights[:4]:
                    lines.append(f"- {insight}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def get_latest_refreshed_at(cls, agent_type: str) -> Optional[datetime]:
        entry = cls.query.filter_by(agent_type=agent_type).order_by(cls.refreshed_at.desc()).first()
        return entry.refreshed_at if entry else None
