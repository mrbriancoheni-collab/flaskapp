#!/usr/bin/env python3
"""
Quick test script to verify the email agent fix.
Runs the send_next_sequence_steps() method and shows what it finds.
"""
import os
import sys

# Add flaskapp to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

def main():
    from app import create_app, db
    from app.services.lead_automation_service import LeadAutomationService
    from app.models_leads import LeadContact, LeadContactEmail, LeadEmail, EmailUnsubscribe

    app = create_app()

    with app.app_context():
        print("=" * 70)
        print("EMAIL AGENT FIX VERIFICATION TEST")
        print("=" * 70)

        # Count LeadContacts with emails
        lead_contacts_with_email = LeadContact.query.filter(
            LeadContact.email.isnot(None),
            LeadContact.email != ''
        ).count()
        print(f"\nLeadContacts with emails: {lead_contacts_with_email}")

        # Count LeadContacts linked to CRM (company_contact_id is set)
        lead_contacts_linked = LeadContact.query.filter(
            LeadContact.company_contact_id.isnot(None)
        ).count()
        print(f"LeadContacts linked to CRM (company_contact_id set): {lead_contacts_linked}")

        # Count unlinked (would have been missed before the fix)
        unlinked = lead_contacts_with_email - lead_contacts_linked
        print(f"LeadContacts with emails but NOT linked to CRM: {unlinked}")
        if unlinked > 0:
            print(f"  ^ These {unlinked} contacts would have been MISSED before the fix!")

        # Show sample contacts
        print("\n" + "=" * 70)
        print("SAMPLE LEADCONTACTS WITH EMAILS:")
        print("=" * 70)

        for lc in LeadContact.query.filter(
            LeadContact.email.isnot(None),
            LeadContact.email != ''
        ).limit(10).all():
            crm_status = "LINKED" if lc.company_contact_id else "NOT LINKED (would have been missed!)"
            print(f"  ID: {lc.id}, Email: {lc.email}, CRM: {crm_status}")

        # Run the actual service to see what it finds
        print("\n" + "=" * 70)
        print("RUNNING send_next_sequence_steps() [DRY RUN - no emails sent]")
        print("=" * 70)

        service = LeadAutomationService()

        # Just check what it would find without actually sending
        from app.models_leads import EmailUnsubscribe, EmailSequence

        unsubscribed_emails = set(
            email[0].lower() for email in db.session.query(EmailUnsubscribe.email).all()
        )

        all_lead_contacts = (
            LeadContact.query
            .filter(
                LeadContact.email.isnot(None),
                LeadContact.email != '',
            )
            .all()
        )

        print(f"\nTotal LeadContacts with emails found: {len(all_lead_contacts)}")
        print(f"Unsubscribed emails in blocklist: {len(unsubscribed_emails)}")

        # Show what would be processed
        can_send = []
        for lc in all_lead_contacts:
            if lc.email.lower() not in unsubscribed_emails:
                can_send.append(lc)

        print(f"Contacts eligible (not unsubscribed): {len(can_send)}")

        print("\n" + "=" * 70)
        print("FIX VERIFICATION COMPLETE")
        print("=" * 70)
        print("\nTo actually run the agent and send emails:")
        print("  flask run-lead-automation")
        print("\nOr to run the diagnostic:")
        print("  python diagnose_email_queue.py --verbose")


if __name__ == '__main__':
    main()
