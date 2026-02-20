#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

from app import create_app
from app.extensions import db
from app.models_leads import LeadContact, LeadContactEmail, LeadEmail

app = create_app()
with app.app_context():
    contacts = LeadContact.query.filter(
        LeadContact.email.isnot(None),
        LeadContact.email != ''
    ).all()
    print(f"Total contacts with email: {len(contacts)}")
    for c in contacts:
        emails_sent = LeadContactEmail.query.filter_by(contact_id=c.id).all()
        legacy = LeadEmail.query.filter_by(to_email=c.email).all() if c.email else []
        print(f"\nContact id={c.id} name={c.name!r}")
        print(f"  email={c.email!r}")
        print(f"  email_status={c.email_status!r}")
        print(f"  lead_id={c.lead_id}")
        print(f"  LeadContactEmails sent: {len(emails_sent)}, steps={[e.sequence_step for e in emails_sent]}")
        print(f"  Legacy LeadEmails: {len(legacy)}")

    # Also check leads directly
    from app.models_leads import Lead
    leads = Lead.query.all()
    print(f"\nTotal leads: {len(leads)}")
    for lead in leads:
        print(f"\nLead id={lead.id} company={lead.company_name!r}")
        print(f"  email_status={lead.email_status!r}")
        print(f"  enrichment_status={lead.enrichment_status!r}")
        print(f"  decision_maker_email={lead.decision_maker_email!r}")
        print(f"  campaign_id={lead.campaign_id}")
