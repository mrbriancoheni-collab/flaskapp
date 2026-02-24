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
from app.models import CompanyContact, CRMContact
from app.configs.lead_automation_config import (
    get_campaign_queue,
    AUTOMATION_CONFIG,
    HOME_SERVICE_CATEGORIES
)
from app.services.serpapi_scraper import SerpAPIScraperService
from app.services.lead_enrichment import LeadEnrichmentService
from app.services.domain_crawler import DomainCrawler
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
        # Cached Brevo-side sent count for today, fetched once per service instance
        self._brevo_today_count: Optional[int] = None

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
        """Check if we can send more emails today."""
        return self._remaining_emails_today() > 0

    def _remaining_emails_today(self) -> int:
        """
        Return how many lead-outreach emails remain in today's budget.

        The local DB count (LeadEmail + LeadContactEmail rows with sent_at today)
        is the authoritative source for the lead-specific daily limit.  Brevo's
        aggregated report covers ALL emails sent through the account (transactional,
        marketing, etc.) so it cannot be used directly as the lead-outreach limit.

        The Brevo count is fetched once per run for diagnostic logging only — it
        helps surface dropped sends (local > brevo) but does not gate the limit.
        """
        today = datetime.utcnow()
        daily_limit = AUTOMATION_CONFIG["daily_email_limit"]

        # Check if today is a skip day (e.g. Sunday)
        if today.weekday() in AUTOMATION_CONFIG["skip_email_days"]:
            logger.info(f"Skipping emails - today is a skip day (weekday {today.weekday()})")
            return 0

        today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)

        # --- Local DB count — authoritative for lead-outreach limit ---
        today_legacy_emails = db.session.query(func.count(LeadEmail.id)).filter(
            LeadEmail.sent_at >= today_start
        ).scalar() or 0

        today_contact_emails = db.session.query(func.count(LeadContactEmail.id)).filter(
            LeadContactEmail.sent_at >= today_start
        ).scalar() or 0

        local_count = today_legacy_emails + today_contact_emails

        # --- Brevo total (informational only — includes non-lead emails) ---
        if self._brevo_today_count is None:
            try:
                brevo_svc = self.outreach or BrevoOutreachService()
                self._brevo_today_count = brevo_svc.get_today_sent_count()
            except Exception as e:
                logger.warning(f"Could not fetch Brevo today count: {e}")
                self._brevo_today_count = -1

        if self._brevo_today_count >= 0:
            if local_count > self._brevo_today_count:
                # We recorded more sends than Brevo accepted — possible data loss
                logger.warning(
                    f"Possible dropped sends — local DB: {local_count}, "
                    f"Brevo total: {self._brevo_today_count} (all email types). "
                    f"Some lead emails may not have reached Brevo."
                )
            else:
                logger.info(
                    f"Lead outreach sent today (local DB): {local_count} | "
                    f"Brevo account total (all types): {self._brevo_today_count}"
                )

        remaining = daily_limit - local_count
        logger.info(f"Daily email budget: {local_count}/{daily_limit} used, {remaining} remaining")
        return max(remaining, 0)

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

    def run_scraping(self) -> Dict:
        """
        Run scraping ONLY (independent operation).
        Can be triggered on-demand or via cron.

        Returns dict with scraping results.
        """
        logger.info("=" * 80)
        logger.info("STARTING LEAD SCRAPING")
        logger.info("=" * 80)

        self._reset_daily_stats_if_new_day()
        scraped = self._process_campaign_scraping()
        self._save_state()

        logger.info("=" * 80)
        logger.info(f"SCRAPING COMPLETE: {scraped} campaigns scraped")
        logger.info("=" * 80)

        return {
            "scraped": scraped,
            "total_campaigns": self.state['campaigns_created']
        }

    def run_enrichment(self) -> Dict:
        """
        Run enrichment ONLY (independent operation).
        Can be triggered on-demand or via cron.

        Returns dict with enrichment results.
        """
        logger.info("=" * 80)
        logger.info("STARTING LEAD ENRICHMENT")
        logger.info("=" * 80)

        self._reset_daily_stats_if_new_day()
        enriched = self._process_lead_enrichment()
        self._save_state()

        logger.info("=" * 80)
        logger.info(f"ENRICHMENT COMPLETE: {enriched} leads enriched")
        logger.info("=" * 80)

        return {
            "enriched": enriched,
            "total_enriched": self.state['leads_enriched']
        }

    def run_email_outreach(self) -> Dict:
        """
        Run email outreach ONLY (independent operation).
        Can be triggered on-demand or via cron.

        Returns dict with email results.
        """
        logger.info("=" * 80)
        logger.info("STARTING EMAIL OUTREACH")
        logger.info("=" * 80)

        self._reset_daily_stats_if_new_day()
        sent = self._process_email_sending()
        self._save_state()

        logger.info("=" * 80)
        logger.info(f"EMAIL OUTREACH COMPLETE: {sent} emails sent")
        logger.info("=" * 80)

        return {
            "sent": sent,
            "total_emails": self.state['emails_sent']
        }

    def run_daily_automation(self):
        """
        Run ALL operations in sequence (scrape → enrich → email).
        This is for backwards compatibility and scheduled automation.

        For independent operations, use:
        - run_scraping()
        - run_enrichment()
        - run_email_outreach()
        """
        logger.info("=" * 80)
        logger.info("STARTING DAILY LEAD AUTOMATION (ALL OPERATIONS)")
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

        Each campaign scrapes one keyword across all 100 cities
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
                        industry_service=campaign_config["business_type"],
                        location="USA - Top 100 Cities",  # Multi-city campaign
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

                # Track leads found (for deduplication within campaign)
                campaign_leads = {}  # {domain: lead_object}
                total_leads_created = 0

                # Get the keyword for this business type
                keyword = campaign_config["keyword"]
                cities = campaign_config["cities"]

                logger.info(f"Scraping '{keyword}' across {len(cities)} cities")

                # Loop through all cities for this keyword
                for city in cities:
                    # Scrape leads for this city
                    query = f"{keyword} {city}"

                    try:
                        results = self.scraper.scrape_campaign(
                            query=query,
                            location=city,
                            scrape_ads=campaign.scrape_ads,
                            scrape_maps=campaign.scrape_maps,
                            scrape_lsa=campaign.scrape_lsa,
                            scrape_organic=campaign.scrape_organic,
                            max_organic=campaign.max_organic_results
                        )

                        city_leads_count = 0

                        # Process leads from this city
                        for source_type, items in results.items():
                            for item in items:
                                domain = item.get('website')

                                # Skip if duplicate domain globally
                                if self._is_duplicate_domain(domain):
                                    logger.debug(f"Skipping duplicate domain globally: {domain}")
                                    continue

                                # Clean domain for comparison
                                domain_clean = domain.lower().replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0] if domain else None

                                # Check if this lead already exists in this campaign (from another city)
                                if domain_clean and domain_clean in campaign_leads:
                                    # Add this city to the existing lead's cities list
                                    existing_lead = campaign_leads[domain_clean]
                                    if 'cities' not in existing_lead.extra_data:
                                        existing_lead.extra_data['cities'] = []
                                    if city not in existing_lead.extra_data['cities']:
                                        existing_lead.extra_data['cities'].append(city)
                                    logger.debug(f"Lead {item['company_name']} also found in: {city}")
                                    continue

                                # Check if lead already exists in database
                                existing_lead = Lead.query.filter_by(
                                    campaign_id=campaign.id,
                                    company_name=item['company_name']
                                ).first()

                                if existing_lead:
                                    # Update existing lead with new city
                                    if 'cities' not in existing_lead.extra_data:
                                        existing_lead.extra_data['cities'] = []
                                    if city not in existing_lead.extra_data['cities']:
                                        existing_lead.extra_data['cities'].append(city)
                                    campaign_leads[domain_clean] = existing_lead
                                    continue

                                # Create new lead
                                extra_data = item.get('extra_data', {})
                                extra_data['cities'] = [city]  # Track which city/cities found this lead
                                extra_data['keyword'] = keyword  # Track the keyword used

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
                                city_leads_count += 1

                                # Track in campaign_leads for deduplication
                                if domain_clean:
                                    campaign_leads[domain_clean] = lead

                                # Mark domain as processed globally
                                self._mark_domain_processed(domain)

                        logger.info(f"  - City '{city}': found {city_leads_count} new leads")

                    except Exception as e:
                        logger.error(f"Error scraping '{keyword}' in {city}: {e}")
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

                logger.info(f"Scraped campaign {campaign.name}: {total_leads_created} unique leads across {len(cities)} cities")

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

        # Fall back to global sequence (campaign_id IS NULL) before creating a new one
        global_sequence = EmailSequence.query.filter_by(
            campaign_id=None,
            step_number=1
        ).first()
        if global_sequence:
            logger.info(f"Using global sequence (id={global_sequence.id}) for campaign '{campaign.name}'")
            return global_sequence

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
            name="Auto Campaign",  # Standardized name for all campaigns
            subject=default_subject,
            body_text=default_body,
            body_html=default_body.replace('\n', '<br>'),
            delay_days=0,
            is_active=True
        )

        db.session.add(sequence)
        db.session.commit()

        logger.info(f"Created 'Auto Campaign' email sequence for campaign '{campaign.name}'")
        return sequence

    def _process_email_sending(self) -> int:
        """Send emails to all pending contacts/leads up to the daily limit.

        Contact-first approach: iterates over every pending LeadContact (and
        leads with a decision_maker_email fallback) across ALL campaigns,
        regardless of campaign status.  Campaign objects are only used to
        look up the email sequence to send.
        """
        # Reset Brevo cache so we get a fresh count from the API at the start
        # of each top-level send run.
        self._brevo_today_count = None

        if not self._can_send_email_today():
            return 0

        sent_count = 0

        try:
            logger.info("Using Brevo email service")
            self.outreach = BrevoOutreachService()
        except Exception as e:
            logger.error(f"Cannot initialize Brevo outreach service: {e}")
            return 0

        from app.models_leads import EmailUnsubscribe
        unsubscribed_emails = set(
            row[0].lower()
            for row in db.session.query(EmailUnsubscribe.email).all()
        )

        # Cache sequences per campaign (keyed by campaign.id or None).
        # Falls back to the primary sequence (id=1) if no campaign-specific one exists.
        sequence_cache: Dict = {}
        _primary_seq: list = [None]  # lazy singleton

        def _primary_sequence():
            if _primary_seq[0] is None:
                _primary_seq[0] = EmailSequence.query.get(1)
            return _primary_seq[0]

        def _get_sequence(campaign):
            cid = campaign.id if campaign else None
            if cid not in sequence_cache:
                seq = EmailSequence.query.filter_by(
                    campaign_id=cid, step_number=1, is_active=True
                ).first() if cid else None
                sequence_cache[cid] = seq or _primary_sequence()
            return sequence_cache[cid]

        # ── Primary path: LeadContact records with pending status ─────────────
        pending_contacts = (
            LeadContact.query
            .filter(
                LeadContact.email_status == 'pending',
                LeadContact.email.isnot(None),
                LeadContact.email != '',
            )
            .all()
        )
        logger.info(f"Found {len(pending_contacts)} pending lead contacts")

        for contact in pending_contacts:
            if not self._can_send_email_today():
                break

            email = contact.email.strip()

            if email.lower() in unsubscribed_emails:
                continue

            lead = Lead.query.get(contact.lead_id)
            if not lead:
                continue

            campaign = LeadCampaign.query.get(lead.campaign_id) if lead.campaign_id else None

            email_sequence = _get_sequence(campaign)
            if not email_sequence:
                logger.warning(f"No sequence available anywhere — skipping contact {contact.id}")
                continue

            # Dedup: skip if already sent this step to this address
            already_sent = LeadContactEmail.query.filter_by(
                contact_id=contact.id,
                sequence_step=email_sequence.step_number,
                to_email=email,
            ).first()
            if already_sent:
                continue

            try:
                subject = self._replace_contact_variables(email_sequence.subject, lead, contact, campaign)
                body = self._replace_contact_variables(email_sequence.body_text, lead, contact, campaign)

                result = self.outreach.send_email(
                    to_email=email,
                    subject=subject,
                    body_html=body.replace('\n', '<br>'),
                    body_text=body,
                    sequence_step=email_sequence.step_number,
                    unsubscribe_url=self.outreach.get_unsubscribe_url(email, campaign.id),
                )

                if result.get('skipped'):
                    continue

                if result.get('rate_limited'):
                    logger.warning(f"Rate limit hit after {sent_count} emails")
                    return sent_count

                if result.get('success'):
                    record = LeadContactEmail(
                        contact_id=contact.id,
                        lead_id=lead.id,
                        campaign_id=campaign.id if campaign else None,
                        sequence_step=email_sequence.step_number,
                        subject=subject,
                        body=body,
                        to_email=email,
                        email_provider='brevo',
                        sent_at=datetime.utcnow(),
                        status='sent',
                    )
                    if result.get('message_id'):
                        record.brevo_message_id = result['message_id']
                    db.session.add(record)

                    contact.email_status = 'sent'
                    contact.last_email_sent_at = datetime.utcnow()
                    if contact.is_primary:
                        lead.email_status = 'sent'
                        lead.last_email_sent_at = datetime.utcnow()
                    if campaign:
                        campaign.emails_sent = (campaign.emails_sent or 0) + 1

                    db.session.commit()
                    self.state["emails_sent"] += 1
                    self.state["daily_stats"]["emails"] += 1
                    sent_count += 1
                    logger.info(f"Sent to {email} ({contact.name})")

            except Exception as e:
                logger.error(f"Error sending to contact {contact.id}: {e}")
                db.session.rollback()

        # ── Legacy path: leads with decision_maker_email, no lead_contacts ────
        pending_leads = (
            Lead.query
            .filter(
                Lead.email_status == 'pending',
                Lead.enrichment_status == 'completed',
                Lead.decision_maker_email.isnot(None),
            )
            .outerjoin(LeadContact, LeadContact.lead_id == Lead.id)
            .filter(LeadContact.id.is_(None))  # only leads with no contacts at all
            .all()
        )
        logger.info(f"Found {len(pending_leads)} pending leads (legacy path)")

        for lead in pending_leads:
            if not self._can_send_email_today():
                break

            email = lead.decision_maker_email.strip()

            if email.lower() in unsubscribed_emails:
                continue

            campaign = LeadCampaign.query.get(lead.campaign_id) if lead.campaign_id else None

            email_sequence = _get_sequence(campaign)
            if not email_sequence:
                continue

            already_sent = LeadEmail.query.filter_by(
                lead_id=lead.id,
                sequence_id=email_sequence.id,
                to_email=email,
            ).first()
            if already_sent:
                continue

            try:
                subject = self._replace_variables(email_sequence.subject, lead, campaign)
                body = self._replace_variables(email_sequence.body_text, lead, campaign)

                result = self.outreach.send_email(
                    to_email=email,
                    subject=subject,
                    body_html=body.replace('\n', '<br>'),
                    body_text=body,
                    sequence_step=1,
                    unsubscribe_url=self.outreach.get_unsubscribe_url(email, campaign.id),
                )

                if result.get('skipped'):
                    continue

                if result.get('rate_limited'):
                    logger.warning(f"Rate limit hit after {sent_count} emails")
                    return sent_count

                if result.get('success'):
                    record = LeadEmail(
                        lead_id=lead.id,
                        sequence_id=email_sequence.id,
                        to_email=email,
                        subject=subject,
                        body_text=body,
                        body_html=body.replace('\n', '<br>'),
                        sent_at=datetime.utcnow(),
                        status='sent',
                    )
                    db.session.add(record)

                    lead.email_status = 'sent'
                    lead.last_email_sent_at = datetime.utcnow()
                    if campaign:
                        campaign.emails_sent = (campaign.emails_sent or 0) + 1

                    db.session.commit()
                    self.state["emails_sent"] += 1
                    self.state["daily_stats"]["emails"] += 1
                    sent_count += 1
                    logger.info(f"Sent to {email} (legacy)")

            except Exception as e:
                logger.error(f"Error sending to lead {lead.id}: {e}")
                db.session.rollback()

        return sent_count

    def send_to_all_unsent_ever(self, sequence_step: int = 1) -> Dict:
        """
        Send emails to ALL contacts who haven't received THIS sequence step yet.

        This method:
        1. Finds all enriched contacts across all campaigns
        2. Checks if they've received THIS SPECIFIC sequence step
        3. Checks if they're unsubscribed
        4. Sends to those who haven't received this step and are not unsubscribed (up to daily limit)

        Args:
            sequence_step: Which sequence step to send (default: 1 for initial outreach)

        Returns: Dict with sent count and details

        Note: This allows sending multiple emails to same contact (different sequence steps),
        but prevents sending the same email twice (same sequence step).
        """
        logger.info("=" * 80)
        logger.info(f"SENDING SEQUENCE STEP {sequence_step} TO ALL WHO HAVEN'T RECEIVED IT")
        logger.info("=" * 80)

        self._brevo_today_count = None  # Refresh Brevo count at start of each run
        self._reset_daily_stats_if_new_day()

        if not self._can_send_email_today():
            logger.info("Daily email limit already reached")
            return {"sent": 0, "reason": "daily_limit_reached"}

        sent_count = 0
        skipped_unsubscribed = 0
        skipped_already_emailed = 0

        # Initialize Brevo outreach service
        try:
            self.outreach = BrevoOutreachService()
        except Exception as e:
            logger.error(f"Cannot initialize Brevo outreach service: {e}")
            return {"sent": 0, "error": str(e)}

        # Import unsubscribe model
        from app.models_leads import EmailUnsubscribe

        # Get all unsubscribed emails
        unsubscribed_emails = set(
            email[0].lower() for email in db.session.query(EmailUnsubscribe.email).all()
        )
        logger.info(f"Found {len(unsubscribed_emails)} unsubscribed email addresses")

        # Query LeadContact directly — works regardless of CRM sync status.
        # (The old CompanyContact path required company_contact_id to be set,
        # which silently excluded all contacts not yet synced to the CRM.)
        all_lead_contacts = LeadContact.query.filter(
            LeadContact.email.isnot(None),
            LeadContact.email != ''
        ).all()

        logger.info(f"Found {len(all_lead_contacts)} total lead contacts with emails")

        # Filter out unsubscribed and already-emailed contacts
        contacts_to_email = []
        for lead_contact in all_lead_contacts:
            email = lead_contact.email.strip()

            if email.lower() in unsubscribed_emails:
                skipped_unsubscribed += 1
                logger.debug(f"Skipping {email} - unsubscribed")
                continue

            # Check if this address already received THIS SPECIFIC sequence step
            received_this_step = db.session.query(LeadContactEmail).filter(
                LeadContactEmail.to_email == email,
                LeadContactEmail.sequence_step == sequence_step
            ).first()

            # Also treat any legacy LeadEmail send as step 1
            if not received_this_step and sequence_step == 1:
                received_this_step = db.session.query(LeadEmail).filter(
                    LeadEmail.to_email == email
                ).first()

            if received_this_step:
                skipped_already_emailed += 1
                logger.debug(f"Skipping {email} - already received sequence step {sequence_step}")
            else:
                contacts_to_email.append(lead_contact)

        logger.info(f"Found {len(contacts_to_email)} contacts who haven't received sequence step {sequence_step}")
        logger.info(f"Skipped {skipped_unsubscribed} unsubscribed, {skipped_already_emailed} already emailed")

        # Send to each contact
        for lead_contact in contacts_to_email:
            if not self._can_send_email_today():
                logger.info(f"Daily email limit reached after sending {sent_count} emails")
                break

            try:
                email = lead_contact.email.strip()

                lead = Lead.query.get(lead_contact.lead_id)
                if not lead:
                    continue

                campaign = LeadCampaign.query.get(lead.campaign_id)
                if not campaign:
                    continue

                # Get the email sequence for this step
                email_sequence = EmailSequence.query.filter_by(
                    campaign_id=campaign.id,
                    step_number=sequence_step
                ).first()

                if not email_sequence:
                    if sequence_step == 1:
                        email_sequence = self._ensure_campaign_has_sequence(campaign)
                    if not email_sequence:
                        logger.warning(f"No sequence step {sequence_step} for campaign '{campaign.name}'")
                        continue

                subject = self._replace_contact_variables(email_sequence.subject, lead, lead_contact, campaign)
                body = self._replace_contact_variables(email_sequence.body_text, lead, lead_contact, campaign)

                result = self.outreach.send_email(
                    to_email=email,
                    subject=subject,
                    body_html=body.replace('\n', '<br>'),
                    body_text=body,
                    sequence_step=sequence_step,
                    unsubscribe_url=self.outreach.get_unsubscribe_url(email, campaign.id),
                )

                if result.get('skipped'):
                    logger.debug(f"Dedup blocked email to {email}: {result.get('skip_reason')}")
                    continue

                if result.get('rate_limited'):
                    retry_after = result.get('retry_after', 300)
                    logger.warning(f"Email rate limit hit. Stopping. Retry after {retry_after} seconds")
                    break

                if result.get('success'):
                    email_record = LeadContactEmail(
                        contact_id=lead_contact.id,
                        lead_id=lead.id,
                        campaign_id=campaign.id,
                        sequence_step=email_sequence.step_number,
                        to_email=email,
                        subject=subject,
                        body=body,
                        email_provider='brevo',
                        brevo_message_id=result.get('message_id'),
                        sent_at=datetime.utcnow(),
                        status='sent'
                    )
                    db.session.add(email_record)

                    lead_contact.email_status = 'sent'
                    lead_contact.last_email_sent_at = datetime.utcnow()
                    campaign.emails_sent = (campaign.emails_sent or 0) + 1

                    db.session.commit()

                    self.state["emails_sent"] += 1
                    self.state["daily_stats"]["emails"] += 1
                    sent_count += 1

                    logger.info(f"✓ Sent to {email} ({lead_contact.name} at {lead.company_name})")

            except Exception as e:
                logger.error(f"Error sending email to lead_contact {lead_contact.id}: {e}")
                db.session.rollback()

        self._save_state()

        logger.info("=" * 80)
        logger.info(f"COMPLETE: Sent {sent_count} emails (sequence step {sequence_step})")
        logger.info(f"Total contacts checked: {len(all_lead_contacts)}, Eligible: {len(contacts_to_email)}")
        logger.info(f"Skipped - Unsubscribed: {skipped_unsubscribed}, Already got this step: {skipped_already_emailed}")
        logger.info("=" * 80)

        return {
            "sent": sent_count,
            "sequence_step": sequence_step,
            "total_contacts_checked": len(all_lead_contacts),
            "eligible_contacts": len(contacts_to_email),
            "skipped_unsubscribed": skipped_unsubscribed,
            "skipped_already_received_step": skipped_already_emailed
        }

    def send_next_sequence_steps(self) -> Dict:
        """
        Smart delay-based email sequencing system.

        For each contact:
        1. Find which sequence steps they've already received
        2. Determine the next step in their campaign's sequence
        3. Check if enough delay_days have passed since last email
        4. Send the next step if eligible

        This automatically progresses contacts through multi-step sequences
        (e.g., step 1 → wait 3 days → step 2 → wait 5 days → step 3, etc.)

        IMPORTANT: This queries LeadContact directly (not via CompanyContact/CRM)
        to ensure all contacts with emails are processed, regardless of CRM sync status.

        Returns: Dict with sent count, steps processed, and details
        """
        from datetime import datetime, timedelta
        from app.models_leads import EmailUnsubscribe, EmailSequence

        logger.info("=" * 80)
        logger.info("SMART SEQUENCE PROGRESSION - SENDING NEXT STEPS")
        logger.info("=" * 80)

        self._brevo_today_count = None  # Refresh Brevo count at start of each run
        self._reset_daily_stats_if_new_day()

        if not self._can_send_email_today():
            logger.info("Daily email limit already reached")
            return {"sent": 0, "reason": "daily_limit_reached"}

        sent_count = 0
        skipped_unsubscribed = 0
        skipped_not_ready = 0
        skipped_complete = 0
        skipped_no_sequence = 0

        # Initialize Brevo outreach service
        try:
            self.outreach = BrevoOutreachService()
        except Exception as e:
            logger.error(f"Cannot initialize Brevo outreach service: {e}")
            return {"sent": 0, "error": str(e)}

        # Get all unsubscribed emails
        unsubscribed_emails = set(
            email[0].lower() for email in db.session.query(EmailUnsubscribe.email).all()
        )
        logger.info(f"Found {len(unsubscribed_emails)} unsubscribed email addresses")

        # Query LeadContact directly - this catches ALL contacts with emails
        # regardless of whether they're synced to CRM (CompanyContact)
        all_lead_contacts = (
            LeadContact.query
            .filter(
                LeadContact.email.isnot(None),
                LeadContact.email != '',
            )
            .all()
        )

        logger.info(f"Found {len(all_lead_contacts)} LeadContacts with emails to check")

        # Group contacts by campaign for efficient sequence lookups
        contacts_by_campaign = {}
        for lead_contact in all_lead_contacts:
            if not lead_contact.lead:
                continue
            campaign_id = lead_contact.lead.campaign_id
            if campaign_id not in contacts_by_campaign:
                contacts_by_campaign[campaign_id] = []
            contacts_by_campaign[campaign_id].append(lead_contact)

        logger.info(f"Grouped contacts into {len(contacts_by_campaign)} campaigns")

        # Process each campaign
        daily_limit = AUTOMATION_CONFIG["daily_email_limit"]
        for campaign_id, contacts in contacts_by_campaign.items():
            if sent_count >= daily_limit:
                logger.info(f"Reached daily limit of {daily_limit} emails")
                break

            # Get all sequence steps for this campaign, ordered by step_number
            sequences = EmailSequence.query.filter_by(
                campaign_id=campaign_id,
                is_active=True
            ).order_by(EmailSequence.step_number).all()

            if not sequences:
                # Try to create a default sequence for this campaign
                campaign = LeadCampaign.query.get(campaign_id)
                if campaign:
                    first_seq = self._ensure_campaign_has_sequence(campaign)
                    if first_seq:
                        sequences = [first_seq]

            if not sequences:
                skipped_no_sequence += len(contacts)
                logger.debug(f"Campaign {campaign_id} has no active sequences, skipping {len(contacts)} contacts")
                continue

            logger.info(f"Campaign {campaign_id}: {len(sequences)} active sequence steps, {len(contacts)} contacts")

            # Process each LeadContact in this campaign
            for lead_contact in contacts:
                if sent_count >= daily_limit:
                    break

                email = lead_contact.email
                if not email:
                    continue

                # Skip unsubscribed
                if email.lower() in unsubscribed_emails:
                    skipped_unsubscribed += 1
                    continue

                # Find which steps this contact has already received (by email address)
                received_steps = db.session.query(LeadContactEmail.sequence_step).filter(
                    LeadContactEmail.to_email == email
                ).all()
                received_step_numbers = set(step[0] for step in received_steps if step[0] is not None)

                # Also check legacy emails (treat as step 1)
                legacy_email = db.session.query(LeadEmail).filter(
                    LeadEmail.to_email == email
                ).first()
                if legacy_email:
                    received_step_numbers.add(1)

                # Find the next step this contact needs
                next_step = None
                for seq in sequences:
                    if seq.step_number not in received_step_numbers:
                        next_step = seq
                        break

                if not next_step:
                    # Contact has received all steps
                    skipped_complete += 1
                    logger.debug(f"{email} has completed all {len(sequences)} sequence steps")
                    continue

                # Check if enough time has passed since last email
                last_email = db.session.query(LeadContactEmail).filter(
                    LeadContactEmail.to_email == email
                ).order_by(LeadContactEmail.sent_at.desc()).first()

                # Get campaign's default delay if sequence delay is not set
                campaign = lead_contact.lead.campaign
                default_delay = campaign.sequence_delay_days or 3

                if not last_email and next_step.step_number == 1:
                    # First email, send immediately
                    ready_to_send = True
                elif last_email and (next_step.delay_days or default_delay) > 0:
                    # Check if delay_days have passed
                    delay_days = next_step.delay_days if next_step.delay_days is not None else default_delay
                    days_since_last = (datetime.utcnow() - last_email.sent_at).days
                    ready_to_send = days_since_last >= delay_days
                    if not ready_to_send:
                        logger.debug(
                            f"{email}: Next step {next_step.step_number} requires "
                            f"{delay_days} days delay, only {days_since_last} days passed"
                        )
                elif not last_email and next_step.step_number > 1:
                    # Contact hasn't received step 1, but next_step is not step 1
                    # This shouldn't happen in normal flow, skip
                    ready_to_send = False
                else:
                    # No delay required or delay is 0
                    ready_to_send = True

                if not ready_to_send:
                    skipped_not_ready += 1
                    continue

                # Send the next step!
                try:
                    logger.info(
                        f"Sending step {next_step.step_number} to {email} "
                        f"(campaign: {campaign_id}, delay: {next_step.delay_days} days)"
                    )

                    success = self._send_campaign_email(
                        contact=lead_contact,
                        campaign=campaign,
                        sequence=next_step
                    )

                    if success:
                        sent_count += 1
                        self.state["emails_sent"] += 1
                        self.state["daily_stats"]["emails"] += 1

                        if sent_count >= daily_limit:
                            logger.info(f"Reached daily limit of {daily_limit} emails")
                            break

                except Exception as e:
                    logger.error(f"Error sending step {next_step.step_number} to {email}: {e}")

        self._save_state()

        logger.info("=" * 80)
        logger.info(f"SMART SEQUENCE COMPLETE:")
        logger.info(f"  - Emails sent: {sent_count}")
        logger.info(f"  - Total LeadContacts checked: {len(all_lead_contacts)}")
        logger.info(f"  - Skipped (unsubscribed): {skipped_unsubscribed}")
        logger.info(f"  - Skipped (not ready/delay pending): {skipped_not_ready}")
        logger.info(f"  - Skipped (completed all steps): {skipped_complete}")
        logger.info(f"  - Skipped (no sequence): {skipped_no_sequence}")
        logger.info("=" * 80)

        return {
            "sent": sent_count,
            "total_contacts_checked": len(all_lead_contacts),
            "skipped_unsubscribed": skipped_unsubscribed,
            "skipped_not_ready": skipped_not_ready,
            "skipped_complete": skipped_complete,
            "skipped_no_sequence": skipped_no_sequence,
        }

    def _send_campaign_email(self, contact: LeadContact, campaign: LeadCampaign, sequence: EmailSequence) -> bool:
        """
        Send a campaign email to a contact.

        Args:
            contact: The LeadContact to send to
            campaign: The LeadCampaign this belongs to
            sequence: The EmailSequence step to send

        Returns:
            True if email was sent successfully, False otherwise
        """
        try:
            lead = contact.lead

            # Initialize outreach service if needed
            if not self.outreach:
                self.outreach = BrevoOutreachService()

            # Prepare email content using contact-specific variables
            subject = self._replace_contact_variables(sequence.subject, lead, contact, campaign)
            body = self._replace_contact_variables(sequence.body_text, lead, contact, campaign)

            # Send email (with dedup check)
            result = self.outreach.send_email(
                to_email=contact.email,
                subject=subject,
                body_html=body.replace('\n', '<br>'),
                body_text=body,
                sequence_step=sequence.step_number,
                unsubscribe_url=self.outreach.get_unsubscribe_url(contact.email, campaign.id),
            )

            # Skip if dedup check blocked the send
            if result.get('skipped'):
                logger.debug(f"Dedup blocked email to {contact.email}: {result.get('skip_reason')}")
                return False

            # Check for rate limiting
            if result.get('rate_limited'):
                retry_after = result.get('retry_after', 300)
                logger.warning(f"Email rate limit hit. Retry after {retry_after} seconds")
                return False

            if result.get('success'):
                # Record email sent to contact using correct LeadContactEmail fields
                email_record = LeadContactEmail(
                    contact_id=contact.id,
                    lead_id=lead.id,
                    campaign_id=campaign.id,
                    sequence_step=sequence.step_number,
                    subject=subject,
                    body=body,  # LeadContactEmail uses 'body' not 'body_text'/'body_html'
                    to_email=contact.email,
                    email_provider='brevo',
                    sent_at=datetime.utcnow(),
                    status='sent'
                )

                # Store Brevo message ID if available
                if result.get('message_id'):
                    email_record.brevo_message_id = result.get('message_id')

                db.session.add(email_record)

                # Update contact status
                contact.email_status = 'sent'
                contact.current_sequence_step = sequence.step_number
                contact.last_email_sent_at = datetime.utcnow()

                # Update lead status if primary contact
                if contact.is_primary:
                    lead.email_status = 'sent'
                    lead.current_sequence_step = sequence.step_number
                    lead.last_email_sent_at = datetime.utcnow()

                # Update campaign stats
                campaign.emails_sent = (campaign.emails_sent or 0) + 1

                db.session.commit()

                logger.info(f"Sent sequence step {sequence.step_number} to {contact.email} ({contact.name})")
                return True
            else:
                logger.warning(f"Failed to send email to {contact.email}: {result.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Error sending campaign email to {contact.email}: {e}")
            db.session.rollback()
            return False

    def _replace_variables(self, text: str, lead: Lead, campaign) -> str:
        """Replace template variables in email text"""
        if not text:
            return ""

        replacements = {
            '{{company_name}}': lead.company_name or '',
            '{{decision_maker_name}}': lead.decision_maker_name or '',
            '{{decision_maker_title}}': lead.decision_maker_title or '',
            '{{service_type}}': (campaign.industry_service if campaign else '') or '',
            '{{location}}': (campaign.location if campaign else '') or '',
        }

        result = text
        for var, value in replacements.items():
            result = result.replace(var, value)

        return result

    def _replace_contact_variables(self, text: str, lead: Lead, contact: LeadContact, campaign) -> str:
        """Replace template variables in email text with contact-specific info"""
        if not text:
            return ""

        replacements = {
            '{{company_name}}': lead.company_name or '',
            '{{decision_maker_name}}': contact.name or '',
            '{{decision_maker_title}}': contact.title or '',
            '{{service_type}}': (campaign.industry_service if campaign else '') or '',
            '{{location}}': (campaign.location if campaign else '') or '',
        }

        result = text
        for var, value in replacements.items():
            result = result.replace(var, value)

        return result

    def get_progress_report(self) -> Dict:
        """Get current automation progress"""
        # Calculate actual stats from database instead of state file
        # This ensures we always show current real data

        # Count ALL campaigns in database (consolidation to 100 hasn't been executed yet)
        campaigns_created_count = LeadCampaign.query.count()

        # Use config's planned total for reference, but show actual count
        campaign_queue = get_campaign_queue()
        total_campaigns_planned = len(campaign_queue)

        total_leads_enriched = db.session.query(func.count(Lead.id)).filter(
            Lead.enrichment_status == 'completed'
        ).scalar() or 0

        # Count emails from both legacy (LeadEmail) and new (LeadContactEmail) tables
        total_legacy_emails = db.session.query(func.count(LeadEmail.id)).scalar() or 0
        total_contact_emails = db.session.query(func.count(LeadContactEmail.id)).scalar() or 0
        total_emails_sent = total_legacy_emails + total_contact_emails

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

        local_emails_today = today_legacy_emails + today_contact_emails

        # Fetch Brevo's authoritative count for today
        try:
            brevo_svc = BrevoOutreachService()
            brevo_emails_today = brevo_svc.get_today_sent_count()
        except Exception:
            brevo_emails_today = -1

        daily_limit = AUTOMATION_CONFIG["daily_email_limit"]
        remaining_today = max(daily_limit - local_emails_today, 0)

        return {
            "total_campaigns_planned": total_campaigns_planned,
            "campaigns_created": campaigns_created_count,
            "campaigns_scraped": self.state["campaigns_scraped"],
            "current_index": campaigns_created_count,  # Use actual DB count
            "progress_percent": (campaigns_created_count / campaigns_created_count * 100) if campaigns_created_count > 0 else 0,  # Always 100% if campaigns exist
            "leads_enriched": total_leads_enriched,
            "emails_sent": total_emails_sent,
            "unique_domains_processed": len(self.state["processed_domains"]),
            "last_run": self.state["last_run"],
            "daily_stats": {
                "date": datetime.now().date().isoformat(),
                "scrapes": today_scrapes,
                "enrichments": today_enrichments,
                "emails_lead_outreach": local_emails_today,          # authoritative for daily limit
                "emails_brevo_total": brevo_emails_today,            # all email types; -1 = unavailable
                "emails_remaining": remaining_today,
                "daily_limit": daily_limit,
            },
            # Service configuration status
            "services_configured": {
                "serpapi": bool(os.getenv('SERPAPI_API_KEY')),
                "brevo": bool(os.getenv('BREVO_API_KEY')),
                "hunter": bool(os.getenv('HUNTER_API_KEY')),
            },
            "all_services_ready": all([
                os.getenv('SERPAPI_API_KEY'),
                os.getenv('BREVO_API_KEY'),
            ])
        }
