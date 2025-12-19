#!/usr/bin/env python3
"""
Lead Automation Diagnostic Script

Checks the current state of lead automation to diagnose why only 8 emails were sent
when the target is 50+/day.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "flaskapp"))

from app import create_app, db
from sqlalchemy import text, func
from app.models_leads import LeadCampaign, Lead, LeadContact, LeadEmail

def main():
    app = create_app()
    with app.app_context():
        print("=" * 80)
        print("LEAD AUTOMATION DIAGNOSTIC REPORT")
        print("=" * 80)
        print()

        # Get today's date
        today = datetime.utcnow().date()
        print(f"📅 Date: {today}")
        print()

        # ============================================================================
        # 1. CAMPAIGN STATUS
        # ============================================================================
        print("=" * 80)
        print("1. CAMPAIGN STATUS")
        print("=" * 80)

        campaigns_by_status = db.session.query(
            LeadCampaign.status,
            func.count(LeadCampaign.id)
        ).group_by(LeadCampaign.status).all()

        total_campaigns = LeadCampaign.query.count()
        print(f"\nTotal Campaigns: {total_campaigns}")
        print("\nBreakdown by status:")
        for status, count in campaigns_by_status:
            print(f"  - {status}: {count}")

        # ============================================================================
        # 2. LEAD STATUS
        # ============================================================================
        print()
        print("=" * 80)
        print("2. LEAD STATUS")
        print("=" * 80)

        total_leads = Lead.query.count()
        print(f"\nTotal Leads: {total_leads}")

        # By enrichment status
        print("\nBy Enrichment Status:")
        enrichment_statuses = db.session.query(
            Lead.enrichment_status,
            func.count(Lead.id)
        ).group_by(Lead.enrichment_status).all()

        for status, count in enrichment_statuses:
            print(f"  - {status}: {count}")

        # By email status
        print("\nBy Email Status:")
        email_statuses = db.session.query(
            Lead.email_status,
            func.count(Lead.id)
        ).group_by(Lead.email_status).all()

        for status, count in email_statuses:
            print(f"  - {status}: {count}")

        # ============================================================================
        # 3. LEADS READY TO EMAIL
        # ============================================================================
        print()
        print("=" * 80)
        print("3. LEADS READY TO EMAIL")
        print("=" * 80)

        # Enriched leads with contacts
        enriched_with_contacts = db.session.query(func.count(Lead.id)).filter(
            Lead.enrichment_status == 'completed'
        ).scalar()

        print(f"\n✅ Enriched leads (completed): {enriched_with_contacts}")

        # Leads with pending contacts
        leads_with_pending_contacts = db.session.query(
            func.count(func.distinct(LeadContact.lead_id))
        ).filter(
            LeadContact.email_status == 'pending',
            LeadContact.email.isnot(None)
        ).scalar()

        print(f"📧 Leads with pending contacts: {leads_with_pending_contacts}")

        # Total pending contacts
        total_pending_contacts = LeadContact.query.filter_by(
            email_status='pending'
        ).filter(
            LeadContact.email.isnot(None)
        ).count()

        print(f"👥 Total pending contacts: {total_pending_contacts}")

        # ============================================================================
        # 4. TODAY'S EMAIL ACTIVITY
        # ============================================================================
        print()
        print("=" * 80)
        print("4. TODAY'S EMAIL ACTIVITY")
        print("=" * 80)

        # Emails sent today
        emails_sent_today = LeadEmail.query.filter(
            func.date(LeadEmail.sent_at) == today
        ).count()

        print(f"\n📨 Emails sent today: {emails_sent_today}")
        print(f"🎯 Daily limit: 250")
        print(f"📊 Remaining capacity: {250 - emails_sent_today}")
        print(f"⚠️  Target minimum: 50")

        if emails_sent_today < 50:
            print(f"\n❌ BELOW MINIMUM! Only {emails_sent_today} sent, need {50 - emails_sent_today} more")
        else:
            print(f"\n✅ Above minimum target")

        # ============================================================================
        # 5. ENRICHMENT ACTIVITY
        # ============================================================================
        print()
        print("=" * 80)
        print("5. ENRICHMENT ACTIVITY")
        print("=" * 80)

        # Leads enriched today
        leads_enriched_today = Lead.query.filter(
            func.date(Lead.enrichment_completed_at) == today
        ).count()

        print(f"\n🔍 Leads enriched today: {leads_enriched_today}")
        print(f"🎯 Daily limit: 100")
        print(f"📊 Remaining capacity: {100 - leads_enriched_today}")

        # Pending enrichments
        pending_enrichments = Lead.query.filter_by(
            enrichment_status='pending'
        ).count()

        print(f"⏳ Pending enrichments: {pending_enrichments}")

        # ============================================================================
        # 6. SCRAPING ACTIVITY
        # ============================================================================
        print()
        print("=" * 80)
        print("6. SCRAPING ACTIVITY")
        print("=" * 80)

        # Campaigns scraped today
        campaigns_scraped_today = LeadCampaign.query.filter(
            func.date(LeadCampaign.last_scraped_at) == today
        ).count()

        print(f"\n🔎 Campaigns scraped today: {campaigns_scraped_today}")
        print(f"🎯 Daily limit: 50")
        print(f"📊 Remaining capacity: {50 - campaigns_scraped_today}")

        # Ready campaigns not yet scraped
        ready_not_scraped = LeadCampaign.query.filter_by(
            status='ready'
        ).filter(
            (LeadCampaign.last_scraped_at.is_(None)) |
            (func.date(LeadCampaign.last_scraped_at) < today)
        ).count()

        print(f"⏳ Ready campaigns not scraped today: {ready_not_scraped}")

        # ============================================================================
        # 7. BOTTLENECK ANALYSIS
        # ============================================================================
        print()
        print("=" * 80)
        print("7. BOTTLENECK ANALYSIS")
        print("=" * 80)
        print()

        bottlenecks = []

        # Check if we have campaigns
        if total_campaigns == 0:
            bottlenecks.append("❌ NO CAMPAIGNS: Create campaigns first")

        # Check if campaigns are ready
        ready_campaigns_count = LeadCampaign.query.filter_by(status='ready').count()
        if ready_campaigns_count == 0:
            bottlenecks.append("❌ NO READY CAMPAIGNS: Campaigns need to be marked as 'ready'")

        # Check if we're scraping
        if campaigns_scraped_today == 0 and ready_not_scraped > 0:
            bottlenecks.append(f"❌ SCRAPING NOT RUNNING: {ready_not_scraped} campaigns waiting to be scraped")

        # Check if we have leads
        if total_leads == 0:
            bottlenecks.append("❌ NO LEADS: Run scraping to generate leads")

        # Check if we're enriching
        if pending_enrichments > 0 and leads_enriched_today == 0:
            bottlenecks.append(f"❌ ENRICHMENT NOT RUNNING: {pending_enrichments} leads waiting to be enriched")

        # Check if we have enriched leads
        if enriched_with_contacts == 0:
            bottlenecks.append("❌ NO ENRICHED LEADS: Run enrichment to get contact info")

        # Check if we have contacts
        if total_pending_contacts == 0 and enriched_with_contacts > 0:
            bottlenecks.append(f"⚠️  NO PENDING CONTACTS: {enriched_with_contacts} enriched leads but no contacts pending")

        # Check if we're sending emails
        if total_pending_contacts > 0 and emails_sent_today < 50:
            bottlenecks.append(f"❌ EMAIL SENDING UNDERPERFORMING: {total_pending_contacts} contacts ready but only {emails_sent_today} emails sent")

        if bottlenecks:
            print("🚨 BOTTLENECKS DETECTED:")
            for i, bottleneck in enumerate(bottlenecks, 1):
                print(f"{i}. {bottleneck}")
        else:
            print("✅ No major bottlenecks detected")

        # ============================================================================
        # 8. RECOMMENDATIONS
        # ============================================================================
        print()
        print("=" * 80)
        print("8. RECOMMENDATIONS")
        print("=" * 80)
        print()

        recommendations = []

        if ready_campaigns_count == 0:
            recommendations.append("1. Create or activate campaigns in the admin panel")

        if campaigns_scraped_today == 0 and ready_not_scraped > 0:
            recommendations.append(f"2. Run scraping: python run_automation.py scrape (or check cron job)")

        if pending_enrichments > 50 and leads_enriched_today < 50:
            recommendations.append(f"3. Run enrichment: python run_automation.py enrich")

        if total_pending_contacts > 50 and emails_sent_today < 50:
            recommendations.append(f"4. Run email sending: python run_automation.py email")
            recommendations.append(f"5. Check email provider credentials (MAILGUN_API_KEY or BREVO_API_KEY)")
            recommendations.append(f"6. Check email provider logs for failures")

        if not recommendations:
            recommendations.append("✅ System appears to be running normally")
            if emails_sent_today < 50:
                recommendations.append(f"⚠️  Only {emails_sent_today} emails sent. May need more enriched leads.")

        for rec in recommendations:
            print(rec)

        print()
        print("=" * 80)
        print("END OF REPORT")
        print("=" * 80)


if __name__ == "__main__":
    main()
