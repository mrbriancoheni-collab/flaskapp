# app/services/lead_automation_service.py
"""
Automated Lead Generation Service

Systematically creates campaigns, scrapes leads, enriches contacts,
and sends automated emails across cities and categories.

Handles:
- State management (resume from where stopped)
- Duplicate domain detection
- Rate limiting
- Sunday skip for emails
- Multi-day/week execution
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func

from app.extensions import db
from app.models_leads import LeadCampaign, Lead, EmailSequence, LeadEmail, LeadContact, LeadContactEmail
from app.configs.lead_automation_config import (
    get_campaign_queue,
    AUTOMATION_CONFIG,
    HOME_SERVICE_CATEGORIES
)
from app.services.serpapi_scraper import SerpAPIScraperService
from app.services.lead_enrichment import LeadEnrichmentService
from app.services.domain_crawler import DomainCrawler
from app.services.mailgun_outreach import MailgunOutreachService
from app.services.brevo_outreach import BrevoOutreachService
from app.services.crm_sync_service import CRMSyncService

logger = logging.getLogger(__name__)


class LeadAutomationService:
    """Automated lead generation and outreach service"""

    # Use relative path from project root, or absolute if env var set
    STATE_FILE = os.getenv('AUTOMATION_STATE_FILE', 'automation_state.json')

    def __init__(self):
        self.state = self._load_state()
        self.scraper = None
        self.enrichment = None
        self.outreach = None
        self.crm_sync = None

    def _load_state(self) -> Dict:
        """Load automation state from file"""
        if os.path.exists(self.STATE_FILE):
            try:
                with open(self.STATE_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading state: {e}")

        # Default state
        return {
            "last_run": None,
            "campaigns_created": 0,
            "campaigns_scraped": 0,
            "leads_enriched": 0,
            "emails_sent": 0,
            "current_campaign_index": 0,
            "processed_domains": [],  # Track domains to avoid duplicates
            "daily_stats": {
                "date": None,
                "scrapes": 0,
                "enrichments": 0,
                "emails": 0
            }
        }

    def _save_state(self):
        """Save automation state to file"""
        try:
            self.state["last_run"] = datetime.utcnow().isoformat()
            with open(self.STATE_FILE, 'w') as f:
                json.dump(self.state, f, indent=2)
            logger.info(f"State saved: {self.state['campaigns_created']} campaigns created, "
                       f"{self.state['leads_enriched']} leads enriched, "
                       f"{self.state['emails_sent']} emails sent")
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def _reset_daily_stats_if_new_day(self):
        """Reset daily stats if it's a new day"""
        today = datetime.utcnow().date().isoformat()
        if self.state["daily_stats"]["date"] != today:
            self.state["daily_stats"] = {
                "date": today,
                "scrapes": 0,
                "enrichments": 0,
                "emails": 0
            }
            logger.info(f"Reset daily stats for {today}")

    def _can_scrape_today(self) -> bool:
        """Check if we can scrape more campaigns today (checks database for all operations)"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Count all leads created today (from manual + automated operations)
        today_scrapes = db.session.query(func.count(Lead.id)).filter(
            Lead.created_at >= today_start
        ).scalar() or 0

        return today_scrapes < AUTOMATION_CONFIG["daily_scrape_limit"]

    def _can_enrich_today(self) -> bool:
        """Check if we can enrich more leads today (checks database for all operations)"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        # Count all leads enriched today (from manual + automated operations)
        today_enrichments = db.session.query(func.count(Lead.id)).filter(
            Lead.enriched_at >= today_start
        ).scalar() or 0

        return today_enrichments < AUTOMATION_CONFIG["daily_enrich_limit"]

    def _can_send_email_today(self) -> bool:
        """Check if we can send more emails today (checks database for all operations)"""
        today = datetime.utcnow()

        # Check if today is Sunday (or other skip day)
        if today.weekday() in AUTOMATION_CONFIG["skip_email_days"]:
            logger.info(f"Skipping emails - today is a skip day (weekday {today.weekday()})")
            return False

        today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)

        # Count all emails sent today from both tables (manual + automated operations)
        today_legacy_emails = db.session.query(func.count(LeadEmail.id)).filter(
            LeadEmail.sent_at >= today_start
        ).scalar() or 0

        today_contact_emails = db.session.query(func.count(LeadContactEmail.id)).filter(
            LeadContactEmail.sent_at >= today_start
        ).scalar() or 0

        today_emails = today_legacy_emails + today_contact_emails

        return today_emails < AUTOMATION_CONFIG["daily_email_limit"]

    def _is_duplicate_domain(self, domain: str) -> bool:
        """Check if domain has already been processed"""
        if not domain:
            return False

        domain_clean = domain.lower().replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]
        return domain_clean in self.state["processed_domains"]

    def _mark_domain_processed(self, domain: str):
        """Mark domain as processed to avoid duplicates"""
        if not domain:
            return

        domain_clean = domain.lower().replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]
        if domain_clean not in self.state["processed_domains"]:
            self.state["processed_domains"].append(domain_clean)

    def run_daily_automation(self):
        """
        Run daily automation cycle:
        1. Create/scrape campaigns (up to daily limit)
        2. Enrich leads (up to daily limit)
        3. Send emails (up to daily limit, skip Sundays)
        """
        logger.info("=" * 80)
        logger.info("STARTING DAILY LEAD AUTOMATION")
        logger.info("=" * 80)

        self._reset_daily_stats_if_new_day()

        # Step 1: Create and scrape campaigns
        scraped = self._process_campaign_scraping()
        logger.info(f"Scraped {scraped} campaigns today")

        # Step 2: Enrich leads
        enriched = self._process_lead_enrichment()
        logger.info(f"Enriched {enriched} leads today")

        # Step 3: Send emails
        sent = self._process_email_sending()
        logger.info(f"Sent {sent} emails today")

        # Save state
        self._save_state()

        logger.info("=" * 80)
        logger.info(f"DAILY AUTOMATION COMPLETE")
        logger.info(f"Total Progress: {self.state['campaigns_created']} campaigns, "
                   f"{self.state['leads_enriched']} leads, {self.state['emails_sent']} emails")
        logger.info("=" * 80)

        return {
            "scraped": scraped,
            "enriched": enriched,
            "sent": sent,
            "total_campaigns": self.state['campaigns_created'],
            "total_emails": self.state['emails_sent']
        }

    def _process_campaign_scraping(self) -> int:
        """Create and scrape campaigns up to daily limit

        Each campaign scrapes ALL keywords for one city
        """
        scraped_count = 0
        campaign_queue = get_campaign_queue()

        # Initialize scraper
        try:
            self.scraper = SerpAPIScraperService()
        except ValueError as e:
            logger.error(f"Cannot initialize scraper: {e}")
            return 0

        while self._can_scrape_today() and self.state["current_campaign_index"] < len(campaign_queue):
            campaign_config = campaign_queue[self.state["current_campaign_index"]]

            try:
                # Check if campaign already exists
                existing = LeadCampaign.query.filter_by(
                    name=campaign_config["name"]
                ).first()

                if existing and existing.status in ['ready', 'active']:
                    logger.info(f"Skipping existing campaign: {campaign_config['name']}")
                    self.state["current_campaign_index"] += 1
                    continue

                # Create or get campaign
                if not existing:
                    campaign = LeadCampaign(
                        name=campaign_config["name"],
                        industry_service="Home Services",  # Generic since we scrape all keywords
                        location=campaign_config["city"],
                        scrape_ads=AUTOMATION_CONFIG["scrape_sources"]["scrape_ads"],
                        scrape_maps=AUTOMATION_CONFIG["scrape_sources"]["scrape_maps"],
                        scrape_lsa=AUTOMATION_CONFIG["scrape_sources"]["scrape_lsa"],
                        scrape_organic=AUTOMATION_CONFIG["scrape_sources"]["scrape_organic"],
                        max_organic_results=AUTOMATION_CONFIG["scrape_sources"]["max_organic_results"],
                        daily_email_limit=AUTOMATION_CONFIG["daily_email_limit"],
                        sequence_delay_days=AUTOMATION_CONFIG["email_sequence_delay_days"],
                        status='draft'
                    )
                    db.session.add(campaign)
                    db.session.commit()
                    self.state["campaigns_created"] += 1
                    logger.info(f"Created campaign: {campaign_config['name']}")
                else:
                    campaign = existing

                # Track leads found by each keyword (for deduplication within campaign)
                campaign_leads = {}  # {domain: lead_object}
                total_leads_created = 0

                # Loop through all keywords for this city
                keywords = campaign_config["keywords"]
                logger.info(f"Scraping {len(keywords)} keywords for {campaign.location}")

                for keyword in keywords:
                    # Scrape leads for this keyword
                    query = f"{keyword} {campaign.location}"

                    try:
                        results = self.scraper.scrape_campaign(
                            query=query,
                            location=campaign.location,
                            scrape_ads=campaign.scrape_ads,
                            scrape_maps=campaign.scrape_maps,
                            scrape_lsa=campaign.scrape_lsa,
                            scrape_organic=campaign.scrape_organic,
                            max_organic=campaign.max_organic_results
                        )

                        # Process leads from this keyword
                        for source_type, items in results.items():
                            for item in items:
                                domain = item.get('website')

                                # Skip if duplicate domain globally
                                if self._is_duplicate_domain(domain):
                                    logger.debug(f"Skipping duplicate domain globally: {domain}")
                                    continue

                                # Clean domain for comparison
                                domain_clean = domain.lower().replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0] if domain else None

                                # Check if this lead already exists in this campaign (from another keyword)
                                if domain_clean and domain_clean in campaign_leads:
                                    # Add this keyword to the existing lead's keywords list
                                    existing_lead = campaign_leads[domain_clean]
                                    if 'keywords' not in existing_lead.extra_data:
                                        existing_lead.extra_data['keywords'] = []
                                    if keyword not in existing_lead.extra_data['keywords']:
                                        existing_lead.extra_data['keywords'].append(keyword)
                                    logger.debug(f"Lead {item['company_name']} also found for keyword: {keyword}")
                                    continue

                                # Check if lead already exists in database
                                existing_lead = Lead.query.filter_by(
                                    campaign_id=campaign.id,
                                    company_name=item['company_name']
                                ).first()

                                if existing_lead:
                                    # Update existing lead with new keyword
                                    if 'keywords' not in existing_lead.extra_data:
                                        existing_lead.extra_data['keywords'] = []
                                    if keyword not in existing_lead.extra_data['keywords']:
                                        existing_lead.extra_data['keywords'].append(keyword)
                                    campaign_leads[domain_clean] = existing_lead
                                    continue

                                # Create new lead
                                extra_data = item.get('extra_data', {})
                                extra_data['keywords'] = [keyword]  # Track which keyword(s) found this lead

                                lead = Lead(
                                    campaign_id=campaign.id,
                                    company_name=item['company_name'],
                                    website=domain,
                                    phone=item.get('phone'),
                                    address=item.get('address'),
                                    source_type=source_type,
                                    source_url=item.get('source_url'),
                                    serp_position=item.get('position'),
                                    enrichment_status='pending',
                                    email_status='pending',
                                    extra_data=extra_data
                                )

                                db.session.add(lead)
                                total_leads_created += 1

                                # Track in campaign_leads for deduplication
                                if domain_clean:
                                    campaign_leads[domain_clean] = lead

                                # Mark domain as processed globally
                                self._mark_domain_processed(domain)

                        logger.info(f"  - Keyword '{keyword}': found {len(items)} items from {source_type}")

                    except Exception as e:
                        logger.error(f"Error scraping keyword '{keyword}' for {campaign.location}: {e}")
                        continue

                # Update campaign
                campaign.status = 'ready'
                campaign.scraping_started_at = datetime.utcnow()
                campaign.scraping_completed_at = datetime.utcnow()
                campaign.leads_scraped = total_leads_created
                db.session.commit()

                self.state["campaigns_scraped"] += 1
                self.state["daily_stats"]["scrapes"] += 1
                scraped_count += 1

                logger.info(f"Scraped campaign {campaign.name}: {total_leads_created} unique leads across {len(keywords)} keywords")

            except Exception as e:
                logger.error(f"Error scraping campaign {campaign_config['name']}: {e}")
                db.session.rollback()

            finally:
                self.state["current_campaign_index"] += 1

        return scraped_count

    def _process_lead_enrichment(self) -> int:
        """Enrich pending leads up to daily limit"""
        enriched_count = 0

        # Initialize enrichment and CRM sync services
        self.enrichment = LeadEnrichmentService()
        self.crm_sync = CRMSyncService()

        # Get pending leads across all campaigns
        pending_leads = Lead.query.filter_by(
            enrichment_status='pending'
        ).filter(
            Lead.website.isnot(None)
        ).limit(AUTOMATION_CONFIG["daily_enrich_limit"]).all()

        for lead in pending_leads:
            if not self._can_enrich_today():
                break

            try:
                enrichment_data = self.enrichment.enrich_lead(
                    company_name=lead.company_name,
                    website=lead.website
                )

                # Update lead with enrichment data (legacy fields for backwards compatibility)
                lead.decision_maker_name = enrichment_data.get('decision_maker_name')
                lead.decision_maker_title = enrichment_data.get('decision_maker_title')
                lead.decision_maker_email = enrichment_data.get('decision_maker_email')
                lead.decision_maker_linkedin = enrichment_data.get('decision_maker_linkedin')
                lead.enrichment_status = 'completed'
                lead.enriched_at = datetime.utcnow()

                # Create LeadContact records for each contact found
                contacts = enrichment_data.get('contacts', [])
                for idx, contact_data in enumerate(contacts):
                    # Check if contact already exists (by name and lead_id)
                    existing_contact = LeadContact.query.filter_by(
                        lead_id=lead.id,
                        name=contact_data['name']
                    ).first()

                    if existing_contact:
                        continue

                    contact = LeadContact(
                        lead_id=lead.id,
                        name=contact_data['name'],
                        title=contact_data.get('title'),
                        email=contact_data.get('email'),
                        linkedin_url=contact_data.get('linkedin_url'),
                        role_category=contact_data.get('role_category', 'other'),
                        is_primary=(idx == 0),  # First contact is primary
                        email_status='pending'
                    )
                    db.session.add(contact)

                db.session.commit()

                # Sync to CRM
                try:
                    crm_contact = self.crm_sync.sync_lead_to_crm(lead, stage="lead")
                    if crm_contact:
                        company_contacts = self.crm_sync.sync_lead_contacts_to_crm(lead)
                        logger.info(f"Synced lead {lead.id} to CRM: company {crm_contact.id}, {len(company_contacts)} contacts")
                except Exception as e:
                    logger.error(f"Error syncing lead {lead.id} to CRM: {e}")
                    # Don't fail enrichment if CRM sync fails

                # Update campaign stats
                campaign = lead.campaign
                campaign.leads_enriched = Lead.query.filter_by(
                    campaign_id=campaign.id,
                    enrichment_status='completed'
                ).count()
                db.session.commit()

                self.state["leads_enriched"] += 1
                self.state["daily_stats"]["enrichments"] += 1
                enriched_count += 1

                logger.info(f"Enriched lead: {lead.company_name} with {len(contacts)} contacts")

            except Exception as e:
                logger.error(f"Error enriching lead {lead.id}: {e}")
                lead.enrichment_status = 'failed'
                db.session.commit()

        return enriched_count

    def _ensure_campaign_has_sequence(self, campaign: LeadCampaign) -> Optional[EmailSequence]:
        """
        Ensure campaign has an email sequence. Create default if missing.

        Returns the first email sequence (step 1) for the campaign.
        """
        # Check if sequence exists
        existing_sequence = EmailSequence.query.filter_by(
            campaign_id=campaign.id,
            step_number=1
        ).first()

        if existing_sequence:
            return existing_sequence

        # Create default sequence for automated campaigns
        logger.info(f"Creating default email sequence for campaign '{campaign.name}'")

        # Default template for home services
        default_subject = "Quick question about {{company_name}}'s {{service_type}} services"
        default_body = """Hi {{decision_maker_name}},

I came across {{company_name}} while searching for {{service_type}} services in {{location}}.

I help local service businesses like yours get more customers through Google Ads and SEO. I noticed a few opportunities that could help you show up higher in search results and get more leads.

Would you be interested in a quick 10-minute call to discuss how we could help grow your business?

Best regards,
FieldSprout Team
https://fieldsprout.io

---
If you'd prefer not to receive these emails, please reply with "unsubscribe" and I'll remove you from my list.
"""

        sequence = EmailSequence(
            campaign_id=campaign.id,
            step_number=1,
            name="Initial Outreach",
            subject=default_subject,
            body_text=default_body,
            body_html=default_body.replace('\n', '<br>'),
            delay_days=0,
            is_active=True
        )

        db.session.add(sequence)
        db.session.commit()

        logger.info(f"Created default email sequence for campaign '{campaign.name}'")
        return sequence

    def _process_email_sending(self) -> int:
        """Send emails to enriched leads up to daily limit"""
        if not self._can_send_email_today():
            return 0

        sent_count = 0

        # Initialize outreach service (Brevo or Mailgun)
        email_provider = os.getenv('EMAIL_PROVIDER', 'mailgun').lower()
        try:
            if email_provider == 'brevo':
                logger.info("Using Brevo email service")
                self.outreach = BrevoOutreachService()
            else:
                logger.info("Using Mailgun email service")
                self.outreach = MailgunOutreachService()
        except Exception as e:
            logger.error(f"Cannot initialize {email_provider} outreach service: {e}")
            return 0

        # Get ALL ready campaigns (we'll create sequences if missing)
        ready_campaigns = LeadCampaign.query.filter_by(status='ready').all()

        logger.info(f"Found {len(ready_campaigns)} ready campaigns")

        for campaign in ready_campaigns:
            if not self._can_send_email_today():
                break

            # Get enriched leads with contacts
            enriched_leads = Lead.query.filter_by(
                campaign_id=campaign.id,
                enrichment_status='completed'
            ).limit(AUTOMATION_CONFIG["daily_email_limit"]).all()

            logger.info(f"Campaign '{campaign.name}': {len(enriched_leads)} enriched leads")

            # Ensure campaign has an email sequence (create if missing)
            email_sequence = self._ensure_campaign_has_sequence(campaign)
            if not email_sequence:
                logger.warning(f"Could not get/create email sequence for campaign '{campaign.name}'")
                continue

            for lead in enriched_leads:
                if not self._can_send_email_today():
                    break

                # Get pending contacts for this lead
                pending_contacts = LeadContact.query.filter_by(
                    lead_id=lead.id,
                    email_status='pending'
                ).filter(
                    LeadContact.email.isnot(None)
                ).all()

                total_contacts = LeadContact.query.filter_by(lead_id=lead.id).count()
                if total_contacts > 0 and not pending_contacts:
                    logger.debug(f"Lead '{lead.company_name}': {total_contacts} contacts but none pending")
                elif total_contacts == 0:
                    logger.debug(f"Lead '{lead.company_name}': No contacts found during enrichment")

                # If no contacts, fall back to legacy decision_maker_email
                if not pending_contacts and lead.email_status == 'pending' and lead.decision_maker_email:
                    # Send using legacy method (use the sequence we ensured exists)
                    try:

                        # Prepare email content
                        subject = self._replace_variables(email_sequence.subject, lead, campaign)
                        body = self._replace_variables(email_sequence.body_text, lead, campaign)

                        # Send email
                        result = self.outreach.send_email(
                            to_email=lead.decision_maker_email,
                            subject=subject,
                            body_html=body.replace('\n', '<br>'),
                            body_text=body
                        )

                        # Check for rate limiting
                        if result.get('rate_limited'):
                            retry_after = result.get('retry_after', 300)
                            logger.warning(f"Mailgun rate limit hit. Stopping email sending. Retry after {retry_after} seconds ({retry_after/3600:.1f} hours)")
                            return sent_count

                        if result.get('success'):
                            # Record email sent
                            email_record = LeadEmail(
                                lead_id=lead.id,
                                campaign_id=campaign.id,
                                sequence_step=1,
                                subject=subject,
                                body=body,
                                sent_at=datetime.utcnow(),
                                status='sent'
                            )
                            db.session.add(email_record)

                            # Update lead status
                            lead.email_status = 'sent'
                            lead.last_email_sent_at = datetime.utcnow()

                            # Update campaign stats
                            campaign.emails_sent = (campaign.emails_sent or 0) + 1

                            db.session.commit()

                            self.state["emails_sent"] += 1
                            self.state["daily_stats"]["emails"] += 1
                            sent_count += 1

                            logger.info(f"Sent email to {lead.decision_maker_email} (legacy)")

                    except Exception as e:
                        logger.error(f"Error sending email to lead {lead.id}: {e}")
                        db.session.rollback()
                    continue

                # Send to each contact
                for contact in pending_contacts:
                    if not self._can_send_email_today():
                        break

                    try:
                        # Prepare email content with contact variables (use the sequence we ensured exists)
                        subject = self._replace_contact_variables(email_sequence.subject, lead, contact, campaign)
                        body = self._replace_contact_variables(email_sequence.body_text, lead, contact, campaign)

                        # Send email
                        result = self.outreach.send_email(
                            to_email=contact.email,
                            subject=subject,
                            body_html=body.replace('\n', '<br>'),
                            body_text=body
                        )

                        # Check for rate limiting
                        if result.get('rate_limited'):
                            retry_after = result.get('retry_after', 300)
                            logger.warning(f"Mailgun rate limit hit. Stopping email sending. Retry after {retry_after} seconds ({retry_after/3600:.1f} hours)")
                            return sent_count

                        if result.get('success'):
                            # Record email sent to contact
                            email_record = LeadContactEmail(
                                contact_id=contact.id,
                                lead_id=lead.id,
                                campaign_id=campaign.id,
                                sequence_step=1,
                                subject=subject,
                                body=body,
                                to_email=contact.email,
                                email_provider=email_provider,
                                sent_at=datetime.utcnow(),
                                status='sent'
                            )

                            # Store provider-specific message ID
                            if email_provider == 'brevo' and result.get('message_id'):
                                email_record.brevo_message_id = result.get('message_id')
                            elif result.get('message_id'):
                                email_record.mailgun_message_id = result.get('message_id')

                            db.session.add(email_record)

                            # Update contact status
                            contact.email_status = 'sent'
                            contact.last_email_sent_at = datetime.utcnow()

                            # Update lead status if this was the first/primary contact
                            if contact.is_primary:
                                lead.email_status = 'sent'
                                lead.last_email_sent_at = datetime.utcnow()

                            # Update campaign stats
                            campaign.emails_sent = (campaign.emails_sent or 0) + 1

                            db.session.commit()

                            self.state["emails_sent"] += 1
                            self.state["daily_stats"]["emails"] += 1
                            sent_count += 1

                            logger.info(f"Sent email to {contact.email} ({contact.name} - {contact.title})")

                    except Exception as e:
                        logger.error(f"Error sending email to contact {contact.id}: {e}")
                        db.session.rollback()

        return sent_count

    def _replace_variables(self, text: str, lead: Lead, campaign: LeadCampaign) -> str:
        """Replace template variables in email text"""
        if not text:
            return ""

        replacements = {
            '{{company_name}}': lead.company_name or '',
            '{{decision_maker_name}}': lead.decision_maker_name or '',
            '{{decision_maker_title}}': lead.decision_maker_title or '',
            '{{service_type}}': campaign.industry_service or '',
            '{{location}}': campaign.location or '',
        }

        result = text
        for var, value in replacements.items():
            result = result.replace(var, value)

        return result

    def _replace_contact_variables(self, text: str, lead: Lead, contact: LeadContact, campaign: LeadCampaign) -> str:
        """Replace template variables in email text with contact-specific info"""
        if not text:
            return ""

        replacements = {
            '{{company_name}}': lead.company_name or '',
            '{{decision_maker_name}}': contact.name or '',
            '{{decision_maker_title}}': contact.title or '',
            '{{service_type}}': campaign.industry_service or '',
            '{{location}}': campaign.location or '',
        }

        result = text
        for var, value in replacements.items():
            result = result.replace(var, value)

        return result

    def get_progress_report(self) -> Dict:
        """Get current automation progress"""
        campaign_queue = get_campaign_queue()
        total_campaigns = len(campaign_queue)

        # Calculate actual stats from database instead of state file
        # This ensures we always show current real data
        total_leads_enriched = db.session.query(func.count(Lead.id)).filter(
            Lead.enrichment_status == 'completed'
        ).scalar() or 0

        # Count emails from both legacy (LeadEmail) and new (LeadContactEmail) tables
        total_legacy_emails = db.session.query(func.count(LeadEmail.id)).scalar() or 0
        total_contact_emails = db.session.query(func.count(LeadContactEmail.id)).scalar() or 0
        total_emails_sent = total_legacy_emails + total_contact_emails

        # Get campaigns created count from database
        campaigns_created_count = LeadCampaign.query.count()

        # Calculate today's stats from database
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        today_scrapes = db.session.query(func.count(Lead.id)).filter(
            Lead.created_at >= today_start
        ).scalar() or 0

        today_enrichments = db.session.query(func.count(Lead.id)).filter(
            Lead.enriched_at >= today_start
        ).scalar() or 0

        today_legacy_emails = db.session.query(func.count(LeadEmail.id)).filter(
            LeadEmail.sent_at >= today_start
        ).scalar() or 0

        today_contact_emails = db.session.query(func.count(LeadContactEmail.id)).filter(
            LeadContactEmail.sent_at >= today_start
        ).scalar() or 0

        today_emails = today_legacy_emails + today_contact_emails

        return {
            "total_campaigns_planned": total_campaigns,
            "campaigns_created": campaigns_created_count,
            "campaigns_scraped": self.state["campaigns_scraped"],
            "current_index": self.state["current_campaign_index"],
            "progress_percent": (self.state["current_campaign_index"] / total_campaigns * 100) if total_campaigns > 0 else 0,
            "leads_enriched": total_leads_enriched,
            "emails_sent": total_emails_sent,
            "unique_domains_processed": len(self.state["processed_domains"]),
            "last_run": self.state["last_run"],
            "daily_stats": {
                "date": datetime.now().date().isoformat(),
                "scrapes": today_scrapes,
                "enrichments": today_enrichments,
                "emails": today_emails
            }
        }
