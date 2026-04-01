#!/usr/bin/env python3
"""
Lead Generation Automation Runner

Run this script to execute the daily automation cycle:
- Creates and scrapes campaigns (up to 50/day)
- Enriches leads (up to 100/day)
- Sends emails (up to 250/day)

Usage:
    python3 run_automation.py
"""
import sys
import os

# Add the app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

# Load .env before importing app (searches parent dir too)
from scripts.load_env import load_environment
load_environment(os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.services.lead_automation_service import LeadAutomationService

def main():
    """Run the daily automation"""
    print("=" * 80)
    print("LEAD GENERATION AUTOMATION")
    print("=" * 80)
    print()

    app = create_app()

    with app.app_context():
        service = LeadAutomationService()

        # Show current progress
        progress = service.get_progress_report()
        print(f"📊 Current Progress:")
        print(f"   Campaigns: {progress['campaigns_created']}/{progress['total_campaigns_planned']}")
        print(f"   Progress: {progress['progress_percent']:.1f}%")
        print(f"   Leads Enriched: {progress['leads_enriched']}")
        print(f"   Emails Sent: {progress['emails_sent']}")
        print(f"   Unique Domains: {progress['unique_domains_processed']}")
        print()

        # Show daily limits
        daily_stats = progress['daily_stats']
        print(f"📅 Today's Activity ({daily_stats.get('date', 'N/A')}):")
        print(f"   Scrapes: {daily_stats.get('scrapes', 0)}/50")
        print(f"   Enrichments: {daily_stats.get('enrichments', 0)}/100")
        print(f"   Emails: {daily_stats.get('emails', 0)}/250")
        print()
        print("=" * 80)
        print()

        # Run automation
        print("🚀 Starting automation cycle...")
        print()

        try:
            result = service.run_daily_automation()

            print()
            print("=" * 80)
            print("✅ AUTOMATION COMPLETE")
            print("=" * 80)
            print(f"   Campaigns Scraped: {result['scraped']}")
            print(f"   Leads Enriched: {result['enriched']}")
            print(f"   Emails Sent: {result['sent']}")
            print()
            print(f"📈 Total Progress:")
            print(f"   Total Campaigns: {result['total_campaigns']}")
            print(f"   Total Emails: {result['total_emails']}")
            print("=" * 80)

            return 0

        except Exception as e:
            print()
            print("=" * 80)
            print("❌ ERROR")
            print("=" * 80)
            print(f"   {str(e)}")
            print("=" * 80)
            import traceback
            traceback.print_exc()
            return 1

if __name__ == "__main__":
    sys.exit(main())
