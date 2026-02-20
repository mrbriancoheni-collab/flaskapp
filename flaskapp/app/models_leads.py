# app/models_leads.py
"""
Lead Generation & Cold Outreach Models

Supports SERP scraping (ads, maps, LSA, organic) + contact enrichment + email sequences
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import (
    String, Integer, Boolean, DateTime, ForeignKey, Text, Float, Enum as SAEnum
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

try:
    from sqlalchemy.dialects.mysql import JSON as MySQLJSON
    JSONType = MySQLJSON
except Exception:
    from sqlalchemy import JSON as SAJSON
    JSONType = SAJSON

from app import db


class LeadCampaign(db.Model):
    """Campaign for scraping and outreach"""
    __tablename__ = "lead_campaigns"

    id = db.Column(Integer, primary_key=True)
    name = db.Column(String(200), nullable=False)

    # Search parameters
    industry_service = db.Column(String(200), nullable=False)  # e.g., "plumbing"
    location = db.Column(String(200), nullable=False)  # e.g., "New York, NY"

    # Scraping settings
    scrape_ads = db.Column(Boolean, default=True)
    scrape_maps = db.Column(Boolean, default=True)
    scrape_lsa = db.Column(Boolean, default=True)
    scrape_organic = db.Column(Boolean, default=True)
    max_organic_results = db.Column(Integer, default=5)

    # Email settings
    daily_email_limit = db.Column(Integer, default=250)
    sequence_delay_days = db.Column(Integer, default=3)  # Days between sequence emails

    # Status
    status = db.Column(
        SAEnum('draft', 'scraping', 'ready', 'sending', 'paused', 'completed', name='campaign_status'),
        default='draft',
        nullable=False
    )

    # Stats
    leads_scraped = db.Column(Integer, default=0)
    leads_enriched = db.Column(Integer, default=0)
    emails_sent = db.Column(Integer, default=0)
    emails_opened = db.Column(Integer, default=0)
    emails_replied = db.Column(Integer, default=0)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    scraping_started_at = db.Column(DateTime, nullable=True)
    scraping_completed_at = db.Column(DateTime, nullable=True)
    sending_started_at = db.Column(DateTime, nullable=True)

    # One-click automation
    is_core = db.Column(Boolean, default=False)  # Flag for core 20 campaigns
    last_automation_run = db.Column(DateTime, nullable=True)  # Last automation run time

    # Relationships
    leads = relationship("Lead", back_populates="campaign", cascade="all, delete-orphan")
    sequences = relationship("EmailSequence", back_populates="campaign", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<LeadCampaign id={self.id} name={self.name!r} status={self.status}>"


class Lead(db.Model):
    """Scraped company/contact"""
    __tablename__ = "leads"

    id = db.Column(Integer, primary_key=True)
    campaign_id = db.Column(Integer, ForeignKey("lead_campaigns.id"), nullable=False, index=True)

    # CRM integration
    crm_contact_id = db.Column(Integer, ForeignKey("crm_contacts.id"), nullable=True, index=True)

    # Company info
    company_name = db.Column(String(255), nullable=False)
    website = db.Column(String(500), nullable=True)
    phone = db.Column(String(50), nullable=True)
    address = db.Column(String(500), nullable=True)

    # Source
    source_type = db.Column(
        SAEnum('ad', 'map', 'lsa', 'organic', name='lead_source_type'),
        nullable=False
    )
    source_url = db.Column(String(1000), nullable=True)
    serp_position = db.Column(Integer, nullable=True)  # Position in SERP results

    # Enrichment data
    email_format = db.Column(String(100), nullable=True)  # e.g., "first@domain.com"
    decision_maker_name = db.Column(String(200), nullable=True)
    decision_maker_title = db.Column(String(100), nullable=True)
    decision_maker_email = db.Column(String(255), nullable=True, index=True)
    decision_maker_linkedin = db.Column(String(500), nullable=True)

    # Enrichment status
    enrichment_status = db.Column(
        SAEnum('pending', 'in_progress', 'completed', 'failed', name='enrichment_status'),
        default='pending',
        nullable=False
    )
    enrichment_attempts = db.Column(Integer, default=0)
    enriched_at = db.Column(DateTime, nullable=True)

    # Email status
    email_status = db.Column(
        SAEnum('pending', 'sending', 'sent', 'opened', 'replied', 'bounced', 'unsubscribed', name='email_status'),
        default='pending',
        nullable=False,
        index=True
    )
    current_sequence_step = db.Column(Integer, default=0)  # Which email in sequence

    # Engagement tracking
    last_email_sent_at = db.Column(DateTime, nullable=True)
    first_opened_at = db.Column(DateTime, nullable=True)
    replied_at = db.Column(DateTime, nullable=True)
    unsubscribed_at = db.Column(DateTime, nullable=True)

    # Auto-cleanup
    auto_delete_at = db.Column(DateTime, nullable=True)  # Set when no response after X days

    # Extra data
    extra_data = db.Column(JSONType, nullable=True)  # Any additional scraped data

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    campaign = relationship("LeadCampaign", back_populates="leads")
    emails_sent = relationship("LeadEmail", back_populates="lead", cascade="all, delete-orphan")
    contacts = relationship("LeadContact", back_populates="lead", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Lead id={self.id} company={self.company_name!r} status={self.email_status}>"


class LeadContact(db.Model):
    """Individual contact at a lead company (supports multiple contacts per company)"""
    __tablename__ = "lead_contacts"

    id = db.Column(Integer, primary_key=True)
    lead_id = db.Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)

    # CRM integration
    company_contact_id = db.Column(Integer, ForeignKey("company_contacts.id"), nullable=True, index=True)

    # Contact info
    name = db.Column(String(200), nullable=False)
    title = db.Column(String(100), nullable=True)
    email = db.Column(String(255), nullable=True, index=True)
    linkedin_url = db.Column(String(500), nullable=True)

    # Contact categorization
    role_category = db.Column(
        SAEnum('executive', 'owner', 'marketing', 'operations', 'sales', 'other', name='contact_role_category'),
        default='other',
        nullable=False
    )
    is_primary = db.Column(Boolean, default=False)  # Primary contact for this lead

    # Email tracking for this specific contact
    email_status = db.Column(
        SAEnum('pending', 'sending', 'sent', 'opened', 'replied', 'bounced', 'unsubscribed', name='contact_email_status'),
        default='pending',
        nullable=False,
        index=True
    )
    current_sequence_step = db.Column(Integer, default=0)
    last_email_sent_at = db.Column(DateTime, nullable=True)
    first_opened_at = db.Column(DateTime, nullable=True)
    replied_at = db.Column(DateTime, nullable=True)
    unsubscribed_at = db.Column(DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    lead = relationship("Lead", back_populates="contacts")
    emails_sent = relationship("LeadContactEmail", back_populates="contact", cascade="all, delete-orphan")
    # company_contact is the canonical record — email addresses should be read from there
    company_contact = relationship("CompanyContact", foreign_keys=[company_contact_id])

    def __repr__(self) -> str:
        return f"<LeadContact id={self.id} name={self.name!r} title={self.title!r} email={self.email!r}>"


class EmailSequence(db.Model):
    """Email template in a sequence"""
    __tablename__ = "email_sequences"

    id = db.Column(Integer, primary_key=True)
    campaign_id = db.Column(Integer, ForeignKey("lead_campaigns.id"), nullable=True, index=True)

    step_number = db.Column(Integer, nullable=False)  # 1 = first email, 2 = follow-up 1, etc.
    name = db.Column(String(200), nullable=False)  # e.g., "Initial Outreach"

    # Email content (supports {{company_name}}, {{decision_maker_name}}, etc.)
    subject = db.Column(String(500), nullable=False)
    body_html = db.Column(Text, nullable=False)
    body_text = db.Column(Text, nullable=True)  # Plain text fallback

    # Timing
    delay_days = db.Column(Integer, default=0)  # Days after previous email (0 for first email)

    # Status
    is_active = db.Column(Boolean, default=True)

    # Stats
    sent_count = db.Column(Integer, default=0)
    opened_count = db.Column(Integer, default=0)
    replied_count = db.Column(Integer, default=0)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    campaign = relationship("LeadCampaign", back_populates="sequences")

    def __repr__(self) -> str:
        return f"<EmailSequence id={self.id} step={self.step_number} name={self.name!r}>"


class LeadEmail(db.Model):
    """Track sent emails for lead campaigns"""
    __tablename__ = "lead_emails_sent"

    id = db.Column(Integer, primary_key=True)
    lead_id = db.Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    sequence_id = db.Column(Integer, ForeignKey("email_sequences.id"), nullable=False, index=True)

    # Email details
    to_email = db.Column(String(255), nullable=False, index=True)
    subject = db.Column(String(500), nullable=False)
    body_html = db.Column(Text, nullable=True)
    body_text = db.Column(Text, nullable=True)

    # Mailgun tracking
    mailgun_message_id = db.Column(String(255), nullable=True, unique=True, index=True)

    # Status
    status = db.Column(
        SAEnum('queued', 'sent', 'delivered', 'opened', 'clicked', 'bounced', 'failed', 'complained', name='email_sent_status'),
        default='queued',
        nullable=False,
        index=True
    )

    # Engagement
    sent_at = db.Column(DateTime, nullable=True)
    delivered_at = db.Column(DateTime, nullable=True)
    opened_at = db.Column(DateTime, nullable=True)
    clicked_at = db.Column(DateTime, nullable=True)
    bounced_at = db.Column(DateTime, nullable=True)
    complained_at = db.Column(DateTime, nullable=True)

    # Error tracking
    error_message = db.Column(Text, nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    lead = relationship("Lead", back_populates="emails_sent")

    def __repr__(self) -> str:
        return f"<LeadEmail id={self.id} to={self.to_email!r} status={self.status}>"


class LeadContactEmail(db.Model):
    """Track emails sent to specific contacts"""
    __tablename__ = "lead_contact_emails"
    __table_args__ = (
        db.UniqueConstraint('contact_id', 'sequence_step', name='uq_lead_contact_emails_contact_step'),
    )

    id = db.Column(Integer, primary_key=True)
    contact_id = db.Column(Integer, ForeignKey("lead_contacts.id"), nullable=False, index=True)
    lead_id = db.Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    campaign_id = db.Column(Integer, ForeignKey("lead_campaigns.id"), nullable=False, index=True)
    sequence_step = db.Column(Integer, nullable=False)

    # Email details
    subject = db.Column(String(500), nullable=False)
    body = db.Column(Text, nullable=True)
    to_email = db.Column(String(255), nullable=True)  # Store recipient email

    # Provider tracking
    email_provider = db.Column(String(50), nullable=True, default='mailgun')  # 'mailgun' or 'brevo'
    mailgun_message_id = db.Column(String(255), nullable=True, unique=True, index=True)
    brevo_message_id = db.Column(String(255), nullable=True, index=True)  # Brevo message ID

    # Status
    status = db.Column(
        SAEnum('queued', 'sent', 'delivered', 'opened', 'clicked', 'bounced', 'failed', name='contact_email_sent_status'),
        default='queued',
        nullable=False,
        index=True
    )

    # Engagement tracking
    sent_at = db.Column(DateTime, nullable=True)
    delivered_at = db.Column(DateTime, nullable=True)
    opened_at = db.Column(DateTime, nullable=True)
    clicked_at = db.Column(DateTime, nullable=True)
    bounced_at = db.Column(DateTime, nullable=True)

    # Error tracking
    error_message = db.Column(Text, nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    contact = relationship("LeadContact", back_populates="emails_sent")

    def __repr__(self) -> str:
        return f"<LeadContactEmail id={self.id} contact_id={self.contact_id} status={self.status}>"


class EmailUnsubscribe(db.Model):
    """Track unsubscribes for CAN-SPAM compliance"""
    __tablename__ = "email_unsubscribes"

    id = db.Column(Integer, primary_key=True)
    email = db.Column(String(255), nullable=False, unique=True, index=True)

    # Metadata
    unsubscribed_from_campaign_id = db.Column(Integer, ForeignKey("lead_campaigns.id"), nullable=True)
    reason = db.Column(String(500), nullable=True)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<EmailUnsubscribe email={self.email!r}>"


# ==============================================================================
# Email Conversation Tracking (AI Auto-Responses)
# ==============================================================================

class EmailConversation(db.Model):
    """Email conversation threads for AI auto-responses"""
    __tablename__ = "email_conversations"

    id = db.Column(Integer, primary_key=True)

    # Link to lead/contact
    lead_contact_id = db.Column(Integer, ForeignKey("lead_contacts.id"), nullable=False)

    # Thread identification
    thread_id = db.Column(String(255), unique=True, index=True)
    subject = db.Column(String(500))

    # Status tracking
    status = db.Column(String(50), default='active')  # active, closed, escalated, spam
    ai_handled = db.Column(Boolean, default=True)
    requires_human = db.Column(Boolean, default=False)

    # Metrics
    total_messages = db.Column(Integer, default=0)
    ai_messages = db.Column(Integer, default=0)
    human_messages = db.Column(Integer, default=0)
    prospect_messages = db.Column(Integer, default=0)

    # Sentiment analysis
    last_sentiment = db.Column(String(50))  # positive, negative, neutral, interested
    lead_score = db.Column(Integer, default=0)  # 0-100

    # Timestamps
    last_message_at = db.Column(DateTime, nullable=False)
    last_prospect_reply_at = db.Column(DateTime)
    last_ai_reply_at = db.Column(DateTime)
    escalated_at = db.Column(DateTime)
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    contact = relationship("LeadContact", backref="conversations")
    messages = relationship("EmailConversationMessage", back_populates="conversation", cascade="all, delete-orphan")
    alerts = relationship("ConversationAlert", back_populates="conversation", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<EmailConversation id={self.id} contact_id={self.lead_contact_id} status={self.status}>"


class EmailConversationMessage(db.Model):
    """Individual messages within conversation threads"""
    __tablename__ = "email_conversation_messages"

    id = db.Column(Integer, primary_key=True)

    # Link to conversation
    conversation_id = db.Column(Integer, ForeignKey("email_conversations.id"), nullable=False)

    # Message details
    direction = db.Column(String(50), nullable=False)  # inbound, outbound
    from_email = db.Column(String(255), nullable=False)
    to_email = db.Column(String(255), nullable=False)
    subject = db.Column(Text)
    body_text = db.Column(Text)
    body_html = db.Column(Text)

    # AI handling
    is_ai_generated = db.Column(Boolean, default=False)
    ai_model = db.Column(String(100))
    ai_prompt_used = db.Column(Text)
    ai_confidence = db.Column(db.Numeric(3, 2))

    # Provider details
    message_id = db.Column(String(255), index=True)
    in_reply_to = db.Column(String(255))
    references = db.Column(Text)

    # Sentiment & analysis
    sentiment = db.Column(String(50))
    contains_question = db.Column(Boolean, default=False)
    urgency_level = db.Column(String(50))

    # Timestamps
    received_at = db.Column(DateTime)
    sent_at = db.Column(DateTime)
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    conversation = relationship("EmailConversation", back_populates="messages")

    def __repr__(self) -> str:
        return f"<EmailConversationMessage id={self.id} direction={self.direction} from={self.from_email}>"


class ConversationAlert(db.Model):
    """Notifications for admin about conversation activity"""
    __tablename__ = "conversation_alerts"

    id = db.Column(Integer, primary_key=True)

    # Link to conversation
    conversation_id = db.Column(Integer, ForeignKey("email_conversations.id"), nullable=False)

    # Alert details
    alert_type = db.Column(String(50), nullable=False)  # new_reply, needs_human, interested, negative, question
    message = db.Column(Text)
    severity = db.Column(String(50), default='info')  # info, warning, urgent

    # Status
    is_read = db.Column(Boolean, default=False, index=True)
    read_at = db.Column(DateTime)
    dismissed = db.Column(Boolean, default=False)
    dismissed_at = db.Column(DateTime)

    # Timestamps
    created_at = db.Column(DateTime, server_default=func.now(), nullable=False, index=True)

    # Relationships
    conversation = relationship("EmailConversation", back_populates="alerts")

    def __repr__(self) -> str:
        return f"<ConversationAlert id={self.id} type={self.alert_type} read={self.is_read}>"


class CampaignAutomationConfig(db.Model):
    """Configuration for automated campaign execution"""
    __tablename__ = "campaign_automation_config"

    id = db.Column(Integer, primary_key=True)
    enabled = db.Column(Boolean, default=False)
    run_time = db.Column(String(5), default='09:00')  # HH:MM format
    run_days = db.Column(JSONType, nullable=True)  # [0,1,2,3,4] for Mon-Fri
    daily_email_limit = db.Column(Integer, default=250)
    skip_weekends = db.Column(Boolean, default=True)
    next_run_at = db.Column(DateTime, nullable=True)
    last_run_at = db.Column(DateTime, nullable=True)
    created_at = db.Column(DateTime, server_default=func.now())
    updated_at = db.Column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<CampaignAutomationConfig id={self.id} enabled={self.enabled} run_time={self.run_time}>"


class AutomationRun(db.Model):
    """Track automation execution history"""
    __tablename__ = "automation_runs"

    id = db.Column(Integer, primary_key=True)
    job_id = db.Column(String(36), unique=True, index=True)
    trigger_type = db.Column(String(20))  # 'manual' or 'scheduled'
    status = db.Column(String(20))  # 'running', 'completed', 'failed'
    started_at = db.Column(DateTime, nullable=False)
    completed_at = db.Column(DateTime, nullable=True)
    duration_minutes = db.Column(Integer, nullable=True)
    campaigns_processed = db.Column(Integer, default=0)
    leads_scraped = db.Column(Integer, default=0)
    leads_enriched = db.Column(Integer, default=0)
    emails_sent = db.Column(Integer, default=0)
    error_count = db.Column(Integer, default=0)
    error_message = db.Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AutomationRun id={self.id} job_id={self.job_id} status={self.status}>"
