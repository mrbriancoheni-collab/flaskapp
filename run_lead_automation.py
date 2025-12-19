#!/usr/bin/env python3
"""
Direct Python script to run lead automation without Flask CLI.
Works on shared hosting where 'flask' command may not be available.

Usage:
    python3 run_lead_automation.py
    python3 run_lead_automation.py --dry-run
"""
import sys
import os

# Add the flaskapp directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flaskapp'))

def run_automation(dry_run=False):
    """Run the lead automation"""
    from app import create_app
    from app.services.lead_automation_service import LeadAutomationService

    print("\n" + "="*80)
    print("LEAD GENERATION AUTOMATION")
    print("="*80 + "\n")

    app = create_app()

    with app.app_context():
        try:
            service = LeadAutomationService()

            if dry_run:
                print("DRY RUN MODE - No changes will be made\n")
                progress = service.get_progress_report()
                print(f"Current Progress:")
                print(f"  Total Campaigns Planned: {progress['total_campaigns_planned']}")
                print(f"  Campaigns Created: {progress['campaigns_created']}")
                print(f"  Campaigns Scraped: {progress['campaigns_scraped']}")
                print(f"  Progress: {progress['progress_percent']:.1f}%")
                print(f"  Leads Enriched: {progress['leads_enriched']}")
                print(f"  Emails Sent: {progress['emails_sent']}")
                print(f"  Unique Domains: {progress['unique_domains_processed']}")
                print(f"\nDaily Stats ({progress['daily_stats']['date']}):")
                print(f"  Scrapes: {progress['daily_stats']['scrapes']}")
                print(f"  Enrichments: {progress['daily_stats']['enrichments']}")
                print(f"  Emails: {progress['daily_stats']['emails']}")
                return 0

            # Run automation
            result = service.run_daily_automation()

            print("\nResults:")
            print(f"  Campaigns Scraped: {result['scraped']}")
            print(f"  Leads Enriched: {result['enriched']}")
            print(f"  Emails Sent: {result['sent']}")
            print(f"\nTotal Progress:")
            print(f"  Total Campaigns: {result['total_campaigns']}")
            print(f"  Total Emails: {result['total_emails']}")

            print(f"\n{'='*80}")
            print("AUTOMATION COMPLETE")
            print(f"{'='*80}\n")

            return 0

        except Exception as e:
            print(f"\nError running automation: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    sys.exit(run_automation(dry_run))
