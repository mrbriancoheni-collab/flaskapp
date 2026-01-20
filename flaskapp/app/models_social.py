# app/models_social.py
"""
Social Media Ad Composer Models

Store generated ad creatives, images, and copy for social media campaigns
"""
from datetime import datetime
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.sql import func

try:
    from sqlalchemy.dialects.mysql import JSON as MySQLJSON
    JSONType = MySQLJSON
except Exception:
    from sqlalchemy import JSON as SAJSON
    JSONType = SAJSON

from app import db


class AdCreative(db.Model):
    """Generated ad creative with image and copy"""
    __tablename__ = "ad_creatives"

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    account_id = db.Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)

    # Creative details
    name = db.Column(String(255), nullable=False)  # User-given name
    platform = db.Column(
        SAEnum('facebook', 'instagram', 'linkedin', 'twitter', 'google', 'multi', name='ad_platform'),
        nullable=False,
        default='facebook'
    )

    # Image
    image_url = db.Column(String(1000), nullable=True)  # URL to generated/uploaded image
    image_prompt = db.Column(Text, nullable=True)  # DALL-E prompt used
    image_storage_key = db.Column(String(500), nullable=True)  # S3/storage key

    # Copy
    headline = db.Column(String(255), nullable=True)
    primary_text = db.Column(Text, nullable=True)  # Main body copy
    description = db.Column(String(500), nullable=True)  # Optional description
    call_to_action = db.Column(String(100), nullable=True)  # CTA button text

    # Generation details
    generation_method = db.Column(
        SAEnum('ai_website', 'ai_manual', 'manual', 'template', name='generation_method'),
        nullable=False,
        default='ai_manual'
    )
    source_url = db.Column(String(1000), nullable=True)  # Website URL if from website scan
    template_id = db.Column(Integer, nullable=True)  # If based on template

    # AI model info
    image_model = db.Column(String(100), nullable=True)  # e.g., "dall-e-3"
    copy_model = db.Column(String(100), nullable=True)  # e.g., "gpt-4", "claude-3"

    # Metadata
    industry = db.Column(String(100), nullable=True)  # e.g., "plumbing", "hvac"
    target_audience = db.Column(String(255), nullable=True)
    ad_objective = db.Column(String(100), nullable=True)  # awareness, leads, conversions

    # Usage tracking
    used_in_campaign = db.Column(Boolean, default=False)
    impressions = db.Column(Integer, default=0)
    clicks = db.Column(Integer, default=0)
    conversions = db.Column(Integer, default=0)

    # Status
    status = db.Column(
        SAEnum('draft', 'approved', 'published', 'archived', name='creative_status'),
        nullable=False,
        default='draft'
    )

    # Additional data
    extra_data = db.Column(JSONType, nullable=True)  # Platform-specific settings, etc.

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    published_at = db.Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<AdCreative id={self.id} name={self.name!r} platform={self.platform}>"


class AdCreativeVariation(db.Model):
    """A/B test variations of an ad creative"""
    __tablename__ = "ad_creative_variations"

    id = db.Column(Integer, primary_key=True)
    parent_creative_id = db.Column(Integer, ForeignKey("ad_creatives.id"), nullable=False, index=True)

    # Variation details (what changed)
    variation_type = db.Column(
        SAEnum('headline', 'image', 'copy', 'cta', 'full', name='variation_type'),
        nullable=False
    )

    # Variation content
    headline = db.Column(String(255), nullable=True)
    primary_text = db.Column(Text, nullable=True)
    description = db.Column(String(500), nullable=True)
    call_to_action = db.Column(String(100), nullable=True)
    image_url = db.Column(String(1000), nullable=True)

    # Performance
    impressions = db.Column(Integer, default=0)
    clicks = db.Column(Integer, default=0)
    conversions = db.Column(Integer, default=0)
    is_winner = db.Column(Boolean, default=False)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<AdCreativeVariation id={self.id} parent={self.parent_creative_id} type={self.variation_type}>"


class AdTemplate(db.Model):
    """Pre-made templates for common local service business ads"""
    __tablename__ = "ad_templates"

    id = db.Column(Integer, primary_key=True)

    # Template details
    name = db.Column(String(255), nullable=False)
    description = db.Column(Text, nullable=True)
    industry = db.Column(String(100), nullable=False)  # plumbing, hvac, electrical, etc.
    category = db.Column(String(100), nullable=True)  # seasonal, emergency, promotion, etc.

    # Template content (with variables like {{business_name}}, {{service}})
    headline_template = db.Column(String(255), nullable=False)
    copy_template = db.Column(Text, nullable=False)
    cta_template = db.Column(String(100), nullable=False)

    # Image guidance
    image_style = db.Column(String(100), nullable=True)  # professional, lifestyle, product, etc.
    image_prompt_template = db.Column(Text, nullable=True)  # DALL-E prompt template

    # Platform compatibility
    platforms = db.Column(String(255), nullable=False)  # Comma-separated: facebook,instagram,linkedin

    # Performance (from aggregated data)
    times_used = db.Column(Integer, default=0)
    avg_ctr = db.Column(db.Float, nullable=True)  # Average click-through rate

    # Status
    is_active = db.Column(Boolean, default=True)
    is_featured = db.Column(Boolean, default=False)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<AdTemplate id={self.id} name={self.name!r} industry={self.industry}>"


class AdGenerationJob(db.Model):
    """Track AI generation jobs (can take time for images)"""
    __tablename__ = "ad_generation_jobs"

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Job details
    job_type = db.Column(
        SAEnum('website_scan', 'image_generation', 'copy_generation', 'full_creative', name='job_type'),
        nullable=False
    )

    # Input
    input_data = db.Column(JSONType, nullable=True)  # URL, prompt, etc.

    # Output
    creative_id = db.Column(Integer, ForeignKey("ad_creatives.id"), nullable=True, index=True)
    output_data = db.Column(JSONType, nullable=True)  # Generated content

    # Status
    status = db.Column(
        SAEnum('pending', 'processing', 'completed', 'failed', name='job_status'),
        nullable=False,
        default='pending'
    )
    error_message = db.Column(Text, nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    completed_at = db.Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<AdGenerationJob id={self.id} type={self.job_type} status={self.status}>"


class AdAnalyticsEvent(db.Model):
    """Track analytics events for ad composer usage and performance"""
    __tablename__ = "ad_analytics_events"

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    account_id = db.Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    creative_id = db.Column(Integer, ForeignKey("ad_creatives.id"), nullable=True, index=True)

    # Event details
    event_type = db.Column(
        SAEnum(
            'ad_generated',
            'creative_saved',
            'image_downloaded',
            'creative_exported',
            'creative_viewed',
            'creative_edited',
            'variation_created',
            name='analytics_event_type'
        ),
        nullable=False,
        index=True
    )

    # Event metadata
    platform = db.Column(String(50), nullable=True)  # facebook, instagram, etc.
    industry = db.Column(String(100), nullable=True)
    generation_method = db.Column(String(50), nullable=True)  # website, manual

    # Cost tracking
    image_count = db.Column(Integer, default=0)  # Number of images generated
    ai_cost = db.Column(db.Float, nullable=True)  # Estimated cost in USD

    # Performance metrics (for generated ads)
    predicted_ctr = db.Column(db.Float, nullable=True)  # Predicted CTR %
    quality_score = db.Column(Integer, nullable=True)  # 0-100
    engagement_score = db.Column(Integer, nullable=True)  # 0-100

    # Additional data
    event_data = db.Column(JSONType, nullable=True)  # Format, download type, export destination, etc.

    # Session tracking
    session_id = db.Column(String(255), nullable=True, index=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False, index=True)

    def __repr__(self) -> str:
        return f"<AdAnalyticsEvent id={self.id} type={self.event_type} user_id={self.user_id}>"
