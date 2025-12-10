#!/usr/bin/env python3
"""
Delete old individual campaigns (Auto: {keyword} - {city} pattern)
Keeps new consolidated campaigns (Auto: Home Services - {city})
"""
import sys
import os

# Add flaskapp to path
sys.path.insert(0, '/home/fieljtgr/flaskapp/flaskapp')

from app import create_app
from app.extensions import db
from app.models_leads import LeadCampaign, Lead, LeadEmail, LeadContactEmail, EmailSequence

app = create_app()

with app.app_context():
    print("=" * 60)
    print("DELETE OLD CAMPAIGNS SCRIPT")
    print("=" * 60)

    # Get all campaigns with Auto: prefix
    all_auto = LeadCampaign.query.filter(LeadCampaign.name.like('Auto:%')).all()
    print(f"\nFound {len(all_auto)} campaigns with 'Auto:' prefix")

    # Filter out new consolidated ones
    old_campaigns = [
        c for c in all_auto
        if not c.name.startswith('Auto: Home Services -')
    ]

    print(f"Identified {len(old_campaigns)} old campaigns to delete")
    print(f"Will keep any 'Auto: Home Services -' campaigns (consolidated)")

    if len(old_campaigns) == 0:
        print("\n✓ No old campaigns to delete!")
        sys.exit(0)

    # Count associated data
    total_leads = sum(Lead.query.filter_by(campaign_id=c.id).count() for c in old_campaigns[:10])
    print(f"\nEstimated data to delete (from first 10 campaigns):")
    print(f"  - {total_leads} leads (estimated)")
    print(f"  - Associated emails and sequences")

    print("\n" + "=" * 60)
    print("WARNING: This will permanently delete all data!")
    print("=" * 60)

    confirm = input("\nType 'DELETE' to confirm: ").strip()

    if confirm != 'DELETE':
        print("\n✗ Cancelled - you did not type DELETE")
        sys.exit(1)

    print(f"\n🗑️  Starting deletion of {len(old_campaigns)} campaigns...\n")

    deleted = 0
    errors = 0

    for idx, campaign in enumerate(old_campaigns):
        try:
            # Delete associated data
            leads = Lead.query.filter_by(campaign_id=campaign.id).all()
            for lead in leads:
                LeadEmail.query.filter_by(lead_id=lead.id).delete()

            Lead.query.filter_by(campaign_id=campaign.id).delete()
            LeadContactEmail.query.filter_by(campaign_id=campaign.id).delete()
            EmailSequence.query.filter_by(campaign_id=campaign.id).delete()

            db.session.delete(campaign)
            deleted += 1

            # Commit every 100 to avoid long transactions
            if (idx + 1) % 100 == 0:
                db.session.commit()
                print(f"  Progress: {idx + 1}/{len(old_campaigns)} campaigns deleted")

        except Exception as e:
            print(f"  ✗ Error deleting campaign {campaign.id}: {e}")
            errors += 1
            db.session.rollback()
            continue

    # Final commit
    try:
        db.session.commit()
        print(f"\n{'=' * 60}")
        print(f"✓ COMPLETED")
        print(f"{'=' * 60}")
        print(f"  Deleted: {deleted} campaigns")
        print(f"  Errors: {errors}")
        print(f"\nRemaining campaigns: {LeadCampaign.query.count()}")
    except Exception as e:
        db.session.rollback()
        print(f"\n✗ Final commit failed: {e}")
        sys.exit(1)
