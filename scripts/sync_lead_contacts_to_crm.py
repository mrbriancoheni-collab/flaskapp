#!/usr/bin/env python3
"""
Sync LeadContacts to CompanyContacts by Email

Links LeadContact records to existing CompanyContact records by email matching.
This handles cases where the contacts were created separately and need to be linked.
"""

import sys
import os

# Load environment BEFORE importing anything from app
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from load_env import load_environment, ensure_app_can_initialize

# Load environment and ensure app can initialize
load_environment()
ensure_app_can_initialize()

# NOW we can safely import the app
import logging
from app import create_app
from app.extensions import db
from app.models import CompanyContact
from app.models_leads import LeadContact

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


def sync_by_email():
    """
    Sync LeadContacts to CompanyContacts by email matching.

    For each LeadContact without a company_contact_id that has an email,
    find a matching CompanyContact by email and link them.
    """
    # Get all LeadContacts without company_contact_id that have an email
    unlinked_contacts = LeadContact.query.filter(
        LeadContact.company_contact_id.is_(None),
        LeadContact.email.isnot(None),
        LeadContact.email != ''
    ).all()

    logger.info(f"Found {len(unlinked_contacts)} unlinked LeadContacts with emails")

    # Build a lookup dict of CompanyContacts by email for efficiency
    company_contacts = CompanyContact.query.filter(
        CompanyContact.email.isnot(None),
        CompanyContact.email != ''
    ).all()

    email_to_company_contact = {}
    for cc in company_contacts:
        email_lower = cc.email.lower().strip()
        if email_lower not in email_to_company_contact:
            email_to_company_contact[email_lower] = cc

    logger.info(f"Built lookup with {len(email_to_company_contact)} unique CompanyContact emails")

    linked_count = 0
    not_found_count = 0

    for lc in unlinked_contacts:
        email_lower = lc.email.lower().strip()

        if email_lower in email_to_company_contact:
            company_contact = email_to_company_contact[email_lower]
            lc.company_contact_id = company_contact.id
            linked_count += 1
            logger.debug(f"Linked LeadContact {lc.id} ({lc.email}) to CompanyContact {company_contact.id}")
        else:
            not_found_count += 1
            logger.debug(f"No CompanyContact found for LeadContact {lc.id} ({lc.email})")

    if linked_count > 0:
        db.session.commit()
        logger.info(f"Committed {linked_count} links to database")

    return linked_count, not_found_count


def main():
    """Run the sync."""
    app = create_app()
    with app.app_context():
        logger.info("Starting LeadContact to CompanyContact sync by email")

        try:
            linked, not_found = sync_by_email()

            logger.info(f"Sync complete:")
            logger.info(f"  - Linked: {linked} LeadContacts to CompanyContacts")
            logger.info(f"  - Not found: {not_found} LeadContacts had no matching CompanyContact")

            # Verify
            still_unlinked = LeadContact.query.filter(
                LeadContact.company_contact_id.is_(None)
            ).count()
            total_linked = LeadContact.query.filter(
                LeadContact.company_contact_id.isnot(None)
            ).count()

            logger.info(f"Final state:")
            logger.info(f"  - Total linked LeadContacts: {total_linked}")
            logger.info(f"  - Total unlinked LeadContacts: {still_unlinked}")

            return 0

        except Exception as e:
            logger.error(f"Error during sync: {e}", exc_info=True)
            return 1


if __name__ == '__main__':
    sys.exit(main())
