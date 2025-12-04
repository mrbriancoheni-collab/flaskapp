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

    def __repr__(self) -> str:
        return f"<LeadContact id={self.id} name={self.name!r} title={self.title!r} email={self.email!r}>"


class EmailSequence(db.Model):
    """Email template in a sequence"""
    __tablename__ = "email_sequences"

    id = db.Column(Integer, primary_key=True)
    campaign_id = db.Column(Integer, ForeignKey("lead_campaigns.id"), nullable=False, index=True)

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
