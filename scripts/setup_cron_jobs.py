#!/usr/bin/env python3
"""
Setup Cron Jobs for FieldSprout Automation

This script sets up all necessary cron jobs for:
- Lead automation (scrape, enrich, send)
- Google Ads intelligence
- Alert system
- LSA missed call monitoring

Run this script to enable automation.
"""

import os
import sys
import subprocess

# Determine the project root directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
PYTHON_PATH = sys.executable
VENV_PYTHON = os.path.join(PROJECT_ROOT, 'venv', 'bin', 'python')

# Use venv python if it exists, otherwise use current python
PYTHON = VENV_PYTHON if os.path.exists(VENV_PYTHON) else PYTHON_PATH

# Log directory
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')

# Create logs directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)

# Cron job definitions
CRON_JOBS = [
    {
        'name': 'Lead Automation - Daily',
        'schedule': '0 2 * * *',  # 2 AM daily
        'command': f'cd {PROJECT_ROOT} && {PYTHON} -c "from app import create_app; from app.cron_tasks import run_daily; app = create_app(); run_daily(app, None)" >> {LOG_DIR}/lead_automation.log 2>&1',
        'description': 'Runs lead scraping, enrichment, and email outreach'
    },
    {
        'name': 'LSA Missed Call Check',
        'schedule': '*/15 * * * *',  # Every 15 minutes
        'command': f'cd {PROJECT_ROOT} && {PYTHON} scripts/check_lsa_missed_calls.py >> {LOG_DIR}/lsa_missed_calls.log 2>&1',
        'description': 'Checks for missed LSA calls and sends alerts'
    },
    {
        'name': 'Alert Notifications',
        'schedule': '*/15 * * * *',  # Every 15 minutes
        'command': f'cd {PROJECT_ROOT} && {PYTHON} -c "from app.tasks.alert_tasks import send_alert_notifications; send_alert_notifications()" >> {LOG_DIR}/alert_notifications.log 2>&1',
        'description': 'Sends email notifications for pending alerts'
    },
    {
        'name': 'Alert Detection - Hourly',
        'schedule': '0 * * * *',  # Every hour
        'command': f'cd {PROJECT_ROOT} && {PYTHON} -c "from app.tasks.alert_tasks import check_alerts_for_all_users; check_alerts_for_all_users()" >> {LOG_DIR}/alert_detection.log 2>&1',
        'description': 'Checks for new Google Ads alerts'
    },
    {
        'name': 'Alert Cleanup - Daily',
        'schedule': '0 3 * * *',  # 3 AM daily
        'command': f'cd {PROJECT_ROOT} && {PYTHON} -c "from app.tasks.alert_tasks import cleanup_old_alerts; cleanup_old_alerts()" >> {LOG_DIR}/alert_cleanup.log 2>&1',
        'description': 'Cleans up old resolved alerts'
    },
    {
        'name': 'Google Ads Auto-Execute - Hourly',
        'schedule': '30 * * * *',  # 30 minutes past every hour
        'command': f'cd {PROJECT_ROOT} && {PYTHON} scripts/auto_execute_google_ads.py >> {LOG_DIR}/google_ads_auto_execute.log 2>&1',
        'description': 'Auto-executes safe Google Ads optimizations'
    },
    {
        'name': 'Stale Alert Resolution - Daily',
        'schedule': '0 4 * * *',  # 4 AM daily
        'command': f'cd {PROJECT_ROOT} && {PYTHON} -c "from app.services.alert_throttle_service import AlertThrottleService; from app import create_app; app = create_app(); app.app_context().push(); AlertThrottleService.mark_alerts_as_stale(hours=72)" >> {LOG_DIR}/stale_alerts.log 2>&1',
        'description': 'Auto-resolves stale alerts (>72 hours old)'
    }
]

def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70 + "\n")

def get_current_crontab():
    """Get current crontab."""
    try:
        result = subprocess.run(
            ['crontab', '-l'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout
        return ""
    except Exception as e:
        print(f"Error reading crontab: {e}")
        return ""

def setup_crontab():
    """Set up cron jobs."""
    print_header("FieldSprout Cron Job Setup")

    # Get current crontab
    current_crontab = get_current_crontab()

    print("Current crontab entries:")
    if current_crontab.strip():
        print(current_crontab)
    else:
        print("(empty)")

    print("\n\nWill add the following cron jobs:\n")
    for job in CRON_JOBS:
        print(f"📅 {job['name']}")
        print(f"   Schedule: {job['schedule']}")
        print(f"   Description: {job['description']}")
        print()

    response = input("Proceed with setup? (yes/no): ").strip().lower()
    if response not in ['yes', 'y']:
        print("\nAborted.")
        return

    # Build new crontab content
    new_crontab_lines = []

    # Keep existing crontab entries (if not FieldSprout-related)
    if current_crontab.strip():
        for line in current_crontab.split('\n'):
            # Skip empty lines and FieldSprout-related entries (we'll re-add them)
            if line.strip() and 'fieldsprout' not in line.lower() and LOG_DIR not in line:
                new_crontab_lines.append(line)

    # Add header
    new_crontab_lines.append("")
    new_crontab_lines.append("# FieldSprout Automation Cron Jobs")
    new_crontab_lines.append(f"# Auto-generated on {subprocess.run(['date'], capture_output=True, text=True).stdout.strip()}")
    new_crontab_lines.append("")

    # Add new cron jobs
    for job in CRON_JOBS:
        new_crontab_lines.append(f"# {job['name']} - {job['description']}")
        new_crontab_lines.append(f"{job['schedule']} {job['command']}")
        new_crontab_lines.append("")

    # Write new crontab
    new_crontab = '\n'.join(new_crontab_lines)

    try:
        # Write to temporary file
        temp_file = '/tmp/fieldsprout_crontab.txt'
        with open(temp_file, 'w') as f:
            f.write(new_crontab)

        # Install new crontab
        result = subprocess.run(
            ['crontab', temp_file],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            print_header("✅ Success!")
            print("Cron jobs have been installed successfully.\n")

            print("Installed jobs:")
            for job in CRON_JOBS:
                print(f"  ✓ {job['name']}")

            print(f"\n📁 Logs will be written to: {LOG_DIR}/")
            print("\nTo view logs:")
            print(f"  tail -f {LOG_DIR}/lead_automation.log")
            print(f"  tail -f {LOG_DIR}/google_ads_auto_execute.log")
            print(f"  tail -f {LOG_DIR}/lsa_missed_calls.log")

            print("\nTo view current crontab:")
            print("  crontab -l")

            print("\nTo remove cron jobs:")
            print("  crontab -r")

            # Clean up temp file
            os.remove(temp_file)

        else:
            print(f"❌ Error installing crontab: {result.stderr}")
            print(f"\nTempfile content saved to: {temp_file}")

    except Exception as e:
        print(f"❌ Error setting up crontab: {e}")

def verify_scripts():
    """Verify that all required scripts exist."""
    print_header("Verifying Required Scripts")

    scripts_to_check = [
        'scripts/check_lsa_missed_calls.py',
        'scripts/auto_execute_google_ads.py',
        'scripts/fix_alert_spam.py'
    ]

    all_exist = True
    for script in scripts_to_check:
        script_path = os.path.join(PROJECT_ROOT, script)
        if os.path.exists(script_path):
            print(f"  ✓ {script}")
        else:
            print(f"  ✗ {script} (MISSING - will be created)")
            all_exist = False

    return all_exist

def create_missing_scripts():
    """Create any missing required scripts."""
    # Create check_lsa_missed_calls.py if missing
    lsa_script = os.path.join(PROJECT_ROOT, 'scripts', 'check_lsa_missed_calls.py')
    if not os.path.exists(lsa_script):
        print(f"\n📝 Creating {lsa_script}")
        with open(lsa_script, 'w') as f:
            f.write('''#!/usr/bin/env python3
"""Check for LSA missed calls and send notifications."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User, Account
from app.services.lsa_missed_call_service import check_and_notify_missed_calls

app = create_app()
with app.app_context():
    accounts = Account.query.filter_by(status='active').all()
    total_missed = 0

    for account in accounts:
        owner = User.query.filter_by(account_id=account.id, role='owner').first()
        if owner and owner.email:
            missed = check_and_notify_missed_calls(account.id, owner.email)
            total_missed += missed

    print(f"Checked {len(accounts)} accounts, found {total_missed} missed calls")
''')
        os.chmod(lsa_script, 0o755)

    # Note: auto_execute_google_ads.py will be created separately

def main():
    """Main execution."""
    print_header("FieldSprout Automation Setup")

    print(f"Project Root: {PROJECT_ROOT}")
    print(f"Python: {PYTHON}")
    print(f"Log Directory: {LOG_DIR}")

    # Verify scripts
    if not verify_scripts():
        print("\n⚠️  Some scripts are missing. They will be created.")
        create_missing_scripts()

    # Setup crontab
    setup_crontab()

if __name__ == '__main__':
    main()
