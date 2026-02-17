#!/usr/bin/env python3
"""
Diagnostic script to show email addresses queued and ready to send.

This script displays all emails that are queued or ready to be sent without
actually sending them. It checks multiple sources:

1. EmailQueue table - Transactional emails pending send
2. LeadContactEmail table - Campaign emails with 'queued' status
3. LeadContacts ready for first email - Enriched contacts not yet emailed
4. LeadContacts ready for next sequence step - Contacts due for follow-up

Usage:
    python diagnose_email_queue.py
    python diagnose_email_queue.py --summary          # Summary only
    python diagnose_email_queue.py --verbose          # Show all details
    python diagnose_email_queue.py --campaign-id 5    # Filter by campaign
    python diagnose_email_queue.py --export emails.csv  # Export to CSV
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta

# Add flaskapp to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

def create_app_context():
    """Create Flask app context for database access."""
    try:
        from app import create_app, db
        app = create_app()
        return app, db
    except Exception as e:
        print(f"Error creating Flask app: {e}")
        print("\nMake sure you're running from the flaskapp directory")
        print("and that all dependencies are installed.")
        sys.exit(1)


def get_email_queue_pending(db, limit=100):
    """Get pending emails from EmailQueue table."""
    from app.models_billing import EmailQueue

    query = db.session.query(EmailQueue).filter(
        EmailQueue.status == 'pending'
    ).order_by(EmailQueue.created_at.asc()).limit(limit)

    return query.all()


def get_queued_lead_contact_emails(db, campaign_id=None, limit=100):
    """Get LeadContactEmail records with 'queued' status."""
    from app.models_leads import LeadContactEmail, LeadContact, LeadCampaign

    query = db.session.query(
        LeadContactEmail,
        LeadContact.name,
        LeadContact.title,
        LeadCampaign.name.label('campaign_name')
    ).join(
        LeadContact, LeadContactEmail.contact_id == LeadContact.id
    ).join(
        LeadCampaign, LeadContactEmail.campaign_id == LeadCampaign.id
    ).filter(
        LeadContactEmail.status == 'queued'
    )

    if campaign_id:
        query = query.filter(LeadContactEmail.campaign_id == campaign_id)

    query = query.order_by(LeadContactEmail.created_at.asc()).limit(limit)

    return query.all()


def get_contacts_ready_for_first_email(db, campaign_id=None, limit=100):
    """
    Get contacts that haven't been sent any emails yet.

    Queries LeadContact directly (not via CompanyContact/CRM) to ensure
    all contacts with emails are found, regardless of CRM sync status.
    """
    from app.models_leads import (
        LeadContact, Lead, LeadCampaign, LeadContactEmail,
        LeadEmail, EmailSequence, EmailUnsubscribe,
    )

    # Get all unsubscribed emails for exclusion
    unsubscribed_emails = set(
        row[0].lower()
        for row in db.session.query(EmailUnsubscribe.email).all()
    )

    # Query LeadContacts with emails directly
    lead_contacts = (
        db.session.query(LeadContact)
        .filter(
            LeadContact.email.isnot(None),
            LeadContact.email != '',
        )
        .all()
    )

    results = []
    for lead_contact in lead_contacts:
        if len(results) >= limit:
            break

        # Skip unsubscribed
        if lead_contact.email.lower() in unsubscribed_emails:
            continue

        lead = Lead.query.get(lead_contact.lead_id)
        if not lead:
            continue

        campaign = LeadCampaign.query.get(lead.campaign_id)
        if not campaign:
            continue

        if campaign_id and campaign.id != campaign_id:
            continue

        # Check if contact has received ANY emails (LeadContactEmail)
        has_email = db.session.query(LeadContactEmail).filter(
            LeadContactEmail.to_email == lead_contact.email
        ).first()
        if has_email:
            continue

        # Also check legacy emails (treat as step 1)
        has_legacy = db.session.query(LeadEmail).filter(
            LeadEmail.to_email == lead_contact.email
        ).first()
        if has_legacy:
            continue

        # Check that campaign has at least one active sequence step
        has_sequence = db.session.query(EmailSequence).filter(
            EmailSequence.campaign_id == campaign.id,
            EmailSequence.is_active == True
        ).first()
        if not has_sequence:
            continue

        results.append((lead_contact, lead.company_name, campaign.name, campaign.id, campaign.status))

    return results


def get_contacts_ready_for_next_sequence(db, campaign_id=None, limit=100):
    """
    Get contacts ready for their next sequence step (follow-up emails).

    Queries LeadContact directly (not via CompanyContact/CRM) to ensure
    all contacts with emails are found, regardless of CRM sync status.
    """
    from app.models_leads import (
        LeadContact, Lead, LeadCampaign, EmailSequence,
        LeadContactEmail, LeadEmail, EmailUnsubscribe,
    )

    results = []

    # Get all unsubscribed emails for exclusion
    unsubscribed_emails = set(
        row[0].lower()
        for row in db.session.query(EmailUnsubscribe.email).all()
    )

    # Query LeadContacts with emails directly
    lead_contacts = (
        db.session.query(LeadContact)
        .filter(
            LeadContact.email.isnot(None),
            LeadContact.email != '',
        )
        .all()
    )

    for lead_contact in lead_contacts:
        if len(results) >= limit:
            break

        # Skip unsubscribed
        if lead_contact.email.lower() in unsubscribed_emails:
            continue

        lead = Lead.query.get(lead_contact.lead_id)
        if not lead:
            continue

        lcampaign = LeadCampaign.query.get(lead.campaign_id)
        if not lcampaign:
            continue

        if campaign_id and lcampaign.id != campaign_id:
            continue

        # Get active sequence steps for this campaign
        sequences = (
            EmailSequence.query
            .filter_by(campaign_id=lcampaign.id, is_active=True)
            .order_by(EmailSequence.step_number)
            .all()
        )
        if not sequences:
            continue

        max_step = max(s.step_number for s in sequences)

        # Find which steps this contact has already received (by email address)
        received_steps = db.session.query(LeadContactEmail.sequence_step).filter(
            LeadContactEmail.to_email == lead_contact.email
        ).all()
        received_step_numbers = set(step[0] for step in received_steps if step[0] is not None)

        # Also check legacy emails (treat as step 1)
        legacy_email = db.session.query(LeadEmail).filter(
            LeadEmail.to_email == lead_contact.email
        ).first()
        if legacy_email:
            received_step_numbers.add(1)

        # Must have received at least one step to be a follow-up candidate
        if not received_step_numbers:
            continue

        # Find the next step this contact needs
        next_seq = None
        for seq in sequences:
            if seq.step_number not in received_step_numbers:
                next_seq = seq
                break

        if not next_seq:
            # All steps completed
            continue

        last_step = max(received_step_numbers)

        # Get last email sent_at for delay check
        last_email = (
            db.session.query(LeadContactEmail)
            .filter(LeadContactEmail.to_email == lead_contact.email)
            .order_by(LeadContactEmail.sent_at.desc())
            .first()
        )

        delay_days = next_seq.delay_days or lcampaign.sequence_delay_days or 3

        if last_email and last_email.sent_at:
            days_since_last = (datetime.utcnow() - last_email.sent_at).days
            ready = days_since_last >= delay_days
        else:
            days_since_last = None
            ready = False

        results.append({
            'contact': lead_contact,
            'company_name': lead.company_name,
            'campaign_name': lcampaign.name,
            'campaign_id': lcampaign.id,
            'last_step': last_step,
            'next_step': next_seq.step_number,
            'max_step': max_step,
            'last_sent_at': last_email.sent_at if last_email else None,
            'days_since_last': days_since_last,
            'delay_days': delay_days,
            'ready': ready,
        })

    return results


def get_unsubscribes(db, limit=10):
    """Get recent unsubscribes to show what's blocked."""
    from app.models_leads import EmailUnsubscribe

    return db.session.query(EmailUnsubscribe).order_by(
        EmailUnsubscribe.created_at.desc()
    ).limit(limit).all()


def print_section_header(title, count=None):
    """Print a formatted section header."""
    header = f"\n{'='*70}\n{title}"
    if count is not None:
        header += f" ({count} found)"
    header += f"\n{'='*70}"
    print(header)


def print_email_queue(emails, verbose=False):
    """Print EmailQueue pending emails."""
    print_section_header("1. EMAIL QUEUE (Transactional)", len(emails))

    if not emails:
        print("  No pending transactional emails in queue.")
        return

    for i, email in enumerate(emails, 1):
        print(f"\n  [{i}] To: {email.to_email}")
        print(f"      Subject: {email.subject[:60]}{'...' if len(email.subject) > 60 else ''}")
        print(f"      Created: {email.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"      Attempts: {email.attempts}/{email.max_attempts}")
        if email.error_message and verbose:
            print(f"      Last Error: {email.error_message[:100]}")


def print_queued_contact_emails(results, verbose=False):
    """Print LeadContactEmail records with queued status."""
    print_section_header("2. LEAD CONTACT EMAILS (Queued Status)", len(results))

    if not results:
        print("  No queued campaign emails found.")
        return

    for i, (email, contact_name, title, campaign_name) in enumerate(results, 1):
        print(f"\n  [{i}] To: {email.to_email}")
        print(f"      Contact: {contact_name} ({title or 'No title'})")
        print(f"      Campaign: {campaign_name}")
        print(f"      Sequence Step: {email.sequence_step}")
        print(f"      Subject: {email.subject[:50]}{'...' if len(email.subject) > 50 else ''}")
        print(f"      Created: {email.created_at.strftime('%Y-%m-%d %H:%M:%S')}")


def print_contacts_ready_first(results, verbose=False):
    """Print contacts ready for first email."""
    print_section_header("3. CONTACTS READY FOR FIRST EMAIL", len(results))

    if not results:
        print("  No contacts ready for first email.")
        return

    for i, (contact, company_name, campaign_name, campaign_id, campaign_status) in enumerate(results, 1):
        print(f"\n  [{i}] Email: {contact.email}")
        print(f"      Name: {contact.name} ({contact.title or 'No title'})")
        print(f"      Company: {company_name}")
        print(f"      Campaign: {campaign_name} (ID: {campaign_id}, Status: {campaign_status})")
        print(f"      Role: {contact.role_category}")


def print_contacts_ready_sequence(results, verbose=False):
    """Print contacts ready for next sequence step."""
    # Separate ready vs not ready
    ready = [r for r in results if r['ready']]
    not_ready = [r for r in results if not r['ready']]

    print_section_header("4. CONTACTS READY FOR NEXT SEQUENCE STEP", len(ready))

    if not ready:
        print("  No contacts ready for next sequence step.")
    else:
        for i, r in enumerate(ready, 1):
            contact = r['contact']
            print(f"\n  [{i}] Email: {contact.email}")
            print(f"      Name: {contact.name} ({contact.title or 'No title'})")
            print(f"      Company: {r['company_name']}")
            print(f"      Campaign: {r['campaign_name']}")
            print(f"      Progress: Step {r['last_step']} -> {r['next_step']} (of {r['max_step']})")
            print(f"      Last Sent: {r['last_sent_at'].strftime('%Y-%m-%d %H:%M:%S') if r['last_sent_at'] else 'Never'}")
            print(f"      Days Since: {r['days_since_last']} (delay: {r['delay_days']} days) - READY")

    if not_ready and verbose:
        print(f"\n  --- Contacts waiting for delay ({len(not_ready)}) ---")
        for r in not_ready[:10]:  # Show max 10
            contact = r['contact']
            days_remaining = r['delay_days'] - (r['days_since_last'] or 0)
            print(f"  - {contact.email}: Step {r['last_step']}->{r['next_step']}, {days_remaining} days remaining")


def print_summary(email_queue, queued_contact_emails, contacts_first, contacts_sequence):
    """Print a summary of all queued emails."""
    ready_sequence = [r for r in contacts_sequence if r['ready']]

    print_section_header("SUMMARY")
    print(f"""
  Transactional Queue (EmailQueue):     {len(email_queue):>5} pending
  Campaign Emails (queued status):      {len(queued_contact_emails):>5} queued
  Contacts Ready for First Email:       {len(contacts_first):>5} ready
  Contacts Ready for Follow-up:         {len(ready_sequence):>5} ready
  {'─'*50}
  TOTAL EMAILS READY TO SEND:           {len(email_queue) + len(queued_contact_emails) + len(contacts_first) + len(ready_sequence):>5}
""")


def export_to_csv(filepath, email_queue, queued_contact_emails, contacts_first, contacts_sequence):
    """Export all queued emails to CSV."""
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['Type', 'Email', 'Name', 'Company', 'Campaign', 'Subject', 'Status', 'Created/Last Sent'])

        # EmailQueue
        for email in email_queue:
            writer.writerow([
                'Transactional',
                email.to_email,
                '',
                '',
                '',
                email.subject,
                f'pending (attempt {email.attempts})',
                email.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        # Queued contact emails
        for email, contact_name, title, campaign_name in queued_contact_emails:
            writer.writerow([
                'Campaign (Queued)',
                email.to_email,
                contact_name,
                '',
                campaign_name,
                email.subject,
                f'queued (step {email.sequence_step})',
                email.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        # First email contacts
        for contact, company_name, campaign_name, campaign_id, campaign_status in contacts_first:
            writer.writerow([
                'First Email',
                contact.email,
                contact.name,
                company_name,
                campaign_name,
                '(template)',
                'ready for step 1',
                contact.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        # Sequence follow-ups
        for r in contacts_sequence:
            if r['ready']:
                contact = r['contact']
                writer.writerow([
                    'Follow-up',
                    contact.email,
                    contact.name,
                    r['company_name'],
                    r['campaign_name'],
                    '(template)',
                    f'ready for step {r["next_step"]}',
                    r['last_sent_at'].strftime('%Y-%m-%d %H:%M:%S') if r['last_sent_at'] else ''
                ])

    print(f"\nExported to: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description='Diagnose email queue - show what emails are ready to send',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                        Show all queued emails
  %(prog)s --summary              Show summary only
  %(prog)s --verbose              Show all details including waiting contacts
  %(prog)s --campaign-id 5        Filter by specific campaign
  %(prog)s --export queue.csv     Export to CSV file
  %(prog)s --limit 50             Limit results per category
        """
    )

    parser.add_argument('--summary', action='store_true',
                        help='Show summary counts only')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show verbose output including waiting contacts')
    parser.add_argument('--campaign-id', type=int,
                        help='Filter by specific campaign ID')
    parser.add_argument('--limit', type=int, default=500,
                        help='Limit results per category (default: 500)')
    parser.add_argument('--export', type=str, metavar='FILE',
                        help='Export results to CSV file')
    parser.add_argument('--show-unsubscribes', action='store_true',
                        help='Show recent unsubscribes')

    args = parser.parse_args()

    print(f"\n{'='*70}")
    print("EMAIL QUEUE DIAGNOSTIC")
    print(f"{'='*70}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.campaign_id:
        print(f"Filter: Campaign ID {args.campaign_id}")
    print(f"Limit: {args.limit} per category")

    # Create app context
    app, db = create_app_context()

    with app.app_context():
        # Gather all data
        email_queue = get_email_queue_pending(db, args.limit)
        queued_contact_emails = get_queued_lead_contact_emails(db, args.campaign_id, args.limit)
        contacts_first = get_contacts_ready_for_first_email(db, args.campaign_id, args.limit)
        contacts_sequence = get_contacts_ready_for_next_sequence(db, args.campaign_id, args.limit)

        if args.summary:
            # Summary only
            print_summary(email_queue, queued_contact_emails, contacts_first, contacts_sequence)
        else:
            # Full output
            print_email_queue(email_queue, args.verbose)
            print_queued_contact_emails(queued_contact_emails, args.verbose)
            print_contacts_ready_first(contacts_first, args.verbose)
            print_contacts_ready_sequence(contacts_sequence, args.verbose)
            print_summary(email_queue, queued_contact_emails, contacts_first, contacts_sequence)

        if args.show_unsubscribes:
            unsubscribes = get_unsubscribes(db)
            print_section_header("RECENT UNSUBSCRIBES (Blocked)", len(unsubscribes))
            for unsub in unsubscribes:
                print(f"  - {unsub.email} (unsubscribed: {unsub.created_at.strftime('%Y-%m-%d')})")

        if args.export:
            export_to_csv(args.export, email_queue, queued_contact_emails, contacts_first, contacts_sequence)

    print(f"\n{'='*70}")
    print("NOTE: This is a READ-ONLY diagnostic. No emails were sent.")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    main()
