#!/usr/bin/env python3
"""
Diagnostic script to check email records in the database.
Run this in your Flask shell or production environment:

    python -c "exec(open('diagnose_email_records.py').read())"

Or copy the code into your Python console.
"""
import sys
import os

# Add the flaskapp directory to path if needed
sys.path.insert(0, os.path.join(os.getcwd(), 'flaskapp'))

from app import create_app
from app.extensions import db
from app.models_leads import LeadContact, LeadContactEmail, LeadEmail, Lead

def diagnose():
    print("=" * 80)
    print("DIAGNOSTIC: Checking email records in database")
    print("=" * 80)

    # Get all enriched contacts
    contacts = db.session.query(LeadContact).join(
        Lead, LeadContact.lead_id == Lead.id
    ).filter(
        Lead.enrichment_status == 'completed',
        LeadContact.email.isnot(None),
        LeadContact.email != ''
    ).all()

    print(f"\nFound {len(contacts)} enriched contacts with emails:")

    for contact in contacts:
        print(f"\n--- Contact: {contact.email} (ID: {contact.id}) ---")
        print(f"    Name: {contact.name}")
        print(f"    Lead ID: {contact.lead_id}")

        # Check LeadContactEmail records for this contact
        lce_records = db.session.query(LeadContactEmail).filter(
            LeadContactEmail.to_email == contact.email
        ).all()

        print(f"    LeadContactEmail records: {len(lce_records)}")
        for rec in lce_records:
            subj = rec.subject[:50] if rec.subject else 'N/A'
            print(f"      - Step {rec.sequence_step}: status={rec.status}, sent_at={rec.sent_at}, subject='{subj}...' (ID: {rec.id})")

        # Check legacy LeadEmail records
        le_records = db.session.query(LeadEmail).filter(
            LeadEmail.to_email == contact.email
        ).all()

        print(f"    Legacy LeadEmail records: {len(le_records)}")
        for rec in le_records:
            subj = rec.subject[:50] if rec.subject else 'N/A'
            print(f"      - status={rec.status}, sent_at={rec.sent_at}, subject='{subj}...' (ID: {rec.id})")

    print("\n" + "=" * 80)
    print("SUMMARY OF ALL lead_contact_emails TABLE:")
    print("=" * 80)

    all_lce = db.session.query(LeadContactEmail).all()
    print(f"Total records: {len(all_lce)}")

    step_counts = {}
    for rec in all_lce:
        step_counts[rec.sequence_step] = step_counts.get(rec.sequence_step, 0) + 1

    for step, count in sorted(step_counts.items()):
        print(f"  Step {step}: {count} records")

    return contacts, all_lce

# If running directly in app context, call diagnose()
# Otherwise, create the app context first
if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        diagnose()
