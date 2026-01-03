#!/usr/bin/env python3
"""
Clean up non-core lead campaigns from database

Keeps only the 20 core home services campaigns and deletes everything else.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app
from app.extensions import db
from app.models_leads import LeadCampaign, Lead, EmailSequence, LeadEmail, LeadContact, LeadContactEmail
from app.configs.lead_automation_config import HOME_SERVICE_CATEGORIES

def cleanup_campaigns():
    """Remove all campaigns that are not part of the core 20"""

    app = create_app()

    with app.app_context():
        # Get the core 20 campaign names
        core_campaign_names = [f"Auto: {business_type}" for business_type in HOME_SERVICE_CATEGORIES.keys()]

        print("="*80)
        print("LEAD CAMPAIGN CLEANUP")
        print("="*80)
        print()
        print("Core 20 Campaigns to KEEP:")
        for i, name in enumerate(core_campaign_names, 1):
            print(f"  {i:2d}. {name}")
        print()

        # Find all campaigns NOT in the core 20
        all_campaigns = LeadCampaign.query.all()
        campaigns_to_delete = [c for c in all_campaigns if c.name not in core_campaign_names]

        if not campaigns_to_delete:
            print("✓ No non-core campaigns found. Database is clean!")
            return

        print(f"Found {len(campaigns_to_delete)} non-core campaigns to DELETE:")
        print()
        for campaign in campaigns_to_delete:
            leads_count = Lead.query.filter_by(campaign_id=campaign.id).count()
            print(f"  - {campaign.name}")
            print(f"    ID: {campaign.id}, Status: {campaign.status}")
            print(f"    Leads: {leads_count}")

        print()
        print("⚠️  WARNING: This will permanently delete:")
        print(f"  - {len(campaigns_to_delete)} campaigns")
        print(f"  - All associated leads")
        print(f"  - All associated contacts")
        print(f"  - All email records")
        print(f"  - All email sequences")
        print()

        response = input("Are you sure you want to DELETE these campaigns? (type 'DELETE' to confirm): ")

        if response != "DELETE":
            print()
            print("Aborted. No changes made.")
            return

        print()
        print("Deleting campaigns and associated data...")

        deleted_count = 0
        deleted_leads = 0
        deleted_contacts = 0
        deleted_emails = 0
        deleted_sequences = 0

        for campaign in campaigns_to_delete:
            # Count what we're deleting
            leads = Lead.query.filter_by(campaign_id=campaign.id).all()
            deleted_leads += len(leads)

            # Delete in correct order (foreign key constraints)
            for lead in leads:
                # Delete contact emails
                contact_emails = LeadContactEmail.query.filter_by(lead_id=lead.id).all()
                for ce in contact_emails:
                    db.session.delete(ce)
                deleted_emails += len(contact_emails)

                # Delete contacts
                contacts = LeadContact.query.filter_by(lead_id=lead.id).all()
                for c in contacts:
                    db.session.delete(c)
                deleted_contacts += len(contacts)

                # Delete lead emails
                lead_emails = LeadEmail.query.filter_by(lead_id=lead.id).all()
                for le in lead_emails:
                    db.session.delete(le)
                deleted_emails += len(lead_emails)

                # Delete the lead
                db.session.delete(lead)

            # Delete email sequences
            sequences = EmailSequence.query.filter_by(campaign_id=campaign.id).all()
            for seq in sequences:
                db.session.delete(seq)
            deleted_sequences += len(sequences)

            # Delete the campaign
            db.session.delete(campaign)
            deleted_count += 1

            print(f"  ✓ Deleted: {campaign.name}")

        # Commit all deletions
        db.session.commit()

        print()
        print("="*80)
        print("CLEANUP COMPLETE")
        print("="*80)
        print()
        print(f"Deleted:")
        print(f"  - {deleted_count} campaigns")
        print(f"  - {deleted_leads} leads")
        print(f"  - {deleted_contacts} contacts")
        print(f"  - {deleted_emails} email records")
        print(f"  - {deleted_sequences} email sequences")
        print()
        print(f"Remaining campaigns: {LeadCampaign.query.count()}")
        print()

if __name__ == "__main__":
    try:
        cleanup_campaigns()
    except KeyboardInterrupt:
        print("\n\nAborted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
