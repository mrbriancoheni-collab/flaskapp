#!/usr/bin/env python3
"""
Script to clear email records so emails can be resent.

CAUTION: Only run this if you're sure you want to resend emails!

Usage in Flask shell:
    exec(open('clear_email_records.py').read())

Then call one of:
    clear_step_records(1)  # Clear all step 1 records
    clear_step_records(2)  # Clear all step 2 records
    clear_all_for_email('someone@example.com')  # Clear all records for specific email
    clear_all_records()  # Clear ALL records (dangerous!)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.getcwd(), 'flaskapp'))

from app import create_app
from app.extensions import db
from app.models_leads import LeadContactEmail, LeadEmail

def clear_step_records(step_number: int, dry_run: bool = True):
    """Clear all LeadContactEmail records for a specific step."""
    records = LeadContactEmail.query.filter_by(sequence_step=step_number).all()
    print(f"Found {len(records)} records for step {step_number}")

    if dry_run:
        print("DRY RUN - no records deleted. Set dry_run=False to actually delete.")
        for rec in records[:5]:
            print(f"  Would delete: {rec.to_email} step {rec.sequence_step} (ID: {rec.id})")
        if len(records) > 5:
            print(f"  ... and {len(records) - 5} more")
    else:
        for rec in records:
            db.session.delete(rec)
        db.session.commit()
        print(f"Deleted {len(records)} records")

    return records

def clear_all_for_email(email: str, dry_run: bool = True):
    """Clear all email records for a specific email address."""
    lce_records = LeadContactEmail.query.filter_by(to_email=email).all()
    le_records = LeadEmail.query.filter_by(to_email=email).all()

    print(f"Found {len(lce_records)} LeadContactEmail records for {email}")
    print(f"Found {len(le_records)} LeadEmail records for {email}")

    if dry_run:
        print("DRY RUN - no records deleted. Set dry_run=False to actually delete.")
        for rec in lce_records:
            print(f"  Would delete LeadContactEmail: step {rec.sequence_step}, sent_at={rec.sent_at}")
        for rec in le_records:
            print(f"  Would delete LeadEmail: sent_at={rec.sent_at}")
    else:
        for rec in lce_records:
            db.session.delete(rec)
        for rec in le_records:
            db.session.delete(rec)
        db.session.commit()
        print(f"Deleted {len(lce_records)} LeadContactEmail + {len(le_records)} LeadEmail records")

    return lce_records, le_records

def clear_all_records(dry_run: bool = True):
    """Clear ALL email records. DANGER!"""
    lce_count = LeadContactEmail.query.count()
    le_count = LeadEmail.query.count()

    print(f"Found {lce_count} LeadContactEmail records total")
    print(f"Found {le_count} LeadEmail records total")

    if dry_run:
        print("DRY RUN - no records deleted. Set dry_run=False to actually delete.")
    else:
        LeadContactEmail.query.delete()
        LeadEmail.query.delete()
        db.session.commit()
        print(f"Deleted ALL records")

    return lce_count, le_count

print("Email record cleanup functions loaded.")
print("Available functions:")
print("  clear_step_records(step_number, dry_run=True)")
print("  clear_all_for_email(email, dry_run=True)")
print("  clear_all_records(dry_run=True)")
print("\nSet dry_run=False to actually delete records!")
