#!/usr/bin/env python3
"""
Standalone job runner — use this with system cron instead of running
APScheduler inside Passenger workers.

Usage:
    python run_job.py <job_name>

Example crontab entries (crontab -e):
    # Email queue — every 5 minutes
    */5 * * * * cd /home/fieldsprout/flaskapp && python run_job.py process_email_queue >> logs/cron.log 2>&1

    # Tactical agents — every 2 hours
    0 */2 * * * cd /home/fieldsprout/flaskapp && python run_job.py run_tactical_agents >> logs/cron.log 2>&1

    # Operational agents + auto-executor — every 4 hours
    0 */4 * * * cd /home/fieldsprout/flaskapp && python run_job.py run_operational_agents >> logs/cron.log 2>&1
    30 */4 * * * cd /home/fieldsprout/flaskapp && python run_job.py run_google_ads_auto_executor >> logs/cron.log 2>&1

    # Offline conversion upload — every 4 hours
    15 */4 * * * cd /home/fieldsprout/flaskapp && python run_job.py upload_offline_conversions_all_accounts >> logs/cron.log 2>&1

    # Daily jobs (all UTC)
    30 3 * * * cd /home/fieldsprout/flaskapp && python run_job.py sync_fb_all_accounts >> logs/cron.log 2>&1
    0  4 * * * cd /home/fieldsprout/flaskapp && python run_job.py sync_structure_all_accounts >> logs/cron.log 2>&1
    30 4 * * * cd /home/fieldsprout/flaskapp && python run_job.py sync_call_view_all_accounts >> logs/cron.log 2>&1
    0  5 * * * cd /home/fieldsprout/flaskapp && python run_job.py sync_dayparting_all_accounts >> logs/cron.log 2>&1
    30 5 * * * cd /home/fieldsprout/flaskapp && python run_job.py sync_auction_insights_all_accounts >> logs/cron.log 2>&1
    0  6 * * * cd /home/fieldsprout/flaskapp && python run_job.py sync_rsa_assets_all_accounts >> logs/cron.log 2>&1
    0  7 * * * cd /home/fieldsprout/flaskapp && python run_job.py run_negative_keyword_agents >> logs/cron.log 2>&1
    0  7 * * * cd /home/fieldsprout/flaskapp && python run_job.py sync_skimmer_all_accounts >> logs/cron.log 2>&1
    30 7 * * * cd /home/fieldsprout/flaskapp && python run_job.py run_overlap_detection_all_groups >> logs/cron.log 2>&1
    0  8 * * * cd /home/fieldsprout/flaskapp && python run_job.py run_lead_automation_daily >> logs/cron.log 2>&1
    0  9 * * * cd /home/fieldsprout/flaskapp && python run_job.py generate_google_ads_insights_daily >> logs/cron.log 2>&1
    0 12 * * * cd /home/fieldsprout/flaskapp && python run_job.py send_to_all_unsent_today >> logs/cron.log 2>&1

    # Weekly jobs
    0 2 * * 0 cd /home/fieldsprout/flaskapp && python run_job.py cleanup_expired_invites >> logs/cron.log 2>&1
    0 3 * * 0 cd /home/fieldsprout/flaskapp && python run_job.py cleanup_old_audit_logs >> logs/cron.log 2>&1
    0 8 * * 1 cd /home/fieldsprout/flaskapp && python run_job.py generate_google_ads_insights_weekly >> logs/cron.log 2>&1
    0 6 * * 1 cd /home/fieldsprout/flaskapp && python run_job.py run_strategic_agents >> logs/cron.log 2>&1
    30 6 * * 1 cd /home/fieldsprout/flaskapp && python run_job.py snapshot_keyword_rankings >> logs/cron.log 2>&1
    0 13 * * 1 cd /home/fieldsprout/flaskapp && python run_job.py send_weekly_digest_all_accounts >> logs/cron.log 2>&1

To enable this mode, set DISABLE_SCHEDULER=1 in your Passenger environment
variables (via cPanel > Software > Setup Python App > Environment Variables,
or in your .htaccess / .env file).
"""

import os
import sys
import logging
from datetime import datetime

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(SCRIPT_DIR, 'flaskapp')
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# ── Logging ──────────────────────────────────────────────────────────────────
os.makedirs(os.path.join(SCRIPT_DIR, 'logs'), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger('run_job')

# ── Load env ─────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
for env_path in [
    os.path.join(os.path.expanduser('~'), '.env'),
    os.path.join(SCRIPT_DIR, '.env'),
    os.path.join(APP_DIR, '.env'),
]:
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
        break

# Map of job_name → function name in background_jobs
JOB_MAP = {
    'cleanup_expired_invites':              'cleanup_expired_invites',
    'sync_subscription_statuses':           'sync_subscription_statuses',
    'cleanup_old_audit_logs':               'cleanup_old_audit_logs',
    'generate_google_ads_insights_weekly':  'generate_google_ads_insights_weekly',
    'generate_google_ads_insights_daily':   'generate_google_ads_insights_daily',
    'run_lead_automation_daily':            'run_lead_automation_daily',
    'send_to_all_unsent_today':             'send_to_all_unsent_today',
    'process_email_queue':                  'process_email_queue',
    'run_tactical_agents':                  'run_tactical_agents',
    'run_negative_keyword_agents':          'run_negative_keyword_agents',
    'run_operational_agents':               'run_operational_agents',
    'run_strategic_agents':                 'run_strategic_agents',
    'run_google_ads_auto_executor':         'run_google_ads_auto_executor',
    'sync_call_view_all_accounts':          'sync_call_view_all_accounts',
    'sync_dayparting_all_accounts':         'sync_dayparting_all_accounts',
    'sync_auction_insights_all_accounts':   'sync_auction_insights_all_accounts',
    'sync_rsa_assets_all_accounts':         'sync_rsa_assets_all_accounts',
    'sync_skimmer_all_accounts':            'sync_skimmer_all_accounts',
    'run_overlap_detection_all_groups':     'run_overlap_detection_all_groups',
    'upload_offline_conversions_all_accounts': 'upload_offline_conversions_all_accounts',
    'sync_structure_all_accounts':             'sync_structure_all_accounts',
    'send_weekly_digest_all_accounts':         'send_weekly_digest_all_accounts',
    'sync_fb_all_accounts':                    'sync_fb_all_accounts',
    'snapshot_keyword_rankings':               'snapshot_keyword_rankings_all_accounts',
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_job.py <job_name>")
        print("\nAvailable jobs:")
        for name in sorted(JOB_MAP):
            print(f"  {name}")
        sys.exit(1)

    job_name = sys.argv[1]
    if job_name not in JOB_MAP:
        logger.error("Unknown job: %s", job_name)
        logger.error("Available: %s", ', '.join(sorted(JOB_MAP)))
        sys.exit(1)

    logger.info("=== Starting job: %s at %s ===", job_name, datetime.utcnow().isoformat())

    # Build Flask app
    try:
        from app import create_app
        app = create_app()
    except Exception:
        logger.exception("Failed to create Flask app")
        sys.exit(1)

    # Import the job function
    try:
        import app.background_jobs as bj
        func = getattr(bj, JOB_MAP[job_name])
    except AttributeError:
        logger.error("Function %s not found in background_jobs", JOB_MAP[job_name])
        sys.exit(1)

    # Run it
    try:
        func(app)
        logger.info("=== Job %s completed successfully ===", job_name)
    except Exception:
        logger.exception("Job %s failed", job_name)
        sys.exit(1)
    finally:
        # Always clean up DB session
        try:
            with app.app_context():
                from app import db
                db.session.remove()
        except Exception:
            pass


if __name__ == '__main__':
    main()
