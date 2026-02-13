#!/usr/bin/env python3
"""
Backfill LeadContact to CompanyContact Links

This script links LeadContact records to existing CompanyContact records using
multiple matching strategies:

1. Email matching (exact, case-insensitive) - Most reliable
2. LinkedIn URL matching (exact) - Unique identifier
3. Name + Company matching - When Lead and CompanyContact share the same CRMContact

Usage:
    python scripts/backfill_lead_contact_links.py [--dry-run] [--verbose]

Options:
    --dry-run   Show what would be linked without making changes
    --verbose   Show detailed matching information
"""

import sys
import os
import argparse

# Load environment BEFORE importing anything from app
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from load_env import load_environment, ensure_app_can_initialize

# Load environment and ensure app can initialize
load_environment()
ensure_app_can_initialize()

# NOW we can safely import the app
import logging
from collections import defaultdict
from app import create_app
from app.extensions import db
from app.models import CRMContact, CompanyContact
from app.models_leads import Lead, LeadContact

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


class BackfillStats:
    """Track statistics for the backfill operation."""

    def __init__(self):
        self.linked_by_email = 0
        self.linked_by_linkedin = 0
        self.linked_by_name_company = 0
        self.not_found = 0
        self.already_linked = 0
        self.details = []

    @property
    def total_linked(self):
        return self.linked_by_email + self.linked_by_linkedin + self.linked_by_name_company

    def report(self):
        """Print summary report."""
        print("\n" + "=" * 60)
        print("BACKFILL SUMMARY")
        print("=" * 60)
        print(f"Already linked (skipped):     {self.already_linked:>6}")
        print(f"Linked by email:              {self.linked_by_email:>6}")
        print(f"Linked by LinkedIn URL:       {self.linked_by_linkedin:>6}")
        print(f"Linked by name + company:     {self.linked_by_name_company:>6}")
        print("-" * 60)
        print(f"TOTAL NEWLY LINKED:           {self.total_linked:>6}")
        print(f"No match found:               {self.not_found:>6}")
        print("=" * 60)


def normalize_email(email):
    """Normalize email for comparison."""
    if not email:
        return None
    return email.lower().strip()


def normalize_linkedin(url):
    """Normalize LinkedIn URL for comparison."""
    if not url:
        return None
    # Remove trailing slashes and normalize
    url = url.lower().strip().rstrip('/')
    # Handle different LinkedIn URL formats
    if '/in/' in url:
        # Extract the profile ID part
        parts = url.split('/in/')
        if len(parts) > 1:
            profile_id = parts[1].split('/')[0].split('?')[0]
            return profile_id
    return url


def normalize_name(name):
    """Normalize name for comparison."""
    if not name:
        return None
    # Lowercase, strip whitespace, and normalize multiple spaces
    return ' '.join(name.lower().strip().split())


def build_company_contact_indexes(verbose=False):
    """
    Build lookup indexes for CompanyContacts.

    Returns:
        tuple: (email_index, linkedin_index, name_by_crm_index)
    """
    company_contacts = CompanyContact.query.all()

    email_index = {}  # email -> CompanyContact
    linkedin_index = {}  # linkedin_profile_id -> CompanyContact
    name_by_crm_index = defaultdict(dict)  # crm_contact_id -> {normalized_name -> CompanyContact}

    for cc in company_contacts:
        # Email index
        email = normalize_email(cc.email)
        if email and email not in email_index:
            email_index[email] = cc

        # LinkedIn index
        linkedin = normalize_linkedin(cc.linkedin_url)
        if linkedin and linkedin not in linkedin_index:
            linkedin_index[linkedin] = cc

        # Name by CRM company index
        name = normalize_name(cc.full_name)
        if name and cc.crm_contact_id:
            if name not in name_by_crm_index[cc.crm_contact_id]:
                name_by_crm_index[cc.crm_contact_id][name] = cc

    if verbose:
        logger.info(f"Built indexes:")
        logger.info(f"  - Email index: {len(email_index)} entries")
        logger.info(f"  - LinkedIn index: {len(linkedin_index)} entries")
        logger.info(f"  - Name by CRM index: {len(name_by_crm_index)} CRM contacts")

    return email_index, linkedin_index, name_by_crm_index


def find_matching_company_contact(lead_contact, email_index, linkedin_index, name_by_crm_index, verbose=False):
    """
    Find a matching CompanyContact for a LeadContact using multiple strategies.

    Returns:
        tuple: (CompanyContact or None, match_type string)
    """
    # Strategy 1: Email match
    email = normalize_email(lead_contact.email)
    if email and email in email_index:
        return email_index[email], 'email'

    # Strategy 2: LinkedIn URL match
    linkedin = normalize_linkedin(lead_contact.linkedin_url)
    if linkedin and linkedin in linkedin_index:
        return linkedin_index[linkedin], 'linkedin'

    # Strategy 3: Name match within same company
    # This requires the Lead to be linked to a CRMContact
    if lead_contact.lead and lead_contact.lead.crm_contact_id:
        crm_contact_id = lead_contact.lead.crm_contact_id
        name = normalize_name(lead_contact.name)

        if name and crm_contact_id in name_by_crm_index:
            if name in name_by_crm_index[crm_contact_id]:
                return name_by_crm_index[crm_contact_id][name], 'name_company'

    return None, None


def backfill_links(dry_run=False, verbose=False):
    """
    Main backfill function.

    Args:
        dry_run: If True, don't commit changes to database
        verbose: If True, print detailed matching information

    Returns:
        BackfillStats object
    """
    stats = BackfillStats()

    # Get all LeadContacts
    all_lead_contacts = LeadContact.query.all()
    logger.info(f"Found {len(all_lead_contacts)} total LeadContacts")

    # Build indexes
    email_index, linkedin_index, name_by_crm_index = build_company_contact_indexes(verbose)

    # Process each LeadContact
    for lc in all_lead_contacts:
        # Skip already linked
        if lc.company_contact_id:
            stats.already_linked += 1
            continue

        # Try to find a match
        company_contact, match_type = find_matching_company_contact(
            lc, email_index, linkedin_index, name_by_crm_index, verbose
        )

        if company_contact:
            if not dry_run:
                lc.company_contact_id = company_contact.id

            if match_type == 'email':
                stats.linked_by_email += 1
            elif match_type == 'linkedin':
                stats.linked_by_linkedin += 1
            elif match_type == 'name_company':
                stats.linked_by_name_company += 1

            if verbose:
                logger.info(f"  [{match_type.upper()}] LeadContact {lc.id} ({lc.name}) -> CompanyContact {company_contact.id}")
        else:
            stats.not_found += 1
            if verbose:
                logger.debug(f"  [NO MATCH] LeadContact {lc.id} ({lc.name}, {lc.email})")

    # Commit changes
    if not dry_run and stats.total_linked > 0:
        db.session.commit()
        logger.info(f"Committed {stats.total_linked} links to database")
    elif dry_run:
        logger.info("DRY RUN - No changes committed")

    return stats


def show_current_state():
    """Show current state of LeadContact linking."""
    total_lead_contacts = LeadContact.query.count()
    linked = LeadContact.query.filter(LeadContact.company_contact_id.isnot(None)).count()
    unlinked = LeadContact.query.filter(LeadContact.company_contact_id.is_(None)).count()

    unlinked_with_email = LeadContact.query.filter(
        LeadContact.company_contact_id.is_(None),
        LeadContact.email.isnot(None),
        LeadContact.email != ''
    ).count()

    unlinked_with_linkedin = LeadContact.query.filter(
        LeadContact.company_contact_id.is_(None),
        LeadContact.linkedin_url.isnot(None),
        LeadContact.linkedin_url != ''
    ).count()

    total_company_contacts = CompanyContact.query.count()
    company_contacts_with_email = CompanyContact.query.filter(
        CompanyContact.email.isnot(None),
        CompanyContact.email != ''
    ).count()

    print("\n" + "=" * 60)
    print("CURRENT STATE")
    print("=" * 60)
    print(f"Total LeadContacts:           {total_lead_contacts:>6}")
    print(f"  - Linked to CRM:            {linked:>6}")
    print(f"  - Unlinked:                 {unlinked:>6}")
    print(f"    - with email:             {unlinked_with_email:>6}")
    print(f"    - with LinkedIn:          {unlinked_with_linkedin:>6}")
    print("-" * 60)
    print(f"Total CompanyContacts:        {total_company_contacts:>6}")
    print(f"  - with email:               {company_contacts_with_email:>6}")
    print("=" * 60 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Backfill LeadContact to CompanyContact links'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be linked without making changes'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed matching information'
    )
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    app = create_app()
    with app.app_context():
        if args.dry_run:
            logger.info("DRY RUN MODE - No changes will be made")

        # Show current state
        show_current_state()

        # Run backfill
        logger.info("Starting backfill...")
        stats = backfill_links(dry_run=args.dry_run, verbose=args.verbose)

        # Show results
        stats.report()

        # Show final state (if not dry run)
        if not args.dry_run and stats.total_linked > 0:
            print("\nFINAL STATE:")
            show_current_state()

        return 0


if __name__ == '__main__':
    sys.exit(main())
