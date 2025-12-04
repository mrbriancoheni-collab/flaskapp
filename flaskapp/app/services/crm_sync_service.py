# app/services/crm_sync_service.py
"""
CRM Sync Service

Syncs enriched leads from lead generation campaigns into the CRM system:
- Lead (company) → CRMContact (company in CRM)
- LeadContact (person) → CompanyContact (person in CRM)
"""
import logging
from datetime import datetime
from typing import Optional, List, Tuple

from app.extensions import db
from app.models_leads import Lead, LeadContact
from app.models import CRMContact, CompanyContact

logger = logging.getLogger(__name__)


class CRMSyncService:
    """Service to sync lead generation data into CRM"""

    def sync_lead_to_crm(self, lead: Lead, stage: str = "stranger") -> Optional[CRMContact]:
        """
        Convert an enriched lead to a CRM contact (company)

        Args:
            lead: Lead object to sync
            stage: CRM stage (stranger, lead, customer, etc.)

        Returns:
            CRMContact object or None if sync failed
        """
        # Skip if already synced
        if lead.crm_contact_id:
            logger.debug(f"Lead {lead.id} already synced to CRM contact {lead.crm_contact_id}")
            return CRMContact.query.get(lead.crm_contact_id)

        # Skip if not enriched
        if lead.enrichment_status != 'completed':
            logger.debug(f"Lead {lead.id} not yet enriched, skipping CRM sync")
            return None

        try:
            # Extract domain from website
            domain = None
            if lead.website:
                domain = lead.website.lower().replace("http://", "").replace("https://", "").replace("www.", "").split("/")[0]

            # Check if company already exists in CRM by domain
            existing_crm_contact = None
            if domain:
                existing_crm_contact = CRMContact.query.filter_by(domain=domain).first()

            if existing_crm_contact:
                logger.info(f"Found existing CRM contact for domain {domain}: {existing_crm_contact.id}")
                # Link lead to existing CRM contact
                lead.crm_contact_id = existing_crm_contact.id
                db.session.commit()
                return existing_crm_contact

            # Create new CRM contact
            crm_contact = CRMContact(
                business_name=lead.company_name,
                contact_name=lead.decision_maker_name,
                email=lead.decision_maker_email,
                phone=lead.phone,
                domain=domain,
                address1=lead.address,
                stage=stage,
                source=f"Lead Campaign: {lead.campaign.name}",
                notes=f"Scraped from {lead.source_type} at position {lead.serp_position}"
            )

            db.session.add(crm_contact)
            db.session.flush()  # Get the ID

            # Link lead to CRM contact
            lead.crm_contact_id = crm_contact.id
            db.session.commit()

            logger.info(f"Created CRM contact {crm_contact.id} for lead {lead.id} ({lead.company_name})")
            return crm_contact

        except Exception as e:
            logger.error(f"Error syncing lead {lead.id} to CRM: {e}")
            db.session.rollback()
            return None

    def sync_lead_contacts_to_crm(self, lead: Lead) -> List[CompanyContact]:
        """
        Sync all contacts from a lead to CRM as CompanyContact records

        Args:
            lead: Lead object with contacts to sync

        Returns:
            List of CompanyContact objects created/updated
        """
        # Ensure lead is synced to CRM first
        if not lead.crm_contact_id:
            logger.warning(f"Lead {lead.id} not synced to CRM, syncing now...")
            crm_contact = self.sync_lead_to_crm(lead)
            if not crm_contact:
                logger.error(f"Failed to sync lead {lead.id} to CRM")
                return []

        synced_contacts = []

        for lead_contact in lead.contacts:
            try:
                # Skip if already synced
                if lead_contact.company_contact_id:
                    logger.debug(f"LeadContact {lead_contact.id} already synced to CompanyContact {lead_contact.company_contact_id}")
                    company_contact = CompanyContact.query.get(lead_contact.company_contact_id)
                    if company_contact:
                        synced_contacts.append(company_contact)
                    continue

                # Check if contact already exists by email
                existing_company_contact = None
                if lead_contact.email:
                    existing_company_contact = CompanyContact.query.filter_by(
                        crm_contact_id=lead.crm_contact_id,
                        email=lead_contact.email
                    ).first()

                if existing_company_contact:
                    logger.info(f"Found existing CompanyContact for {lead_contact.email}: {existing_company_contact.id}")
                    lead_contact.company_contact_id = existing_company_contact.id
                    db.session.commit()
                    synced_contacts.append(existing_company_contact)
                    continue

                # Create new CompanyContact
                company_contact = CompanyContact(
                    crm_contact_id=lead.crm_contact_id,
                    full_name=lead_contact.name,
                    title=lead_contact.title,
                    email=lead_contact.email,
                    linkedin_url=lead_contact.linkedin_url,
                    role_category=lead_contact.role_category,
                    source=f"Lead enrichment from campaign: {lead.campaign.name}",
                    discovered_at=datetime.utcnow()
                )

                db.session.add(company_contact)
                db.session.flush()

                # Link LeadContact to CompanyContact
                lead_contact.company_contact_id = company_contact.id
                db.session.commit()

                logger.info(f"Created CompanyContact {company_contact.id} for LeadContact {lead_contact.id} ({lead_contact.name})")
                synced_contacts.append(company_contact)

            except Exception as e:
                logger.error(f"Error syncing LeadContact {lead_contact.id} to CRM: {e}")
                db.session.rollback()
                continue

        return synced_contacts

    def sync_enriched_leads_batch(self, limit: int = 100) -> Tuple[int, int]:
        """
        Batch sync enriched leads that haven't been synced to CRM yet

        Args:
            limit: Maximum number of leads to sync in one batch

        Returns:
            Tuple of (companies_synced, contacts_synced)
        """
        # Get enriched leads that aren't synced to CRM yet
        unsynced_leads = Lead.query.filter_by(
            enrichment_status='completed',
            crm_contact_id=None
        ).limit(limit).all()

        companies_synced = 0
        contacts_synced = 0

        logger.info(f"Starting batch sync of {len(unsynced_leads)} enriched leads to CRM")

        for lead in unsynced_leads:
            # Sync lead to CRM contact (company)
            crm_contact = self.sync_lead_to_crm(lead)
            if crm_contact:
                companies_synced += 1

                # Sync all contacts for this lead
                company_contacts = self.sync_lead_contacts_to_crm(lead)
                contacts_synced += len(company_contacts)

        logger.info(f"Batch sync complete: {companies_synced} companies, {contacts_synced} contacts")
        return (companies_synced, contacts_synced)
