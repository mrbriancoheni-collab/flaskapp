#!/usr/bin/env python3
"""
Script to standardize all email sequences to 'Auto Campaign'
and delete non-campaign email sequences.

This script:
1. Updates all campaign-related email sequences to be named 'Auto Campaign'
2. Deletes all other email sequences
3. Ensures consistency across all campaigns
"""

import sys
import os

# Add the flaskapp directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app
from app.extensions import db
from app.models_leads import EmailSequence, LeadCampaign

def standardize_sequences():
    """Standardize all campaign email sequences to 'Auto Campaign'"""
    app = create_app()

    with app.app_context():
        print("=" * 60)
        print("STANDARDIZING EMAIL SEQUENCES")
        print("=" * 60)

        # Get all email sequences
        all_sequences = EmailSequence.query.all()
        print(f"\nTotal email sequences found: {len(all_sequences)}")

        # Get all campaigns
        campaigns = LeadCampaign.query.all()
        print(f"Total lead campaigns found: {len(campaigns)}")

        campaign_ids = {c.id for c in campaigns}

        # Separate campaign and non-campaign sequences
        campaign_sequences = []
        non_campaign_sequences = []

        for seq in all_sequences:
            if seq.campaign_id in campaign_ids:
                campaign_sequences.append(seq)
            else:
                non_campaign_sequences.append(seq)

        print(f"\nCampaign-related sequences: {len(campaign_sequences)}")
        print(f"Non-campaign sequences: {len(non_campaign_sequences)}")

        # Update all campaign sequences to 'Auto Campaign'
        if campaign_sequences:
            print("\n" + "-" * 60)
            print("UPDATING CAMPAIGN SEQUENCES TO 'Auto Campaign'")
            print("-" * 60)

            updated_count = 0
            for seq in campaign_sequences:
                old_name = seq.name
                if old_name != 'Auto Campaign':
                    seq.name = 'Auto Campaign'
                    updated_count += 1
                    print(f"  ✓ Updated: '{old_name}' → 'Auto Campaign' (Campaign ID: {seq.campaign_id})")

            if updated_count > 0:
                db.session.commit()
                print(f"\n✅ Updated {updated_count} email sequences to 'Auto Campaign'")
            else:
                print("\n✅ All campaign sequences already named 'Auto Campaign'")

        # Delete non-campaign sequences
        if non_campaign_sequences:
            print("\n" + "-" * 60)
            print("DELETING NON-CAMPAIGN SEQUENCES")
            print("-" * 60)

            for seq in non_campaign_sequences:
                print(f"  ✗ Deleting: '{seq.name}' (ID: {seq.id}, Campaign ID: {seq.campaign_id})")
                db.session.delete(seq)

            db.session.commit()
            print(f"\n✅ Deleted {len(non_campaign_sequences)} non-campaign email sequences")
        else:
            print("\n✅ No non-campaign sequences to delete")

        # Final summary
        remaining = EmailSequence.query.count()
        print("\n" + "=" * 60)
        print(f"COMPLETE - {remaining} email sequences remain (all 'Auto Campaign')")
        print("=" * 60)


if __name__ == '__main__':
    try:
        standardize_sequences()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
