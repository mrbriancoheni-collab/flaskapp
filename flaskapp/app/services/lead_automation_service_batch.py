# app/services/lead_automation_service_batch.py
"""
IMPROVED: Batch Email Sending for Lead Automation

This is a drop-in replacement for the _process_email_sending method
that sends emails in batches instead of one-by-one.

MUCH FASTER: Sends up to 500 emails per API call instead of 1!
"""
import logging
from datetime import datetime
from typing import List, Dict
from sqlalchemy import func

from app.extensions import db
from app.models_leads import LeadCampaign, Lead, LeadContact, LeadEmail, LeadContactEmail
from app.configs.lead_automation_config import AUTOMATION_CONFIG
from app.services.brevo_outreach import BrevoOutreachService

logger = logging.getLogger(__name__)


def process_email_sending_batch(automation_service) -> int:
    """
    Send emails in BATCHES instead of one-by-one

    This function replaces the old _process_email_sending method
    and is MUCH faster because it uses Brevo's batch API.

    Args:
        automation_service: The LeadAutomationService instance

    Returns:
        Number of emails sent
    """
    if not automation_service._can_send_email_today():
        return 0

    sent_count = 0

    # Initialize Brevo outreach service
    try:
        logger.info("Using Brevo email service (BATCH MODE)")
        outreach = BrevoOutreachService()
    except Exception as e:
        logger.error(f"Cannot initialize Brevo outreach service: {e}")
        return 0

    # Get ALL ready campaigns
    ready_campaigns = LeadCampaign.query.filter_by(status='ready').all()
    logger.info(f"Found {len(ready_campaigns)} ready campaigns")

    # Collect ALL emails to send across all campaigns
    emails_to_send = []
    email_metadata = []  # Track what to update after sending

    for campaign in ready_campaigns:
        # Ensure campaign has an email sequence
        email_sequence = automation_service._ensure_campaign_has_sequence(campaign)
        if not email_sequence:
            logger.warning(f"Could not get/create email sequence for campaign '{campaign.name}'")
            continue

        # Get enriched leads with contacts
        enriched_leads = Lead.query.filter_by(
            campaign_id=campaign.id,
            enrichment_status='completed'
        ).limit(AUTOMATION_CONFIG["daily_email_limit"]).all()

        logger.info(f"Campaign '{campaign.name}': {len(enriched_leads)} enriched leads")

        for lead in enriched_leads:
            # Check daily limit
            remaining = AUTOMATION_CONFIG["daily_email_limit"] - automation_service.state["daily_stats"]["emails"]
            if len(emails_to_send) >= remaining:
                logger.info(f"Reached daily email limit ({AUTOMATION_CONFIG['daily_email_limit']}). Stopping collection.")
                break

            # Get pending contacts for this lead
            pending_contacts = LeadContact.query.filter_by(
                lead_id=lead.id,
                email_status='pending'
            ).filter(
                LeadContact.email.isnot(None)
            ).all()

            # If no contacts, fall back to legacy decision_maker_email
            if not pending_contacts and lead.email_status == 'pending' and lead.decision_maker_email:
                # DUPLICATE PREVENTION: Check if we've already sent this sequence to this email
                already_sent = LeadEmail.query.filter_by(
                    lead_id=lead.id,
                    sequence_id=email_sequence.id,
                    to_email=lead.decision_maker_email
                ).first()

                if already_sent:
                    logger.debug(f"Batch: Skipping {lead.decision_maker_email} - already sent sequence step {email_sequence.step_number}")
                    continue

                subject = automation_service._replace_variables(email_sequence.subject, lead, campaign)
                body = automation_service._replace_variables(email_sequence.body_text, lead, campaign)

                emails_to_send.append({
                    'email': lead.decision_maker_email,
                    'params': {
                        'company_name': lead.company_name or 'there',
                        'subject': subject
                    }
                })

                email_metadata.append({
                    'type': 'lead',
                    'lead_id': lead.id,
                    'campaign_id': campaign.id,
                    'sequence_id': email_sequence.id,
                    'to_email': lead.decision_maker_email,
                    'subject': subject,
                    'body': body
                })
                continue

            # Send to each contact
            for contact in pending_contacts:
                remaining = AUTOMATION_CONFIG["daily_email_limit"] - automation_service.state["daily_stats"]["emails"]
                if len(emails_to_send) >= remaining:
                    break

                # DUPLICATE PREVENTION: Check if we've already sent this sequence to this contact
                already_sent = LeadContactEmail.query.filter_by(
                    contact_id=contact.id,
                    sequence_step=email_sequence.step_number,
                    to_email=contact.email
                ).first()

                if already_sent:
                    logger.debug(f"Batch: Skipping {contact.email} ({contact.name}) - already sent sequence step {email_sequence.step_number}")
                    continue

                subject = automation_service._replace_contact_variables(email_sequence.subject, lead, contact, campaign)
                body = automation_service._replace_contact_variables(email_sequence.body_text, lead, contact, campaign)

                emails_to_send.append({
                    'email': contact.email,
                    'params': {
                        'company_name': lead.company_name or 'there',
                        'contact_name': contact.name or 'there',
                        'subject': subject
                    }
                })

                email_metadata.append({
                    'type': 'contact',
                    'lead_id': lead.id,
                    'contact_id': contact.id,
                    'campaign_id': campaign.id,
                    'sequence_id': email_sequence.id,
                    'to_email': contact.email,
                    'subject': subject,
                    'body': body
                })

        # Break outer loop if we hit limit
        if len(emails_to_send) >= AUTOMATION_CONFIG["daily_email_limit"] - automation_service.state["daily_stats"]["emails"]:
            break

    if not emails_to_send:
        logger.info("No emails to send")
        return 0

    logger.info(f"Prepared {len(emails_to_send)} emails to send in batches")

    # Get the email template (use first campaign's sequence as template)
    first_campaign = ready_campaigns[0]
    email_sequence = automation_service._ensure_campaign_has_sequence(first_campaign)

    # Create a generic template with {{subject}} placeholder
    subject_template = "{{subject}}"
    body_template = email_sequence.body_text.replace('\n', '<br>')

    # SEND IN BATCHES (up to 500 at a time)
    try:
        result = outreach.send_batch_emails(
            recipients=emails_to_send,
            subject_template=subject_template,
            body_html_template=body_template,
            tags=['lead_automation', 'batch_send']
        )

        logger.info(f"Batch send result: {result['sent']} sent, {result['failed']} failed")

        # If successful, record the emails in the database
        if result['success'] or result['sent'] > 0:
            for i, metadata in enumerate(email_metadata[:result['sent']]):
                try:
                    if metadata['type'] == 'lead':
                        # Record email sent to lead
                        email_record = LeadEmail(
                            lead_id=metadata['lead_id'],
                            sequence_id=metadata['sequence_id'],
                            to_email=metadata['to_email'],
                            subject=metadata['subject'],
                            body_text=metadata['body'],
                            body_html=metadata['body'].replace('\n', '<br>'),
                            sent_at=datetime.utcnow(),
                            status='sent'
                        )
                        db.session.add(email_record)

                        # Update lead status
                        lead = Lead.query.get(metadata['lead_id'])
                        if lead:
                            lead.email_status = 'sent'
                            lead.last_email_sent_at = datetime.utcnow()

                    else:  # contact
                        # Record email sent to contact
                        email_record = LeadContactEmail(
                            contact_id=metadata['contact_id'],
                            lead_id=metadata['lead_id'],
                            campaign_id=metadata['campaign_id'],
                            sequence_step=1,
                            subject=metadata['subject'],
                            body=metadata['body'],
                            to_email=metadata['email'],
                            email_provider='brevo',
                            sent_at=datetime.utcnow(),
                            status='sent'
                        )
                        db.session.add(email_record)

                        # Update contact status
                        contact = LeadContact.query.get(metadata['contact_id'])
                        if contact:
                            contact.email_status = 'sent'
                            contact.last_contact_date = datetime.utcnow()

                    # Update campaign stats
                    campaign = LeadCampaign.query.get(metadata['campaign_id'])
                    if campaign:
                        campaign.emails_sent = (campaign.emails_sent or 0) + 1

                    automation_service.state["emails_sent"] += 1
                    automation_service.state["daily_stats"]["emails"] += 1
                    sent_count += 1

                except Exception as e:
                    logger.error(f"Error recording email sent: {e}")
                    db.session.rollback()

            db.session.commit()
            logger.info(f"Successfully recorded {sent_count} emails sent")

    except Exception as e:
        logger.error(f"Batch email send failed: {e}")
        db.session.rollback()

    return sent_count
