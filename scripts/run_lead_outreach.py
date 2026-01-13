#!/usr/bin/env python3
"""
Run Lead Email Outreach Only

Sends emails to enriched leads without scraping or enriching.
Can be run on-demand or via cron.
"""

import sys
import os

# Load environment BEFORE importing anything from app
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from load_env import load_environment, ensure_app_can_initialize

# Load environment and ensure app can initialize
load_environment()
ensure_app_can_initialize()

# NOW we can safely import the app
import logging
from app import create_app
from app.services.lead_automation_service import LeadAutomationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/lead_outreach.log')
    ]
)
logger = logging.getLogger(__name__)


def main():
    """Run lead email outreach."""
    app = create_app()
    with app.app_context():
        logger.info("Starting lead email outreach")

        try:
            service = LeadAutomationService()
            result = service.run_email_outreach()

            logger.info(f"Email outreach complete: {result['sent']} emails sent")
            logger.info(f"Total emails sent: {result['total_emails']}")

            return 0

        except Exception as e:
            logger.error(f"Error during email outreach: {e}", exc_info=True)
            return 1


if __name__ == '__main__':
    sys.exit(main())
