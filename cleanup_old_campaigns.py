#!/usr/bin/env python3
"""
Script to delete old individual campaigns and create 100 consolidated campaigns
"""
import sys
import os

# Add the flaskapp directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app
from app.extensions import db
from app.models_leads import LeadCampaign, Lead, LeadEmail, LeadContactEmail, EmailSequence

app = create_app()

with app.app_context():
    print("Starting cleanup of old campaigns...")

    # Get all campaigns with Auto: prefix
    all_auto_campaigns = LeadCampaign.query.filter(
        LeadCampaign.name.like('Auto:%')
    ).all()

    print(f"Found {len(all_auto_campaigns)} campaigns with 'Auto:' prefix")

    # Filter out the new consolidated ones (keep these)
    old_campaigns = [
        c for c in all_auto_campaigns
        if not c.name.startswith('Auto: Home Services -')
    ]

    print(f"Identified {len(old_campaigns)} old campaigns to delete")

    if len(old_campaigns) == 0:
        print("No old campaigns to delete!")
        sys.exit(0)

    # Confirm deletion
    print("\nWARNING: This will delete:")
    print(f"  - {len(old_campaigns)} old campaigns")

    # Count associated data
    total_leads = 0
    total_emails = 0
    for campaign in old_campaigns:
        leads_count = Lead.query.filter_by(campaign_id=campaign.id).count()
        total_leads += leads_count

        emails_count = LeadContactEmail.query.filter_by(campaign_id=campaign.id).count()
        total_emails += emails_count

    print(f"  - {total_leads} leads")
    print(f"  - {total_emails} emails")
    print("\nType 'DELETE' to confirm: ", end='')

    confirmation = input().strip()

    if confirmation != 'DELETE':
        print("Deletion cancelled.")
        sys.exit(0)

    print("\nDeleting campaigns and associated data...")

    deleted_count = 0
    for campaign in old_campaigns:
        try:
            # Delete associated leads and their emails
            leads = Lead.query.filter_by(campaign_id=campaign.id).all()
            for lead in leads:
                LeadEmail.query.filter_by(lead_id=lead.id).delete()
            Lead.query.filter_by(campaign_id=campaign.id).delete()

            # Delete associated contact emails
            LeadContactEmail.query.filter_by(campaign_id=campaign.id).delete()

            # Delete email sequences
            EmailSequence.query.filter_by(campaign_id=campaign.id).delete()

            # Delete campaign
            db.session.delete(campaign)
            deleted_count += 1

            if deleted_count % 100 == 0:
                print(f"  Deleted {deleted_count}/{len(old_campaigns)} campaigns...")
                db.session.commit()

        except Exception as e:
            print(f"Error deleting campaign {campaign.id}: {e}")
            db.session.rollback()

    # Final commit
    db.session.commit()

    print(f"\n✓ Successfully deleted {deleted_count} old campaigns and associated data")

    # Show remaining campaigns
    remaining = LeadCampaign.query.count()
    print(f"✓ {remaining} campaigns remaining in database")
