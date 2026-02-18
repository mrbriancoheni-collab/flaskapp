#!/usr/bin/env python3
"""
Comprehensive database audit to find where email addresses live
and why the agents aren't finding them.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

def main():
    from app import create_app, db
    from sqlalchemy import text

    app = create_app()

    with app.app_context():
        print("=" * 70)
        print("COMPREHENSIVE EMAIL DATABASE AUDIT")
        print("=" * 70)

        # 1. Check LeadCampaign table
        from app.models_leads import LeadCampaign, Lead, LeadContact, LeadContactEmail, LeadEmail, EmailSequence
        from app.models import CompanyContact, CRMContact

        campaigns = LeadCampaign.query.all()
        print(f"\n--- CAMPAIGNS ({len(campaigns)}) ---")
        for c in campaigns:
            print(f"  ID: {c.id}, Name: {c.name}, Status: {c.status}, "
                  f"Leads: {c.leads_scraped}, Enriched: {c.leads_enriched}, "
                  f"Emails Sent: {c.emails_sent}")

        # 2. Check Leads table
        total_leads = Lead.query.count()
        enriched_leads = Lead.query.filter_by(enrichment_status='completed').count()
        pending_leads = Lead.query.filter_by(enrichment_status='pending').count()
        leads_with_dm_email = Lead.query.filter(Lead.decision_maker_email.isnot(None)).count()
        print(f"\n--- LEADS ---")
        print(f"  Total leads: {total_leads}")
        print(f"  Enriched: {enriched_leads}")
        print(f"  Pending enrichment: {pending_leads}")
        print(f"  With decision_maker_email: {leads_with_dm_email}")

        # Show leads with decision_maker_email
        leads_dm = Lead.query.filter(Lead.decision_maker_email.isnot(None)).limit(20).all()
        if leads_dm:
            print(f"\n  Leads with decision_maker_email:")
            for l in leads_dm:
                print(f"    ID: {l.id}, Company: {l.company_name}, DM Email: {l.decision_maker_email}, "
                      f"Status: {l.enrichment_status}, Email Status: {l.email_status}")

        # 3. Check LeadContact table
        total_contacts = LeadContact.query.count()
        contacts_with_email = LeadContact.query.filter(
            LeadContact.email.isnot(None),
            LeadContact.email != ''
        ).count()
        contacts_pending = LeadContact.query.filter_by(email_status='pending').count()
        contacts_sent = LeadContact.query.filter_by(email_status='sent').count()
        print(f"\n--- LEAD CONTACTS ---")
        print(f"  Total: {total_contacts}")
        print(f"  With email: {contacts_with_email}")
        print(f"  Pending email: {contacts_pending}")
        print(f"  Sent email: {contacts_sent}")

        all_lc = LeadContact.query.limit(20).all()
        if all_lc:
            print(f"\n  All LeadContacts:")
            for lc in all_lc:
                print(f"    ID: {lc.id}, Name: {lc.name}, Email: {lc.email}, "
                      f"Status: {lc.email_status}, Lead ID: {lc.lead_id}, "
                      f"CRM Link: {lc.company_contact_id}")

        # 4. Check CompanyContact (CRM) table
        total_crm_contacts = CompanyContact.query.count()
        crm_with_email = CompanyContact.query.filter(
            CompanyContact.email.isnot(None),
            CompanyContact.email != ''
        ).count()
        print(f"\n--- CRM COMPANY CONTACTS ---")
        print(f"  Total: {total_crm_contacts}")
        print(f"  With email: {crm_with_email}")

        all_cc = CompanyContact.query.limit(20).all()
        if all_cc:
            print(f"\n  All CompanyContacts:")
            for cc in all_cc:
                print(f"    ID: {cc.id}, Name: {cc.full_name}, Email: {cc.email}, "
                      f"CRM Contact ID: {cc.crm_contact_id}")

        # 5. Check CRMContact (company) table
        total_crm = CRMContact.query.count()
        print(f"\n--- CRM CONTACTS (Companies) ---")
        print(f"  Total: {total_crm}")

        all_crm = CRMContact.query.limit(20).all()
        if all_crm:
            print(f"\n  All CRMContacts:")
            for crm in all_crm:
                print(f"    ID: {crm.id}, Business: {crm.business_name}, "
                      f"Email: {crm.email}, Domain: {crm.domain}, Stage: {crm.stage}")

        # 6. Check EmailSequence table
        sequences = EmailSequence.query.all()
        print(f"\n--- EMAIL SEQUENCES ({len(sequences)}) ---")
        for s in sequences:
            print(f"  ID: {s.id}, Campaign: {s.campaign_id}, Step: {s.step_number}, "
                  f"Name: {s.name}, Active: {s.is_active}, Delay: {s.delay_days}d")

        # 7. Check sent emails
        legacy_emails = LeadEmail.query.count()
        contact_emails = LeadContactEmail.query.count()
        print(f"\n--- EMAILS SENT ---")
        print(f"  Legacy (LeadEmail): {legacy_emails}")
        print(f"  Contact (LeadContactEmail): {contact_emails}")

        all_sent = LeadContactEmail.query.limit(10).all()
        if all_sent:
            print(f"\n  Recent LeadContactEmails:")
            for e in all_sent:
                print(f"    ID: {e.id}, To: {e.to_email}, Step: {e.sequence_step}, "
                      f"Status: {e.status}, Sent: {e.sent_at}")

        all_legacy = LeadEmail.query.limit(10).all()
        if all_legacy:
            print(f"\n  Recent LeadEmails (legacy):")
            for e in all_legacy:
                print(f"    ID: {e.id}, To: {e.to_email}, Status: {e.status}, Sent: {e.sent_at}")

        # 8. Check automation config
        from app.configs.lead_automation_config import AUTOMATION_CONFIG, get_campaign_queue
        print(f"\n--- AUTOMATION CONFIG ---")
        print(f"  Daily scrape limit: {AUTOMATION_CONFIG['daily_scrape_limit']}")
        print(f"  Daily enrich limit: {AUTOMATION_CONFIG['daily_enrich_limit']}")
        print(f"  Daily email limit: {AUTOMATION_CONFIG['daily_email_limit']}")
        print(f"  Skip email days: {AUTOMATION_CONFIG['skip_email_days']}")
        queue = get_campaign_queue()
        print(f"  Campaign queue size: {len(queue)}")

        # 9. Check automation state file
        print(f"\n--- AUTOMATION STATE ---")
        import json
        state_file = 'automation_state.json'
        if os.path.exists(state_file):
            with open(state_file) as f:
                state = json.load(f)
            print(f"  Last run: {state.get('last_run')}")
            print(f"  Current campaign index: {state.get('current_campaign_index')}")
            print(f"  Campaigns created: {state.get('campaigns_created')}")
            print(f"  Emails sent: {state.get('emails_sent')}")
        else:
            print(f"  No state file found at {state_file}")

        # SUMMARY
        print("\n" + "=" * 70)
        print("DIAGNOSIS SUMMARY")
        print("=" * 70)

        issues = []
        if total_leads == 0:
            issues.append("No leads in database - scraping hasn't run or found anything")
        if enriched_leads == 0 and total_leads > 0:
            issues.append(f"{total_leads} leads exist but none enriched")
        if contacts_with_email == 0 and leads_with_dm_email > 0:
            issues.append(f"{leads_with_dm_email} leads have decision_maker_email but no LeadContact records with emails")
        if contacts_with_email == 0 and leads_with_dm_email == 0:
            issues.append("No email addresses found anywhere - enrichment hasn't found any contacts")
        if len(sequences) == 0:
            issues.append("No email sequences defined - emails can't be sent without templates")
        if len(campaigns) == 0:
            issues.append("No campaigns created yet")

        ready_campaigns = [c for c in campaigns if c.status == 'ready']
        if len(campaigns) > 0 and len(ready_campaigns) == 0:
            issues.append(f"All {len(campaigns)} campaigns exist but none have status 'ready'")

        if issues:
            print("\nISSUES FOUND:")
            for i, issue in enumerate(issues, 1):
                print(f"  {i}. {issue}")
        else:
            print("\nNo obvious issues found. The data looks correct.")

        print()


if __name__ == '__main__':
    main()
